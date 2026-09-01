"""did:julia reference resolver.

    from did_julia import resolve
    result = resolve("did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX")
    print(result["didDocument"])

Resolution reads public Chia blockchain state (spec §7.2) through any full
node RPC — by default the open Coinset endpoint, or a local node via
``FullNodeClient``. No did:julia-specific service is contacted.

Version-specific resolution (spec §7.2.1) is supported through the
``versionId`` and ``versionTime`` DID parameters::

    resolve(did, version_time="2026-08-01T00:00:00Z")
    resolve(did, version_id="0x2af60aad…")
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from . import identifier
from .chain import (
    ChainError,
    CoinRecord,
    FullNodeClient,
    NotFoundError,
    SingletonHistory,
    trace_history,
    trace_singleton,
)
from .diddoc import build_document, error_result, not_found, resolution_result
from .state import (
    CURRENT_JULIA_DID_PUZZLE_HASH,
    JuliaDidState,
    StateError,
    extract_state_from_spend,
    genesis_public_key,
    revealed_keys_from_spend,
    revealed_state_from_spend,
    verify_state,
)

__version__ = "0.1.0"
__all__ = ["resolve", "FullNodeClient", "identifier"]

_FRACTION = re.compile(r"\.(\d+)")


def _parse_version_id(value: str) -> bytes:
    """A did:julia version ID is the coin ID of a singleton generation
    (spec §8.5): 32 octets, hex, with or without a ``0x`` prefix."""
    text = value.strip()
    if text[:2].lower() == "0x":
        text = text[2:]
    if len(text) != 64:
        raise ValueError(
            "a did:julia versionId is a 32-octet coin ID in hex "
            f"(64 hex digits); got {len(text)}"
        )
    return bytes.fromhex(text)


def _parse_version_time(value: str) -> int:
    """XML datetime -> POSIX seconds. Sub-second precision is truncated: the
    DID Resolution specification requires datetimes without it, and a Chia
    block's timestamp has one-second resolution anyway."""
    text = _FRACTION.sub("", value.strip(), count=1)
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(
            "versionTime must carry a UTC designator or an explicit offset"
        )
    return int(parsed.astimezone(timezone.utc).timestamp())


def _select_generation(
    history: SingletonHistory,
    did: str,
    version_id: Optional[bytes],
    version_time: Optional[int],
) -> int:
    """Index of the generation a version request names (spec §7.2.1)."""
    generations = history.generations
    if version_id is not None:
        for index, record in enumerate(generations):
            if record.coin.coin_id() == version_id:
                return index
        raise NotFoundError(
            f"no generation of {did} has version ID 0x{version_id.hex()}"
        )

    # The latest generation confirmed at or before the requested time. Several
    # generations can share a timestamp (a singleton may be spent more than
    # once in one block); the last of them is the state that block left behind.
    selected = None
    for index, record in enumerate(generations):
        if record.timestamp and record.timestamp <= version_time:
            selected = index
    if selected is None:
        first = generations[0].timestamp
        raise NotFoundError(
            f"{did} had no version at the requested time; its first version "
            f"was confirmed at "
            f"{datetime.fromtimestamp(first, tz=timezone.utc):%Y-%m-%dT%H:%M:%SZ}"
        )
    return selected


def _state_of_generation(
    client: FullNodeClient,
    launcher_id: bytes,
    record: CoinRecord,
    parent: CoinRecord,
) -> Tuple[JuliaDidState, List[bytes]]:
    """State held by one singleton generation, and the public keys its own
    spend record offers as verification-method candidates.

    A superseded generation reveals its state in its own spend, which the
    coin's puzzle commits to (spec §7.2.1). The unspent current generation
    has no spend of its own, so its state is read from the REMARK its parent's
    spend emitted (spec §7.2).
    """
    if record.spent:
        spend = client.get_puzzle_and_solution(
            record.coin.coin_id(), record.spent_block_index
        )
        state = revealed_state_from_spend(
            spend, record.coin.puzzle_hash, launcher_id
        )
    else:
        spend = client.get_puzzle_and_solution(
            parent.coin.coin_id(), parent.spent_block_index
        )
        state = extract_state_from_spend(spend, launcher_id)
    return state, revealed_keys_from_spend(spend, state)


def resolve(
    did: str,
    client: Optional[FullNodeClient] = None,
    version_id: Optional[str] = None,
    version_time: Optional[str] = None,
) -> dict:
    """Resolve a did:julia DID to a DID resolution result (spec §7.2, §8).

    Returns a dict with ``didDocument``, ``didDocumentMetadata``, and
    ``didResolutionMetadata``. On failure the document is None and
    ``didResolutionMetadata.error`` is set (``invalidDid`` / ``invalidDidUrl``
    / ``notFound`` / ``internalError``).

    ``version_id`` and ``version_time`` are the ``versionId`` and
    ``versionTime`` DID parameters (spec §7.2.1). They are mutually exclusive,
    as the DID Resolution specification requires. Given either, the result is
    the DID Document of the singleton generation that version names, with the
    document metadata that places it in the DID's history.
    """
    try:
        launcher_id = identifier.parse(did)
    except identifier.InvalidDidError as e:
        return error_result("invalidDid", str(e))

    if version_id is not None and version_time is not None:
        return error_result(
            "unsupportedResolutionOption",
            "versionId and versionTime are mutually exclusive; supply at "
            "most one",
        )
    target_id: Optional[bytes] = None
    target_time: Optional[int] = None
    try:
        if version_id is not None:
            target_id = _parse_version_id(version_id)
        if version_time is not None:
            target_time = _parse_version_time(version_time)
    except ValueError as e:
        return error_result("invalidDidUrl", str(e))

    versioned = target_id is not None or target_time is not None
    client = client or FullNodeClient()
    try:
        if versioned:
            history = trace_history(client, launcher_id)
            index = _select_generation(history, did, target_id, target_time)
            record = history.generations[index]
            parent = (
                history.generations[index - 1] if index else history.launcher
            )
            following = (
                history.generations[index + 1]
                if index + 1 < len(history.generations)
                else None
            )
            created = history.generations[0].timestamp
        else:
            lineage = trace_singleton(client, launcher_id)
            history = None
            record, parent, following, created = (
                lineage.current,
                lineage.parent,
                None,
                None,
            )

        state, candidates = _state_of_generation(
            client, launcher_id, record, parent
        )
        genesis_key = genesis_public_key(
            client,
            history.lineage() if history is not None else lineage,
        )
        if genesis_key is not None:
            candidates.append(genesis_key)
    except NotFoundError as e:
        return not_found(str(e))
    except (ChainError, StateError) as e:
        return error_result("internalError", str(e))

    verified = verify_state(state, record.coin.puzzle_hash)
    document = build_document(state, candidate_keys=candidates)
    return resolution_result(
        state,
        document,
        version_coin_id=record.coin.coin_id(),
        confirmed_timestamp=record.timestamp,
        verified=verified,
        current_puzzle=state.julia_did_puzzle_hash == CURRENT_JULIA_DID_PUZZLE_HASH,
        created_timestamp=created,
        next_version_coin_id=(
            following.coin.coin_id() if following is not None else None
        ),
        next_timestamp=following.timestamp if following is not None else None,
    )
