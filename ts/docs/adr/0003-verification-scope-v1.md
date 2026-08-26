# ADR 0003 — Verification scope for v1

Status: accepted (2026-08-26)

## Context

The project rule is that overclaiming is worse than shipping less. A resolver
that quietly dropped did:julia's puzzle-hash verification in order to avoid the
CLVM problem would be exactly that: the documents would still look right, and
`did:julia:stateVerified` would still say `true`, while nothing was checked.

## Decision

**Verification scope matches the Python reference resolver exactly. No reduced
mode exists, and none is needed.**

- **State verification is unconditional.** The eight-slot state is only served
  after its recomputed singleton puzzle hash equals the unspent coin's on-chain
  puzzle hash. ADR 0001 explains why removing CLVM execution did not cost this.
- **`did:julia:stateVerified` and `did:julia:currentPuzzle` are both reported**,
  with the same names and meanings the reference resolver uses.
- **Verification-method enumeration follows spec §8.2 unchanged**: a key is
  listed only when its membership in the *current* authentication Merkle root
  is proven by on-chain data. Multi-key Merkle-path replay is not implemented —
  the same documented v1 limitation the Python reference carries — so a
  multi-class DID publishes its authentication commitment and no verification
  methods. This is a limitation of both implementations, not a divergence
  between them, and it is visible in the organization canary's document.
- **The prelauncher reveal is authenticated** before its genesis key is used:
  its tree hash must equal the prelauncher coin's on-chain puzzle hash.

## Divergences from the reference resolver

Two, both strictly more conservative, both deliberate:

1. **`stateVerified` is `true` by construction.** The reference resolver can
   return a document with `stateVerified: false` — it reads state from the
   `REMARK` and reports the hash check as a field. This driver derives state
   *through* the hash check, so an unverifiable state cannot produce a document
   at all; it returns `didResolutionMetadata.error = "unverifiableState"`. The
   field is still emitted, for parity and because its absence would itself be a
   silent claim.
2. **The parent spend's puzzle reveal is checked** against the parent coin's
   puzzle hash before its solution is read. The reference resolver performs
   this check for the prelauncher only. It costs one tree hash and detects a
   lying or broken RPC endpoint one step earlier.

Neither divergence changes the output for any resolvable DID: both canaries
resolve byte-equivalently to the reference resolver's live output.

## Not implemented (and reported honestly)

- **Version-specific resolution.** `versionId` and `versionTime` resolution
  options are not consulted, matching both the reference resolver and every
  sibling driver in ThisDID. The resolver always answers with current state.
- **Representations other than `application/did+ld+json`.**
- **DID URL dereferencing** — path, query, and fragment dereferencing beyond
  the document itself.

## Trust model, stated plainly

The full node is a **data source, not an authority**. It can withhold (the
resolver then errors) but it cannot forge: state is bound to the coin's puzzle
hash, the coin is reached by singleton lineage from the launcher ID that the
DID itself encodes, and the genesis key is bound to the prelauncher coin's
puzzle hash. Choosing a different endpoint — or Coinset's one-call
`get_singleton_info` fast path over the portable per-generation traversal —
changes performance and availability, never what can be proven.
