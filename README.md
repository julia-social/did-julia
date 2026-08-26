# did-julia

The specification and reference material for **`did:julia`**, a [W3C Decentralized Identifier](https://www.w3.org/TR/did-1.1/) method rooted in [Chia blockchain](https://www.chia.net/) singletons, operated by [Julia Social](https://not.bot).

A `did:julia` identifier is the base58 encoding of a Chia singleton launcher ID — a hash commitment to the DID's original BLS12-381 key. A DID's full key history verifies from genesis, signatures survive key rotation, and every resolution and credential verification is a read of public chain state: no identity provider sits on the verification path.

## Contents

- **[spec/did-julia.md](spec/did-julia.md)** — the method specification: identifier syntax, on-chain data model, CRUD operations, DID Document construction, the Verifiable Credentials 2.0 mapping, and security and privacy considerations.
- **[src/did_julia/](src/did_julia/)** — the Python reference resolver.
- **[ts/](ts/)** — the TypeScript resolver for the DIF `did-resolver` interface, for edge runtimes.
- **[registration/](registration/)** — the W3C DID method registry entry.

## The reference resolver

```bash
pip install -e .
python examples/resolve.py did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX
```

```python
from did_julia import resolve
result = resolve("did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX")
print(result["didDocument"])
```

Resolution reads public Chia blockchain state — by default through the open [Coinset](https://coinset.org) mainnet RPC, or your own full node via `FullNodeClient(base_url=..., cert=...)`. The resolver does not trust its data source: it recomputes the singleton's full puzzle hash from the parsed state and checks it against the on-chain coin (`did:julia:stateVerified` in the resolution metadata). Tests run offline against committed mainnet fixtures: `python -m pytest`.

Dependencies are `requests` and `chia_rs` (the consensus VM binding, used only to execute the most recent spend for its state-carrying `REMARK` condition); base58, CLVM (de)serialization, tree hashing, and curried-puzzle-hash math are implemented in readable pure Python.

## The TypeScript resolver

[`ts/`](ts/) holds `@julia-social/did-julia-resolver`, a port of the reference resolver to the DIF [`did-resolver`](https://github.com/decentralized-identity/did-resolver) interface that runs in edge runtimes such as Cloudflare Workers.

```ts
import { Resolver } from "did-resolver";
import { getResolver } from "@julia-social/did-julia-resolver";

const result = await new Resolver(getResolver()).resolve(
  "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
);
```

It reaches the same verified state by a different route: rather than executing the most recent spend to read its `REMARK`, it **derives** the next generation's state from the spend's own solution and proves the derivation by recomputing the singleton puzzle hash. A derivation that matches the chain's commitment is the state; one that does not is never served. That removes the CLVM engine from the dependency graph entirely — SHA-256 is the only primitive it needs — without weakening verification ([ADR 0001](ts/docs/adr/0001-state-derivation-without-clvm.md)).

Both implementations replay the same language-neutral fixtures in [`tests/fixtures/`](tests/fixtures), and the TypeScript suite asserts its resolution results are **byte-equivalent** to the Python resolver's recorded output. Its state transitions are pinned by ground-truth vectors captured from executing the real compiled Chialisp puzzles.

Known v1 limitation, stated in the spec (§8.2): verification-method enumeration proves key membership for single-key configurations (the personal-DID common case). Multi-key Merkle-path replay from historical spends is future work; the authentication commitment is always published.

## Status

The on-chain protocol is shipped and running on Chia mainnet; the Chialisp puzzle source is public at [julia-social/julia_did_chialisp](https://github.com/julia-social/julia_did_chialisp) (Apache 2.0). The specification is honest about what is not yet implemented: DID Document publication through Chia DataLayer is specified but not shipped (spec §7.2, §12), and the VC 2.0 export driver is planned.

## Example

```
did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX
```

A live mainnet DID. The method-specific identifier decodes to the 32-octet launcher ID `0x92543c68190662dc0e22ecc1d5315024a946dc572b253630d7983ac373249502`. Validate by decoding — never by character count (spec §5.2).

## More

Design-level and product documentation: <https://not.bot/technology/>

## License

[Apache License 2.0](LICENSE)
