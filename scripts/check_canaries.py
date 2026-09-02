#!/usr/bin/env python3
"""Resolve the canary DIDs against live Chia mainnet and check the answers.

    python scripts/check_canaries.py [--node https://your-node:8555]

This is the live counterpart to the offline suite. The offline suite proves the
resolver still agrees with its recorded evidence; this proves the recorded
evidence still describes the chain. It is run on a schedule, never as a pull
request gate — a failure here is news about the chain or the endpoint, not
about a commit.

What is checked, for each canary:

  * current-state resolution verifies (`did:julia:stateVerified`), and the
    document is the DID's own;
  * every generation of the DID resolves by its `versionId`, each verified
    against that generation's own on-chain puzzle hash (spec §7.2.1);
  * resolving the current generation by ID agrees with plain resolution;
  * `versionTime` at each generation's confirmation selects that generation or
    a later one confirmed in the same block, and a time before the DID existed
    is `notFound`.

A DID that has advanced past its committed fixture is reported, not failed:
that is a legitimate update, and the fixtures are refreshed deliberately.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from did_julia import FullNodeClient, resolve  # noqa: E402
from did_julia.chain import trace_history  # noqa: E402
from did_julia.identifier import parse  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"

CANARIES = [
    (
        "personal alias",
        "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
        "expected_resolution_ArD2.json",
    ),
    (
        "Julia Social organization",
        "did:julia:BqJasSrzc9aGJmU4U3A2z4XrqozAAMiMhnqHaq4F2cDc",
        "expected_resolution_julia_org.json",
    ),
]


class Failures(list):
    def check(self, condition: bool, message: str) -> bool:
        print(f"  {'ok  ' if condition else 'FAIL'}  {message}")
        if not condition:
            self.append(message)
        return condition


def _utc(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def check_canary(label: str, did: str, fixture: str, client, failures: Failures):
    print(f"\n{label}\n  {did}")

    current = resolve(did, client=client)
    meta = current["didResolutionMetadata"]
    document = current["didDocument"]
    if not failures.check(document is not None, f"resolves ({meta.get('error', '')})"):
        return
    failures.check(document["id"] == did, "document is this DID's")
    failures.check(
        meta.get("did:julia:stateVerified") is True,
        "state verified against the on-chain puzzle hash",
    )
    failures.check(
        meta.get("did:julia:currentPuzzle") is True,
        "singleton runs the current julia_did puzzle",
    )

    version_id = current["didDocumentMetadata"]["versionId"]
    print(f"  version {version_id}  updated {current['didDocumentMetadata'].get('updated')}")

    generations = trace_history(client, parse(did)).generations
    print(f"  {len(generations)} generation(s) on chain")

    for index, record in enumerate(generations, start=1):
        coin = "0x" + record.coin.coin_id().hex()
        result = resolve(did, client=client, version_id=coin)
        ok = failures.check(
            result["didDocument"] is not None
            and result["didResolutionMetadata"].get("did:julia:stateVerified")
            is True
            and result["didDocumentMetadata"]["versionId"] == coin,
            f"generation {index} resolves and verifies by versionId",
        )
        if ok and index == len(generations):
            failures.check(
                result["didDocument"] == document,
                "the current generation by ID matches plain resolution",
            )

    # versionTime at each generation's own confirmation must land on that
    # generation, or on a later one confirmed in the same block.
    for index, record in enumerate(generations, start=1):
        at = resolve(did, client=client, version_time=_utc(record.timestamp))
        selected = at["didDocumentMetadata"].get("versionId")
        expected = [
            "0x" + g.coin.coin_id().hex()
            for g in generations
            if g.timestamp == record.timestamp
        ]
        failures.check(
            selected in expected,
            f"versionTime at generation {index}'s block selects that block's state",
        )

    before = _utc(generations[0].timestamp - 1)
    early = resolve(did, client=client, version_time=before)
    failures.check(
        early["didResolutionMetadata"].get("error") == "notFound",
        f"versionTime {before}, before the DID existed, is notFound",
    )

    recorded = json.loads((FIXTURES / fixture).read_text())
    if recorded["didDocumentMetadata"]["versionId"] != version_id:
        print(
            f"  NOTE  this DID has advanced past {fixture}: recorded version "
            f"{recorded['didDocumentMetadata']['versionId']}, chain has "
            f"{version_id}. Refresh the fixtures when the update is intended."
        )
    elif recorded["didDocument"] != document:
        failures.append(f"{fixture} disagrees with the chain at the same version")
        print(f"  FAIL  {fixture} disagrees with the chain at the same version")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--node", default=None, help="full node RPC base URL")
    args = ap.parse_args()
    client = FullNodeClient(base_url=args.node) if args.node else FullNodeClient()

    failures = Failures()
    for label, did, fixture in CANARIES:
        check_canary(label, did, fixture, client, failures)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("all canary checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
