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
from datetime import datetime, timedelta, timezone
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

# An XML Schema dateTime with a timezone, the form DID Resolution requires.
# The fields are validated below rather than handed to a parser:
# `datetime.fromisoformat` accepts basic-format strings on Python 3.11+ and
# rejects them on 3.10, so relying on it would make this resolver's contract
# depend on the interpreter it happens to run under.
_XML_DATETIME = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"T(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?:[Zz]|(?P<sign>[+-])(?P<offset_hour>\d{2}):(?P<offset_minute>\d{2}))$"
)

_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _days_in_month(year: int, month: int) -> int:
    if month == 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        return 29
    return _MONTH_LENGTHS[month - 1]


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
    """XML datetime -> POSIX seconds.

    Every field is range-checked against the calendar, so a date that does not
    exist is rejected rather than rolled forward into one that does: a resolver
    that answered ``2026-02-30`` with the version current on 2026-03-02 would be
    answering a different question than the caller asked, which is the one
    failure they cannot detect.

    Sub-second precision is truncated — the DID Resolution specification
    requires datetimes without it, and a Chia block's timestamp has one-second
    resolution anyway.
    """
    match = _XML_DATETIME.match(value.strip())
    if match is None:
        raise ValueError(
            "versionTime must be an XML datetime carrying a UTC designator or "
            f"an explicit offset; got {value!r}"
        )
    year, month, day, hour, minute, second = (
        int(match.group(name))
        for name in ("year", "month", "day", "hour", "minute", "second")
    )
    if not 1 <= month <= 12:
        raise ValueError(f"versionTime month must be in 1..12; got {month}")
    if not 1 <= day <= _days_in_month(year, month):
        raise ValueError(
            f"versionTime day {day} does not exist in month {month} of {year}"
        )

    # `24:00:00` is XML Schema's end-of-day form and denotes the following
    # day's midnight (xmlschema11-2 §3.3.8, endOfDayFrag). It is a defined
    # lexical mapping onto one unambiguous instant, not a value being coerced
    # into a different one, so honouring it answers exactly the question asked.
    fraction = match.group("fraction")
    end_of_day = hour == 24
    if end_of_day:
        if minute or second or (fraction is not None and set(fraction) != {"0"}):
            raise ValueError(
                "versionTime hour 24 is only the end-of-day form 24:00:00"
            )
    elif hour > 23 or minute > 59 or second > 59:
        raise ValueError(
            f"versionTime {hour:02d}:{minute:02d}:{second:02d} is not a time of day"
        )

    offset = timezone.utc
    if match.group("sign") is not None:
        offset_hour = int(match.group("offset_hour"))
        offset_minute = int(match.group("offset_minute"))
        # XML Schema admits offsets of ±00:00 through ±13:59, plus exactly
        # ±14:00 — the range real timezones occupy. Anything wider is not an
        # XML datetime, whatever instant it might seem to denote.
        if not (
            (offset_hour <= 13 and offset_minute <= 59)
            or (offset_hour == 14 and offset_minute == 0)
        ):
            raise ValueError(
                f"versionTime carries a UTC offset outside XML Schema's "
                f"±14:00 range: {match.group('sign')}"
                f"{offset_hour:02d}:{offset_minute:02d}"
            )
        delta = timedelta(hours=offset_hour, minutes=offset_minute)
        offset = timezone(-delta if match.group("sign") == "-" else delta)

    moment = datetime(
        year, month, day, 0 if end_of_day else hour, minute, second, tzinfo=offset
    )
    if end_of_day:
        moment += timedelta(days=1)
    return int(moment.timestamp())


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
