"""Spec §8: DID Document construction and full resolution."""

from dataclasses import replace

from did_julia import resolve
from did_julia.diddoc import build_document, multikey, single_key_root
from did_julia.chain import trace_singleton
from did_julia.identifier import parse
from did_julia.chain import trace_history
from did_julia.state import (
    extract_state_from_spend,
    genesis_public_key,
    revealed_state_from_spend,
)

DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"

# This DID was rekeyed on 2026-09-02 (generation 3), so the genesis key it was
# created with is no longer the key its current authentication root commits to.
# Generation 2 is the last one it does commit to.
PRE_REKEY = "0x0e04c04dbb693f72eb5151753bf7b69ec468476945fe50d684e03609cf390f29"


def test_full_resolution_matches_expected(mainnet_client, expected_resolution):
    assert resolve(DID, client=mainnet_client) == expected_resolution


def test_document_shape_of_a_single_key_generation(mainnet_client):
    """Spec §8.2 enumeration, proved on the generation whose authentication
    root is the single-key tree of a key the chain reveals."""
    result = resolve(DID, client=mainnet_client, version_id=PRE_REKEY)
    doc = result["didDocument"]
    assert doc["@context"][0] == "https://www.w3.org/ns/did/v1"
    assert doc["id"] == DID
    vms = doc["verificationMethod"]
    assert len(vms) == 1
    vm = vms[0]
    assert vm["type"] == "Multikey"
    assert vm["controller"] == DID
    assert vm["publicKeyMultibase"].startswith("z")
    assert vm["id"] == f"{DID}#{vm['publicKeyMultibase']}"
    assert doc["authentication"] == [vm["id"]]
    assert doc["assertionMethod"] == [vm["id"]]
    assert result["didResolutionMetadata"]["did:julia:stateVerified"] is True
    assert result["didResolutionMetadata"]["did:julia:currentPuzzle"] is True
    assert "deactivated" not in result["didDocumentMetadata"]


def test_current_document_after_a_rekey_publishes_only_the_commitment(
    mainnet_client,
):
    """A rekey installs a new authentication root, and the key it commits to is
    not on chain until a spend authorized under it reveals one. The document
    says exactly that: the new commitment, and no verification method it cannot
    prove (spec §8.2)."""
    result = resolve(DID, client=mainnet_client)
    doc = result["didDocument"]
    assert "verificationMethod" not in doc
    assert "authentication" not in doc
    before = resolve(DID, client=mainnet_client, version_id=PRE_REKEY)
    assert (
        doc["juliaAuthentication"]["merkleRoot"]
        != before["didDocument"]["juliaAuthentication"]["merkleRoot"]
    )
    assert result["didResolutionMetadata"]["did:julia:stateVerified"] is True
    assert result["didResolutionMetadata"]["did:julia:currentPuzzle"] is True


def test_genesis_key_is_the_single_key_root_until_it_is_rotated_out(
    mainnet_client,
):
    """Before the rekey this DID's root is the single-key tree of its genesis
    key — the shape ((K . K) . 0) verified against mainnet. After it, the same
    key no longer satisfies the root, which is what a rekey means."""
    launcher_id = parse(DID)
    history = trace_history(mainnet_client, launcher_id)
    lineage = history.lineage()
    key = genesis_public_key(mainnet_client, lineage)

    pre_rekey_coin = history.generations[-2]
    pre_rekey_spend = mainnet_client.get_puzzle_and_solution(
        pre_rekey_coin.coin.coin_id(), pre_rekey_coin.spent_block_index
    )
    pre_rekey = revealed_state_from_spend(
        pre_rekey_spend, pre_rekey_coin.coin.puzzle_hash, launcher_id
    )
    assert single_key_root(key) == pre_rekey.authentication.merkle_root

    current = extract_state_from_spend(pre_rekey_spend, launcher_id)
    assert single_key_root(key) != current.authentication.merkle_root


def test_multikey_encoding_prefix():
    # multicodec bls12_381-g1-pub (0xea 0x01), multibase base58-btc
    key = bytes(48)
    mk = multikey(key)
    from did_julia.identifier import b58decode
    decoded = b58decode(mk[1:])
    assert mk[0] == "z"
    assert decoded[:2] == bytes([0xEA, 0x01])
    assert decoded[2:] == key


def test_key_not_in_root_is_not_listed(mainnet_client):
    launcher_id = parse(DID)
    lineage = trace_singleton(mainnet_client, launcher_id)
    spend = mainnet_client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    state = extract_state_from_spend(spend, launcher_id)
    doc = build_document(state, candidate_keys=[b"\x01" * 48])
    assert "verificationMethod" not in doc


def test_deactivated_document(mainnet_client):
    launcher_id = parse(DID)
    lineage = trace_singleton(mainnet_client, launcher_id)
    spend = mainnet_client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    state = extract_state_from_spend(spend, launcher_id)
    bricked = replace(state, authentication=None, custodians=[], recovery=None)
    assert bricked.deactivated
    doc = build_document(bricked, candidate_keys=[])
    assert doc == {"@context": ["https://www.w3.org/ns/did/v1"], "id": DID}


def test_invalid_did_error():
    result = resolve("did:julia:0000")
    assert result["didDocument"] is None
    assert result["didResolutionMetadata"]["error"] == "invalidDid"
