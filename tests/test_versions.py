"""Spec §7.2.1: version-specific resolution.

A did:julia version ID is the coin ID of a singleton generation (§8.5), so a
version request names a coin and the answer is checked against that coin's own
puzzle hash — the same commitment current-state resolution checks, applied to
the generation the caller asked for. Every case here replays the committed
mainnet recordings offline.
"""

import json

import pytest

from did_julia import _parse_version_time, resolve
from did_julia.chain import trace_history
from did_julia.identifier import parse
from did_julia.state import (
    StateError,
    extract_state_from_spend,
    revealed_state_from_spend,
    verify_state,
)

from conftest import FIXTURES, FixtureClient

ALIAS_DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"
ORG_DID = "did:julia:BqJasSrzc9aGJmU4U3A2z4XrqozAAMiMhnqHaq4F2cDc"

ALIAS_GEN1 = "0xe3d06a75d3e2c9ed7b71e18646dbf900d17d0cc55fd6584539ea9f72c01f58aa"
ALIAS_GEN2 = "0x0e04c04dbb693f72eb5151753bf7b69ec468476945fe50d684e03609cf390f29"
ALIAS_GEN3 = "0x6db248a37284af64ddc068ee80968363c96d1929ba006e3dc514312e34d2ac33"
ORG_GEN1 = "0xa61c53bf8dd53c55da7d5ac8b53667c00ca36c87370c67497f20e79cc72e4084"
ORG_GEN2 = "0x172f7246668c6cf8836e2379fde00006aaefc8543e2ce79a0b021a13fbcc69e6"
ORG_GEN3 = "0x2af60aad4e7519bf9ee3eb0fd5624aaf608b066f51bb506207af35f6a0299ca5"
ORG_GEN4 = "0xf295281cc99108b6c64fc71952cf2419da8df2830b1bd6842b44bc41a94ab75c"


@pytest.fixture
def alias_client() -> FixtureClient:
    return FixtureClient("rpc_calls_ArD2.json")


@pytest.fixture
def org_client() -> FixtureClient:
    return FixtureClient("rpc_calls_julia_org.json")


def _expected(name: str) -> dict:
    with open(FIXTURES / f"expected_version_{name}.json") as f:
        return json.load(f)


# --- resolution by version ID -------------------------------------------


@pytest.mark.parametrize(
    "fixture,did,version",
    [
        ("ArD2_gen1", ALIAS_DID, ALIAS_GEN1),
        ("ArD2_gen2", ALIAS_DID, ALIAS_GEN2),
        ("julia_org_gen1", ORG_DID, ORG_GEN1),
        ("julia_org_gen2", ORG_DID, ORG_GEN2),
        ("julia_org_gen3", ORG_DID, ORG_GEN3),
    ],
)
def test_version_id_matches_recorded_result(request, fixture, did, version):
    client = request.getfixturevalue(
        "alias_client" if did == ALIAS_DID else "org_client"
    )
    assert resolve(did, client=client, version_id=version) == _expected(fixture)


def test_every_generation_verifies_against_its_own_coin(org_client):
    """The state served for a superseded generation is the one that coin's
    puzzle hash commits to — the check is not weakened for history."""
    for version in (ORG_GEN1, ORG_GEN2, ORG_GEN3, ORG_GEN4):
        result = resolve(ORG_DID, client=org_client, version_id=version)
        assert result["didResolutionMetadata"]["did:julia:stateVerified"] is True
        assert result["didDocumentMetadata"]["versionId"] == version
        assert result["didDocument"]["id"] == ORG_DID


def test_version_id_accepts_an_unprefixed_coin_id(org_client):
    assert resolve(
        ORG_DID, client=org_client, version_id=ORG_GEN2[2:]
    ) == _expected("julia_org_gen2")


def test_superseded_version_reports_what_replaced_it(org_client):
    meta = resolve(ORG_DID, client=org_client, version_id=ORG_GEN2)[
        "didDocumentMetadata"
    ]
    assert meta["nextVersionId"] == ORG_GEN3
    # gen 3 is the block after gen 2, so its confirmation is when gen 2 stopped
    # being the current version.
    assert meta["nextUpdate"] == "2026-07-30T16:11:07Z"
    assert meta["created"] == "2026-07-30T15:23:35Z"


def test_current_version_has_no_successor(org_client):
    meta = resolve(ORG_DID, client=org_client, version_id=ORG_GEN4)[
        "didDocumentMetadata"
    ]
    assert meta["versionId"] == ORG_GEN4
    assert "nextVersionId" not in meta
    assert "nextUpdate" not in meta


