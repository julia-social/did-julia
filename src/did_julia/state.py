"""Parsing and verification of did:julia singleton state (spec §6).

The current eight-slot state is read from the most recent spend: every
state-writing did:julia operation re-emits the full state in a REMARK
condition (spec §6.1). The spend is executed on the consensus VM and the
REMARK extracted from its conditions — the same route the production Rust
drivers take. The parsed state is then *verified* by recomputing the
singleton's full puzzle hash from it and comparing against the unspent
coin's on-chain puzzle hash, so a lying or buggy data source cannot slip
an inconsistent state past the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .chain import CoinSpend, FullNodeClient, SingletonLineage
from .clvm_util import (
    Node,
    as_int,
    conditions_from_spend,
    curried_puzzle_hash,
    deserialize,
    sha256tree,
    to_list,
    uncurry,
)

CONDITION_REMARK = b"\x01"

# Standard Chia singleton_top_layer_v1_1 mod hash. The full puzzle hash
# recomputed with this constant is checked against the on-chain coin, so an
# incorrect value fails verification loudly rather than being trusted.
SINGLETON_TOP_LAYER_V1_1_HASH = bytes.fromhex(
    "7faa3253bfddd1e0decb0906b2dc6247bbc4cf608f58345d173adb63e8b47c9f"
)

# The current julia_did.clsp compiled hash, from the pinned puzzle-hash table
# in the julia_did_chialisp README. A singleton whose state slot 1 differs is
# a coin from a predecessor deployment of the protocol, not a conforming
# did:julia DID under the current specification; the resolver still resolves
# it but reports "did:julia:currentPuzzle": false in resolution metadata.
CURRENT_JULIA_DID_PUZZLE_HASH = bytes.fromhex(
    "86361d36c86f3eb892a39b09539fda6d424628a4c7e25d6a4375efa5c4923fa1"
)
BLS_G1_SIZE = 48


class StateError(RuntimeError):
    pass


@dataclass(frozen=True)
class KeyClass:
    class_id: bytes
    required_members: int


@dataclass(frozen=True)
class AuthenticationConfig:
    """Slot 4: (classes class-depth required-classes required-root). Spec §6.2."""
    classes: List[KeyClass]
    class_depth: int
    required_classes: int
    merkle_root: bytes

    @property
    def disabled(self) -> bool:
        """True when the root is the inert-key-tree sentinel: no valid key
        can ever prove membership, so this configuration is unsatisfiable."""
        return self.merkle_root == SENTINEL_ROOT_KEYS


def _single_leaf_root(leaf_value: bytes) -> bytes:
    """Root of the deterministic single-leaf tree ((V . V) . 0) — the shape
    the production drivers build for one-key and one-participant configs."""
    from hashlib import sha256 as _s
    leaf = _s(b"\x01" + leaf_value).digest()
    cls = _s(b"\x02" + leaf + leaf).digest()
    nil = _s(b"\x01").digest()
    return _s(b"\x02" + cls + nil).digest()


# The protocol's uniform inert-tree sentinel (spec §7.3, §7.4): a
# single-leaf tree of an all-zero value, with the leaf width matching the
# committed value type. 48 zero octets is not a valid BLS12-381 G1 public
# key and 32 zero octets is no real launcher ID, so the commitments are
# unsatisfiable by construction. Derived, not hardcoded.
SENTINEL_ROOT_KEYS = _single_leaf_root(bytes(48))    # inert auth / pre-rotation
SENTINEL_ROOT_AGENTS = _single_leaf_root(bytes(32))  # empty recovery-agent tree
PREROTATION_DISABLED_ROOT = SENTINEL_ROOT_KEYS


@dataclass(frozen=True)
class RecoveryConfig:
    """Slot 6: (prerotation-multisig-info classes class-depth
    required-classes required-root recovery-delay).

    ``parsed`` is False when the slot is non-empty but not in the current
    layout (predecessor puzzle versions lack the prerotation element); the
    remaining fields are then meaningless and the configuration is reported
    only as present."""
    agents_configured: bool
    agents_merkle_root: Optional[bytes]
    prerotation: Optional[str]          # "committed" | "disabled" | None
    delay_blocks: int
    parsed: bool = True


@dataclass(frozen=True)
class JuliaDidState:
    """The eight-slot did:julia singleton state. Spec §6.1."""
    julia_did_puzzle_hash: bytes                    # slot 1
    launcher_id: bytes                              # slot 2
    recovery_delay: int                             # slot 3 (0 = no pending recovery)
    authentication: Optional[AuthenticationConfig]  # slot 4 (None = empty)
    custodians: List[bytes]                         # slot 5 (launcher IDs)
    recovery: Optional[RecoveryConfig]              # slot 6 (None = empty)
    document_pointer: Optional[bytes]               # slot 7 (DataLayer launcher ID)
    recovery_pending: bool                          # slot 8 non-empty
    raw: tuple = field(repr=False, default=())      # the raw CLVM slots

    @property
    def recovery_configured(self) -> bool:
        return self.recovery is not None

    @property
    def deactivated(self) -> bool:
        """Spec §7.4: deactivated when no satisfiable control path exists.
        Each control structure is dead when empty (the null encoding) or
        when it carries its inert-tree sentinel. A recovery configuration
        in an unrecognized (predecessor) layout is conservatively treated
        as a live path."""
        auth_dead = self.authentication is None or self.authentication.disabled
        rec = self.recovery
        rec_dead = rec is None or (
            rec.parsed
            and not rec.agents_configured
            and rec.prerotation != "committed"
        )
        return auth_dead and not self.custodians and rec_dead


def _parse_auth(node: Node) -> Optional[AuthenticationConfig]:
    if node == b"":
        return None
    classes_node, class_depth, required_classes, merkle_root = to_list(node)
    classes = [
        KeyClass(class_id=pair[0], required_members=as_int(pair[1]))
        for pair in to_list(classes_node)
    ]
    return AuthenticationConfig(
        classes=classes,
        class_depth=as_int(class_depth),
        required_classes=as_int(required_classes),
        merkle_root=merkle_root,
    )


def _parse_recovery(node: Node) -> Optional[RecoveryConfig]:
    if node == b"":
        return None
    try:
        items = to_list(node)
    except ValueError:
        items = []
    if len(items) != 6 or isinstance(items[0], bytes) and items[0] != b"":
        return RecoveryConfig(
            agents_configured=False,
            agents_merkle_root=None,
            prerotation=None,
            delay_blocks=0,
            parsed=False,
        )
    prerotation_node, classes, _depth, _req, root, delay = items
    prerotation = None
    if prerotation_node != b"":
        pre = _parse_auth(prerotation_node)
        prerotation = (
            "disabled" if pre.merkle_root == PREROTATION_DISABLED_ROOT else "committed"
        )
    agents = (
        classes != b""
        and isinstance(root, bytes)
        and len(root) == 32
        and root != SENTINEL_ROOT_AGENTS
    )
    return RecoveryConfig(
        agents_configured=agents,
        agents_merkle_root=root if agents else None,
        prerotation=prerotation,
        delay_blocks=as_int(delay),
    )


def parse_state(slots_node: Node) -> JuliaDidState:
    slots = to_list(slots_node)
    if len(slots) != 8:
        raise StateError(f"expected 8 state slots, found {len(slots)}")
    custodians_node = slots[4]
    custodians = [c for c in to_list(custodians_node)] if custodians_node != b"" else []
    doc = slots[6]
    return JuliaDidState(
        julia_did_puzzle_hash=slots[0],
        launcher_id=slots[1],
        recovery_delay=as_int(slots[2]),
        authentication=_parse_auth(slots[3]),
        custodians=custodians,
        recovery=_parse_recovery(slots[5]),
        document_pointer=doc if doc != b"" else None,
        recovery_pending=slots[7] != b"",
        raw=tuple(slots),
    )


def _remark_payload(condition: Node) -> Optional[Node]:
    if not isinstance(condition, tuple) or condition[0] != CONDITION_REMARK:
        return None
    rest = condition[1]
    if not isinstance(rest, tuple):
        return None
    payload = rest[0]
    if isinstance(payload, bytes):
        # Some toolchains emit the state as a serialized-CLVM atom.
        try:
            return deserialize(payload)
        except ValueError:
            return None
    return payload


def extract_state_from_spend(spend: CoinSpend, launcher_id: bytes) -> JuliaDidState:
    """Run the spend and return the state REMARKed for the next generation."""
    conditions = conditions_from_spend(spend.puzzle_reveal, spend.solution)
    for condition in conditions:
        payload = _remark_payload(condition)
        if payload is None:
            continue
        try:
            state = parse_state(payload)
        except (StateError, ValueError):
            continue
        if state.launcher_id == launcher_id:
            return state
    raise StateError(
        "no REMARK carrying did:julia state found in the most recent spend "
        "(is this launcher ID a did:julia DID?)"
    )


def revealed_state_from_spend(
    spend: CoinSpend, coin_puzzle_hash: bytes, launcher_id: bytes
) -> JuliaDidState:
    """The state a SPENT generation held, read from its own spend (spec §7.2.1).

    Every ``julia_did`` solution reveals the spend's own pre-spend state as its
    first inner argument — the coin's puzzle curries in that state's hash, so
    the reveal is what the coin committed to. Nothing here is taken on trust:
    the puzzle reveal must hash to the coin's on-chain puzzle hash, and the
    state read out of the solution must recompute to that same hash. A wrong
    or tampered reveal fails both checks rather than producing a document.

    This is the route version-specific resolution takes for every superseded
    generation. It needs no state transition at all — the state is *revealed*
    rather than derived — and it works for the DID's first generation, whose
    parent is the launcher and therefore REMARKs nothing.
    """
    puzzle = deserialize(spend.puzzle_reveal)
    if sha256tree(puzzle) != coin_puzzle_hash:
        raise StateError(
            "spend puzzle reveal does not hash to its coin's puzzle hash"
        )
    solution = deserialize(spend.solution)
    try:
        outer = to_list(solution)              # (lineage_proof amount inner_solution)
        inner = to_list(outer[2])              # (curried-args parent-info solution)
        curried_args = inner[0]
    except (ValueError, IndexError) as e:
        raise StateError(f"spend solution is not a julia_did solution: {e}")
    state = parse_state(curried_args)
    if state.launcher_id != launcher_id:
        raise StateError(
            "the state revealed by this spend belongs to a different DID"
        )
    if not verify_state(state, coin_puzzle_hash):
        raise StateError(
            "the state revealed by this spend does not recompute to the coin's "
            "own puzzle hash"
        )
    return state


def expected_puzzle_hash(state: JuliaDidState) -> bytes:
    """Recompute the singleton's full puzzle hash from parsed state (spec §6.1):
    singleton_top_layer_v1_1 curried with (SINGLETON_STRUCT, julia_did curried
    with sha256tree(state))."""
    inner = curried_puzzle_hash(
        state.julia_did_puzzle_hash,
        [sha256tree(sha256tree(_slots_node(state)))],
    )
    struct_hash = sha256tree(
        (
            SINGLETON_TOP_LAYER_V1_1_HASH,
            (state.launcher_id, _launcher_ph()),
        )
    )
    return curried_puzzle_hash(SINGLETON_TOP_LAYER_V1_1_HASH, [struct_hash, inner])


def _slots_node(state: JuliaDidState) -> Node:
    node: Node = b""
    for slot in reversed(state.raw):
        node = (slot, node)
    return node


def _launcher_ph() -> bytes:
    from .chain import SINGLETON_LAUNCHER_PH
    return SINGLETON_LAUNCHER_PH


def verify_state(state: JuliaDidState, current_coin_puzzle_hash: bytes) -> bool:
    return expected_puzzle_hash(state) == current_coin_puzzle_hash


def revealed_keys_from_spend(spend: CoinSpend, state: JuliaDidState) -> List[bytes]:
    """BLS public keys revealed in the most recent spend's solution.

    These are candidates for the spec §8.2 enumeration rule. A key revealed
    in the spend's authorization path proves membership in the root that was
    current *at that spend*; it is only offered as a candidate when the spend
    left the authentication configuration unchanged, so the proof carries to
    the current root.
    """
    solution = deserialize(spend.solution)
    try:
        outer = to_list(solution)              # (lineage_proof amount inner_solution)
        inner = to_list(outer[2])              # (curried-args parent-info solution)
        own_auth = to_list(inner[0])[3]
    except (ValueError, IndexError):
        return []
    if sha256tree(own_auth) != sha256tree(state.raw[3]):
        return []

    keys: List[bytes] = []

    def walk(node: Node) -> None:
        if isinstance(node, bytes):
            if len(node) == BLS_G1_SIZE and node not in keys:
                keys.append(node)
        else:
            walk(node[0])
            walk(node[1])

    walk(inner[2] if len(inner) > 2 else b"")
    return keys


def genesis_public_key(client: FullNodeClient, lineage: SingletonLineage) -> Optional[bytes]:
    """Extract the DID's original BLS12-381 G1 public key from the prelauncher
    puzzle reveal (spec §7.1). Returns None when the parent coin is not a
    recognizable did:julia prelauncher.

    The reveal is authenticated by consensus: its tree hash must equal the
    prelauncher coin's on-chain puzzle hash.
    """
    pre = lineage.prelauncher
    if not pre.spent:
        return None
    spend = client.get_puzzle_and_solution(pre.coin.coin_id(), pre.spent_block_index)
    puzzle = deserialize(spend.puzzle_reveal)
    if sha256tree(puzzle) != pre.coin.puzzle_hash:
        raise StateError("prelauncher puzzle reveal does not hash to its coin puzzle hash")
    uncurried = uncurry(puzzle)
    if uncurried is None:
        return None
    _mod, args = uncurried
    keys = [a for a in args if isinstance(a, bytes) and len(a) == BLS_G1_SIZE]
    if len(keys) != 1:
        return None
    return keys[0]
