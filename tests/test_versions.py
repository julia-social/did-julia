"""Spec §7.2.1: version-specific resolution.

A did:julia version ID is the coin ID of a singleton generation (§8.5), so a
version request names a coin and the answer is checked against that coin's own
puzzle hash — the same commitment current-state resolution checks, applied to
the generation the caller asked for. Every case here replays the committed
mainnet recordings offline.
"""

import json

import pytest

from did_julia import resolve
from did_julia.chain import trace_history
from did_julia.identifier import parse
from did_julia.state import StateError, revealed_state_from_spend

from conftest import FIXTURES, FixtureClient

ALIAS_DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"
ORG_DID = "did:julia:BqJasSrzc9aGJmU4U3A2z4XrqozAAMiMhnqHaq4F2cDc"

ALIAS_GEN1 = "0xe3d06a75d3e2c9ed7b71e18646dbf900d17d0cc55fd6584539ea9f72c01f58aa"
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


@pytest.mark.parametrize(
    "version_time",
    ["yesterday", "2026-08-01", "2026-08-01T00:00:00", "2026-13-01T00:00:00Z"],
)
def test_malformed_version_time_is_an_invalid_did_url(version_time):
    meta = resolve(ORG_DID, client=None, version_time=version_time)[
        "didResolutionMetadata"
    ]
    assert meta["error"] == "invalidDidUrl"


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