def test_resolving_the_current_version_by_id_agrees_with_plain_resolution(
    org_client,
):
    versioned = resolve(ORG_DID, client=org_client, version_id=ORG_GEN4)
    current = resolve(ORG_DID, client=FixtureClient("rpc_calls_julia_org.json"))
    assert versioned["didDocument"] == current["didDocument"]
    assert versioned["didResolutionMetadata"] == current["didResolutionMetadata"]
    # Only the history a version request walks is reported in addition.
    assert versioned["didDocumentMetadata"] == {
        **current["didDocumentMetadata"],
        "created": "2026-07-30T15:23:35Z",
    }


# --- resolution by version time -----------------------------------------


def test_version_time_selects_the_version_current_at_that_moment(org_client):
    assert resolve(
        ORG_DID, client=org_client, version_time="2026-08-01T00:00:00Z"
    ) == _expected("julia_org_gen3")


def test_version_time_after_the_last_update_is_the_current_version(org_client):
    assert resolve(
        ORG_DID, client=org_client, version_time="2026-09-01T00:00:00Z"
    ) == _expected("julia_org_current")


def test_version_time_ties_resolve_to_the_later_generation(org_client):
    """Generations 1 and 2 were confirmed in the same block. The state that
    block left behind is generation 2's."""
    meta = resolve(
        ORG_DID, client=org_client, version_time="2026-07-30T15:23:35Z"
    )["didDocumentMetadata"]
    assert meta["versionId"] == ORG_GEN2


def test_version_time_accepts_an_explicit_offset(org_client):
    with_offset = resolve(
        ORG_DID, client=org_client, version_time="2026-07-31T20:00:00-04:00"
    )
    assert with_offset["didDocumentMetadata"]["versionId"] == ORG_GEN3


def test_version_time_before_the_did_existed_is_not_found(org_client):
    meta = resolve(
        ORG_DID, client=org_client, version_time="2026-05-01T00:00:00Z"
    )["didResolutionMetadata"]
    assert meta["error"] == "notFound"
    assert "first version was confirmed at 2026-07-30T15:23:35Z" in (
        meta["errorMessage"]
    )


# --- refusals ------------------------------------------------------------


def test_unknown_version_id_is_not_found(org_client):
    meta = resolve(ORG_DID, client=org_client, version_id="0x" + "11" * 32)[
        "didResolutionMetadata"
    ]
    assert meta["error"] == "notFound"


@pytest.mark.parametrize(
    "version_id", ["", "0x", "abcd", "0x" + "zz" * 32, "0x" + "11" * 31]
)
def test_malformed_version_id_is_an_invalid_did_url(version_id):
    meta = resolve(ORG_DID, client=None, version_id=version_id)[
        "didResolutionMetadata"
    ]
    assert meta["error"] == "invalidDidUrl"


# Kept identical, case for case, to the list in the TypeScript suite: the two
# resolvers must agree about which requests are even valid, and a date that does
# not exist must be refused rather than rolled forward into one that does. A
# resolver that answered "2026-02-30" with the version current on 2026-03-02
# would be answering a different question than the caller asked.
REFUSED_TIMES = [
    "yesterday",
    "",
    "2026-08-01",  # date only, no time
    "2026-08-01T00:00:00",  # no UTC designator or offset
    "2026-13-01T00:00:00Z",  # month 13
    "2026-00-10T00:00:00Z",  # month 0
    "2026-01-32T00:00:00Z",  # day 32
    "2026-01-00T00:00:00Z",  # day 0
    "2026-02-30T00:00:00Z",  # February has no 30th
    "2026-04-31T00:00:00Z",  # April has no 31st
    "2026-02-29T00:00:00Z",  # 2026 is not a leap year
    "2100-02-29T00:00:00Z",  # nor is 2100 — divisible by 100, not by 400
    "2026-01-01T25:00:00Z",  # hour 25
    "2026-01-01T23:60:00Z",  # minute 60
    "2026-01-01T23:59:60Z",  # leap second
    "2026-08-01T24:00:01Z",  # hour 24 is the end-of-day form only
    "2026-08-01T24:30:00Z",
    "2026-08-01T24:00:00.5Z",  # a non-zero fraction is not end-of-day
    "2026-01-01T00:00:00+14:01",  # beyond XML Schema's ±14:00
    "2026-01-01T00:00:00+23:59",
    "2026-01-01T00:00:00-14:30",
    "2026-01-01T00:00:00+25:00",  # impossible offset
    "2026-01-01T00:00:00+00:60",  # impossible offset minutes
    "2026-01-01T00:00:00-99:99",
    "0000-01-01T00:00:00Z",  # XML Schema's 1 BCE, outside 0001..9999
    "9999-12-31T24:00:00Z",  # end of day here names midnight of year 10000
]


@pytest.mark.parametrize("version_time", REFUSED_TIMES)
def test_malformed_version_time_is_an_invalid_did_url(version_time):
    meta = resolve(ORG_DID, client=None, version_time=version_time)[
        "didResolutionMetadata"
    ]
    assert meta["error"] == "invalidDidUrl"


