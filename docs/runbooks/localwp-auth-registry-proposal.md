# Proposal: LocalWP auth registry (non-secret inventory, OS secret store for values)

> **Status: CLEAR PROPOSAL, NOT IMPLEMENTED.** No credential database exists or
> was created. No registry tool is available in this repository, and this
> document does not invoke any CLI. Nothing here logs in to WordPress, mints or
> revokes a key, or changes a site, a serving store, or a secret store. The
> architecture choices below are proposals for review, not canonical mandates.
> Canon rows cited are from heuristics-canon v0.26.2 and are normative as
> published.

## Decision

Scope is LocalWP sites only. Out of scope: the demo WordPress site and its
secrets on the VM, historical material, and any cross-tenant service
credential.

Where wp-admin passwords and API keys go:

1. **SQLite holds only a non-secret inventory.** It records references and
   metadata: LocalWP site identifier, origin, install path, service base URL,
   verified store/environment, tenant UUID, key ID, credential kind, an opaque
   secret-store reference, config source (constant or option), and timestamps.
   It holds no secret value, hash, prefix, fragment, or length. The database
   file and any export stay out of Git and out of client bundles.
2. **Raw secret values live only in the OS Keychain or an approved OS secret
   store.** The Keychain value is the authority. The WordPress config value is
   a derived consumer copy.
3. **Three credential kinds, kept separate:**
   - *WordPress admin interactive password*: a human login. The registry never
     logs in automatically and never uses it to call a service.
   - *WordPress application password*: for REST/automation only; it cannot be
     used for interactive wp-login/wp-admin login and is distinct from the
     ordinary WordPress login password. Use only if the site's existing
     permissions support it. This design does not depend on it.
   - *Tenant service API key*: the key the plugin sends to one hosted service,
     for one tenant, in one store.

   The WordPress login credential is distinct from the service API key.
   WordPress nonces are per-session request tokens and are not stored.
4. **Never in the WordPress registry:** cross-tenant service admin tokens, Clerk
   secrets, database DSNs, or SSH private keys.

## Why the database cannot hold the secret

The metadata database cannot be a plaintext secret store. It also cannot be an
encrypted secret vault whose key sits beside it. SQLCipher with a co-located key
is not the proposed solution, because anyone who can read both the file and its
key gets the secret. Canon WEB-16 keeps plaintext secrets out of source,
committed config, and client artifacts; this design goes further and keeps
secret values out of the registry entirely. Canon SEC-06: anything an LLM agent
can read can be extracted by a user, so this document and the registry carry no
secret values, and agent transcripts must not echo them.

## Binding model

A registry record binds all of the following. A record is valid only when they
agree:

| Field | Meaning |
| --- | --- |
| LocalWP site UUID | Registry-assigned stable identifier for the site |
| LocalWP origin and install path | Observed origin (for example `http://localhost:10028`) and install path |
| Service base URL | The hosted service the plugin calls |
| Verified store/environment | The serving store that URL resolves to (for example `dev-fir`) |
| Tenant UUID | The tenant in that store |
| Key ID | Non-secret ID of the key |
| Keychain reference | Opaque reference to the secret-store item. No value |
| Config source | `constant` or `option`, as the plugin resolves it |

