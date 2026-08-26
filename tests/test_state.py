"""Spec §6/§7.2: state extraction and verification against real mainnet data."""

from did_julia.chain import trace_singleton
from did_julia.identifier import parse
from did_julia.state import (
    extract_state_from_spend,
    genesis_public_key,
    verify_state,
)

DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"


def _state_and_lineage(client):
    launcher_id = parse(DID)
    lineage = trace_singleton(client, launcher_id)
    spend = client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    return extract_state_from_spend(spend, launcher_id), lineage


def test_eight_slot_state_parses(mainnet_client):
    state, _ = _state_and_lineage(mainnet_client)
    assert state.launcher_id == parse(DID)
    assert state.recovery_delay == 0
    assert not state.recovery_pending
    assert state.custodians == []
    assert state.recovery_configured
    auth = state.authentication
    assert auth is not None
    assert auth.required_classes == 1
    assert auth.class_depth == 1
    assert len(auth.classes) == 1
    assert auth.classes[0].required_members == 1


def test_state_verifies_against_onchain_puzzle_hash(mainnet_client):
    state, lineage = _state_and_lineage(mainnet_client)
    assert verify_state(state, lineage.current.coin.puzzle_hash)


def test_state_verification_catches_tampering(mainnet_client):
    state, lineage = _state_and_lineage(mainnet_client)
    assert not verify_state(state, b"\x00" * 32)


def test_genesis_public_key_authenticated_by_consensus(mainnet_client):
    state, lineage = _state_and_lineage(mainnet_client)
    key = genesis_public_key(mainnet_client, lineage)
    assert key is not None and len(key) == 48


def test_not_deactivated(mainnet_client):
    state, _ = _state_and_lineage(mainnet_client)
    assert not state.deactivated