@pytest.mark.parametrize(
    "version_time", ["2028-02-29T00:00:00Z", "2000-02-29T00:00:00Z"]
)
def test_real_leap_days_are_accepted(org_client, version_time):
    """The refusals above are about dates that do not exist, not about February
    29th: 2028 is a leap year, and 2000 is one under the 400-year rule."""
    meta = resolve(ORG_DID, client=org_client, version_time=version_time)[
        "didResolutionMetadata"
    ]
    assert meta.get("error") in (None, "notFound")
    assert meta.get("error") != "invalidDidUrl"


def test_an_offset_time_and_its_utc_equivalent_select_the_same_version(
    org_client,
):
    same = [
        resolve(ORG_DID, client=org_client, version_time=t)["didDocumentMetadata"][
            "versionId"
        ]
        for t in ("2026-08-01T00:00:00Z", "2026-07-31T20:00:00-04:00")
    ]
    assert same[0] == same[1]


@pytest.mark.parametrize(
    "version_time",
    [
        "2026-01-01T00:00:00+14:00",
        "2026-01-01T00:00:00-14:00",
        "2026-01-01T00:00:00+13:59",
    ],
)
def test_offsets_within_the_xml_schema_range_are_accepted(org_client, version_time):
    """±14:00 is the edge of XML Schema's timezone range, and the edge of the
    range real timezones occupy — it is admitted, and only past it is not."""
    meta = resolve(ORG_DID, client=org_client, version_time=version_time)[
        "didResolutionMetadata"
    ]
    assert meta.get("error") != "invalidDidUrl"


def test_end_of_day_is_the_next_midnight(org_client):
    """`24:00:00` is XML Schema's end-of-day form (§3.3.8, endOfDayFrag), and
    denotes the following day's midnight. It names one unambiguous instant, so
    honouring it answers the question asked — unlike a date that does not exist,
    which has no instant to name."""
    assert (
        resolve(ORG_DID, client=org_client, version_time="2026-08-01T24:00:00Z")
        == resolve(ORG_DID, client=org_client, version_time="2026-08-02T00:00:00Z")
    )


def test_sub_second_precision_is_truncated_not_rejected(org_client):
    assert (
        resolve(ORG_DID, client=org_client, version_time="2026-08-01T00:00:00.500Z")
        == resolve(ORG_DID, client=org_client, version_time="2026-08-01T00:00:00Z")
    )


def test_version_id_and_version_time_are_mutually_exclusive():
    meta = resolve(
        ORG_DID,
        client=None,
        version_id=ORG_GEN2,
        version_time="2026-08-01T00:00:00Z",
    )["didResolutionMetadata"]
    assert meta["error"] == "unsupportedResolutionOption"
    assert "mutually exclusive" in meta["errorMessage"]


def test_a_malformed_did_is_rejected_before_any_version_option():
    meta = resolve("did:julia:not-base58!", version_id="nonsense")[
        "didResolutionMetadata"
    ]
    assert meta["error"] == "invalidDid"


# --- the revealed-state route itself -------------------------------------


def test_revealed_state_must_recompute_to_its_own_coins_puzzle_hash(org_client):
    """The route is self-checking: offer the spend against any other coin and
    it fails closed rather than serving state that coin never held.

    (Generations 2, 3 and 4 of this DID share a puzzle hash — the singleton was
    re-spent without changing state — so the coin substituted here is one with
    a genuinely different commitment.)"""
    launcher_id = parse(ORG_DID)
    history = trace_history(org_client, launcher_id)
    gen2 = history.generations[1]
    spend = org_client.get_puzzle_and_solution(
        gen2.coin.coin_id(), gen2.spent_block_index
    )
    other = bytearray(gen2.coin.puzzle_hash)
    other[0] ^= 0xFF
    with pytest.raises(StateError):
        revealed_state_from_spend(spend, bytes(other), launcher_id)


def test_revealed_state_must_belong_to_the_did_being_resolved(org_client):
    launcher_id = parse(ORG_DID)
    history = trace_history(org_client, launcher_id)
    gen2 = history.generations[1]
    spend = org_client.get_puzzle_and_solution(
        gen2.coin.coin_id(), gen2.spent_block_index
    )
    with pytest.raises(StateError):
        revealed_state_from_spend(spend, gen2.coin.puzzle_hash, bytes(32))


def test_history_walk_records_every_generation_in_order(org_client):
    history = trace_history(org_client, parse(ORG_DID))
    assert ["0x" + g.coin.coin_id().hex() for g in history.generations] == [
        ORG_GEN1,
        ORG_GEN2,
        ORG_GEN3,
        ORG_GEN4,
    ]
    assert not history.generations[-1].spent
    assert all(g.spent for g in history.generations[:-1])


