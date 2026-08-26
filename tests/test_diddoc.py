"""Spec §8: DID Document construction and full resolution."""

from dataclasses import replace

from did_julia import resolve
from did_julia.diddoc import build_document, multikey, single_key_root
from did_julia.chain import trace_singleton
from did_julia.identifier import parse
from did_julia.state import extract_state_from_spend, genesis_public_key

DID = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"


def test_full_resolution_matches_expected(mainnet_client, expected_resolution):
    assert resolve(DID, client=mainnet_client) == expected_resolution


def test_document_shape(mainnet_client):
    result = resolve(DID, client=mainnet_client)
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


def test_genesis_key_is_current_single_key(mainnet_client):
    """The example DID's current root is the single-key tree of its genesis
    key — the tree shape ((K . K) . 0) verified against mainnet."""
    launcher_id = parse(DID)
    lineage = trace_singleton(mainnet_client, launcher_id)
    spend = mainnet_client.get_puzzle_and_solution(
        lineage.parent.coin.coin_id(), lineage.parent.spent_block_index
    )
    state = extract_state_from_spend(spend, launcher_id)
    key = genesis_public_key(mainnet_client, lineage)
    assert single_key_root(key) == state.authentication.merkle_root


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
