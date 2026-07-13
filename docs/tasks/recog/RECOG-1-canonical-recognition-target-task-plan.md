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

## Key decisions from the enumeration (resolves open questions)

The codemap-grounded inventory (`RECOG-1-inventory.md`, 58 rows / 10 surprises) forced these explicit calls:

1. **Local surface is bigger than Settings.** It also includes the Workbench local-mode banner (`WorkbenchPage.tsx:100-110`), the WP admin notice (`class-admin.php:render_recognition_config_notice`), and a **second localhost default** in `config.ts:normalizeConfig` (missing `effectiveTargetUrl` → `http://localhost:8000`). All three are in the product-retire scope.
2. **Settings REST contract**: DROP the writable `local_url` field and the UI-posted `recognition_source`/`probe_target=local`. KEEP a read-only `effective_target_*` (+ `recognition_source` as read-only diagnostics) in the GET snapshot so the hatch state stays observable. Greenfield: no migration; stale `acx_recognition_local_url` options are simply ignored.
3. **Remove the unauthenticated local `/health` probe** (`test_connection` local path, keyless). Retiring `probe_target=local` deletes a keyless code path — a small attack-surface reduction [SEC-04]; a dev using the constant hatch can curl `/health` directly.
4. **The dev hatch is wp-config `define()`, not `.env`** — `alt-context.php` bootstraps env only for `ACX_RECOGNITION_URL`/`_API_KEY`, not `_SOURCE`/`_LOCAL_URL`. Document the `define()` recipe; optionally add env bootstrap for the two (decide in S1).
5. **`provision-customer` Makefile default `ENV=local` is a prod footgun** — real customers minted against the local DB by default. Fix in S3: require explicit `--env prod` (or flip the default) so the canonical issuer is not bypassed by omission.
6. **LocalWP smoke scripts hard-require `source=local`** (`batch-run-smoke.php`, `describe-run-smoke.php`) and the e2e `wp-rest.ts` helper POSTs `recognition_source: local` on probe failure — both break when the default flips; retarget them to the constant hatch or service.
7. **The keyless local probe is the only no-auth path**; the proxy already always requires a key (`AbstractRecognitionProxyController:91-98`) — confirms "no no-auth hatch" is already true for real traffic, and removing the probe closes the last keyless door.

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

### Slice 2: Retire local from the product surface (Settings + Workbench + admin notice + config default) [RLSE-04, REF-21, LAY-10, SEC-04]

**Goal**: The product presents a single hosted-service configuration everywhere; no local URL field, source toggle, local target card/probe, or local banners.

Changes:
- `settings-controller.php`: drop the `acx_recognition_local_url` write + `local` from UI-posted `recognition_source`/`probe_target` validation; **remove the unauthenticated local `/health` probe path** [SEC-04]. GET snapshot keeps read-only `effective_target_*` + `recognition_source` diagnostics.
- FE: `SettingsForm.tsx` (remove `TargetCardGroup` radio, local card, local URL input, local probe), `useSettingsPageState.ts` (drop `localUrl`/source actions), `SettingsPage.tsx` (drop `local_url`/source from save + `localUrlReadOnly`), `settingsApi.ts` (drop `local_url*` types + `local` probe mode), `healthStatus.ts` (drop local branch), `config.ts` (**stop defaulting `effectiveTargetUrl` to localhost** → empty/service). Collapse the service card to a non-radio single form; re-design the state matrix (loading/empty/error/unpaired/offline) for one target incl. focus + `role=status` announcements [RLSE-04 ↔ A11Y-24].
- Notices: `WorkbenchPage.tsx:100-110` local-mode banner + `class-admin.php:render_recognition_config_notice` — remove, or reword to a constant-hatch-only diagnostic.
- Tests: update the named set in the inventory §4.1 — `SettingsControllerTest`, `AdminTest`, `SettingsPage.test.tsx`, `healthStatus.test.ts`, `settingsResponseContract.test.ts`, `WorkbenchPage.test.tsx`, e2e `wp-rest.ts` + `workbench-evidence`/`scan-runtime-evidence`; keep `settings-axe` green.

Proof: vitest settings/workbench suites + `SettingsControllerTest`/`AdminTest` green; `settings-axe` empty-state 0 serious/critical; state-matrix walk recorded; grep confirms no product-path `local_url`/local-probe writes remain.

### Slice 3: Canonical key issuance + fixtures-only `dev-mint-key` + smoke/e2e retarget [DATA-14]

**Goal**: One documented system-of-record for tenant keys; `dev-mint-key` unambiguously local-fixtures-only; the default-flip doesn't break the local smokes.

Changes:
- `apps/prototype-description-service/Makefile` + `README.md` + `docs/secrets-inventory.md`: document OCI/prod `--env` DB as canonical issuer; relabel `dev-mint-key`/`dev-setup` as "local test fixtures only — not a real tenant" (help + stderr banner); **fix the `provision-customer` `ENV=local` default** so real customers require explicit `--env prod` (decision 5).
- Retarget `scripts/localwp/batch-run-smoke.php` + `describe-run-smoke.php` (which hard-require `source=local`) and the `wp-rest.ts` `ensureLocalRecognitionWhenProbeFails` helper to the constant hatch or service, so the default flip doesn't break them.
- Docs: add the wp-config `define()` dev-hatch recipe (`ACX_RECOGNITION_SOURCE=local` + `ACX_RECOGNITION_LOCAL_URL`) to `localwp-development-runbook.md`; update `portable-packaging-runbook.md` "Default: local" → service. Keep the single `mint_api_key`; no second minter.

