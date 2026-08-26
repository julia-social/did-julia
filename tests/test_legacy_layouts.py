"""Predecessor-puzzle state layouts, covered synthetically.

Earlier deployments of the protocol used a 5-element recovery-info (no
pre-rotation slot). The resolver reports such configurations coarsely
(present, no details) rather than failing. Live legacy coins exist on
mainnet but are not used as fixtures."""

from dataclasses import replace

from did_julia.diddoc import build_document
from did_julia.chain import trace_singleton
from did_julia.identifier import parse
from did_julia.state import _parse_recovery, extract_state_from_spend

DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"


def _to_node(items):
    node = b""
    for item in reversed(items):
        node = (item, node)
    return node


def test_five_element_recovery_info_parses_coarsely():
    # (classes class-depth required-classes required-root delay) — the
    # pre-prerotation layout: first element is a list, not a prerotation
    # multisig-info, so the 6-element destructure does not apply.
    legacy = _to_node([
        _to_node([(b"\x11" * 32, b"\x01")]),  # classes
        b"\x01",                               # class-depth
        b"\x01",                               # required-classes
        b"\x22" * 32,                          # required-root
        b"",                                   # delay (empty atom)
    ])
    rec = _parse_recovery(legacy)
    assert rec is not None
    assert not rec.parsed
    assert not rec.agents_configured
    assert rec.prerotation is None


def test_coarse_recovery_reported_as_configured_only(mainnet_client):
    launcher_id = parse(DID)
    lineage = trace_singleton(mainnet_client, launcher_id)
    spend = mainnet_client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    state = extract_state_from_spend(spend, launcher_id)
    legacy_rec = _parse_recovery(_to_node([_to_node([]), b"", b"", b"", b""]))
    coarse = replace(state, recovery=legacy_rec)
    doc = build_document(coarse, candidate_keys=[])
    assert doc["juliaRecovery"] == {"configured": True}
    # an unrecognized layout is conservatively a live control path
    assert not replace(coarse, authentication=None, custodians=[]).deactivated
