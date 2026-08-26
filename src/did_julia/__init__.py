"""did:julia reference resolver.

    from did_julia import resolve
    result = resolve("did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX")
    print(result["didDocument"])

Resolution reads public Chia blockchain state (spec §7.2) through any full
node RPC — by default the open Coinset endpoint, or a local node via
``FullNodeClient``. No did:julia-specific service is contacted.
"""

from __future__ import annotations

from typing import Optional

from . import identifier
from .chain import ChainError, FullNodeClient, NotFoundError, trace_singleton
from .diddoc import build_document, not_found, resolution_result
from .state import (
    CURRENT_JULIA_DID_PUZZLE_HASH,
    StateError,
    extract_state_from_spend,
    genesis_public_key,
    revealed_keys_from_spend,
    verify_state,
)

__version__ = "0.1.0"
__all__ = ["resolve", "FullNodeClient", "identifier"]


def resolve(did: str, client: Optional[FullNodeClient] = None) -> dict:
    """Resolve a did:julia DID to a DID resolution result (spec §7.2, §8).

    Returns a dict with ``didDocument``, ``didDocumentMetadata``, and
    ``didResolutionMetadata``. On failure the document is None and
    ``didResolutionMetadata.error`` is set (``invalidDid`` / ``notFound``).
    """
    try:
        launcher_id = identifier.parse(did)
    except identifier.InvalidDidError as e:
        return {
            "didDocument": None,
            "didDocumentMetadata": {},
            "didResolutionMetadata": {"error": "invalidDid", "errorMessage": str(e)},
        }

    client = client or FullNodeClient()
    try:
        lineage = trace_singleton(client, launcher_id)
        parent_spend = client.get_puzzle_and_solution(
            lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
        )
        state = extract_state_from_spend(parent_spend, launcher_id)
        candidates = revealed_keys_from_spend(parent_spend, state)
        genesis_key = genesis_public_key(client, lineage)
        if genesis_key is not None:
            candidates.append(genesis_key)
    except NotFoundError as e:
        return not_found(str(e))
    except (ChainError, StateError) as e:
        return {
            "didDocument": None,
            "didDocumentMetadata": {},
            "didResolutionMetadata": {"error": "internalError", "errorMessage": str(e)},
        }

    verified = verify_state(state, lineage.current.coin.puzzle_hash)
    document = build_document(state, candidate_keys=candidates)
    return resolution_result(
        state,
        document,
        version_coin_id=lineage.current.coin.coin_id(),
        confirmed_timestamp=lineage.current.timestamp,
        verified=verified,
        current_puzzle=state.julia_did_puzzle_hash == CURRENT_JULIA_DID_PUZZLE_HASH,
    )
