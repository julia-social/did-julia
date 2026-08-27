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

- **Version-specific resolution.** `versionId` and `versionTime` are **refused**
  with `unsupportedResolutionOption`, not ignored.

  Ignoring them is the sibling-driver convention in ThisDID and matches the
  reference resolver, and it was this package's original behaviour. Review of
  PR #1 was right to reject it: a caller who asks for version X and receives
  the current document, correctly formed and stamped `stateVerified: true`, has
  no way to detect that it answered a different question. Every other limitation
  here is visible in the result; that one was not. A refusal is honest, and a
  caller who does not pass the options is unaffected.

  The code is method-specific — the vendored DIF `did-resolver` core registers
  no error for an unsupported resolution option — and follows the precedent of
  ThisDID's other method-specific fail-closed codes (e.g. hedera's
  `resourceLimitExceeded`). It is neither transport-class nor
  unsupported-method-class there, so it reaches the caller as a resolution
  verdict rather than triggering a fallback chain.
- **Representations other than `application/did+ld+json`.**
- **DID URL dereferencing** — path, query, and fragment dereferencing beyond
  the document itself.

## Withholding is not absence

"It can withhold, and the resolver then errors" is a claim the code has to earn.
`notFound` is a semantic verdict that downstream resolvers may cache, so it is
returned only when the node *itself* reports the coin absent — either a stock
full node's `{ success: true, coin_record: null }` or a gateway's explicit
not-found code (Coinset answers `success: false` with
`structuredError.code = "COIN_RECORD_NOT_FOUND"`, so both shapes are
recognized, and anything unrecognized is treated as a real error). Every other
failure — network, timeout, non-2xx, oversized, non-JSON — raises
`internalError`, which is transport-class to ThisDID.

Erring toward `internalError` is the safe direction: a transport-class error
makes a caller retry or fall through, while a wrong `notFound` is a durable,
cacheable lie about someone's identity.

## Trust model, stated plainly

The full node is a **data source, not an authority**. It can withhold (the
resolver then errors, as above) but it cannot forge: state is bound to the coin's puzzle
hash, the coin is reached by singleton lineage from the launcher ID that the
DID itself encodes, and the genesis key is bound to the prelauncher coin's
puzzle hash. Choosing a different endpoint — or Coinset's one-call
`get_singleton_info` fast path over the portable per-generation traversal —
changes performance and availability, never what can be proven.
