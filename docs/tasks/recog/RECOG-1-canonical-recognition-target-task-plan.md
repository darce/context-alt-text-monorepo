# RECOG-1. Canonical recognition target: retire the local backend from the product surface

> **Metadata**
>
> - **Date**: 2026-07-13 EST
> - **Author**: claude-opus-4-8
> - **Project**: prototype-wp-alt-context + prototype-description-service
> - **Task ID**: RECOG-1
> - **Target Branch**: `feature/recog-1`
> - **Review Coverage Target**: 2

## Objective

Make the hosted/remote recognition service the single canonical target the WP plugin talks to. Retire the local backend from the **product surface** (Settings UI, the `acx_recognition_local_url` option, and the local/service source toggle) while keeping local reachable as a **dev-only, code-level escape hatch** (constant/filter). Flip the default recognition source `local → service`. Consolidate tenant-key issuance so the OCI/prod `--env` database is the canonical issuer and `dev-mint-key` is explicitly a local-fixtures-only tool. Do **not** add an unauthenticated recognition path.

## Problem Statement

Facial recognition and image captioning are GPU workloads that now run only on the OCI bursty-GPU VM; the local Mac backend cannot reproduce them. Yet the plugin **defaults `recognition_source` to `local`** and exposes a local/hosted target chooser in Settings, so:

- Product/UX is validated against a low-fidelity local target that does not match what any real user gets [DIAG-08 QA≠prod; PROD-12 builder–user proximity].
- A fresh install sits in "waiting for service" because the default source is `local` and local is unpaired.
- The Settings surface carries local-vs-hosted complexity (two URL fields, a source toggle, per-target probes, two target cards) that no shipped configuration needs [REF-21 pull complexity down; LAY-10 every surviving default must be a choice].
- Two Makefile minting entrypoints (`dev-mint-key`, `provision-customer`) issue tenant keys against different `--env` databases with no stated system-of-record [DATA-14].

## Design direction (heuristics-anchored)

1. **Retire the target, not the capability [DIAG-08].** The plugin talks to hosted by default; local remains reachable but only through the resolver's constant/filter tiers, which already sit above the option tier. Removing the *option + UI* is the retirement; keeping the *constant/filter* is the dev hatch.
2. **The escape hatch is code-level, never a product feature or an auth hole [REF-12 YAGNI; SEC-04 least-privilege].** No unauthenticated recognition path — pairing/auth stays uniform across dev and prod (a no-auth path would test a different code path than prod, exactly the anti-parity DIAG-08 warns against). Dev convenience is solved by a one-shot pairing helper against the canonical issuer, not by removing auth.
3. **Every surviving default is a choice [LAY-10].** Flip `recognition_source` default to `service`; the "waiting for service" papercut is the default `local` speaking.
4. **One issuer of record [DATA-14].** The OCI/prod `--env` DB is canonical for real tenants; `dev-mint-key` is re-scoped and labeled as local-test-fixtures only (the two entrypoints already share one minter — `scripts.manage_api_keys` / `scripts.provision_customer` — so this is a scoping + docs consolidation, not a code merge).
5. **Removing a target re-opens the state matrix [RLSE-04].** The Settings loading/empty/error/probe/offline states must be re-designed for a single-target world, incl. focus + live-region announcements (↔ A11Y-24), not left to merely render.

Greenfield policy applies: delete-over-flag, no back-compat shim for the removed option (no production data to preserve).

## Out of scope (explicit)

- **No unauthenticated recognition path** (evaluated and rejected: negative value — security surface + parity break + no GPU fidelity gain).
- **Hot-sync remote dev environment** (sub-second file sync + warm remote test runner). This is the only thing that would justify retiring the *local test suite* too; it is a separate future task and is NOT required by this one. The fast local *unit* suite stays.
- No change to the local pytest inner-loop suite (GPU-independent, mocked) — that is the fast dev loop and is unaffected.

## Constraints

- Cross-boundary: touches the plugin↔recognition proxy contract (headers, target resolution) and the settings REST shape. Contract table below.
- Keep `class-recognition-endpoint-resolver.php` precedence (constant → filter → option → default) intact; only the option tier + default value change.
- Frontend token discipline (sr-004) for any Settings UI change; the target-card component and its SCSS are already token-clean (WBUX-DEEMPH-A11Y).
- No secrets in code/config [WEB-16]. Minting keys printed once, never committed.

## Terminology

