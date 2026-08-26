"""Spec §5: identifier syntax and validation."""

import pytest

from did_julia import identifier
from did_julia.identifier import InvalidDidError, b58encode, format_did, parse

EXAMPLE = "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX"
EXAMPLE_LAUNCHER = bytes.fromhex(
    "92543c68190662dc0e22ecc1d5315024a946dc572b253630d7983ac373249502"
)


def test_worked_example_decodes():
    assert parse(EXAMPLE) == EXAMPLE_LAUNCHER


def test_round_trip():
    assert format_did(EXAMPLE_LAUNCHER) == EXAMPLE


def test_43_character_identifier():
    # ~5.7% of launcher IDs encode to 43 characters (any value below 58^43,
    # e.g. one with a small leading octet); spec §5.2 forbids length-based
    # validation, so this MUST parse.
    launcher = b"\x01" + EXAMPLE_LAUNCHER[1:]
    did = format_did(launcher)
    assert len(did.removeprefix("did:julia:")) == 43
    assert parse(did) == launcher


def test_short_decoding_rejected_not_padded():
    # 31 octets of payload MUST be rejected (spec §5.2), never zero-padded.
    short = "did:julia:" + b58encode(EXAMPLE_LAUNCHER[:31])
    with pytest.raises(InvalidDidError, match="31 octets"):
        parse(short)


def test_long_decoding_rejected():
    long = "did:julia:" + b58encode(EXAMPLE_LAUNCHER + b"\x01")
    with pytest.raises(InvalidDidError):
        parse(long)


@pytest.mark.parametrize("bad", ["0", "O", "I", "l"])
def test_excluded_alphabet_characters_rejected(bad):
    with pytest.raises(InvalidDidError):
        parse(EXAMPLE[:-1] + bad)


@pytest.mark.parametrize(
    "did",
    [
        "did:JULIA:" + EXAMPLE.split(":", 2)[2],  # prefix is case-sensitive
        "DID:julia:" + EXAMPLE.split(":", 2)[2],
        "did:julia:",
        "did:julia",
        "",
    ],
)
def test_malformed_rejected(did):
    assert not identifier.is_valid(did)


def test_leading_zero_octets_preserved():
    launcher = b"\x00\x00" + EXAMPLE_LAUNCHER[2:]
    assert parse(format_did(launcher)) == launcher
