#!/usr/bin/env python3
"""Resolve a did:julia DID and print the resolution result.

    python examples/resolve.py did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX

A past version of the DID resolves the same way (spec §7.2.1):

    python examples/resolve.py <did> --version-time 2026-08-01T00:00:00Z
    python examples/resolve.py <did> --version-id 0x2af60aad…

Uses the open Coinset mainnet RPC by default. To use a local Chia node:

    python examples/resolve.py <did> --node https://localhost:8555 \
        --cert ~/.chia/mainnet/config/ssl/full_node/private_full_node.crt \
        --key  ~/.chia/mainnet/config/ssl/full_node/private_full_node.key
"""

import argparse
import json
import sys

from did_julia import FullNodeClient, resolve


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("did")
    ap.add_argument("--node", default=None, help="full node RPC base URL")
    ap.add_argument("--cert", default=None)
    ap.add_argument("--key", default=None)
    version = ap.add_mutually_exclusive_group()
    version.add_argument(
        "--version-id",
        default=None,
        help="coin ID of the singleton generation to resolve",
    )
    version.add_argument(
        "--version-time",
        default=None,
        help="XML datetime, e.g. 2026-08-01T00:00:00Z",
    )
    args = ap.parse_args()

    client = None
    if args.node:
        cert = (args.cert, args.key) if args.cert else None
        client = FullNodeClient(base_url=args.node, cert=cert)

    result = resolve(
        args.did,
        client=client,
        version_id=args.version_id,
        version_time=args.version_time,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["didDocument"] is not None else 1


if __name__ == "__main__":
    sys.exit(main())