Proof: `dev-mint-key`/`provision-customer` help asserts scope; smokes run against the retargeted source; minter unit tests unaffected (scoped or remote gate); docs reviewed.

## Files and Surfaces to Change

> Authoritative per-file/per-method list: `RECOG-1-inventory.md` (58 rows, §1; option/constant matrix §2; UI elements §3; named test methods §4; minting §5; state matrix §6). Clustered summary:

| Cluster | Files | Change | Slice |
| --- | --- | --- | --- |
| Resolver defaults | `src/api/class-recognition-endpoint-resolver.php` | source default `local→service`; drop option tier for source + local_url; keep constant/filter/default | S1 |
| Settings REST | `src/api/class-settings-controller.php` | drop `local_url` write + local source/probe + keyless probe; GET keeps read-only effective/source | S2 |
| Proxy (verify) | `class-abstract-recognition-proxy-controller.php`, `class-blobs-controller.php`, `class-sync-health-controller.php` | no change beyond resolver; verify no local special-casing | S1/S2 |
| Settings FE | `js/admin/pages/settings/SettingsForm.tsx`, `useSettingsPageState.ts`, `SettingsPage.tsx`, `healthStatus.ts`, `js/components/ui/target-card.tsx`, `js/admin/api/settingsApi.ts` | remove local card/toggle/URL/probe; single service form; state matrix | S2 |
| Local defaults + notices | `js/admin/api/config.ts` (localhost default), `js/admin/pages/WorkbenchPage.tsx` + `workbench/WorkbenchContext.tsx` (banner), `src/admin/class-admin.php` (notice) | remove/flip local defaults + banners | S2 |
| Minting policy | `apps/prototype-description-service/Makefile`, `README.md`, `docs/secrets-inventory.md`, `docs/portable-packaging-runbook.md`, `docs/localwp-development-runbook.md` | fixtures-only labels; canonical `--env prod`; hatch recipe; default-source docs | S3 |
| Smokes | `scripts/localwp/batch-run-smoke.php`, `describe-run-smoke.php` | retarget off hard-required local source | S3 |
| Env bootstrap (optional) | `alt-context.php` | optionally `acx_define_env_constant` for SOURCE/LOCAL_URL (hatch via `.env`) | S1 |
| Tests | inventory §4.1 (~35 named methods across PHP unit + TS unit + e2e) | update default/local/probe/contract assertions | S1-S3 |

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

### Checklist for Slice 2: Product-surface retirement
- [ ] `local_url` write + local source/probe removed from Settings; **keyless local `/health` probe path deleted** [SEC-04]; resolver constant/filter preserved.
- [ ] Local banners removed/reworded (Workbench `WorkbenchPage.tsx`, WP admin `class-admin.php`); `config.ts` no longer defaults `effectiveTargetUrl` to localhost.
- [ ] Settings single-target; state matrix (loading/empty/error/unpaired/offline) re-designed with focus + announcements [RLSE-04].
- [ ] settings-axe 0 serious/critical; named FE/PHP/e2e tests (inventory §4.1) updated and green.

### Checklist for Slice 3: Canonical issuance + smoke/e2e retarget
- [ ] OCI `--env prod` documented canonical; `dev-mint-key`/`dev-setup` relabeled fixtures-only (help + stderr banner).
- [ ] `provision-customer` no longer defaults `ENV=local` for real customers (explicit `--env prod`).
- [ ] LocalWP smokes + `wp-rest.ts` local-fallback retargeted so the default flip doesn't break them.
- [ ] wp-config `define()` dev-hatch recipe documented; packaging runbook default → service. Single `mint_api_key` preserved.

## Review Readiness
- [ ] Boundary deltas (settings REST, proxy target) have matching test/fixture evidence.
- [ ] State-matrix + a11y evidence captured for the new single-target Settings.
- [ ] Handoff decision records the contract changes and the deliberate escape-hatch design.

## Success Criteria
- [ ] Default recognition source is `service` (resolver + `config.ts`); a fresh plugin targets hosted with no "waiting for service" from a local default.
- [ ] Product surface (Settings + Workbench banner + admin notice) exposes one hosted-service configuration; no local URL/toggle/card/banner; local reachable only via wp-config constant/filter.
- [ ] No unauthenticated recognition path exists — the keyless local `/health` probe is removed and the proxy still always requires a key.
- [ ] OCI `--env prod` is documented canonical; `dev-mint-key` is unambiguously fixtures-only; `provision-customer` does not default real customers to the local DB.
- [ ] LocalWP smokes + e2e retargeted; scoped PHP + vitest green; settings-axe 0 serious/critical; `make check-remote` green.

## Heuristic IDs cited
[DIAG-08] [DATA-14] [LAY-10] [RLSE-04] [REF-12] [REF-21] [REF-24] [SEC-04] [WEB-16] [PROD-11] [PROD-12] [PROD-14] + repo Greenfield Policy, sr-004. All verified present in heuristics-canon (engineering, business-marketing, security, design-aesthetics) 2026-07-13.
