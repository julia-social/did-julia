"""Chia full-node RPC client and did:julia singleton traversal.

Works against any Chia full node RPC. Defaults to the open Coinset endpoint
(https://api.coinset.org) so the reference resolver runs with zero setup; a
local node is used by passing ``base_url="https://localhost:8555"`` and the
node's client certificate pair.

Traversal (spec §7.2, ported from the production Rust drivers): start at the
launcher coin, follow the odd-amount child of each spend — the singleton
consensus rules permit exactly one odd child per singleton spend — until the
unspent current coin is reached.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Optional

import requests

from .clvm_util import int_to_atom

COINSET_MAINNET = "https://api.coinset.org"

# Standard Chia singleton launcher puzzle hash (verified against mainnet
# launcher coins; also embedded in julia_did_chialisp/singleton_launcher.clsp.hex).
SINGLETON_LAUNCHER_PH = bytes.fromhex(
    "eff07522495060c066f66f32acc2a77e3a3e737aca8baea4d1a64ea4cdc13da9"
)


class ChainError(RuntimeError):
    pass


class NotFoundError(ChainError):
    pass


@dataclass(frozen=True)
class Coin:
    parent_coin_info: bytes
    puzzle_hash: bytes
    amount: int

    def coin_id(self) -> bytes:
        return sha256(
            self.parent_coin_info + self.puzzle_hash + int_to_atom(self.amount)
        ).digest()


@dataclass(frozen=True)
class CoinRecord:
    coin: Coin
    spent: bool
    confirmed_block_index: int
    spent_block_index: int
    timestamp: int


@dataclass(frozen=True)
class CoinSpend:
    coin: Coin
    puzzle_reveal: bytes
    solution: bytes


def _hexb(s: str) -> bytes:
    return bytes.fromhex(s[2:] if s.startswith("0x") else s)


def _parse_coin(d: dict) -> Coin:
    return Coin(_hexb(d["parent_coin_info"]), _hexb(d["puzzle_hash"]), int(d["amount"]))


def _parse_record(d: dict) -> CoinRecord:
    return CoinRecord(
        coin=_parse_coin(d["coin"]),
        spent=bool(d.get("spent", d.get("spent_block_index", 0) != 0)),
        confirmed_block_index=int(d["confirmed_block_index"]),
        spent_block_index=int(d.get("spent_block_index", 0)),
        timestamp=int(d.get("timestamp", 0)),
    )


class FullNodeClient:
    def __init__(
        self,
        base_url: str = COINSET_MAINNET,
        cert: Optional[tuple] = None,
        timeout: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        if cert is not None:
            self.session.cert = cert
            self.session.verify = False

    def _post(self, method: str, payload: dict) -> dict:
        resp = self.session.post(
            f"{self.base_url}/{method}", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", False):
            raise ChainError(f"{method}: {data.get('error', 'RPC returned success=false')}")
        return data

    def get_coin_record_by_name(self, coin_id: bytes) -> Optional[CoinRecord]:
        try:
            data = self._post("get_coin_record_by_name", {"name": "0x" + coin_id.hex()})
        except ChainError:
            return None
        rec = data.get("coin_record")
        return _parse_record(rec) if rec else None

    def get_coin_records_by_parent_ids(
        self, parent_ids: list, include_spent_coins: bool = True
    ) -> list:
        data = self._post(
            "get_coin_records_by_parent_ids",
            {
                "parent_ids": ["0x" + p.hex() for p in parent_ids],
                "include_spent_coins": include_spent_coins,
            },
        )
        return [_parse_record(r) for r in data.get("coin_records", [])]

    def get_puzzle_and_solution(self, coin_id: bytes, height: int) -> CoinSpend:
        data = self._post(
            "get_puzzle_and_solution", {"coin_id": "0x" + coin_id.hex(), "height": height}
        )
        cs = data["coin_solution"]
        return CoinSpend(
            coin=_parse_coin(cs["coin"]),
            puzzle_reveal=_hexb(cs["puzzle_reveal"]),
            solution=_hexb(cs["solution"]),
        )


@dataclass(frozen=True)
class SingletonLineage:
    """The coins a resolver needs: genesis commitment through current state."""
    prelauncher: CoinRecord
    launcher: CoinRecord
    current: CoinRecord          # the unspent singleton coin
    parent: CoinRecord           # its parent — the most recent spend
    generations: int             # number of singleton generations traversed


def trace_singleton(client: FullNodeClient, launcher_id: bytes) -> SingletonLineage:
    """Walk from launcher ID to the current unspent singleton coin (spec §7.2)."""
    launcher = client.get_coin_record_by_name(launcher_id)
    if launcher is None:
        raise NotFoundError("launcher coin not found on chain")
    if launcher.coin.puzzle_hash != SINGLETON_LAUNCHER_PH:
        raise NotFoundError("coin exists but is not a singleton launcher")
    if not launcher.spent:
        raise NotFoundError("launcher coin exists but was never spent")

    prelauncher = client.get_coin_record_by_name(launcher.coin.parent_coin_info)
    if prelauncher is None:
        raise NotFoundError("prelauncher coin not found")

    record = launcher
    parent = launcher
    generations = 0
    while record.spent:
        children = client.get_coin_records_by_parent_ids([record.coin.coin_id()])
        nxt = [c for c in children if c.coin.amount % 2 == 1]
        if len(nxt) != 1:
            raise ChainError(
                f"expected exactly one odd-amount singleton child, found {len(nxt)}"
            )
        parent = record
        record = nxt[0]
        generations += 1
    return SingletonLineage(
        prelauncher=prelauncher,
        launcher=launcher,
        current=record,
        parent=parent,
        generations=generations,
    )
