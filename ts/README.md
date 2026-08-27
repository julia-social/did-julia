# @julia-social/did-julia-resolver

A `did:julia` resolver for the DIF
[`did-resolver`](https://github.com/decentralized-identity/did-resolver)
interface — a port of the Python reference resolver in
[`src/did_julia/`](../src/did_julia), reading public Chia blockchain state
through any full node RPC and running in the Cloudflare Workers runtime.

The [method specification](../spec/did-julia.md) is normative; the Python
resolver is the port's source of truth; the fixtures in
[`tests/fixtures/`](../tests/fixtures) are shared by both suites.

```ts
import { Resolver } from "did-resolver";
import { getResolver } from "@julia-social/did-julia-resolver";

const resolver = new Resolver(getResolver());
const result = await resolver.resolve(
  "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
);
```

## What it implements

- **Identifier validation by decoding** (spec §5.2): base58, Bitcoin alphabet,
  no checksum, decoding to exactly 32 octets. Length is never used as
  validation, and a short decoding is rejected rather than left-padded.
- **Singleton traversal** (spec §7.2): launcher coin → the odd-amount child of
  each spend → the unspent current coin. Coinset's `POST /get_singleton_info`
  extension is used as a **fast path** when the configured endpoint serves it
  (one call instead of two per generation); any node that does not simply falls
  back to the portable walk. Both paths produce identical results — verified
  live against both canary DIDs.
- **State derivation without CLVM execution**: the eight-slot state is derived
  from the most recent spend's solution and then proven against the unspent
  coin's puzzle hash. See
  [ADR 0001](docs/adr/0001-state-derivation-without-clvm.md).
- **DID Document construction** (spec §8): the `did/v1`,
  `security/multikey/v1`, and `https://not.bot/ns/did-julia/v1` contexts,
  Multikey verification methods (multicodec `0xea 0x01` + a 48-octet BLS12-381
  G1 key, base58-btc), content-addressed fragments, and the method-specific
  `juliaAuthentication` / `juliaCustodians` / `juliaRecovery` /
  `juliaRecoveryPending` / `juliaDocumentPointer` properties.
- **Deactivation** (spec §7.4), recognizing both the null encoding and the
  protocol's uniform inert-tree sentinels — which are *derived* from the
  all-zero leaf, never hardcoded.

Not implemented, and **refused rather than faked**: version-specific resolution.
A request carrying `versionId` or `versionTime` returns
`unsupportedResolutionOption` instead of the current document — answering a
question the caller did not ask is the one failure they cannot detect. Also not
implemented: representations other than `application/did+ld+json`, DID URL
dereferencing, and multi-key Merkle-path replay for verification-method
enumeration (a v1 limitation shared with the Python reference — a multi-class
DID publishes its authentication commitment and no verification methods). See
[ADR 0003](docs/adr/0003-verification-scope-v1.md).

## Trust model and fail-closed behavior

**The full node is a data source, not an authority.** It can withhold — in
which case resolution errors — but it cannot forge:

- the DID's method-specific identifier *is* the singleton launcher ID, so the
  lineage the resolver walks is fixed by the identifier itself;
- the state served is only ever a state whose recomputed
  `singleton_top_layer_v1_1` puzzle hash equals the unspent coin's on-chain
  puzzle hash, so a lying or buggy endpoint cannot substitute a different
  authentication configuration, recovery configuration, or document pointer;
- the spend's puzzle reveal must hash to its own coin's puzzle hash before its
  solution is read;
- the genesis public key is only used after the prelauncher puzzle reveal is
  hashed against the prelauncher coin's puzzle hash;
- a key is published as a verification method only when its membership in the
  *current* authentication Merkle root is provable (spec §8.2).

**An outage is never an answer.** `notFound` is returned only when the node
itself reports the coin absent — a stock full node's `{ success: true,
coin_record: null }`, or a gateway's explicit not-found code. A transport
failure, timeout, non-2xx status, oversized body, or non-JSON body raises
`internalError`, which callers such as ThisDID treat as transport-class. The
distinction matters because `notFound` is a semantic verdict that downstream
resolvers may cache: an unreachable node must never become an authoritative
claim that a DID does not exist. Response bodies are bounded *while streaming*
(and rejected up front on an oversized `content-length`), so a hostile endpoint
cannot exhaust an edge runtime before the limit is consulted.

**Fail-closed:** a spend for which no known state transition reproduces the
chain's commitment returns `didResolutionMetadata.error = "unverifiableState"`.
The resolver never serves a guess, and never downgrades to an unverified
document. Solution shapes are puzzle-version-specific, so this is the honest
outcome for a DID on a `julia_did` puzzle version this resolver predates —
`did:julia:currentPuzzle` reports that condition explicitly.

## Test provenance

Two independent bodies of ground truth, both replayed offline:

- **Recorded mainnet RPC traffic** for the two canary DIDs
  (`tests/fixtures/rpc_calls_*.json`), with the resolution results the Python
  reference resolver produced from them
  (`tests/fixtures/expected_resolution_*.json`). The suite asserts **byte
  equivalence**, key order included, against those files — the same recordings
  the Python suite replays. The recordings carry no `get_singleton_info`
  response, so every fixture test also exercises the portable traversal.
- **Compiled-puzzle transition vectors** (`tests/fixtures/transitions.json`):
  18 recorded input/output pairs produced by executing the real compiled
  `julia_did` sub-puzzles on the consensus VM through the chialisp toolchain
  (`julia-social/julia_did_chialisp` @ `7fbc6bc`, chialisp 0.4.5), using each
  puzzle's own test environment. All six state-changing operations are covered,
  including adversarial cases pinning inputs the puzzles deliberately ignore.

Live end-to-end (2026-08-26): both canary DIDs resolved against
`api.coinset.org` through the fast path and through the portable traversal, and
both outputs diffed identical to the Python reference resolver's live output.

```bash
npm test          # offline: fixtures + transition vectors
npm run build     # tsc → lib/
```

## Canary DIDs

- `did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX` — single-key
  personal alias; resolves with a real Multikey verification method.
- `did:julia:BqJasSrzc9aGJmU4U3A2z4XrqozAAMiMhnqHaq4F2cDc` — the production
  Julia Social DID; multi-class multisig, so it publishes its authentication
  commitment and no verification methods.

## Configuration

| Option | Default | Meaning |
| --- | --- | --- |
| `baseUrl` | `https://api.coinset.org` | Chia full node RPC base. Any node works. |
| `timeoutMs` | `8000` | Per-request wall-clock bound. |
| `useSingletonInfo` | `true` | Try Coinset's one-call singleton lookup before the portable walk. |
| `transport` | HTTP `fetch` | Replace the transport entirely (tests, mTLS proxies, custom auth). |

## Exit criteria

Retire this package if and when the DIF ecosystem gains a maintained,
workerd-compatible did:julia driver from another source; until then the Chia
chain and the `julia_did` puzzles are the source of truth it must keep
matching. Re-derive `tests/fixtures/transitions.json` whenever the puzzles are
recompiled — the pinned hash table in `src/transitions.ts` and the vectors are
the only two places a puzzle change must land. Adding a seventh state-changing
operation to the protocol requires adding its transition here; until it is
added, such a spend fails closed rather than resolving incorrectly.

## Design decisions

- [ADR 0001 — Derive did:julia state instead of executing CLVM](docs/adr/0001-state-derivation-without-clvm.md)
- [ADR 0002 — Package custody, naming, and distribution](docs/adr/0002-package-custody-and-distribution.md)
- [ADR 0003 — Verification scope for v1](docs/adr/0003-verification-scope-v1.md)

## License

Apache-2.0, as the rest of this repository.