# --- resolution across a real rekey --------------------------------------
#
# The personal alias was rekeyed on 2026-09-02: generation 3 carries a
# different authentication root, and a different singleton puzzle hash, from
# the two before it. It is the first mainnet state *change* either resolver
# has been tested against — every other recording is a spend that left state
# untouched — so these cases guard the transition machinery itself.


def test_the_rekey_changed_the_authentication_root(alias_client):
    before = resolve(ALIAS_DID, client=alias_client, version_id=ALIAS_GEN2)
    after = resolve(ALIAS_DID, client=alias_client, version_id=ALIAS_GEN3)
    root = lambda r: r["didDocument"]["juliaAuthentication"]["merkleRoot"]
    assert root(before) != root(after)
    # Both sides of the change are served only under their own coin's hash.
    for result in (before, after):
        assert result["didResolutionMetadata"]["did:julia:stateVerified"] is True


def test_the_rekey_is_the_generation_the_history_chains_to(alias_client):
    meta = resolve(ALIAS_DID, client=alias_client, version_id=ALIAS_GEN2)[
        "didDocumentMetadata"
    ]
    assert meta["nextVersionId"] == ALIAS_GEN3
    assert meta["nextUpdate"] == "2026-09-02T11:34:09Z"


def test_a_retired_key_is_listed_for_the_versions_it_governed(alias_client):
    """The method's point: a signature made under a key that has since been
    rotated out still verifies, because the version that was current when it
    was made still resolves to that key."""
    governed = resolve(ALIAS_DID, client=alias_client, version_id=ALIAS_GEN2)[
        "didDocument"
    ]
    current = resolve(ALIAS_DID, client=alias_client)["didDocument"]
    assert len(governed["verificationMethod"]) == 1
    assert "verificationMethod" not in current


def test_the_post_rekey_state_is_derived_not_revealed(alias_client):
    """Generation 3 is unspent, so its state cannot be read from a spend of its
    own — it is derived from the rekey spend and accepted only because it
    reproduces generation 3's on-chain puzzle hash."""
    launcher_id = parse(ALIAS_DID)
    history = trace_history(alias_client, launcher_id)
    assert len(history.generations) == 3
    current = history.generations[-1]
    assert not current.spent
    parent = history.generations[-2]
    assert parent.coin.puzzle_hash != current.coin.puzzle_hash
    spend = alias_client.get_puzzle_and_solution(
        parent.coin.coin_id(), parent.spent_block_index
    )
    # The spend reveals the OLD state; the new one is not in it verbatim.
    revealed = revealed_state_from_spend(
        spend, parent.coin.puzzle_hash, launcher_id
    )
    assert not verify_state(revealed, current.coin.puzzle_hash)
    derived = extract_state_from_spend(spend, launcher_id)
    assert verify_state(derived, current.coin.puzzle_hash)
    assert (
        derived.authentication.merkle_root != revealed.authentication.merkle_root
    )


# --- the instant a version time denotes ----------------------------------
#
# Kept identical to the table in the TypeScript suite. Resolution outcome alone
# cannot police this: every year before the DID existed answers `notFound`
# whether it was read as 0001 or as 1901, so the arithmetic has to be asserted
# where it can be seen. `Date.UTC` applies a legacy 1900 offset to years 0..99,
# which is exactly the kind of silent substitution that stays invisible through
# the public API.

VERSION_TIME_EPOCHS = [
    ("0001-01-01T00:00:00Z", -62135596800),
    ("0099-01-01T00:00:00Z", -59042995200),
    ("1901-01-01T00:00:00Z", -2177452800),
    ("1970-01-01T00:00:00Z", 0),
    ("2026-09-02T11:34:09Z", 1788348849),
    ("2026-08-01T24:00:00Z", 1785628800),
    ("2026-08-02T00:00:00Z", 1785628800),
    ("2026-01-01T00:00:00+14:00", 1767175200),
    ("2026-01-01T00:00:00-14:00", 1767276000),
    ("9999-12-31T23:59:59Z", 253402300799),
]


@pytest.mark.parametrize("version_time,epoch", VERSION_TIME_EPOCHS)
def test_version_time_denotes_the_expected_instant(version_time, epoch):
    assert _parse_version_time(version_time) == epoch


def test_a_version_time_at_the_edge_of_the_range_cannot_escape_as_an_exception(
    org_client,
):
    """Date arithmetic at the boundary raises OverflowError rather than
    ValueError. A version request must always come back as a resolution
    result — an exception through the caller's stack is not one."""
    result = resolve(
        ORG_DID, client=org_client, version_time="9999-12-31T24:00:00Z"
    )
    assert result["didDocument"] is None
    assert result["didResolutionMetadata"]["error"] == "invalidDidUrl"
