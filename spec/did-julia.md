# The did:julia DID Method Specification

**Version:** 1.0 (Working Draft)
**Date:** 2026-08-24
**Author:** Ken Griggs, Julia.Social, Inc. (<ken@julia.social>)
**License:** [Apache License 2.0](../LICENSE)
**Reference implementation (on-chain puzzles):** <https://github.com/julia-social/julia_did_chialisp> (Apache 2.0)
**Further reading:** <https://not.bot/technology/>

---

## Abstract

`did:julia` is a [Decentralized Identifier](https://www.w3.org/TR/did-1.1/) (DID) method rooted in singleton coins on the Chia blockchain. A `did:julia` identifier is the base58 encoding of a Chia singleton launcher ID. The launcher ID is a cryptographic commitment to the DID's original BLS12-381 authentication key, so a DID's complete key history is verifiable from genesis, and signatures remain verifiable across key rotation. The current state of any `did:julia` DID — its authentication configuration, custodian list, recovery configuration, and DID Document pointer — is read from the chain by any Chia node, with no identity provider on the verification path.

The method supports single-key, multi-key, and multi-class multisig ownership; custodied DIDs; routine key rotation; time-locked and pre-rotated-key recovery; delegated credential issuance through issuer key singletons; credential presentation on-chain, off-chain, and fully offline; and Merkleized-bitfield revocation. Credential claims map to [W3C Verifiable Credentials 2.0](https://www.w3.org/TR/vc-data-model-2.0/) JSON-LD documents, and DID resolution produces a [DID 1.1](https://www.w3.org/TR/did-1.1/)-conformant DID Document.

This document is the self-contained specification of the method: identifier syntax, on-chain data model, create/read/update/deactivate operations, DID Document construction, the Verifiable Credential mapping, and the method's security and privacy considerations.

---

## 1. Introduction

### 1.1 What the method is and does

A `did:julia` DID is a long-lived, self-certifying, on-chain identity. It is implemented as a Chia **singleton** — a coin with a permanent launcher ID and exactly one live generation at any time. The launcher ID is the stable identifier; the singleton coin is recreated across generations as the DID's state changes, and every state change is a recorded, replayable spend.

Three properties distinguish the method:

1. **Self-certification from genesis.** A `did:julia` DID is created through a *prelauncher* coin that embeds the DID's original BLS12-381 public key. The launcher ID therefore commits to that key. Because every subsequent state change is a recorded spend, the full key history of a DID is verifiable from its identifier alone, with no registry, PKI, or key directory. A signature produced under a retired key still verifies against the DID that made it, because verification resolves the signer's lineage from the launcher commitment rather than from the current key.

2. **No issuer or provider on the verification path.** Resolving a DID, checking its current keys, and verifying a credential it presents are all reads of public Chia blockchain state, answerable by any of the thousands of public Chia nodes, the verifier's own node, or (for offline verification) a local snapshot. Julia Social, the method's originator, is not contacted during resolution or verification.

3. **Whole-identity signatures.** Authorization in `did:julia` is not a bare key signature. A DID spend is authorized under the identity's configured ownership model — single key, multi-key, multi-class multisig, or custody by another DID — and every signature in a spend bundle aggregates into one fixed-size BLS12-381 signature. A credential presentation can compose claims from any number of independent, uncoordinated issuers under a single aggregate signature.

The method serves humans, organizations, software agents, and physical objects through one model. Its first production deployment is [not.bot](https://not.bot), a passport-anchored personal identity product.

### 1.2 Audience and scope

This document is written for implementers of `did:julia` resolvers, verifiers, and wallets, and for reviewers of the W3C DID method registry. It is self-contained: everything needed to evaluate the method's syntax, operations, security, and privacy is in this document. The design-level and product-level companion documents at <https://not.bot/technology/> provide additional background but are not required reading.

### 1.3 Implementation status

The on-chain protocol described here is shipped and running on Chia mainnet. The Chialisp puzzle source is public at [julia-social/julia_did_chialisp](https://github.com/julia-social/julia_did_chialisp). One capability is **specified but not yet implemented**, and is flagged as such wherever it appears: the publication path that writes DID Document contents to Chia DataLayer and resolves them for readers (see [7.2](#72-read-resolve) and [12](#12-implementation-status)). The DID singleton's document-pointer mechanism is shipped; a `did:julia` DID is fully usable without any DID Document lookup, since the only required element of a DID Document is the DID itself.

---

## 2. Conformance

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in [BCP 14](https://www.rfc-editor.org/info/bcp14) ([RFC 2119](https://www.rfc-editor.org/rfc/rfc2119), [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174)) when, and only when, they appear in all capitals.

This specification targets:

- **[Decentralized Identifiers (DIDs) v1.1](https://www.w3.org/TR/did-1.1/)** for identifier syntax, DID Documents, and method requirements.
- **[Verifiable Credentials Data Model v2.0](https://www.w3.org/TR/vc-data-model-2.0/)** for the credential mapping in [Section 9](#9-verifiable-credentials).
- **[Controlled Identifiers v1.0](https://www.w3.org/TR/cid-1.0/)** for the `Multikey` verification method type.

Grammar in this document uses ABNF as defined in [RFC 5234](https://www.rfc-editor.org/rfc/rfc5234).

---

## 3. Terminology

Chia-specific terms used throughout:

| Term | Meaning |
|---|---|
| **Coin** | The unit of state on the Chia blockchain. A coin is identified by its coin ID, `sha256(parent coin ID, puzzle hash, amount)`. |
| **Puzzle** | The CLVM (Chialisp Virtual Machine) program locking a coin. The puzzle hash is a Merkle tree hash (`sha256tree`) of the program. |
| **Solution** | The arguments a spend supplies to a puzzle. |
| **Spend / spend bundle** | Spending a coin evaluates its puzzle with a solution and yields *conditions* (signature requirements, coin creations, announcements, assertions). A spend bundle is a set of coin spends plus one aggregate BLS12-381 signature covering all of them. The blockchain does not store conditions; a verifier replays the spend to derive them. |
| **Singleton** | A standard Chia construction guaranteeing that exactly one live coin descends from a given *launcher* coin at any time. The **launcher ID** — the coin ID of the launcher — is the singleton's permanent identifier. |
| **Prelauncher** | A `did:julia`-specific coin, spent immediately before the standard singleton launcher, whose puzzle embeds a BLS12-381 public key. See [7.1](#71-create). |
| **Curried arguments** | State values bound into a puzzle. The `did:julia` singleton commits to its state as `sha256tree(curried-args)`; the full state is revealed in each spend's solution and in a `REMARK` condition. |
| **`sha256tree`** | The CLVM tree hash: an atom hashes as `sha256(0x01 ‖ atom)`; a pair hashes as `sha256(0x02 ‖ sha256tree(left) ‖ sha256tree(right))`. |
| **DataLayer** | Chia's production key-value store construction, anchored by singletons. |
| **Issuer key singleton** | A separate singleton, launched by a DID, that carries credential-issuance authority: a signing key, validity window, allowed property set, and revocation state. See [Section 9.1](#91-the-claim-model). |
| **Claim** | A single issuer-signed statement: one property, one value commitment, one subject DID. `did:julia` credentials are single-claim; see [Section 9](#9-verifiable-credentials). |

---

## 4. DID Method Name

The method name is **`julia`**.

A DID that uses this method MUST begin with the prefix `did:julia:`. The prefix, including the method name, is case-sensitive and MUST be lowercase. The remainder of the DID after the second colon is the method-specific identifier defined in [Section 5](#5-method-specific-identifier).

## 5. Method-Specific Identifier

A `did:julia` method-specific identifier is the base58 encoding of the DID's 32-octet singleton launcher ID.

### 5.1 Syntax

```abnf
did-julia          = "did:julia:" method-specific-id
method-specific-id = 1*44base58char
base58char         = %x31-39 / %x41-48 / %x4A-4E / %x50-5A
                   / %x61-6B / %x6D-7A
```

The alphabet is the Bitcoin base58 alphabet:

```
123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz
```

which omits `0` (zero), `O` (capital o), `I` (capital i), and `l` (lower L). No checksum is applied. The encoding is the standard base58 big-integer conversion with leading-zero-octet preservation (each leading `0x00` octet encodes as a leading `1` character).

### 5.2 Validation

**The character count of the method-specific identifier is not fixed and MUST NOT be used for validation.** The base58 encoding of a 32-octet value varies in length: launcher IDs are SHA-256 outputs and therefore uniformly distributed, so approximately 94% of identifiers encode to 44 characters, about 5.7% to 43 characters, and roughly 1 in 1,000 to 42 or fewer. A length-based check would reject legitimate DIDs while passing every test a developer is likely to write.

A conforming implementation:

- MUST decode the method-specific identifier and MUST reject the DID unless the decoded value is exactly 32 octets;
- MUST NOT pad a decoding shorter than 32 octets;
- MUST reject any character outside the alphabet above.

The decoded value is the singleton launcher ID: a commitment to the DID's original authentication key, established at genesis by the prelauncher ([7.1](#71-create)), permanent across the identity's lifetime.

### 5.3 Example

```
did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX
```

This is a live mainnet DID. Its method-specific identifier decodes to the 32-octet launcher ID:

```
0x92543c68190662dc0e22ecc1d5315024a946dc572b253630d7983ac373249502
```

### 5.4 DID URLs

`did:julia` DIDs support the path, query, and fragment components defined by [DID 1.1 syntax](https://www.w3.org/TR/did-1.1/#did-url-syntax). This specification defines fragment identifiers for verification methods in [Section 8.2](#82-verification-methods). The method-independent `versionId` and `versionTime` DID parameters are supported; their `did:julia` semantics are defined in [Section 7.2.1](#721-version-specific-resolution). No method-specific path or query parameters are defined in this version.

---

## 6. On-Chain Data Model

### 6.1 DID singleton state

The DID singleton carries its state as eight curried-argument slots. The singleton puzzle is curried with `sha256tree(curried-args)` rather than the full state; the full state is revealed in every spend's solution, verified against the hash, and re-emitted in a `REMARK` condition, so a resolver reads current state directly from the most recent spend.

| Slot | Field | Purpose |
|---:|---|---|
| 1 | DID puzzle hash | Hash of the raw `did:julia` method puzzle |
| 2 | Launcher ID | The permanent DID identifier ([Section 5](#5-method-specific-identifier)) |
| 3 | Recovery status | `0` when no recovery is pending; the recovery delay while one is |
| 4 | Authentication configuration | Key Merkle root, class structure, and quorum requirements ([6.2](#62-authentication-configuration)) |
| 5 | Custodian DIDs | Launcher IDs of DIDs authorized to control this DID through custody |
| 6 | Recovery configuration | Recovery participant DIDs, quorum rules, delay, and pre-rotation commitment |
| 7 | DID Document pointer | DataLayer singleton launcher ID for the DID Document, or empty |
| 8 | Pending recovery parameters | The proposed replacement `(authentication, custodians, recovery)` triple while a recovery is armed; the empty atom otherwise |

### 6.2 Authentication configuration

The authentication configuration (slot 4) is the tuple:

```
(classes class-depth required-classes required-root)
```

- `classes` — a list of `(class-hash . required-members)` pairs;
- `class-depth` — the depth in the key Merkle tree at which internal nodes identify classes;
- `required-classes` — how many classes must be satisfied;
- `required-root` — the Merkle root of the key tree.

Authorized public keys are **leaves of a Merkle tree committed by `required-root`; the keys themselves are not stored in DID state.** A signer proves authorization by revealing a Merkle path from their BLS12-381 public key to the committed root, and the spend requires an `AGG_SIG_PUZZLE` signature from that key over the tree hash of the operation solution. Single-key DIDs are the degenerate case: one required class requiring one member. Multi-class configurations express organizational policies such as "two engineering keys and one executive key," beyond flat M-of-N. Every class MUST require at least one member; a zero-member class would be anyone-can-spend and is rejected by the on-chain code.

This commitment structure has a direct consequence for DID Documents: a resolver can always publish the authentication *commitment*, but can enumerate individual public keys only when the chain proves their membership. [Section 8.2](#82-verification-methods) defines the enumeration rule.

### 6.3 Issuer key singleton state

An issuer key singleton ([9.1](#91-the-claim-model)) carries: the issuer DID's launcher ID, its own launcher ID, a BLS12-381 public key, a Merkleized revocation-bitfield root, a validity window (`valid-from`, `valid-to`), a maximum credential expiration, a Merkle root of allowed credential property hashes, and an optional payment requirement for liveness attestation. The issuer DID retains lifecycle control: it can command revocation updates and can melt the key singleton, invalidating every credential that key ever signed.

---

## 7. CRUD Operations

### 7.1 Create

Creation establishes the launcher-ID-to-key commitment that makes the method self-certifying.

1. A **prelauncher** coin is created whose puzzle is curried with the DID's original BLS12-381 public key.
2. The prelauncher spend creates the standard Chia **singleton launcher**, and requires (via a `RECEIVE_MESSAGE` condition in the `JDID` protocol namespace) that the DID coin it gives rise to confirms back to it in the same spend bundle.
3. The launcher creates the first DID singleton generation (the *eve* coin), which asserts the launcher as its parent and emits the initial eight-slot state.

Because a Chia coin ID is `sha256(parent coin ID, puzzle hash, amount)`, and the launcher's parent is the prelauncher whose puzzle hash commits to the original public key, **the launcher ID — the DID identifier — is a hash commitment to the original key.** Anyone can verify the commitment by replaying the creation spends.

Creation requires small amounts of XCH for the coins and blockchain fees. In the production deployment this is supplied by a faucet mechanism in which the operator signs a fee-bearing spend bound to the user's spend by mutual concurrent-spend assertions, so the funds cannot be diverted and the user never holds XCH. The faucet is an operational convenience, not part of the method: any XCH source can fund creation.

### 7.2 Read (Resolve)

The current state of a `did:julia` DID is read from the Chia blockchain:

1. Decode and validate the method-specific identifier per [Section 5.2](#52-validation), yielding the launcher ID.
2. Locate the singleton's current (unspent) coin by walking the launcher's descendant chain — a standard Chia singleton traversal any full node supports.
3. Obtain the eight-slot state from the most recent spend's output `REMARK` condition, verifying `sha256tree(curried-args)` against the puzzle's curried commitment.
4. Construct the DID Document per [Section 8](#8-did-documents).

Any Chia full node can answer. Resolution requires no participation from Julia Social or any other party specific to this method.

A DID whose launcher ID does not correspond to a valid `did:julia` creation ([7.1](#71-create)) does not exist; resolution MUST return a `notFound` error. A DID in the deactivated state resolves per [7.4](#74-deactivate).

**DID Document contents and the DataLayer pointer.** Slot 7 of the DID state may carry the launcher ID of a Chia DataLayer singleton holding extended DID Document contents (service endpoints and other metadata) as structured key-value pairs. The pointer mechanism — announcing and updating slot 7 — is shipped. **The publication path that writes DID Document contents to DataLayer and resolves them for readers is specified and not yet implemented.** Until it ships, no `did:julia` DID has a linked document, and a conforming resolver produces the *default DID Document* defined in [Section 8](#8-did-documents) from on-chain singleton state alone. A `did:julia` DID is fully usable without any DID Document lookup: the only required element of a DID Document is the DID itself, and `did:julia` verification runs against chain state rather than against document contents.

### 7.2.1 Version-specific resolution

Every state change is a new singleton generation, and every generation the DID has ever had remains on chain. `did:julia` therefore supports the method-independent `versionId` and `versionTime` DID parameters, which a resolver accepts as DID resolution options or as DID URL query parameters. They are **mutually exclusive**: a request carrying both MUST be refused rather than answered by one of them.

A `did:julia` **version ID is the coin ID of a singleton generation** — the same value [Section 8.5](#85-resolution-metadata) requires in `versionId` document metadata. Version IDs are 32-octet content commitments, not sequence numbers: a coin ID is the hash of the coin's own parent, puzzle hash, and amount, so a version ID names one specific generation of one specific DID and cannot be guessed forward. A resolver MUST accept the value in lower-case hexadecimal, with or without a `0x` prefix.

Resolution proceeds as follows:

1. Decode and validate the method-specific identifier per [Section 5.2](#52-validation), yielding the launcher ID.
2. Walk the singleton's descendant chain from the launcher, recording every generation. This is the traversal of [Section 7.2](#72-read-resolve) run to completion rather than stopped at the unspent coin.
3. Select the requested generation:
   - **`versionId`** selects the generation whose coin ID equals the requested value.
   - **`versionTime`** — an [XML datetime](https://www.w3.org/TR/xmlschema11-2/#dateTime) carrying a UTC designator or an explicit offset — selects the *latest* generation whose confirming block timestamp is at or before the requested time. A singleton may be spent more than once in a single block, so several generations can share a timestamp; the last of them is the state that block left behind, and is the one selected.
4. Read that generation's state:
   - A **superseded** generation reveals its own state in its own spend: every `julia_did` solution carries the spend's pre-spend eight-slot state verbatim as its first inner argument, and the coin's puzzle curries in that state's hash. No state transition need be replayed, and none is trusted.
   - The **current** (unspent) generation has no spend of its own and is read exactly as in [Section 7.2](#72-read-resolve).
5. Verify before serving. A resolver MUST check that the revealed puzzle hashes to the generation's on-chain puzzle hash and that the state read out of the spend recomputes to that same puzzle hash. Because the commitment checked is the one held by the coin the caller named, a resolver cannot substitute a different version — including the current one — for the version requested.
6. Construct the DID Document per [Section 8](#8-did-documents) and populate document metadata per [Section 8.5](#85-resolution-metadata).

The first generation is always resolvable this way: creation requires the eve coin to be spent in the same spend bundle that creates it ([7.1](#71-create)), so it has a spend of its own from the moment the DID exists.

Verification-method enumeration ([8.2](#82-verification-methods)) applies to the *requested* version: a key is listed only when its membership in that generation's authentication Merkle root is proven, which is what makes a historical document usable for checking a signature made while that version was current ([7.3](#73-update)).

Errors are distinguished:

- A well-formed `versionId` that no generation of the DID has, and a `versionTime` earlier than the DID's first generation, are `notFound`: the version named does not exist.
- A `versionId` that is not a 32-octet hex value, and a `versionTime` that is not an XML datetime with a UTC designator or offset, are `invalidDidUrl`.
- A resolver that does not implement version-specific resolution MUST refuse the option rather than returning the current document in its place; silently answering a different question than the one asked is the one failure a caller cannot detect.

### 7.3 Update

All updates are authenticated state changes on the singleton, authorized under the DID's ownership model (single-key, multi-key, multi-class multisig — [6.2](#62-authentication-configuration) — or custody). The update operations are:

- **Rekey** — replaces the authentication configuration (slot 4) under authorization of the *current* configuration. Key rotation does not invalidate previously issued signatures: verification resolves the signer's key history from the launcher commitment ([7.1](#71-create)), so a signature made under a retired key still verifies against the DID that made it.
- **DID Document pointer update** — replaces slot 7.
- **Custodian command** — a DID that lists custodian DIDs (slot 5) can be operated by a custodian through a spend-bundle message committing to the exact operation. Custody is DID-native and attributable: the custodied DID's spend record identifies the commanding custodian. A custodian cannot rotate the owner's keys, cannot participate in recovery, and cannot extend custody to a third identity.
- **Time-locked assisted recovery** — recovery participants are DIDs, not raw keys. A quorum of configured participants *initiates* recovery, committing a pending replacement triple (slot 8) and starting a delay (slot 3). During the delay, normal authenticated operations are blocked; the participants can *cancel*. After the delay, anyone can *complete* the recovery, applying the pending state.
- **Pre-rotated-key recovery** — the DID commits in advance to a successor key configuration inside slot 6. If current keys are lost or compromised, the pre-rotated keys take over immediately, with no delay, and the operation commits the next pre-rotation so the property is preserved.

The protocol uses one uniform **inert-tree sentinel** wherever a control structure is present but deliberately unsatisfiable: a single-leaf Merkle tree of an all-zero value, with the leaf width matching the committed value type. A pre-rotation or authentication configuration is disabled by committing to the all-zero **48-octet** value — not a valid BLS12-381 public key, so no signature can ever satisfy it. A recovery-agent tree is empty when its root commits to the all-zero **32-octet** value — no real launcher ID, so no participant can ever prove membership. A DID that does not use pre-rotation carries the sentinel rather than an absent commitment.

Operations that do not change state — signing messages, presenting credentials, commanding DID-owned coins, announcing the document pointer — are designed to be *fast-forward compatible*: authorization binds to the puzzle hash (which commits to state) via `AGG_SIG_PUZZLE` and `ASSERT_MY_PUZZLEHASH` rather than to a specific coin, so any number of unchanged-state spend bundles remain valid regardless of confirmation order. A state-changing spend produces a new puzzle hash and invalidates authorizations bound to the old state.

### 7.4 Deactivate

**A `did:julia` DID cannot be deleted.** The Chia singleton *melt* operation is deliberately excluded from the method: a melt is irreversible, and if a malicious recovery took temporary control of a DID, melting it would leave the owner nothing to recover. Deactivation without destruction gets no such shortcut.

Deactivation is **bricking**: an authenticated update (or completed recovery) that leaves the DID with no satisfiable control path — no key, custodian, or recovery participant can ever operate it again — while its singleton, launcher ID, and full history remain on chain permanently. Each control structure is dead in either of two recognized encodings: the empty atom (**the canonical brick encoding** for slots 4, 5, and 6), or the inert-tree sentinel of [7.3](#73-update) (the all-zero 48-octet key tree for authentication and pre-rotation; the all-zero 32-octet tree for recovery agents). No `did:julia` DID has been deactivated on mainnet as of this document's date.

A resolver MUST report a DID as deactivated — `"deactivated": true` in the DID document metadata — when the authentication configuration, the custodian list, and every recovery path (agents and pre-rotation) are each empty or inert under the encodings above. A DID with an unsatisfiable authentication configuration but a live custodian list or recovery path is not deactivated: control can return through those paths.

---

## 8. DID Documents

Resolution produces a JSON-LD DID Document conforming to [DID 1.1](https://www.w3.org/TR/did-1.1/). Because the DataLayer publication path is not yet implemented ([7.2](#72-read-resolve)), this section defines the **default DID Document**: the document a conforming resolver constructs from on-chain singleton state alone. When DataLayer publication ships, published contents will extend — never contradict — the default document; the state projected from the singleton remains authoritative.

### 8.1 Representation

The default DID Document is JSON-LD with the context:

```json
"@context": [
  "https://www.w3.org/ns/did/v1",
  "https://w3id.org/security/multikey/v1",
  "https://not.bot/ns/did-julia/v1"
]
```

The first context is the DID **v1** context rather than `…/ns/did/v1.1`: as of this document's date the v1.1 context URL does not dereference (W3C returns HTTP 300 even under JSON-LD content negotiation), so documents citing it fail JSON-LD expansion in conforming processors. Every core term this specification uses (`id`, `verificationMethod`, `authentication`, `assertionMethod`) is defined identically in the v1 context. This specification will move to the v1.1 context URL when W3C publishes a dereferenceable document there.

The third context defines this method's `julia`-prefixed properties ([8.3](#83-method-specific-properties)) and the `proof` terms of [Section 9.6](#96-mapping-claims-to-a-vc-20-document). Its source of record is [`contexts/did-julia-v1.jsonld`](../contexts/did-julia-v1.jsonld) in this repository, served at `https://not.bot/ns/did-julia/v1` with content type `application/ld+json`. **The published `/v1` context is immutable once this specification is registered**: semantic changes mint `/v2`, never edit `/v1` in place, so processors may cache the context indefinitely. Term IRIs are minted under the unversioned vocabulary namespace `https://not.bot/ns/did-julia#`, independent of the context version, so documents produced under different context versions share term identity and canonicalize together.

### 8.2 Verification methods

`did:julia` signing keys are BLS12-381 public keys in the G1 group (48 octets, compressed), the key type native to Chia. A verification method is represented as a [`Multikey`](https://www.w3.org/TR/cid-1.0/#multikey):

- `type`: `"Multikey"`
- `publicKeyMultibase`: the multibase base58-btc encoding (`z` prefix) of the multicodec `bls12_381-g1-pub` header (`0xea`, varint-encoded as `0xea 0x01`) followed by the 48-octet compressed G1 public key
- `controller`: the DID itself
- `id`: the DID followed by `#` and the `publicKeyMultibase` value, making the fragment content-addressed and stable

The `bls12_381-g1-pub` multicodec entry has *draft* status in the multicodec registry; this specification pins the code value `0xea` regardless of future registry changes.

**Enumeration rule.** On-chain DID state commits to authorized keys by Merkle root and does not store the keys ([6.2](#62-authentication-configuration)). A resolver therefore MUST include a verification method for exactly those public keys whose membership in the **current** authentication root is proven by on-chain data:

- the original key revealed by the prelauncher spend, when the current root still commits to the genesis configuration; and
- any key revealed in a spend solution whose validated Merkle path terminates in the current root.

A resolver MUST NOT list a key whose membership in the current root it cannot prove, and MUST NOT treat the absence of a listed key as evidence the DID has no keys. For the common case — a single-key personal DID — the current key is enumerable from creation onward. After a rekey to keys that have not yet signed, the document may contain no verification methods until a new key first appears in a spend; the authentication *commitment* ([8.3](#83-method-specific-properties)) is always present.

Enumerable keys are referenced from the `authentication` and `assertionMethod` verification relationships.

**Verification does not flow through the DID Document.** Consumers should understand that `did:julia` proofs (spends, presentations, signed messages) are verified by replaying Chia spends against chain state and the launcher commitment — not by looking up a key in the DID Document and checking a detached signature. The DID Document is a standards-conformant *projection* of on-chain state for interoperability with DID-consuming software; it is not the verification mechanism.

### 8.3 Method-specific properties

The default document carries the full on-chain control state under method-defined properties (context: `https://not.bot/ns/did-julia/v1`):

| Property | Content |
|---|---|
| `juliaAuthentication` | The slot-4 tuple: `merkleRoot` (hex), `classDepth`, `requiredClasses`, and `classes` as `[{ "classId": hex, "requiredMembers": n }]` |
| `juliaCustodians` | Array of custodian DIDs (as `did:julia` DIDs), from slot 5 |
| `juliaRecovery` | The recovery configuration (slot 6): `configured`, `recoveryAgents` (whether a participant quorum is committed), `delayBlocks` (the time-lock), and `prerotation` (`"committed"`, or `"disabled"` when the commitment is the all-zero sentinel of [7.3](#73-update)). On chain, recovery participants and pre-rotated keys are committed by Merkle root and class hashes — the same commitment structure as the authentication configuration — so the identities of a DID's recovery agents are not readable from chain state and are revealed only by the Merkle paths a recovery operation itself discloses. The document publishes structure and presence, never participant identities. |
| `juliaRecoveryPending` | `true` while a time-locked recovery is armed (slot 3 nonzero); absent otherwise |
| `juliaDocumentPointer` | The DataLayer singleton launcher ID from slot 7, hex, when set |

Generic DID resolvers and consumers will understand `id`, `verificationMethod`, `authentication`, and `assertionMethod`, and will ignore the `julia`-prefixed properties; nothing a generic consumer ignores is required for correct use of the standard properties.

### 8.4 Example: single-key DID

The DID from [Section 5.3](#53-example), as a genesis-configuration single-key document. Every value below is real and independently checkable against the chain.

That DID has since been rekeyed, so this is the document the reference resolver produces for the *version* that its genesis key governed — `versionId` `0x0e04c04dbb693f72eb5151753bf7b69ec468476945fe50d684e03609cf390f29`, equivalently any `versionTime` between its confirmation and the rekey ([7.2.1](#721-version-specific-resolution)). Resolving the same DID with no version option returns its current document, which carries the *new* authentication commitment and, until a spend authorized under the new key reveals one, no verification method ([8.2](#82-verification-methods)). Both are shown below, because the pair is the method's central property: rotating a key does not invalidate what the retired key signed, since the version that was current at signing time still resolves to it ([7.3](#73-update)).

```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/multikey/v1",
    "https://not.bot/ns/did-julia/v1"
  ],
  "id": "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
  "verificationMethod": [{
    "id": "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX#z3tEGcUFd9MoqHs65VRn6QB5t8SYEshaWvXnxbGzUzSCRCeLvMFjCtcTFRjLYUzdEAQPWk",
    "type": "Multikey",
    "controller": "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
    "publicKeyMultibase": "z3tEGcUFd9MoqHs65VRn6QB5t8SYEshaWvXnxbGzUzSCRCeLvMFjCtcTFRjLYUzdEAQPWk"
  }],
  "authentication": [
    "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX#z3tEGcUFd9MoqHs65VRn6QB5t8SYEshaWvXnxbGzUzSCRCeLvMFjCtcTFRjLYUzdEAQPWk"
  ],
  "assertionMethod": [
    "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX#z3tEGcUFd9MoqHs65VRn6QB5t8SYEshaWvXnxbGzUzSCRCeLvMFjCtcTFRjLYUzdEAQPWk"
  ],
  "juliaAuthentication": {
    "merkleRoot": "0x4dd0f8d8ff9869ecfab8d49ea96757e3f3c0a5f9345a5cf03bfa253a42712357",
    "classDepth": 1,
    "requiredClasses": 1,
    "classes": [{
      "classId": "0xa0ec22f33862573137ad49d2b7af224d4d722b73bf5c0ecc27edf688e614892f",
      "requiredMembers": 1
    }]
  },
  "juliaCustodians": [],
  "juliaRecovery": {
    "configured": true,
    "recoveryAgents": true,
    "delayBlocks": 4320,
    "prerotation": "disabled"
  }
}
```

The same DID after the rekey, resolved with no version option:

```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/multikey/v1",
    "https://not.bot/ns/did-julia/v1"
  ],
  "id": "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
  "juliaAuthentication": {
    "merkleRoot": "0x76e9c885bf0fa6b637ac3da01c652081ff4d8ab7521ccb8542fd14c2fd5a786c",
    "classDepth": 1,
    "requiredClasses": 1,
    "classes": [{
      "classId": "0xcce929457b710a08b1e060a2968561ac958388945836589baa7f837903f1df39",
      "requiredMembers": 1
    }]
  },
  "juliaCustodians": [],
  "juliaRecovery": {
    "configured": true,
    "recoveryAgents": true,
    "delayBlocks": 4320,
    "prerotation": "disabled"
  }
}
```

A rekey publishes a commitment, not a key: slot 4 carries the new Merkle root and class identifiers, and the public key itself never appears in DID state ([6.2](#62-authentication-configuration)). The rekey spend reveals only the *outgoing* key, which is what authorized the rotation. So a conforming resolver enumerates no verification method for the new configuration until a later spend proves a key's membership in it — the [8.2](#82-verification-methods) rule applied to a configuration nothing has yet satisfied, rather than a resolver limitation.

For a single-key DID, the key tree has a fixed two-level shape: the class node is the key paired with itself, `(K . K)`, and the root is the pair of that class with the empty atom, so `merkleRoot = sha256tree(((K . K) . 0))` and `classDepth` is 1. The `merkleRoot` and `classId` above recompute from the `publicKeyMultibase` key by exactly that construction.

A multisig organizational DID differs in `juliaAuthentication` (multiple classes, higher quorums) and typically lists several verification methods as its keys appear in spends. A custodied DID may have an empty `verificationMethod` array and one or more entries in `juliaCustodians`. A deactivated DID resolves to a minimal document (`@context` and `id`) with `"deactivated": true` in the DID document metadata.

### 8.5 Resolution metadata

Resolvers MUST populate DID document metadata with at least:

- `deactivated`: per [7.4](#74-deactivate);
- `versionId`: the coin ID of the singleton generation the document was read from, hexadecimal with a `0x` prefix;
- `updated`: the timestamp of the block confirming that generation, when the resolver has it.

A result produced by version-specific resolution ([7.2.1](#721-version-specific-resolution)) MUST additionally carry, since walking the lineage establishes them:

- `created`: the timestamp of the block confirming the DID's first generation;
- `nextVersionId` and `nextUpdate`: the coin ID of the generation that superseded the one resolved, and the timestamp of the block confirming it — present only when the resolved version is not the current one.

Current-state resolution reports only what a single reading of the unspent coin establishes, so that its metadata does not vary with which traversal a node's RPC surface allowed. All timestamps are XML datetimes in UTC without sub-second precision.

---

## 9. Verifiable Credentials

`did:julia` carries credentials as **single-claim, individually signed statements** anchored to issuer key singletons on chain, and maps sets of claims to [W3C Verifiable Credentials 2.0](https://www.w3.org/TR/vc-data-model-2.0/) JSON-LD documents. This section defines the claim model, the property-name grammar, and the JSON-LD mapping.

### 9.1 The claim model

A **claim** is one issuer-signed statement: one property, one value, one subject DID. Its structural fields are:

- the **subject** DID launcher ID;
- the **issuer** DID launcher ID and the issuer key singleton that signed it;
- `sha2-256(property name)` — the property, stored hashed ([9.2](#92-property-names));
- a **32-octet value commitment** produced by the property's encoding pipeline ([9.3](#93-value-encoding));
- validity bounds (inception and expiration);
- a **revocation index** into the issuer key's Merkleized revocation bitfield;
- optional **antecedent** requirements: other claims that must be presented alongside this one for it to be valid ([9.5](#95-antecedents));
- a **delegatable** flag;
- a hash reference to a shared **metadata document** ([9.4](#94-credential-metadata));
- the issuer key's BLS12-381 signature over the claim's tree hash.

Issuance is delegated through **issuer key singletons** ([6.3](#63-issuer-key-singleton-state)). A DID launches an issuer key for its own signing or for a delegate; the key's validity window, maximum credential expiration, and allowed-property Merkle root bound what it can issue. The issuer DID can revoke individual credentials by index (up to 512 in one on-chain transaction) or melt the key, invalidating everything it ever signed. Claim presentation requires an issuer-key liveness attestation, so a melted key's credentials stop being presentable.

Single-claim packaging makes **selective disclosure a list operation**: the holder presents the claims that match a request and omits the rest, with no zero-knowledge machinery. The signatures on presented claims remain valid; omitted claims never appear.

Presentations operate in three modes with the same credentials: **on-chain** (a permanent public record, available to smart contracts), **online off-chain** (verified locally against any Chia node; no transaction recorded), and **fully offline** (verified against a snapshot of issuer keys and revocation state, using the DID's self-certifying lineage). Off-chain presentations carry a structural invalidator — an assertion of a concurrent spend of a coin that cannot exist — so they can never be submitted to the chain; see [11](#11-privacy-considerations). Every presentation aggregates the presenter's authentication signature and all claim signatures into one BLS12-381 signature, bound by a nonce; see [10.5](#105-aggregation-and-signature-subtraction).

### 9.2 Property names

Every claim names its property with a URI:

```abnf
property-name = encoding "://" authority path
encoding      = enc-stage *( "|" enc-stage ) / reserved-enc
enc-stage     = "cleartext" / "sha2-256" / "argon2id" / "aes256gcm"
              / "rsa3072" / "zip" / "CBOR"
reserved-enc  = "julia" / "notbot"
authority     = "." / method-specific-id      ; "." = the issuing DID
path          = 1*( "/" segment )
segment       = 1*( unreserved )              ; RFC 3986 unreserved
```

- **Encoding** names the value-encoding pipeline ([9.3](#93-value-encoding)).
- **Authority** is the DID whose namespace defines the property's semantics: `.` denotes the issuing DID; otherwise a `did:julia` method-specific identifier (base58, without the `did:julia:` prefix).
- **Path** is the authority's own taxonomy, e.g. `/v1/pii/age_range_18_20`.

Examples: `cleartext://./.julia-payment`, `notbot://./v1/notbot0`, `sha2-256|CBOR://./v1/domain_name`. The `julia` and `notbot` encoding identifiers are reserved: they denote Julia Social-defined encodings, and decoding a value under either requires Julia Social software. A third party cannot mint property names under them.

The signed claim stores `sha2-256(property name)`, not the cleartext. The cleartext name travels in every presentation; the verifier hashes the name it expects and matches the claim. The chain never reveals cleartext property names.

### 9.3 Value encoding

The encoding segment specifies the pipeline that reduces a cleartext value to the claim's 32-octet commitment. Stages compose with `|` in **function-composition order: the rightmost stage applies to the value first, and the leftmost stage produces the final committed form.** `sha2-256|CBOR` means the value is CBOR-encoded (as deterministic dCBOR), then SHA2-256-hashed: `sha2-256(CBOR(value))`.

| Stage | Role |
|---|---|
| `cleartext` | Identity: the value fits in 32 octets and is not transformed |
| `sha2-256` | Hash commitment for values larger than 32 octets |
| `argon2id` | Hardened commitment for low-entropy values |
| `aes256gcm` | Symmetric encryption |
| `rsa3072` | Asymmetric encryption, restricting decryption to a specific verifier |
| `zip` | Compression |
| `CBOR` | Deterministic serialization (dCBOR) of structured values |

A verifier replays (or, for encrypting stages, reverses) the pipeline against the value the holder reveals and matches the result against the claim's commitment. Every credential incorporates entropy from a cryptographically secure source before commitment, so two claims over the same underlying value never share a committed form; see [11](#11-privacy-considerations). Stage parameters (Argon2id constants, salt and nonce conventions, key fingerprints) are fixed by the reference implementation.

### 9.4 Credential metadata

A claim references a shared **metadata document** by hash. The metadata document carries the issuer's human-readable name and description, per-claim names, descriptions, and translations, and the W3C-standard refresh-service, terms-of-use, and evidence fields. Metadata is inline by default — hosted metadata would let the issuer observe credential use through fetches ([11](#11-privacy-considerations)) — and partially elidable: presenting one claim does not require revealing metadata for the others the document describes.

### 9.5 Antecedents

A claim may require **antecedent** claims: the claim is valid in a presentation only when its antecedents are presented and valid alongside it. Antecedents may come from other issuers and may name other subjects. They give the method machine-verifiable authority chains and **cascade revocation**: revoking an antecedent invalidates, at presentation time, every claim that depends on it, with no action by the dependent claims' issuers. Presenting a claim necessarily discloses its antecedent structure; see [11](#11-privacy-considerations).

### 9.6 Mapping claims to a VC 2.0 document

Claims that share a metadata document hash MAY be combined into one W3C Verifiable Credential:

1. `@context` begins with `https://www.w3.org/ns/credentials/v2`.
2. `type` includes `VerifiableCredential` and `JuliaCredential`.
3. `issuer` is the issuer's `did:julia` DID.
4. `credentialSubject.id` is the subject's `did:julia` DID; each combined claim contributes one property, keyed by its cleartext property name, with the revealed (decoded) value.
5. `validFrom` is the latest inception among the combined claims; `validUntil` is the earliest expiration.
6. The **`proof`** is a `DataIntegrityProof` with the method-defined cryptosuite **`julia-clvm-2026`**. The proof carries the material a verifier needs to check the claims against the chain: the signed claim structures, the (possibly partially elided) metadata document, the hash reveals tying cleartext property names and values to the claims' commitments, and the aggregate BLS12-381 signature. `verificationMethod` identifies the signing issuer key singleton as a DID URL fragment on the issuer DID: `did:julia:<issuer>#issuer-key-<base58 issuer-key launcher ID>`.

**Cryptosuite status, stated plainly:** a `did:julia` proof is a BLS12-381 aggregate signature over CLVM structures. It corresponds to no cryptosuite in the [Data Integrity cryptosuite registry](https://www.w3.org/TR/vc-di-bbs/) family. Emitting a conformant VC 2.0 *data model* with a method-defined cryptosuite is legitimate under VC 2.0; claiming a registered cryptosuite would not be, and this specification does not. Verifiers without `julia-clvm-2026` support can consume the credential's data model but cannot verify its proof.

Example (illustrative values):

```json
{
  "@context": [
    "https://www.w3.org/ns/credentials/v2",
    "https://not.bot/ns/did-julia/v1"
  ],
  "type": ["VerifiableCredential", "JuliaCredential"],
  "issuer": "did:julia:<issuer-method-specific-id>",
  "validFrom": "2026-08-01T00:00:00Z",
  "validUntil": "2026-08-31T23:59:59Z",
  "credentialSubject": {
    "id": "did:julia:ArD2JyqfkVVbT9Liegqu4jcfBEXtHnPofmF2rsBuq1TX",
    "notbot://./v1/pii/age_over_18": true
  },
  "proof": {
    "type": "DataIntegrityProof",
    "cryptosuite": "julia-clvm-2026",
    "proofPurpose": "assertionMethod",
    "verificationMethod": "did:julia:<issuer-method-specific-id>#issuer-key-<base58-launcher-id>",
    "juliaClaims": ["<dCBOR, multibase-encoded signed claim>"],
    "juliaMetadata": "<dCBOR, multibase-encoded metadata document, elided fields omitted>",
    "juliaReveals": [{ "property": "notbot://./v1/pii/age_over_18", "value": "<revealed encoding-pipeline input>" }],
    "proofValue": "<multibase-encoded aggregate BLS12-381 signature>"
  }
}
```

The byte-level serialization of `juliaClaims`, `juliaMetadata`, `juliaReveals`, and `proofValue` is fixed by the reference drivers and will be documented with them; the structure above is normative.

---

## 10. Security Considerations

This section addresses the security topics [DID 1.1 §7.3](https://www.w3.org/TR/did-1.1/#security-requirements) requires of method specifications, in method-relevant terms.

### 10.1 Trust model

The root of trust is Chia blockchain consensus plus the launcher commitment. A verifier trusts (a) that the Chia chain it reads is the honest chain, and (b) SHA-256 and BLS12-381. It does not trust Julia Social, any resolver operator, or any issuer for *authentication* facts; issuers are trusted only for the *content* of the claims they sign. Because conditions are derived by replaying spends rather than read from storage, a verifier with a full node validates everything locally. Verifiers reading through a remote node they do not control should be aware that a lying node can misreport chain state; verifiers with higher assurance requirements run their own node or check multiple independent nodes. Recently confirmed operations carry ordinary blockchain settlement risk; verifiers apply confirmation-depth policies appropriate to their use.

### 10.2 Authorization binding and state integrity

Every operation is authorized under the DID's configured ownership model, and the authorization is **state-bound**: signatures are `AGG_SIG_PUZZLE` over the tree hash of the operation solution, tied to the puzzle hash that commits to current DID state. A state change changes the puzzle hash and invalidates every authorization bound to the old state, so a stolen pre-signed operation cannot be applied after a rekey. Operation routing is **hash-enforced**: an authenticated spend can invoke only a fixed allowlist of operation puzzles, identified by embedded compiled hashes, so an authenticated caller cannot inject arbitrary behavior into the identity layer.

### 10.3 Eavesdropping, replay, insertion, deletion, modification

All on-chain data is public by design and carries no secrets ([Section 11](#11-privacy-considerations) covers what that publicity discloses). Modification and deletion of recorded state are prevented by chain consensus; a DID's history cannot be rewritten below reorganization depth. Replay is prevented at three layers: state-bound authorization ([10.2](#102-authorization-binding-and-state-integrity)); optional nonces embedded in signed messages and presentations; and, for off-chain presentations, optional time-window assertions bounding validity. Message insertion into the identity layer is prevented by the **`JDID` namespace guard**: the arbitrary-condition passthrough operation rejects caller-supplied announcements and messages that are structured or `JDID`-prefixed, so application conditions cannot spoof DID, credential, issuer, or recovery signals. 

### 10.4 Key rotation, recovery, and compromise scenarios

- **Routine rotation:** rekey replaces the authentication configuration at any time; past signatures survive rotation because verification resolves from the launcher commitment.
- **Key compromise:** the owner rekeys immediately, or — if the attacker rekeyed first — invokes pre-rotated-key recovery, which switches to the pre-committed successor configuration instantly and cancels any recovery in flight, or time-locked assisted recovery through recovery-participant DIDs.
- **Recovery lockout:** while an assisted recovery is pending, all normal authenticated operations are blocked, so a compromised current key cannot race state changes through the recovery window. The configured participants can cancel a recovery they did not intend.
- **Malicious recovery:** an attacker who suborns a recovery quorum gains control only after the time-lock, during which the owner's pre-rotated keys or a cancellation quorum can intervene. The deliberate absence of a melt operation ([7.4](#74-deactivate)) caps the damage: a temporary controller cannot destroy the identity.
- **Issuer key compromise:** the issuer DID melts the issuer key singleton, invalidating everything it ever signed in one transaction; per-credential revocation handles finer cases.

### 10.5 Aggregation and signature subtraction

BLS aggregation admits a *signature-subtraction* attack: an attacker holding an aggregate and all but one of its components could recover the remaining component as a reusable signature. `did:julia` closes this with required nonces on presentations: the aggregate binds to a presentation-scoped nonce, so no clean signature over a lone claim can be extracted. This is also what prevents a verifier that receives a presentation from re-presenting the claims it saw ([9.1](#91-the-claim-model)).

### 10.6 Denial of service

A singleton can be spent once per transaction block (~52 seconds on Chia). The design keeps this from being an attack surface or a bottleneck: unchanged-state operations are fast-forward compatible ([7.3](#73-update)), so concurrent spends do not invalidate each other; multiple operations combine into one spend; and off-chain presentations consume no chain capacity at all and can be produced in unlimited number. On-chain spam against a specific DID is not possible: only authorized parties can spend the singleton (completion of a matured recovery being the deliberate exception). Chain-level flooding is mitigated by Chia's fee market, which is outside this method's scope.

### 10.7 Identifier integrity and validation pitfalls

The method-specific identifier is self-certifying ([7.1](#71-create)): it cannot be squatted or forged, since binding a launcher ID to a different genesis key would require a SHA-256 second preimage. Uniqueness is guaranteed by coin-ID uniqueness under Chia consensus. An easily-hit known pitfall is implementation-side: implementations MUST validate by decoding to exactly 32 octets ([5.2](#52-validation)) — length-only heuristics pass ~999 of 1,000 identifiers and silently reject the rest, and padding a short decoding manufactures a plausible-looking launcher ID that identifies nothing.

### 10.8 Cryptographic agility

The method deliberately has **no signature agility**: BLS12-381 is the only supported signature scheme at the identity layer, because non-interactive constant-size aggregation is structural to credential composition and it is the scheme Chia verifies natively. P-256, secp256k1, Ed25519, and passkey keys are not supported. The hash function throughout is SHA-256. The consequence is stated honestly: a break of BLS12-381 or SHA-256, including by cryptographically relevant quantum computers, is not survivable by algorithm substitution within this method version; migration would require a protocol revision and new DIDs, mitigated for continuity by the recovery and custody structures. Timestamps in signed messages are **self-attested** by the signer's clock and must be weighed as a trust property of the signer, not as notarized time; block timestamps bound on-chain operations independently.

---

## 11. Privacy Considerations

This section addresses the privacy topics [DID 1.1 §7.4](https://www.w3.org/TR/did-1.1/#privacy-requirements) requires, in method-relevant terms. The formal party-by-party assertions for the production deployment are published at <https://not.bot/technology/> (Privacy Architecture).

**No personal data on chain.** A `did:julia` DID and its state contain no personal data: state is keys-by-commitment, configuration, and pointers. Credential claims store `sha2-256(property name)` and a 32-octet value commitment and every commitment incorporates fresh entropy, so identical underlying values (a name, an over-18 flag) never produce matching on-chain or presented forms, defeating frequency analysis and cross-credential matching. DID Documents produced under this method carry no personal data, and implementations MUST NOT write personal data into DataLayer document contents when that path ships.

**No issuer contact at presentation (anti-surveillance).** Verification reads the Chia blockchain: the issuer key singleton, its revocation bitfield, the subject DID's state, and any antecedent claims. The issuer is not contacted and learns nothing about when, where, or to whom a credential is shown. Credential metadata defaults to inline for this reason — externally hosted metadata would reveal use through the fetch — and a holder can elide external metadata links before presenting. Blockchain reads can go to any of thousands of public nodes or the verifier's own node, so no single party observes a user's query pattern.

**Correlation resistance across contexts.** The method is designed for one entity to hold many DIDs cheaply (creation is faucet-fundable), and the production deployment derives every DID in an identity independently from one secret: given two alias public keys, no observer can determine they share a parent. The same credential value issued to two DIDs yields two cryptographically unlinkable claims. Entities SHOULD use distinct DIDs for distinct contexts; nothing in the method links them.

**No on-chain record of off-chain use.** Off-chain presentations carry a structural invalidator — an asserted concurrent spend of a coin that cannot exist — so a presentation given privately can never be submitted to the chain and repurposed into a permanent public record of the interaction.

**Revocation without holder disclosure.** Revocation state is a Merkleized bitfield on the issuer key singleton, carrying no holder identifiers. An observer of a revocation update learns that some index changed, not which credential or whose. An offline verifier's snapshot of issuer state contains nothing about individual holders. Two issuer-side rules protect subjects further, and issuers MUST follow them: **revocation indices MUST NOT be assigned in issuance order** (an ordered index leaks issuance order and volume; assign indices randomly across the field), and **validity windows MUST NOT encode sensitive attributes** (setting Valid-From on an over-18 credential to the subject's eighteenth birthday writes the birth date into every presentation).

**On-chain traffic analysis and decoys.** DID creation, rekey, and recovery are on-chain and observable, and their timing is a correlation channel: several DIDs rekeying in one block would suggest common ownership. The production deployment runs a decoy service submitting faucet-funded creates, rekeys, and recoveries structurally indistinguishable from real ones, adding noise against timing analysis and clustering. Network-level observers of a user's node connections see queries, not identity data; users route reads across random public nodes, and a VPN and encrypted DNS mitigate what remains.

**Structural disclosure through antecedents.** Presenting a claim discloses the existence and property hashes of its antecedents, which must themselves be presented. Credential schema designers MUST treat antecedent structure as visible to every verifier.

**Permanence.** A `did:julia` DID cannot be deleted ([7.4](#74-deactivate)). Its singleton, key history, and every state change remain publicly readable forever, including after deactivation. This is the method's ledger permanence: users get unlinkable per-context DIDs and content-free on-chain state *instead of* erasability. What is never written cannot need erasing; implementers and issuers MUST keep it never-written.

---

## 12. Implementation Status

| Capability | Status |
|---|---|
| DID singleton protocol: create, authenticate (single-key, multisig, custody), rekey, recovery (assisted, cancel, pre-rotation), document pointer, message signing, coin control, presentations, issuer keys, revocation | **Shipped**, Chia mainnet; puzzle source public at [julia-social/julia_did_chialisp](https://github.com/julia-social/julia_did_chialisp) |
| Production drivers (Rust) and mobile app (not.bot) | **Shipped** (proprietary) |
| DataLayer DID Document publication and resolution ([7.2](#72-read-resolve)) | **Specified, not implemented** |
| Python reference resolver (this repository, `src/did_julia/`) | **Shipped** — resolves live mainnet DIDs and verifies recomputed state against the on-chain singleton puzzle hash |
| TypeScript resolver for the DIF `did-resolver` interface (this repository, `ts/`) | **Shipped** — same verification, no CLVM execution; byte-equivalent to the Python reference against the committed mainnet recordings |
| Version-specific resolution: `versionId` and `versionTime` ([7.2.1](#721-version-specific-resolution)) | **Shipped** in both resolvers |
| VC 2.0 export driver ([Section 9.6](#96-mapping-claims-to-a-vc-20-document)) | **Planned** |
| Universal Resolver / Universal Registrar drivers | **Planned** |

## 13. Intellectual Property

The Chialisp reference implementation and this specification are published under the [Apache License 2.0](../LICENSE). The `julia` and `notbot` credential property namespaces are reserved by Julia.Social, Inc. ([9.2](#92-property-names)); the DID method itself carries no usage restriction.

## 14. References

### Normative

- [Decentralized Identifiers (DIDs) v1.1](https://www.w3.org/TR/did-1.1/), W3C
- [Verifiable Credentials Data Model v2.0](https://www.w3.org/TR/vc-data-model-2.0/), W3C
- [Controlled Identifiers v1.0](https://www.w3.org/TR/cid-1.0/), W3C
- [Verifiable Credential Data Integrity 1.0](https://www.w3.org/TR/vc-data-integrity/), W3C
- [RFC 5234](https://www.rfc-editor.org/rfc/rfc5234): ABNF
- [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) / [RFC 8174](https://www.rfc-editor.org/rfc/rfc8174): Key words
- [Multibase](https://github.com/multiformats/multibase) and [Multicodec](https://github.com/multiformats/multicodec) (`bls12_381-g1-pub` = `0xea`)
- [BLS Signatures (draft-irtf-cfrg-bls-signature)](https://datatracker.ietf.org/doc/draft-irtf-cfrg-bls-signature/), as deployed by Chia (Augmented scheme, G1 public keys)

### Informative

- [julia-social/julia_did_chialisp](https://github.com/julia-social/julia_did_chialisp) — the on-chain reference implementation
- [Chia singletons](https://docs.chia.net/guides/singletons/) and [CLVM condition reference](https://docs.chia.net/coin-set-and-conditions/), Chia Network
- not.bot technology documentation — <https://not.bot/technology/>, including the design-level did:julia Technical Specification at <https://not.bot/technology/did-julia-specification/>
- [No Phone Home](https://nophonehome.com/) — the verification-architecture principle [Section 11](#11-privacy-considerations) implements