A `localhost` browser origin does not make the backend key local. A key is
correct only for the serving store its service base URL resolves to (see
[key management, dev-fir client](key-management.md#localwp-dev-fir-client-remote-isolated-store)).
The binding is per site and per store, not per portal user.

## Config source and drift

The plugin resolves constants before options (see
[key management, step 5](key-management.md#steps-prod-admin-console--canonical)).
The registry records the effective source and reports drift when the effective
constant differs from the recorded source. It never silently overwrites a user
edit, never imports credentials from a remote site, and never falls back to
another site's credential. The Keychain value is authoritative; the WordPress
copy is checked by effective source and key ID, never by value or hash.

## Recovery and replacement

- The registry cannot recover an old API key by ID. The service stores keys as
  hashes and shows each raw key once, so a key cannot be read back from it.
- Recovery order: (1) use the authorized existing copy in the Keychain or
  approved secret store, if one exists, and verify it; (2) otherwise issue a new
  scoped key with the environment's maintained CLI or admin console, install it,
  and verify the correct endpoint, tenant, and store; (3) revoke the old key ID
  only after that verification is healthy.
- Create and revoke are not retried blindly. A retried create mints a second key
  (canon RES-01). After an ambiguous create, list the tenant's keys and reconcile
  before any retry. Verification calls carry bounded timeouts (canon RES-02).
- CLI create/revoke and portal rotation are different contracts. This proposal
  does not invent rotation flags; follow
  [tenant onboarding §3](tenant-onboarding-smoke-test.md#cli-mintrevoke-and-portal-rotation-are-different-contracts).
- After revoke, prove the old key is denied and the new key still passes. That
  operational negative control checks the replacement.

## Single workflow for future implementation

Proposed, not built:

1. **Register (read-only).** The operator names a LocalWP site. The registry
   records origin, install path, service base URL, and verified environment from
   observation or operator entry. It writes no secret value.
2. **Capture the secret once.** The operator creates or receives the secret and
   stores it in the OS Keychain or an approved OS secret store, through that
   store's own prompt. The registry records only the opaque reference and key
   ID. The value is shown once, never echoed, and never placed in argv, a log,
   or a transcript.
3. **Install.** The operator installs the value as a constant or Settings option,
   as [key management](key-management.md) describes. Constants override options.
   The registry does not write WordPress config on its own.
4. **Verify.** The operator runs Settings Test Connection against the effective
   credentials. The registry records the effective source and key ID only.
5. **Replace or revoke** under the rules above.

Access controls on the operator's Mac stay in force. Any access prompt or
approval the Mac requires still applies. The design does not depend on
unattended reads and does not promise to bypass those controls.

## Scope limits

These limits are stated here so the summary below does not overstate the design
(canon WRIT-81):

- This registry does not fix Aura TLS readiness or model accuracy. Those are
  separate work.
- It adds no UI flow. It reuses the existing Settings page and Test Connection.
- The demo WordPress site and its VM secret store stay outside the registry. No
  central ingestion or copy of them is proposed.
- This is not a compliance checklist.

## Current state (known facts, no values)

- LocalWP `fir` site at `http://localhost:10028`, targeting
  `https://fir.dev.api.altcontext.com`, key environment `dev-fir`, SFace 128D
  model space.
- LocalWP `wp-context-alt-text` site at `http://localhost:10010`, a laptop-only
  InsightFace evaluation path.
- The existing working demo key stays active. This proposal does not revoke or
  rotate it.
- Measured endpoint facts are not endpoint-quality PASS results.

## Prior art and canon

In repo:

- [Key management](key-management.md): the two-track model and the canonical
  entry point for tenant and key work.
- [Tenant onboarding smoke test](tenant-onboarding-smoke-test.md): §1 targets and
  readiness gates, §3 CLI and portal contracts.
- [LocalWP development runbook, gate secrets](../../apps/prototype-wp-alt-context/docs/localwp-development-runbook.md#gate-secrets-site-local-config):
  the site-local config include pattern.

Canon (heuristics-canon v0.26.2): SEC-06, WEB-16, DATA-14, RES-01, RES-02,
SEC-01, TEST-15, WRIT-81.

- DATA-14: one system of record per value. The Keychain owns values; the registry
  derives status from observed effective source.
- SEC-01: the registry validates the service base URL and store at the boundary
  before it binds a key.

## Acceptance checks for a future implementation (not run)

- The registry schema has no column that can hold a secret value, hash, prefix,
  or length.
- No secret value appears in logs, argv, exports, or the Git tree.
- Drift is reported when the effective constant differs from the recorded
  source, and no file is overwritten.
- A replacement first verifies the new key passes Test Connection, then revokes
  the old key ID, then proves the old key is denied and the new key still passes.

## Open decisions

- Which LocalWP sites have WordPress application passwords enabled under their
  existing permissions. Until that is checked, the design does not use them.
- The Keychain item naming convention for each credential kind.
