# ADR 0002 — Package custody, naming, and distribution

Status: accepted (2026-08-26)

## Context

The did:julia method specification and its reference resolver live in
`julia-social/did-julia`. The TypeScript resolver needs a home, a name, and a
distribution path to ThisDID, whose convention is a ThisDID-custodied
`@thisdid/<method>-did-resolver` package vendored under `vendor/`, in one of
two families:

- **Wrappers** (`webvh`, `plc`) — a thin DIF-interface shim whose only runtime
  dependency is the method's own published npm package.
- **Clean-room implementations** (13 packages, e.g. `tz`, `xrpl`, `iota`) —
  built where no workerd-compatible package exists.

## Decision

**The canonical TypeScript resolver lives in this repository, at `ts/`, as
`@julia-social/did-julia-resolver`, beside the Python reference resolver and
the specification it implements.**

Julia Social owns the implementation of its own method. The spec, the Python
reference, the fixtures, and the TypeScript port move together, and the
language-neutral fixtures in `tests/fixtures/` are the single source of truth
both suites replay.

**ThisDID receives a vendored copy as `@thisdid/julia-did-resolver`**, following
its clean-room family rather than its wrapper family. A wrapper is not
available: wrappers depend on a published npm package, and this one is not
published (see below). The vendored README names this repository as upstream
and states retiring the copy in favour of a published package as its exit
criterion.

**The package is not published to npm.** `ts/package.json` carries
`"private": true`, which makes an accidental publish fail rather than succeed.
Publishing is a deliberate future step that needs an npm organization and an
owner for the release process; nothing in the ThisDID integration depends on
it.

## Alternatives considered

- **ThisDID-custodied only, no copy here.** Fastest to a merged PR and zero
  maintenance for Julia Social, but the canonical implementation of did:julia
  would live in someone else's repository, and the fixtures would have to be
  duplicated away from the spec they document.
- **Publish `@julia-social/did-julia-resolver` first, then a thin ThisDID
  wrapper.** The cleanest long-term shape and the one to move to eventually,
  but it puts an npm publish, an org, and a release process on the critical
  path of the ThisDID PR, and pins ThisDID to a version this project must then
  maintain. Deferred, not rejected.

## Consequences

- Two copies of the source exist while ThisDID vendors it. The copy is
  mechanical and the fixtures are checked for drift
  (`src/__tests__/fixtures.sync.test.ts` fails if the package's fixture copies
  diverge from `tests/fixtures/`).
- When the package is published, the ThisDID copy can be replaced by a wrapper
  in the `webvh`/`plc` shape without changing any resolution behaviour.
