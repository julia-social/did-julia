# ADR 0001 — Derive did:julia state instead of executing CLVM

Status: accepted (2026-08-26)

## Context

`julia_did.clsp` re-emits the next generation's full eight-slot state in a
`REMARK` condition. The Python reference resolver reads that state the direct
way: it runs the most recent spend on the consensus VM (`chia_rs.run_chia_program`,
with `ENABLE_BLS_OPS_OUTSIDE_GUARD | ENABLE_FIXED_DIV | ALLOW_BACKREFS`, because
did:julia spends use BLS operators) and picks the `REMARK` out of the resulting
conditions.

That route is not available to this driver:

- The driver runs in the Cloudflare Workers runtime. Executing CLVM there means
  shipping a WASM VM build, and a VM whose operator set and hardfork flags must
  stay bit-compatible with mainnet consensus or the resolver silently diverges
  from the chain.
- Fetching the conditions instead is not possible: no Chia full-node RPC parses
  spends for callers. Coinset's extended API has transfer and memo summaries,
  but no parsed-conditions endpoint (verified 2026-08-26).

## Decision

**The driver executes no CLVM. It derives the state and then proves the
derivation against the chain.**

Three facts make this exact rather than approximate:

1. **The spend reveals its own pre-spend state.** `julia_did`'s parameters are
   `(CURRIED-ARGS-HASH curried-args parent-info solution)`, so every solution
   carries `curried-args` — the full eight-slot state as it stood before the
   spend — verbatim.
2. **New state is a pure function of old state and the same solution.** Only
   six sub-puzzles rewrite state; each one's `update-curry` reads only the old
   slots and values present in the solution:

   | Operation | New state |
   | --- | --- |
   | eve spend / any pass-through | unchanged |
   | `rekey` | slot 4 ← solution's `new-multisig-info`; slot 8 ← nil |
   | `DIDdoc_set` | slot 7 ← solution's `new-DID-doc`; slot 8 ← nil |
   | `recovery_initiate` | slot 3 ← old slot 6's delay; slot 8 ← the proposed triple from the solution |
   | `recovery_cancel` | slot 3 ← nil; slot 8 ← nil |
   | `recovery_complete` | slots 4/5/6 ← old slot 8's triple; slots 3, 8 ← nil |
   | `recovery_prerotation` | slot 4 ← old slot 6's pre-rotation multisig; slot 6 ← solution's next pre-rotation plus the old recovery class fields; slots 3, 8 ← nil |

   Every other sub-puzzle in the call chain (`singlesig`, `multisig`,
   `custody_minion`, `sign_message`, `coin_control`, `invalidate`,
   `DIDdoc_announce`, `pass_thru`, `present_claims`, `present_delegated`,
   `issuer_key_control`, `launch_issuer_key`, `custodian`,
   `recovery_authorize`) passes `curried-args` through untouched.
3. **Exactly one state-changing operation runs per spend** (spec §7.3).

## Why this is not fragile

Derivation is never trusted. Each candidate state is hashed into a full
singleton puzzle hash — `singleton_top_layer_v1_1` curried with the
`SINGLETON_STRUCT` and `julia_did` curried with `sha256tree(state)` — and
compared against the puzzle hash of the coin the chain actually holds.

The coin's puzzle hash *commits* to the state. A candidate that matches
therefore **is** the state, whichever rule produced it; a wrong prediction
cannot match without a SHA-256 collision. Identifying the operation is an
optimization, not a security property:

- **Primary**: the solution tree is scanned for a `(puzzle . solution)` pair
  whose car tree-hashes to an entry in the pinned puzzle-hash table, which
  names the operation directly.
- **Backstop**: every known transition is tried against every solution subtree
  (bounded), so a stale puzzle-hash table costs performance, never correctness.
- **Failure**: a spend that matches no candidate returns
  `didResolutionMetadata.error = "unverifiableState"`. The resolver never
  serves a guess.

## Validation

`tests/fixtures/transitions.json` holds ground-truth vectors captured by
executing the **real compiled puzzles** on the consensus VM through the
chialisp toolchain, using each puzzle's own test environment
(`julia-social/julia_did_chialisp` @ `7fbc6bc`, chialisp 0.4.5). Every
state-changing puzzle is covered, including two adversarial cases that pin
inputs the puzzles deliberately ignore (`recovery_complete`'s hostile
solution, `DIDdoc_set`'s extra solution elements). A transition that disagrees
with a vector disagrees with the chain.

The two committed mainnet recordings additionally prove the identity path
end to end: both canary DIDs resolve to documents byte-equivalent to the Python
reference resolver's.

**Updated 2026-09-02 — a real state change is now covered.** Until then every
committed recording was a spend that left state untouched, so this design had
been proved against the compiled puzzles but never against a mainnet
transition. The personal alias canary was rekeyed at block 9235350: generation
3 carries a different authentication root and a different singleton puzzle hash
than the generation before it. Derivation identifies that spend as `rekey`
through the child-puzzle-hash table (`source: "identified"`, not the exhaustive
backstop) and reproduces generation 3's on-chain puzzle hash, and both
resolvers produce byte-equivalent documents on either side of the change.
`versions.test.ts` asserts the operation and the source, so a table that stops
matching the chain fails loudly rather than degrading quietly into a search.

## Scope and limits

- Solution shapes are **puzzle-version specific**. This closed transition set
  is the current `julia_did` puzzle, which `did:julia:currentPuzzle` already
  reports. A DID on a predecessor puzzle still resolves when its most recent
  spend changed no state (the identity candidate is version-independent); one
  whose last spend rewrote state under an unrecognized puzzle version fails
  closed with `unverifiableState`.
- If resolving through unrecognized puzzle versions ever becomes necessary,
  adding a real CLVM engine is a separate, deliberate decision — not something
  to be reached by loosening the verification here.

## Consequences

- No WASM, no VM, no BLS operator implementation, no hardfork-flag tracking.
  The dependency surface is `@noble/hashes` for SHA-256 and nothing else.
- The verification is **stronger** than the reference resolver's: Python can
  report `stateVerified: false` for a state it read but could not verify, while
  this driver cannot serve such a state at all (see ADR 0003).
- Adding a seventh state-changing operation to the protocol requires adding its
  transition here. Until then such a spend fails closed, visibly, with a
  message that says why.
