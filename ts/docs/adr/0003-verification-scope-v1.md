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

- ~~**Version-specific resolution.** `versionId` and `versionTime` are
  **refused** with `unsupportedResolutionOption`, not ignored.~~
  **Superseded by [ADR 0004](0004-version-specific-resolution.md) (2026-09-01):
  both options are now implemented.** The reasoning that produced the refusal
  still stands and is why the implementation looks the way it does — a version
  request is answered under the commitment of the coin the caller named, or it
  is an error; the current document is never returned in its place.
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

## Trust model, corrected

**Corrected 2026-08-27 after re-review of PR #1.** This ADR previously said the
full node "cannot forge". That was false, and it was the most load-bearing
sentence in the package's documentation. A working forgery was demonstrated: a
hostile endpoint served a self-consistent fabricated lineage for a real DID and
the resolver published an attacker-chosen key with `stateVerified: true`.

The response is in two parts, and the second matters more than the first.

**Checks added.** Every RPC record is now verified against the identifier it
was requested by — a coin record must hash back to the requested coin id,
children must carry the requested parent, a spend must be a spend of the coin
asked for. Every spend must carry a `parent-info` that re-derives the DID's
launcher ID (the same check `julia_did` makes on chain before consensus will
honour a spend), and the revealed pre-spend state must match the
`CURRIED-ARGS-HASH` its own authenticated puzzle commits to. Because a launcher
coin id is the hash of its own fields, this pins the launcher coin, the
prelauncher coin, and — through the prelauncher puzzle hash — `sha256tree` of
the genesis key. **The DID string commits to its genesis public key**, so that
key is no longer forgeable by any endpoint.

**The boundary, stated instead of papered over.** Nothing in a bare Chia RPC
response proves that a coin was ever created on chain. An endpoint that
fabricates a *coherent* lineage forward from the real launcher — real launcher
coin, real prelauncher, a genuine `parent-info`, a real singleton puzzle
wrapped around a state of its choosing — is still not detected. Detecting it
requires block-level verification: headers and inclusion proofs, i.e. a light
client. That is a different project, and pretending otherwise is exactly the
overclaim this rewrite exists to remove.

The endpoint is therefore **trusted for the DID's current state**. Operators
should point the resolver at a node they trust, which `baseUrl` exists to
allow; the open Coinset default is a zero-configuration convenience, not a
security assumption. Choosing the `get_singleton_info` fast path over the
portable traversal changes performance, not what can be proven either way.

`src/__tests__/integrity.test.ts` asserts this boundary against the README's own
text, so the claim and the code cannot silently drift apart again.

## Why the puzzle-hash check still earns its place

It is not authentication, and it is no longer described as such — but it is
what makes state *derivation* safe (ADR 0001). Within a given endpoint's
answers, a state that recomputes to the reported coin is the state that coin
commits to, so the resolver never has to guess which transition ran. An
inconsistent endpoint is caught; a coherent liar is not.