- **Recognition source**: `local` | `service` — which backend the plugin proxies to (`acx_recognition_source`).
- **Product surface**: the Settings UI + persisted `acx_*` options a non-developer touches.
- **Dev hatch**: the `ACX_RECOGNITION_LOCAL_URL` constant + `acx_recognition_source` constant/filter — code-level, wp-config/dev only.
- **Canonical issuer**: the OCI/prod `--env` tenant DB that mints real customer keys.

## Current State Analysis (ground-truth via codemap, 2026-07-13, worktree @ 45a6c4de)

- `src/api/class-recognition-endpoint-resolver.php`: `resolve_service_url_source()`, `resolve_local_url_source()` (default `DEFAULT_LOCAL_URL`), `resolve_recognition_source_source()` (**default `'local'`**), all constant→filter→option→default.
- `src/api/class-settings-controller.php`: save path writes `acx_recognition_url`, `acx_recognition_source` (validated), `acx_recognition_api_key`, `acx_recognition_local_url` (:137/:150/:156/:169); `probe_target ∈ {local, service}` (:218-238); snapshot exposes `local_url`, `effective_target_mode/url`, `recognition_source`.
- `src/api/class-abstract-recognition-proxy-controller.php`: reads base_url + local_url, sends `X-Tenant-ID` + `X-API-Key`.
- TS: `js/admin/pages/SettingsPage.tsx`, `settings/SettingsForm.tsx`, `settings/useSettingsPageState.ts`, `js/components/ui/target-card.tsx` (local + service cards; the deemphasized card fixed in WBUX-DEEMPH-A11Y).
- Service minting: `Makefile` `dev-mint-key` (→ `scripts.manage_api_keys --env local`), `provision-customer` (AP-7 → `scripts.provision_customer --env <local|…>`), `admin-dev`; both go through the shared minter.
- Prior art: `MAINT-tenant-pairing-recovery-20260711` recently reworked the resolver for pairing — review its decisions (#1933/#1947) before touching resolution precedence.
- **Authoritative touchpoint inventory: see `Files and Surfaces to Change` (populated from the RECOG-1 codemap-grounded enumeration).**

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compat? | Verification |
| --- | --- | --- | --- | --- | --- |
| Settings REST (`acx/v1` settings GET/POST) | PHP plugin | body accepts `recognition_source`, `local_url`, `probe_target ∈{local,service}`; snapshot returns `local_url`/`effective_target_mode` | Drop `local_url` write + `local` from UI-posted source/probe; snapshot keeps `effective_target_*` (now always service) | no (greenfield; no external consumer) | SettingsControllerTest, e2e wp-rest fixture |
| Plugin↔recognition proxy | PHP proxy ctrl | resolves target from source+urls; sends tenant+key | default target = service; local only via constant | no | RecognitionEndpointResolverTest, ProxyRequestTest |
| Tenant key issuance | description-service | two Makefile entrypoints over one minter | OCI `--env` canonical; `dev-mint-key` labeled fixtures-only | n/a (docs+scope) | manage_api_keys/provision tests |

## Proposed Solution / Slice Delivery

### Slice 1: Flip default to service + preserve the dev constant hatch

**Goal**: A fresh/unconfigured plugin targets hosted by default; local stays reachable only via constant/filter.

Changes:
- `class-recognition-endpoint-resolver.php`: `resolve_recognition_source_source()` default `'local' → 'service'`. Keep constant/filter/option precedence untouched.
- Confirm proxy + sync-health behave when source=service and no local_url is set.
- Tests: update `RecognitionEndpointResolverTest` default-source assertions; add a test that `ACX_RECOGNITION_SOURCE=local` constant still overrides (hatch preserved).

Proof: `vendor/bin/phpunit --filter RecognitionEndpointResolver` green; default source asserted `service`; constant-override test green.

### Slice 2: Retire local from the Settings product surface (UI + option) [RLSE-04, REF-21, LAY-10]

**Goal**: Settings presents a single hosted-service configuration; no local URL field, no source toggle, no local target card/probe.

Changes:
- `settings-controller.php`: stop writing/reading `acx_recognition_local_url` from the UI path; drop `local` from UI-posted `recognition_source`/`probe_target` validation (constant/filter still honored by the resolver). Snapshot returns a single effective (service) target.
- `SettingsForm.tsx` / `useSettingsPageState.ts` / `target-card.tsx` / `SettingsPage.tsx`: remove the local target card + local URL field + source toggle; keep the service URL + API key + a single health/probe. Re-design the state matrix (loading/empty/error/unpaired/offline) for one target, incl. focus + `role=status` announcements [RLSE-04 ↔ A11Y-24].
- Tests: update `SettingsControllerTest`, `AdminTest`, settings e2e (`wp-rest.ts`, settings-axe); add a state-matrix assertion for the single-target error/unpaired states.

Proof: vitest settings suites + `SettingsControllerTest` green; `settings-axe` empty-state 0 serious/critical; manual state-matrix walk recorded.

### Slice 3: Consolidate key issuance to the canonical OCI issuer [DATA-14]

**Goal**: One documented system-of-record for tenant keys; `dev-mint-key` unambiguously local-fixtures-only.

Changes:
- `apps/prototype-description-service/Makefile` + `docs/`: document the OCI/prod `--env` DB as the canonical issuer for real tenants (via `provision-customer`/admin); relabel `dev-mint-key` help + output as "local test fixtures only — not a real tenant". Add a one-shot `make dev-pair` (or documented flow) that mints a fixture key and prints the wp-config constants for the dev hatch (no auth removed).
- No change to the shared minter internals unless the enumeration finds a real divergence.
- Tests/docs: update `docs/secrets-inventory.md` / onboarding docs; confirm `provision-customer`/`manage_api_keys` tests unaffected.

Proof: docs reviewed; `dev-mint-key`/`provision-customer` help text asserts scope; no behavior regression in minter tests (remote gate or local scoped).

## Files and Surfaces to Change

> Populated from the RECOG-1 codemap-grounded enumeration (grok inventory, `recog-1-inventory-OUT.md`). Placeholder until merged:

| Surface | File | Change | Slice |
| --- | --- | --- | --- |
| _(from inventory)_ | | | |

## Verification Strategy

- Deterministic: `vendor/bin/phpunit` (scoped: RecognitionEndpointResolver, SettingsController, ProxyRequest, Admin, SyncHealth) + `node_modules/.bin/vitest run` (settings suites).
- A11y/visual: `settings-axe.spec.ts` empty-state 0 serious/critical (runs headless, no pairing needed); state-matrix walk for the single-target Settings.
- Gate: `make check-remote` on committed HEAD (backend Python suite; no JS/PHP target on the gate — run scoped PHP/vitest locally, per the standing gap).
- Contract: settings REST fixture (`wp-rest.ts`) reflects the dropped `local_url`.
- **Operator-dependent (flagged, not blocking this task)**: the online keyboard-walk/live-region a11y specs still require the plugin paired to a live backend; unaffected by this task's scope.

## Consolidated Checklist

## Context and Ownership
- [ ] Loaded resolver + settings + minting ground truth and the MAINT-tenant-pairing-recovery lineage before editing.
- [ ] Recorded the Settings REST + proxy contract deltas.

### Checklist for Slice 1: Default flip + dev hatch
- [ ] Resolver default source `service`; precedence intact.
- [ ] Constant-override (hatch) test green; resolver suite green.

### Checklist for Slice 2: Settings retirement
- [ ] `local_url` + local source/probe removed from the UI/save path; resolver constant/filter preserved.
- [ ] Settings UI single-target; state matrix (loading/empty/error/unpaired/offline) re-designed with focus + announcements.
- [ ] settings-axe 0 serious/critical; settings unit/e2e green.

### Checklist for Slice 3: Minting consolidation
- [ ] OCI `--env` documented canonical; `dev-mint-key` relabeled fixtures-only.
- [ ] `make dev-pair` (or documented flow) mints a fixture key + prints dev-hatch constants; no auth removed.

## Review Readiness
- [ ] Boundary deltas (settings REST, proxy target) have matching test/fixture evidence.
- [ ] State-matrix + a11y evidence captured for the new single-target Settings.
- [ ] Handoff decision records the contract changes and the deliberate escape-hatch design.

## Success Criteria
- [ ] Default recognition source is `service`; a fresh plugin targets hosted with no "waiting for service" from a local default.
- [ ] Settings exposes one hosted-service configuration; no local URL/toggle/card; local reachable only via constant/filter.
- [ ] No unauthenticated recognition path exists.
- [ ] OCI issuer is documented canonical; `dev-mint-key` is unambiguously fixtures-only.
- [ ] Scoped PHP + vitest green; settings-axe 0 serious/critical; `make check-remote` green.

## Heuristic IDs cited
[DIAG-08] [DATA-14] [LAY-10] [RLSE-04] [REF-12] [REF-21] [REF-24] [SEC-04] [WEB-16] [PROD-11] [PROD-12] [PROD-14] + repo Greenfield Policy, sr-004. All verified present in heuristics-canon (engineering, business-marketing, security, design-aesthetics) 2026-07-13.
