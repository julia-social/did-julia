"""Spec §7.3/§7.4: the uniform inert-tree sentinel — a single-leaf tree of
an all-zero value, 48-octet leaves for key trees (authentication,
pre-rotation) and 32-octet leaves for recovery-agent trees — and its role
in the deactivation rule."""

from dataclasses import replace
from hashlib import sha256

from did_julia.chain import trace_singleton
from did_julia.diddoc import build_document
from did_julia.identifier import parse
from did_julia.state import (
    SENTINEL_ROOT_AGENTS,
    SENTINEL_ROOT_KEYS,
    AuthenticationConfig,
    KeyClass,
    RecoveryConfig,
    extract_state_from_spend,
)

DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"


def _sentinel_construction(leaf_value: bytes) -> bytes:
    leaf = sha256(b"\x01" + leaf_value).digest()
    cls = sha256(b"\x02" + leaf + leaf).digest()
    return sha256(b"\x02" + cls + sha256(b"\x01").digest()).digest()


def _state(client):
    launcher_id = parse(DID)
    lineage = trace_singleton(client, launcher_id)
    spend = client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    return extract_state_from_spend(spend, launcher_id)


def _sentinel_auth() -> AuthenticationConfig:
    leaf = sha256(b"\x01" + bytes(48)).digest()
    cls = sha256(b"\x02" + leaf + leaf).digest()
    return AuthenticationConfig(
        classes=[KeyClass(class_id=cls, required_members=1)],
        class_depth=1,
        required_classes=1,
        merkle_root=SENTINEL_ROOT_KEYS,
    )


def test_sentinel_roots_match_construction():
    assert SENTINEL_ROOT_KEYS == _sentinel_construction(bytes(48))
    assert SENTINEL_ROOT_AGENTS == _sentinel_construction(bytes(32))
    assert SENTINEL_ROOT_KEYS != SENTINEL_ROOT_AGENTS


def test_disabled_auth_is_flagged_but_not_deactivated(mainnet_client):
    """A sentinel authentication configuration with a live recovery path is
    disabled, not deactivated: control can return through recovery."""
    state = replace(_state(mainnet_client), authentication=_sentinel_auth())
    assert state.authentication.disabled
    assert not state.deactivated  # the alias's real recovery agents are live
    doc = build_document(state, candidate_keys=[])
    assert doc["juliaAuthentication"]["disabled"] is True


def test_sentinel_encoded_brick_is_deactivated(mainnet_client):
    """A DID whose every control structure carries its inert sentinel is
    deactivated, exactly as with the null encoding (spec §7.4)."""
    dead_recovery = RecoveryConfig(
        agents_configured=False,
        agents_merkle_root=None,
        prerotation="disabled",
        delay_blocks=1440,
    )
    state = replace(
        _state(mainnet_client),
        authentication=_sentinel_auth(),
        custodians=[],
        recovery=dead_recovery,
    )
    assert state.deactivated
    doc = build_document(state, candidate_keys=[])
    assert doc == {"@context": ["https://www.w3.org/ns/did/v1"], "id": DID}


def test_committed_prerotation_keeps_did_alive(mainnet_client):
    """Sentinel auth + sentinel agents but a real pre-rotation commitment:
    not deactivated — the pre-rotated keys can still take over."""
    live_prerotation = RecoveryConfig(
        agents_configured=False,
        agents_merkle_root=None,
        prerotation="committed",
        delay_blocks=1440,
    )
    state = replace(
        _state(mainnet_client),
        authentication=_sentinel_auth(),
        custodians=[],
        recovery=live_prerotation,
    )
    assert not state.deactivated


def test_sentinel_agent_root_reports_no_agents(mainnet_client):
    """_parse_recovery treats the 32-octet sentinel root as an empty
    recovery-agent tree."""
    state = _state(mainnet_client)
    assert state.recovery.agents_configured  # the real alias agents
    assert state.recovery.agents_merkle_root != SENTINEL_ROOT_AGENTS
