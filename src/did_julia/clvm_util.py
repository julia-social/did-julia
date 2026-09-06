"""Minimal CLVM utilities for the did:julia resolver.

CLVM values are represented as plain Python objects: an atom is ``bytes``,
a pair is a 2-tuple ``(left, right)``. This module provides (de)serialization
of the standard CLVM wire format, the CLVM tree hash, uncurrying, curried
puzzle-hash computation, and condition extraction.

Library choice (recorded per the project ground rules): program *execution*
uses ``chia_rs.run_chia_program`` — the consensus VM binding — because
re-implementing the VM would be both wasted and risky. Everything else is
pure Python so the reference code is readable end to end.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Iterator, Optional, Union

import chia_rs
from chia_rs import run_chia_program

Node = Union[bytes, tuple]  # atom | (left, right)

NIL: Node = b""
MAX_COST = 11_000_000_000  # Chia block cost limit

# Post-hardfork mainnet consensus behavior: BLS operators outside the softfork
# guard, hardfork division semantics, and backref-compressed serialization.
# did:julia spends use BLS operators, so replaying them faithfully requires
# that behavior — with flags of 0, a multisig spend fails with julia error 15.
#
# Each of the three was a hardfork-gated option when this resolver was written
# and has since become unconditional consensus, so chia_rs stopped defining the
# constants (they are absent from 0.48). Look each one up by name and OR in
# whatever this build actually has: on a build that still gates the behavior
# the flag is set, and on a build that has retired the gate the behavior is
# already the default. The resolver's own verification is what makes this safe
# to do dynamically — a spend replayed under the wrong semantics yields state
# that does not recompute to the coin's puzzle hash, so it fails closed rather
# than resolving to something plausible.
CONSENSUS_FLAG_NAMES = (
    "ENABLE_BLS_OPS_OUTSIDE_GUARD",
    "ENABLE_FIXED_DIV",
    "ALLOW_BACKREFS",
)
RUN_FLAGS = 0
for _flag in CONSENSUS_FLAG_NAMES:
    RUN_FLAGS |= getattr(chia_rs, _flag, 0)


# ---------------------------------------------------------------- serialization

def deserialize(blob: bytes) -> Node:
    """Deserialize the standard CLVM wire format into a Node tree."""
    node, pos = _de(blob, 0)
    if pos != len(blob):
        raise ValueError(f"{len(blob) - pos} trailing bytes after CLVM object")
    return node


def _de(b: bytes, i: int) -> tuple:
    op = b[i]
    if op == 0xFF:
        left, i = _de(b, i + 1)
        right, i = _de(b, i)
        return (left, right), i
    if op == 0x80:
        return b"", i + 1
    if op <= 0x7F:
        return bytes([op]), i + 1
    if op <= 0xBF:
        size, hdr = op & 0x3F, 1
    elif op <= 0xDF:
        size, hdr = ((op & 0x1F) << 8) | b[i + 1], 2
    elif op <= 0xEF:
        size, hdr = int.from_bytes(bytes([op & 0x0F]) + b[i + 1:i + 3], "big"), 3
    elif op <= 0xF7:
        size, hdr = int.from_bytes(bytes([op & 0x07]) + b[i + 1:i + 4], "big"), 4
    elif op <= 0xFB:
        size, hdr = int.from_bytes(bytes([op & 0x03]) + b[i + 1:i + 5], "big"), 5
    else:
        raise ValueError(f"invalid CLVM serialization byte 0x{op:02x}")
    start = i + hdr
    if start + size > len(b):
        raise ValueError("truncated CLVM atom")
    return b[start:start + size], start + size


def serialize(node: Node) -> bytes:
    if isinstance(node, tuple):
        return b"\xff" + serialize(node[0]) + serialize(node[1])
    a = node
    if len(a) == 0:
        return b"\x80"
    if len(a) == 1 and a[0] <= 0x7F:
        return a
    size = len(a)
    if size <= 0x3F:
        return bytes([0x80 | size]) + a
    if size <= 0x1FFF:
        return bytes([0xC0 | (size >> 8), size & 0xFF]) + a
    if size <= 0xFFFFF:
        return bytes([0xE0 | (size >> 16)]) + (size & 0xFFFF).to_bytes(2, "big") + a
    raise ValueError("atom too large for this serializer")


# ---------------------------------------------------------------- tree hashing

def sha256tree(node: Node) -> bytes:
    """CLVM tree hash: atoms as sha256(0x01 || atom), pairs as sha256(0x02 || l || r)."""
    if isinstance(node, tuple):
        return sha256(b"\x02" + sha256tree(node[0]) + sha256tree(node[1])).digest()
    return sha256(b"\x01" + node).digest()


_Q = sha256tree(b"\x01")   # opcode q (also the atom 1)
_A = sha256tree(b"\x02")   # opcode a
_C = sha256tree(b"\x04")   # opcode c
_NIL_H = sha256tree(b"")
_ONE_H = _Q


def _pair_h(l: bytes, r: bytes) -> bytes:
    return sha256(b"\x02" + l + r).digest()


def curried_puzzle_hash(mod_hash: bytes, arg_hashes: list) -> bytes:
    """Tree hash of ``curry(mod, args)`` given the mod's tree hash and each
    argument's tree hash, without materializing the curried program.

    A curried puzzle is ``(a (q . mod) (c (q . arg1) (c (q . arg2) 1)))``.
    """
    env = _ONE_H
    for h in reversed(arg_hashes):
        quoted_arg = _pair_h(_Q, h)
        env = _pair_h(_C, _pair_h(quoted_arg, _pair_h(env, _NIL_H)))
    quoted_mod = _pair_h(_Q, mod_hash)
    return _pair_h(_A, _pair_h(quoted_mod, _pair_h(env, _NIL_H)))


# ---------------------------------------------------------------- structure

def uncurry(node: Node) -> Optional[tuple]:
    """If ``node`` is a curried program ``(a (q . mod) env)``, return
    ``(mod, [arg, ...])``; otherwise None. Arguments are Node values.
    """
    try:
        op, rest = node
        if op != b"\x02":
            return None
        (q1, mod), rest2 = rest[0], rest[1]
        if q1 != b"\x01":
            return None
        env, nil = rest2
        if nil != b"":
            return None
        args = []
        while env != b"\x01":
            c_op, c_rest = env
            if c_op != b"\x04":
                return None
            (q2, arg), tail = c_rest[0], c_rest[1]
            if q2 != b"\x01":
                return None
            args.append(arg)
            env = tail[0]
            if tail[1] != b"":
                return None
        return mod, args
    except (TypeError, ValueError, IndexError):
        return None


def iter_list(node: Node) -> Iterator[Node]:
    """Iterate a proper CLVM list; raises ValueError on an improper tail."""
    while node != b"":
        if not isinstance(node, tuple):
            raise ValueError("improper CLVM list")
        yield node[0]
        node = node[1]


def to_list(node: Node) -> list:
    return list(iter_list(node))


def as_int(atom: Node) -> int:
    """CLVM atom to integer (big-endian, two's complement)."""
    if not isinstance(atom, bytes):
        raise ValueError("expected atom")
    return int.from_bytes(atom, "big", signed=True)


def int_to_atom(n: int) -> bytes:
    """Integer to minimal CLVM atom encoding."""
    if n == 0:
        return b""
    size = (n.bit_length() + 8) // 8
    return n.to_bytes(size, "big", signed=True)


# ---------------------------------------------------------------- execution

def _from_lazy(n) -> Node:
    if n.pair is None:
        return bytes(n.atom)
    return (_from_lazy(n.pair[0]), _from_lazy(n.pair[1]))


def run_program(program: bytes, solution: bytes) -> Node:
    """Run serialized CLVM ``program`` with serialized ``solution`` on the
    consensus VM and return the result as a Node tree."""
    _cost, result = run_chia_program(program, solution, MAX_COST, RUN_FLAGS)
    return _from_lazy(result)


def conditions_from_spend(puzzle_reveal: bytes, solution: bytes) -> list:
    """Run a coin spend and return its conditions as a list of Node lists."""
    return to_list(run_program(puzzle_reveal, solution))
