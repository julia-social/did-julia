"""Spec §6.2: multi-class multisig, tested against the production Julia
Social DID — two required classes (2-of-N founders and 1-of-N airgapped)
on the current puzzle version."""

import json

import pytest

from did_julia import resolve
from did_julia.chain import trace_singleton
from did_julia.identifier import parse
from did_julia.state import extract_state_from_spend, verify_state

from conftest import FIXTURES, FixtureClient

ORG_DID = "did:julia:BqJasSrzc9aGJmU4U3A2z4XrqozAAMiMhnqHaq4F2cDc"


@pytest.fixture
def org_client() -> FixtureClient:
    return FixtureClient("rpc_calls_julia_org.json")


def _state_and_lineage(client, did):
    launcher_id = parse(did)
    lineage = trace_singleton(client, launcher_id)
    spend = client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    return extract_state_from_spend(spend, launcher_id), lineage


def test_org_full_resolution_matches_expected(org_client):
    with open(FIXTURES / "expected_resolution_julia_org.json") as f:
        expected = json.load(f)
    assert resolve(ORG_DID, client=org_client) == expected


def test_org_multiclass_configuration(org_client):
    state, lineage = _state_and_lineage(org_client, ORG_DID)
    auth = state.authentication
    assert auth.required_classes == 2
    assert auth.class_depth == 1
    assert sorted(c.required_members for c in auth.classes) == [1, 2]
    assert verify_state(state, lineage.current.coin.puzzle_hash)
    assert not state.deactivated


def test_org_runs_current_puzzle(org_client):
    meta = resolve(ORG_DID, client=org_client)["didResolutionMetadata"]
    assert meta["did:julia:currentPuzzle"] is True
    assert meta["did:julia:stateVerified"] is True


def test_org_document_publishes_commitment_without_keys(org_client):
    """Per spec §8.2, no verification method is listed unless membership in
    the current root is proven; multi-key path replay is a documented v1
    gap, so the multiclass document carries the commitment only."""
    doc = resolve(ORG_DID, client=org_client)["didDocument"]
    assert "verificationMethod" not in doc
    assert doc["juliaAuthentication"]["requiredClasses"] == 2
    assert len(doc["juliaAuthentication"]["classes"]) == 2


def test_org_recovery_configuration(org_client):
    """The production DID has one recovery-agent class requiring one
    participant (a 1440-block time-lock) and a pre-rotation commitment to
    the all-zero 48-octet value — the sentinel that marks the pre-rotation
    path disabled, since 48 zero octets is not a valid BLS12-381 key."""
    state, _ = _state_and_lineage(org_client, ORG_DID)
    rec = state.recovery
    assert rec.parsed and rec.agents_configured
    assert rec.delay_blocks == 1440
    assert rec.prerotation == "disabled"


def test_recovery_agents_differ_between_org_and_alias(org_client):
    """The org DID and the example personal alias have different
    recovery-agent commitments: they do not share a recovery DID."""
    alias_client = FixtureClient("rpc_calls_ArD2.json")
    alias_did = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"
    org_state, _ = _state_and_lineage(org_client, ORG_DID)
    alias_state, _ = _state_and_lineage(alias_client, alias_did)
    assert org_state.recovery.agents_merkle_root != alias_state.recovery.agents_merkle_root
    # while both share the disabled-prerotation sentinel
    assert org_state.recovery.prerotation == alias_state.recovery.prerotation == "disabled"
