"""Parsing, validation, and formatting of did:julia identifiers.

Spec: spec/did-julia.md §5. The method-specific identifier is the base58
encoding (Bitcoin alphabet, no checksum) of the DID's 32-octet singleton
launcher ID. Validation is by decoding — the character count is not fixed
and MUST NOT be used for validation (§5.2).
"""

from __future__ import annotations

PREFIX = "did:julia:"
ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(ALPHABET)}
LAUNCHER_ID_SIZE = 32


class InvalidDidError(ValueError):
    """The string is not a valid did:julia DID."""


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        if ch not in _INDEX:
            raise InvalidDidError(f"invalid base58 character {ch!r}")
        n = n * 58 + _INDEX[ch]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def parse(did: str) -> bytes:
    """Parse a did:julia DID and return the 32-octet launcher ID.

    Raises InvalidDidError on any violation of §5: wrong or wrongly cased
    prefix, characters outside the base58 alphabet, or a decoding that is
    not exactly 32 octets. Short decodings are rejected, never padded.
    """
    if not isinstance(did, str) or not did.startswith(PREFIX):
        raise InvalidDidError("missing case-sensitive 'did:julia:' prefix")
    msi = did[len(PREFIX):]
    if not msi:
        raise InvalidDidError("empty method-specific identifier")
    decoded = b58decode(msi)
    if len(decoded) != LAUNCHER_ID_SIZE:
        raise InvalidDidError(
            f"decoded launcher ID is {len(decoded)} octets, must be exactly {LAUNCHER_ID_SIZE}"
        )
    return decoded


def format_did(launcher_id: bytes) -> str:
    """Format a 32-octet launcher ID as a did:julia DID."""
    if len(launcher_id) != LAUNCHER_ID_SIZE:
        raise ValueError(f"launcher ID must be {LAUNCHER_ID_SIZE} octets, got {len(launcher_id)}")
    return PREFIX + b58encode(launcher_id)


def is_valid(did: str) -> bool:
    try:
        parse(did)
        return True
    except InvalidDidError:
        return False
