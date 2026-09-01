"""DID Document construction (spec §8) and the resolution result envelope.

The default DID Document is a pure projection of on-chain singleton state.
Verification-method enumeration follows the rule in spec §8.2: a key is
listed only when its membership in the *current* authentication Merkle root
is proven by on-chain data. This version proves membership for single-key
configurations — the dominant personal-DID case — using the tree shape the
production drivers build and which is verified against mainnet: the key
tree is ``((K . K) . 0)``, i.e. the class is the key paired with itself and
the root is ``pair_hash(class, nil_hash)``. Candidate keys come from the
prelauncher reveal (the genesis key) and from keys revealed in the most
recent spend's solution. Multi-key Merkle-path replay is not yet
implemented (a documented v1 limitation); the authentication commitment
itself is always published.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import List, Optional

from .identifier import b58encode, format_did
from .state import JuliaDidState

# The DID context is v1, not v1.1: as of 2026-08 the https://www.w3.org/ns/
# did/v1.1 URL does not dereference (W3C returns 300 even under JSON-LD
# content negotiation), so documents citing it fail JSON-LD expansion. Every
# term this resolver emits is defined in the v1 context. Spec §8.1.
CONTEXTS = [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/multikey/v1",
    "https://not.bot/ns/did-julia/v1",
]

# multicodec bls12_381-g1-pub (0xea), varint-encoded, per spec §8.2
MULTICODEC_BLS_G1 = bytes([0xEA, 0x01])


def multikey(public_key: bytes) -> str:
    """Multibase base58-btc Multikey encoding of a BLS12-381 G1 public key."""
    return "z" + b58encode(MULTICODEC_BLS_G1 + public_key)


def _atom_hash(b: bytes) -> bytes:
    return sha256(b"\x01" + b).digest()


def _pair_hash(l: bytes, r: bytes) -> bytes:
    return sha256(b"\x02" + l + r).digest()


def single_key_root(public_key: bytes) -> bytes:
    """Merkle root of the single-key authentication tree ``((K . K) . 0)``,
    the construction the production drivers build (verified on mainnet)."""
    leaf = _atom_hash(public_key)
    key_class = _pair_hash(leaf, leaf)
    return _pair_hash(key_class, _atom_hash(b""))


def _key_provably_current(state: JuliaDidState, public_key: bytes) -> bool:
    """Spec §8.2 enumeration rule, single-key case: the current root is the
    single-key tree of this key."""
    if state.authentication is None:
        return False
    return state.authentication.merkle_root == single_key_root(public_key)


def build_document(
    state: JuliaDidState,
    candidate_keys: Optional[List[bytes]] = None,
) -> dict:
    did = format_did(state.launcher_id)

    if state.deactivated:
        return {"@context": CONTEXTS[:1], "id": did}

    doc: dict = {"@context": list(CONTEXTS), "id": did}

    verification_methods = []
    seen = set()
    for key in candidate_keys or []:
        if key in seen or not _key_provably_current(state, key):
            continue
        seen.add(key)
        mk = multikey(key)
        verification_methods.append(
            {
                "id": f"{did}#{mk}",
                "type": "Multikey",
                "controller": did,
                "publicKeyMultibase": mk,
            }
        )
    if verification_methods:
        refs = [vm["id"] for vm in verification_methods]
        doc["verificationMethod"] = verification_methods
        doc["authentication"] = refs
        doc["assertionMethod"] = refs

    if state.authentication is not None:
        doc["juliaAuthentication"] = {
            **({"disabled": True} if state.authentication.disabled else {}),
            "merkleRoot": "0x" + state.authentication.merkle_root.hex(),
            "classDepth": state.authentication.class_depth,
            "requiredClasses": state.authentication.required_classes,
            "classes": [
                {
                    "classId": "0x" + c.class_id.hex(),
                    "requiredMembers": c.required_members,
                }
                for c in state.authentication.classes
            ],
        }
    doc["juliaCustodians"] = [format_did(c) for c in state.custodians]
    if state.recovery is None:
        doc["juliaRecovery"] = {"configured": False}
    elif not state.recovery.parsed:
        doc["juliaRecovery"] = {"configured": True}
    else:
        recovery: dict = {
            "configured": True,
            "recoveryAgents": state.recovery.agents_configured,
            "delayBlocks": state.recovery.delay_blocks,
        }
        if state.recovery.prerotation is not None:
            recovery["prerotation"] = state.recovery.prerotation
        doc["juliaRecovery"] = recovery
    if state.recovery_pending:
        doc["juliaRecoveryPending"] = True
    if state.document_pointer is not None:
        doc["juliaDocumentPointer"] = "0x" + state.document_pointer.hex()
    return doc


def _timestamp(unix_seconds: int) -> str:
    """XML datetime in UTC, without sub-second precision (DID Resolution)."""
    return (
        datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def resolution_result(
    state: JuliaDidState,
    document: dict,
    version_coin_id: bytes,
    confirmed_timestamp: int,
    verified: bool,
    current_puzzle: bool,
    created_timestamp: Optional[int] = None,
    next_version_coin_id: Optional[bytes] = None,
    next_timestamp: Optional[int] = None,
) -> dict:
    """The DID resolution result: document, document metadata (§8.5), and
    resolution metadata.

    ``created_timestamp``, ``next_version_coin_id`` and ``next_timestamp`` are
    supplied only by version-specific resolution, which walks the DID's whole
    lineage and therefore knows them. Current-state resolution reports what a
    single look at the unspent coin establishes, so that its metadata does not
    depend on which traversal route a node happened to support (§8.5).
    """
    doc_meta: dict = {
        "versionId": "0x" + version_coin_id.hex(),
    }
    if created_timestamp:
        doc_meta["created"] = _timestamp(created_timestamp)
    if confirmed_timestamp:
        doc_meta["updated"] = _timestamp(confirmed_timestamp)
    if next_version_coin_id is not None:
        doc_meta["nextVersionId"] = "0x" + next_version_coin_id.hex()
    if next_timestamp:
        doc_meta["nextUpdate"] = _timestamp(next_timestamp)
    if state.deactivated:
        doc_meta["deactivated"] = True
    return {
        "didDocument": document,
        "didDocumentMetadata": doc_meta,
        "didResolutionMetadata": {
            "contentType": "application/did+ld+json",
            "did:julia:stateVerified": verified,
            "did:julia:currentPuzzle": current_puzzle,
        },
    }


def not_found(message: str) -> dict:
    return error_result("notFound", message)


def error_result(error: str, message: str) -> dict:
    return {
        "didDocument": None,
        "didDocumentMetadata": {},
        "didResolutionMetadata": {"error": error, "errorMessage": message},
    }
