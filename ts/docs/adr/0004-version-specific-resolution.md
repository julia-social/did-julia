# ADR 0004 — Version-specific resolution (`versionId`, `versionTime`)

Status: accepted (2026-09-01)

Supersedes the "not implemented" entry for version-specific resolution in
[ADR 0003](0003-verification-scope-v1.md).

## Context

[ADR 0003](0003-verification-scope-v1.md) refused `versionId` and `versionTime`
with `unsupportedResolutionOption`, on the grounds that returning the current
document in place of a requested version is the one failure a caller cannot
detect. That was the right refusal for a resolver that could not answer the
question. It was never an argument that the question is unanswerable.

A W3C registry editor reviewing the `did:julia` registration
([w3c/did-extensions#748](https://github.com/w3c/did-extensions/pull/748))
asked the obvious follow-up: since the whole update history is on chain, can
`versionTime` be supported? It can, and the chain makes the answer verifiable
rather than merely available.

## Decision

**Both options are implemented, under exactly the commitment current-state
resolution runs under.** Spec §7.2.1.

### A version ID is a coin ID

Spec §8.5 already defined `versionId` as the coin ID of the singleton
generation a document was read from, so version identifiers were fixed before
this ADR: 32-octet content commitments, accepted with or without a `0x` prefix.
They are not sequence numbers, and a caller cannot guess one forward — which is
a feature, because a version ID names one generation of one DID and nothing
else.

### History is read from the generation's own spend, not derived

`deriveVerifiedState` exists because the unspent coin has no spend of its own,
so its state must be derived from its parent's and checked against its puzzle
hash. A *superseded* generation has no such problem: its own spend reveals its
own pre-spend state verbatim as the first inner solution argument, and its
puzzle curries in that state's hash.

So `revealedVerifiedState` replays no transition at all. It requires three
things to agree before it returns anything:

1. the puzzle reveal hashes to the generation's on-chain puzzle hash;
2. the revealed state matches the `CURRIED-ARGS-HASH` that puzzle curries in;
3. the state recomputes to that same puzzle hash.

Consequences worth stating. The transition machinery of ADR 0001 is not on the
path for history, so a version this resolver can serve is one the chain's own
commitment proves — there is no window in which an unrecognized operation makes
a *past* version unreadable. And because the hash checked is the one held by the
coin the caller named, substituting a different version for the requested one
cannot pass: the failure ADR 0003 refused to risk is structurally impossible
here rather than merely avoided.

It also answers for the DID's first generation, whose parent is the launcher and
therefore `REMARK`s nothing. Creation spends the eve coin in the same spend
bundle that creates it (spec §7.1), so the first generation always has a spend
of its own.

### Selection rules

- `versionTime` selects the latest generation confirmed at or before the
  requested time. A singleton can be spent more than once in one block, so
  several generations may share a timestamp; the last of them is the state that
  block left behind, and is the one selected. (Both mainnet canaries exercise
  this: their first two generations share a confirming block.)
- The `get_singleton_info` fast path is not used for a version request. It
  answers "which coin is current", which is the one question a version request
  is not asking.

### Metadata

A version-specific result adds `created`, and `nextVersionId`/`nextUpdate` when
the resolved version has been superseded. Current-state resolution does **not**
report `created`, even though the portable traversal would know it: the fast
path does not walk the lineage, and metadata that changes with which RPC surface
a node happens to offer is worse than metadata that reports only what one
reading of the unspent coin establishes. Version requests always walk, so the
field is always available where it is emitted.

### Errors

| Condition | Error |
|---|---|
| `versionId` no generation of this DID has | `notFound` |
| `versionTime` earlier than the first generation | `notFound` |
| `versionId` that is not 32 octets of hex | `invalidDidUrl` |
| `versionTime` that is not an XML datetime with a UTC designator or offset | `invalidDidUrl` |
| `versionId` and `versionTime` together | `unsupportedResolutionOption` |

Malformed values are `invalidDidUrl` because these are DID URL parameters and
the caller wrote one wrong; well-formed values naming a version that does not
exist are `notFound`, which is the truth about that version and is safe for a
downstream resolver to cache, since a version ID names an immutable generation.

DID Resolution makes `versionId` and `versionTime` mutually exclusive, so
supplying both is refused rather than silently resolved by one of them. The code
reused for it is the method-specific `unsupportedResolutionOption` this package
already mints, with a message naming the conflict: the combination is what is
unsupported, not either option.

## Validation

Both mainnet canaries are replayed offline for every generation they have — the
organization DID has four, the personal alias three — and the TypeScript results
are compared byte for byte against the Python reference resolver's output for
the same requests, the same way current-state resolution is compared. Every
generation is served only after its own coin's puzzle hash is reproduced.

The alias's third generation is a **rekey** (block 9235350, 2026-09-02), which
makes it the case this design most needed: its two earlier versions resolve to
the key the DID was created with, and its current version resolves to the new
authentication commitment with no verification method, because a rekey publishes
a commitment and the incoming key is not on chain until a spend proves
membership in it. A signature made under the retired key is still verifiable —
resolve the DID at a `versionTime` before the rekey and the key that governed it
is right there. That is the property the registry editor's question was really
about.

## What this does not add

Version-specific **DID URL dereferencing** (`?versionId=…#fragment` resolving to
a verification method) remains out of scope with the rest of dereferencing.
Verification-method enumeration for a historical version follows spec §8.2
unchanged, including the multi-key Merkle-path limitation: a multi-class DID
publishes its authentication commitment for that generation and no verification
methods.
