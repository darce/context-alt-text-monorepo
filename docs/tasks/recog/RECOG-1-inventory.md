# RECOG-1 touchpoint inventory (authoritative surface list)

**Task:** RECOG-1 inventory + plan grunt (READ-ONLY)  
**Worktree:** `/Users/daniel/Development/context-alt-text-monorepo-recog-1`  
**Branch/HEAD:** `feature/recog-1` @ `45a6c4de115b2625f9241742cb4239dd9a9c73ba`  
**Generated:** 2026-07-13  
**Decision context (accepted, not relitigated):** hosted/service is canonical product target; retire local from product surface (Settings UI + `acx_recognition_local_url` option + source toggle); keep local as code-level hatch via `ACX_RECOGNITION_LOCAL_URL` + `ACX_RECOGNITION_SOURCE` / filters; flip default source `local` → `service`; re-scope `dev-mint-key` to local fixtures only; prod mint via OCI `--env` DB; no no-auth hatch.

Legend for **required change** column: `REMOVE-from-UI-or-option` | `KEEP-behind-constant` | `FLIP-default` | `UPDATE-test` | `DOC` (may combine with `+`).

---

## 0. Surprises (decision context did not fully anticipate)

1. **Workbench local-mode banner** — not only Settings: `WorkbenchPage.tsx:100-110` shows local targeting notice + “Use Settings to switch…”. Product-retire surface.
2. **Admin WP notice** — `class-admin.php:284-304` `render_recognition_config_notice()` warns when source is local and links to Settings. Product-retire / rewrite.
3. **Localized SPA config defaults to localhost** — `js/admin/api/config.ts:54-58` `normalizeConfig` maps missing `effectiveTargetUrl` → `'http://localhost:8000'` and coerces non-local source → `'service'`. Soft local default outside resolver.
4. **No env bootstrap for SOURCE / LOCAL_URL** — `alt-context.php:226-227` only maps env → `ACX_RECOGNITION_URL` / `ACX_RECOGNITION_API_KEY`. `ACX_RECOGNITION_SOURCE` and `ACX_RECOGNITION_LOCAL_URL` are read if defined, but **not** `acx_define_env_constant`’d. Dev hatch requires `define()` (wp-config), not `.env` alone.
5. **Local probe is unauthenticated liveness** — `SettingsController::test_connection` local path hits `/health` with **no** API key (`class-settings-controller.php:238-251`). Service path hits `/health/detailed` + key + tenant pairing. Retiring UI local probe does not remove this code path unless product also drops `probe_target=local`.
6. **LocalWP smoke scripts hard-require local source** — `scripts/localwp/batch-run-smoke.php:86-92` and `describe-run-smoke.php:40-46` exit if source ≠ `local`. Break when default flips unless smokes retarget to constant hatch or service.
7. **e2e fallback mutates source option to local** — `tests/e2e/fixtures/wp-rest.ts:166-183` `ensureLocalRecognitionWhenProbeFails` POSTs `recognition_source: 'local'` when service probe fails. Depends on product option write for source.
8. **API key still required for local proxy traffic** — `AbstractRecognitionProxyController` always requires API key (`class-abstract-recognition-proxy-controller.php:91-98`). Confirms “no no-auth hatch” already true for proxy; only the Settings **local health probe** is keyless.
9. **codemap listed Blobs/SyncHealth as primary** — neither controller special-cases local URL/source; they inherit proxy resolver. Only tests pin `acx_recognition_source`.
10. **Shared minter already** — `mint_api_key` is shared by `manage_api_keys`, `provision_customer`, `/admin` router, and demo provision. Re-scope is policy/docs/Makefile guardrails, not a second key store.

---

## 1. Per-file inventory rows

| file | symbol/line anchor | what it references | required change | classification | breakage risk if changed |
| --- | --- | --- | --- | --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-recognition-endpoint-resolver.php` | `DEFAULT_LOCAL_URL` L19 | hard default local base `http://localhost:8000` | KEEP-behind-constant (default URL for hatch) | dev-hatch-keep | Low if kept; high if deleted without constant fallback |
| same | `resolve_service_url_source()` L24-40 | service URL: constant `ACX_RECOGNITION_URL` → filter `acx_recognition_base_url` → option `acx_recognition_url` → empty default | KEEP (product service path) | product-retire (unchanged chain except consumers) | High if precedence inverted (BR-07 history) |
| same | `resolve_local_url_source()` L46-62 | local URL: `ACX_RECOGNITION_LOCAL_URL` → filter `acx_recognition_local_url` → option `acx_recognition_local_url` → DEFAULT_LOCAL_URL | REMOVE option tier; KEEP constant+filter+default | product-retire + dev-hatch-keep | Medium: sites with only option-saved local URL lose it unless constant set |
| same | `resolve_recognition_source_source()` L68-84 | source: `ACX_RECOGNITION_SOURCE` → filter `acx_recognition_source` → option `acx_recognition_source` → **default `'local'`** | FLIP-default to `service`; REMOVE option tier (decision); KEEP constant+filter | product-retire + FLIP-default | **High**: flips all unset installs to service (empty service URL → not configured) |
| same | `get_effective_base_url()` L91-97 | routes local vs service effective URL | KEEP-behind-constant (hatch still selects local chain) | dev-hatch-keep | High if local branch removed entirely |
| same | `resolve_settings_snapshot()` L111-128 | exposes `local_url`, `local_url_source`, `recognition_source*`, `effective_target_*` to Settings GET | REMOVE/trim fields for product UI; may keep for code hatch diagnostics | product-retire | Medium: TS contract + tests couple to field names |
| `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` | `get_settings()` L97-121 | returns `local_url`, `local_url_source`, `recognition_source`, `recognition_source_source`, `effective_target_*` | REMOVE-from-UI-or-option (response fields optional trim) | product-retire | Medium: frontend + e2e snapshot types |
| same | `save_settings()` L141-151 | writes `acx_recognition_source` option | REMOVE-from-UI-or-option | product-retire | Medium: e2e/helpers that POST source break |
| same | `save_settings()` L160-170 | writes `acx_recognition_local_url` option; validates URL | REMOVE-from-UI-or-option | product-retire | Medium |
| same | `save_settings()` L128-138, L154-157 | service `url` + `api_key` options | KEEP (product) | product-retire (unchanged) | Low |
| same | `test_connection()` L216-251 | `probe_target` local\|service; local → unauth `/health` (`local_liveness`) | REMOVE UI local probe; KEEP or drop code path for hatch | product-retire / dev-hatch-keep | Medium: tests assert local probe + dual cards |
| same | `test_connection()` L254-296 | service probe `/health/detailed` + pairing | KEEP | product-retire (keep) | High if pairing broken |
| same | `resolve_key_source()` L538-562 | constant → filter → option for API key | KEEP | unchanged | High if order regresses (RR-01) |
| same | `is_valid_recognition_source()` L587-589 | allows `service`\|`local` | KEEP-behind-constant if source option/body retained for hatch; else narrow | product-retire | Low |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | `get_recognition_base_url()` L198-200 | uses resolver effective URL | KEEP-behind-constant | dev-hatch-keep | High for all proxy traffic |
| same | `get_recognition_source()` L202-204 | exposes source (few callers) | KEEP | dev-hatch-keep | Low |
| same | `get_recognition_api_key()` L218-237 | constant → filter → option; **no missing-key bypass** | KEEP (no no-auth) | minting/auth unchanged | Critical if relaxed |
| same | missing-key error L91-98 | directs operator to Settings or `ACX_RECOGNITION_API_KEY` | DOC (maybe still valid) | docs | Low |
| `apps/prototype-wp-alt-context/src/admin/class-admin.php` | `render_recognition_config_notice()` L284-304 | WP admin warning when source=`local`; links Settings | REMOVE-from-UI-or-option or reword for constant-only hatch | product-retire | Low-Medium UX |
| same | `localize_spa_config()` L319-320 | injects `recognitionSource`, `effectiveTargetUrl` into `AltContextAdmin` | KEEP (runtime routing for Workbench banner) | product-retire (banner consumers) | Medium |
| same | `get_recognition_source()` / `get_effective_target_url()` L380-386 | wrappers over resolver | KEEP | dev-hatch-keep | Low |
| `apps/prototype-wp-alt-context/src/api/class-blobs-controller.php` | (extends proxy; no local symbols) | inherits effective URL only | none direct | unaffected (verify only) | Low — **assumption verified: no local_url/source refs** |
| `apps/prototype-wp-alt-context/src/api/class-sync-health-controller.php` | (no local symbols) | inherits proxy | none direct | unaffected | Low — **verified no matches** |
| `apps/prototype-wp-alt-context/alt-context.php` | `acx_define_env_constant` L226-227 | env bootstrap only URL + API_KEY | optional DOC/KEEP; decide whether to add SOURCE/LOCAL_URL env maps for hatch | dev-hatch-keep | Low |
| `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts` | `SettingsResponse` L3-21 | `local_url`, `local_url_source`, `recognition_source*` types | REMOVE-from-UI-or-option (+ contract) | product-retire | Medium |
| same | `RecognitionSource` L45-48 | `SERVICE` / `LOCAL` enum | REMOVE `LOCAL` from product UI types or keep for hatch diagnostics | product-retire | Medium |
| same | `SaveSettingsPayload` L52-59 | optional `local_url`, `recognition_source` | REMOVE | product-retire | Medium |
| same | `TestConnectionProbeMode` L88; payload L128-131 | `local_liveness` / `probe_target` | REMOVE local probe mode from UI path | product-retire | Medium |
| `apps/prototype-wp-alt-context/js/admin/api/config.ts` | `normalizeConfig` L54-58 | source coerce; **default effectiveTargetUrl localhost:8000** | FLIP-default / product-retire (default to empty or service URL) | product-retire | Medium Workbench display |
| `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx` | `handleSave` L93-102 | diffs + posts `recognition_source`, `local_url` | REMOVE-from-UI-or-option | product-retire | Medium |
| same | `handleTest` L126-129 | `probe_target` dual-card | REMOVE local target probe | product-retire | Medium |
| same | read-only flags L158-165 | `localUrlReadOnly`, unsaved includes `localUrl` | REMOVE | product-retire | Low |
| same | loading/error L139-155 | page-level loading/error (not per-target) | KEEP | product-retire (state matrix) | Low |
| same | default compare L94 | fallback `RecognitionSource.LOCAL` when data missing | FLIP-default to SERVICE | product-retire | Low |
| `apps/prototype-wp-alt-context/js/admin/pages/settings/SettingsForm.tsx` | TargetCard local L76-103 | **Local development** card + local URL input + local health check | REMOVE-from-UI-or-option | product-retire | **High** UX |
| same | TargetCard service L105-148 | hosted card + URL + API key + health | KEEP (simplify to non-radio if source toggle gone) | product-retire | Medium layout |
| same | `TargetCardGroup` L71-75 | radio group for source selection | REMOVE (no dual target) | product-retire | Medium |
| same | effective target copy L151-158 | local vs hosted wording | UPDATE (service-only product) | product-retire | Low |
| same | source provenance L161-164 | `recognition_source_source` description | REMOVE or constant-only notice | product-retire | Low |
| same | Save disabled L226 | includes `localUrlReadOnly` | UPDATE | product-retire | Low |
| `apps/prototype-wp-alt-context/js/admin/pages/settings/useSettingsPageState.ts` | state L11-19; INITIAL L34-38 | `localUrl`; initial `recognitionSource: SERVICE` (UI already service-default) | REMOVE `localUrl` / source actions | product-retire | Low |
| same | `syncFromSettings` L47-55 | hydrates `local_url`, `recognition_source` | REMOVE | product-retire | Low |
| `apps/prototype-wp-alt-context/js/components/ui/target-card.tsx` | `TargetCardGroup`/`TargetCard` L12-137 | generic radio target cards | REMOVE usage for local; may keep component for service-only or delete if unused | product-retire | Medium if other consumers appear — **verified: SettingsForm is primary consumer** |
| `apps/prototype-wp-alt-context/js/admin/pages/settings/healthStatus.ts` | L10-19 | maps probe_mode local_liveness vs service_auth | REMOVE local branch | product-retire | Low |
| `apps/prototype-wp-alt-context/js/admin/pages/settings/SettingsRoutingBanner.tsx` | L1 | stub: routing moved into form | none | unaffected | none |
| `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` | L100-110 | local-mode info notice + “Use Settings to switch” | REMOVE-from-UI-or-option or reword for constant hatch only | product-retire | Medium |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx` | L129,145,392,450 | threads `recognitionSource` from config | KEEP (display) or narrow | product-retire | Low |
| `apps/prototype-wp-alt-context/docs/portable-packaging-runbook.md` | L44-68 | documents source default **local**, full precedence incl options | DOC + FLIP-default + drop-option wording | docs | Low |
| `apps/prototype-wp-alt-context/docs/localwp-development-runbook.md` | L142-143,233-234 | prod key via constants; no SOURCE/LOCAL_URL examples | DOC (add hatch recipe: SOURCE=local + LOCAL_URL) | docs | Low |
| `apps/prototype-wp-alt-context/scripts/localwp/batch-run-smoke.php` | L86-92 | **requires** recognition source `local` | UPDATE (constant hatch or service smoke) | test/docs | High for local smoke |
| `apps/prototype-wp-alt-context/scripts/localwp/describe-run-smoke.php` | L40-46 | same hard require local | UPDATE | test/docs | High |
| `apps/prototype-description-service/Makefile` | `dev-mint-key` L112-123 | `--env local` tenant create + key for fixed `DEV_TENANT_ID` | DOC/policy re-scope fixtures-only; optionally rename/guard | minting | Medium ops confusion if still used for “real” tenants |
| same | `dev-setup` L127-146 | seeds `.env` then calls `dev-mint-key` | DOC re-scope | minting | Low |
| same | `provision-customer` L163-175 | concierge real tenant; default `ENV=local` | KEEP; DOC that real tenants use `--env prod` OCI DB | minting | **High if default ENV stays local for prod operators** |
| same | `admin-dev` L157-158 | starts local `/admin` console | KEEP local-dev tooling | minting | Low |
| `apps/prototype-description-service/scripts/manage_api_keys.py` | module L1-20; `_cmd_create` L103-129 | operator CLI; `mint_api_key`; env/DSN guard | KEEP; DOC fixtures vs prod; optional refuse non-fixture tenants under local | minting | Medium if over-restricted |
| `apps/prototype-description-service/scripts/provision_customer.py` | L1-14, `_format_wp_snippet` L86-99 | real customer mint; WP snippet forces `ACX_RECOGNITION_SOURCE='service'` | KEEP; DOC prod env | minting | Medium |
| `apps/prototype-description-service/recognition/application/services/customer_provision_service.py` | `provision_customer` L79+ | shared real-tenant provision + `mint_api_key` | KEEP | minting | High |
| `apps/prototype-description-service/recognition/application/services/api_key_admin_service.py` | `mint_api_key` (imported) | **shared minter** for CLI/admin/demo/provision | KEEP single minter | minting | Critical if split |
| `apps/prototype-description-service/scripts/admin_dev.sh` | L1-12, ensure_admin_env | local admin env + smoke mint via `/admin` | KEEP (local operator UI) | minting | Low |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/admin.py` | mint path ~L245 | `/admin` uses `mint_api_key` | KEEP; prod gated | minting | High if no-auth introduced |
| `apps/prototype-description-service/README.md` | ~L97-101,225 | documents `dev-setup` / `dev-mint-key` / `admin-dev` | DOC fixtures-only language | docs | Low |
| `apps/prototype-description-service/docs/secrets-inventory.md` | minting rows | key mint via admin/CLI | DOC | docs | Low |
| `apps/prototype-wp-alt-context/tests/Unit/RecognitionEndpointResolverTest.php` | see §3 | default local + option local_url + precedence | UPDATE-test + FLIP-default | test | High if not updated |
| `apps/prototype-wp-alt-context/tests/Unit/SettingsControllerTest.php` | see §3 | default local, local probe, save source | UPDATE-test | test | High |
| `apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php` | see §3 | local source routing, localhost default | UPDATE-test | test | High |
| `apps/prototype-wp-alt-context/tests/Unit/AdminTest.php` | notice + localize source | local notice tests | UPDATE-test | test | Medium |
| `apps/prototype-wp-alt-context/tests/Unit/SyncHealthControllerTest.php` | L80,119,135 | pins `source=service` only | unaffected (unless default-sensitive setup) | test | Low |
| `apps/prototype-wp-alt-context/tests/Unit/BlobsControllerTest.php` | L20 | pins `source=service` | unaffected | test | Low |
| `apps/prototype-wp-alt-context/tests/e2e/fixtures/wp-rest.ts` | L8-12,128-200 | source option mutations + local fallback | UPDATE-test | test | High for evidence e2e |
| `apps/prototype-wp-alt-context/tests/e2e/evidence/workbench-evidence.spec.ts` | L228-229,240 | assumes default local; uses local fallback helper | UPDATE-test | test | High |
| `apps/prototype-wp-alt-context/tests/e2e/evidence/scan-runtime-evidence.spec.ts` | L24-25,104-105,130 | records/validates source modes | UPDATE-test (still allow local via hatch?) | test | Medium |
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/SettingsPage.test.tsx` | see §3 | dual cards, local save, local_url editable | UPDATE-test | test | High |
| `apps/prototype-wp-alt-context/js/admin/pages/settings/__tests__/healthStatus.test.ts` | local probe modes | UPDATE-test | test | Low |
| `apps/prototype-wp-alt-context/js/admin/api/__tests__/settingsResponseContract.test.ts` | required `local_url*` fields | UPDATE-test | test | Medium |
| `apps/prototype-wp-alt-context/js/admin/__tests__/banned-vocabulary.test.tsx` | fixture includes local_url | UPDATE if contract drops fields | test | Low |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx` | L69,404 | fixtures service/local | UPDATE-test for banner cases | test | Medium |

**Row count (table above): 58**

---

## 2. Option / constant / filter matrix

| symbol | kind | read sites (primary) | write sites | disposition |
| --- | --- | --- | --- | --- |
| `acx_recognition_url` | option | resolver L35; settings save/get; many tests | `SettingsController::save_settings` L137 | **unchanged** (product service URL) |
| `acx_recognition_local_url` | option | resolver L57; settings GET/save; probes | `save_settings` L169 | **drop-option-keep-constant** (remove option tier + UI write) |
| `acx_recognition_source` | option | resolver L79; admin notice; e2e save; smokes | `save_settings` L150; e2e helpers | **drop-option-keep-constant** (remove UI write; hatch via constant/filter only) |
| `acx_recognition_api_key` | option | settings key resolve L557; proxy L229 | `save_settings` L156 | **unchanged** |
| `acx_recognition_tenant_id` | option | `TenantIdentity` | TenantIdentity adopt/derive | **unchanged** (out of local-retire scope) |
| `acx_recognition_tenant_paired` | option | TenantIdentity | adopt_paired_tenant | **unchanged** |
| `acx_recognition_circuit_*` | transient key prefix | circuit keys | proxy circuit | **unchanged** (not settings) |
| `ACX_RECOGNITION_URL` | constant | resolver L25; env define alt-context L226; provision WP snippet | env bootstrap / wp-config | **unchanged** |
| `ACX_RECOGNITION_LOCAL_URL` | constant | resolver L47 only | manual `define()` (no env bootstrap today) | **KEEP hatch**; optional env bootstrap addition |
| `ACX_RECOGNITION_SOURCE` | constant | resolver L69; smokes; provision snippet sets `'service'` | manual `define()` | **KEEP hatch**; product default flips without it |
| `ACX_RECOGNITION_API_KEY` | constant | settings L547; proxy L233; env L227 | env / wp-config | **unchanged** |
| `ACX_RECOGNITION_TENANT_ID` | constant | TenantIdentity | wp-config / provision snippet | **unchanged** |
| `acx_recognition_base_url` | filter | resolver L30 | external plugins/mu | **unchanged** |
| `acx_recognition_local_url` | filter | resolver L52 | external | **KEEP hatch** |
| `acx_recognition_source` | filter | resolver L74 | external | **KEEP hatch** |
| `acx_recognition_api_key` | filter | settings L552; proxy L224 | external | **unchanged** |
| `acx_recognition_tenant_id` | filter | TenantIdentity | external | **unchanged** |
| `acx_recognition_transport` | filter | analyze path (multipart vs url) | tests | **unchanged** (orthogonal) |

**Default flip:** `resolve_recognition_source_source()` L84 currently `array( 'value' => 'local', 'source' => 'default' )` → must become `'service'`. Documented at `portable-packaging-runbook.md:51` (“Default: local”).

---

## 3. Settings UI element inventory

| surface | file:lines | local vs service | keep/remove |
| --- | --- | --- | --- |
| Section title “Recognition target” | SettingsForm L69 | both | keep (rename optional) |
| `TargetCardGroup` radio group | SettingsForm L71-75 + target-card L19-34 | source toggle | **remove** |
| Local card `acx-target-local` | SettingsForm L76-103 | local | **remove** |
| Local URL input `#acx-settings-local-url` | SettingsForm L89-98 | local_url option | **remove** |
| Local URL source description | SettingsForm L99-102 | local_url_source | **remove** |
| Local “Check health” | SettingsForm L85-87 | local probe | **remove** |
| Service card `acx-target-service` | SettingsForm L105-148 | service | **keep** (may drop radio chrome) |
| Service empty CTA “Configure service URL” | SettingsForm L114-115 | service empty | **keep** |
| Service URL input | SettingsForm L120-129 | service | **keep** |
| API key input | SettingsForm L134-147 | service auth | **keep** |
| Service “Check health” | SettingsForm L116-118 | service probe | **keep** |
| Effective target line | SettingsForm L151-158 | both | **keep/simplify** (service-centric; hatch may still show local if constant) |
| Source provenance line | SettingsForm L161-164 | source | **remove or hatch-only** |
| Unsaved routing warning | SettingsForm L166-170 | both | keep (service URL edits) |
| Description budget block | SettingsForm L172-220 | n/a | **keep** |
| Save Settings button | SettingsForm L222-229 | both | keep (drop localUrlReadOnly from disable logic) |
| Page loading | SettingsPage L139-145 | n/a | keep |
| Page error | SettingsPage L148-154 | n/a | keep |
| Tenant pairing banners | TestConnectionBannerView via SettingsPage L211-216 | service probe | keep |
| Workbench local notice | WorkbenchPage L100-110 | local | **remove or constant-hatch only** |
| WP admin local notice | class-admin.php L284-304 | local | **remove or reword** |

---

## 4. Test inventory

### 4.1 Must-update (asserts default-local, option local_url, UI local target, local probe, or option source toggle)

**PHP unit — RecognitionEndpointResolverTest**

| method | why |
| --- | --- |
| `testDefaultsToLocalTargetWhenNothingConfigured` | asserts default source `local` + default local URL |
| `testLocalModeIgnoresStoredServiceUrlForEffectiveTarget` | local option mode |
| `testCustomLocalUrlOptionIsUsedInLocalMode` | **local_url option** |
| `testSavedServiceUrlWithoutExplicitSourceResolvesLocal` | default local despite service URL |
| `testFilterSourcedServiceUrlWithoutExplicitSourceResolvesLocal` | default local |
| `testConstantServiceUrlWithoutExplicitSourceResolvesLocal` | default local |
| `testExplicitOptionSourcePrecedesSavedServiceUrl` | option source tier |
| `testFilterSourcedRecognitionSourcePrecedesOption` | keep as hatch test (may reframe) |
| `testConstantRecognitionSourcePrecedesOption` | keep as hatch test |
| `testServiceModeUsesStoredServiceUrl` | still valid; may become default-path |

**PHP unit — SettingsControllerTest**

| method | why |
| --- | --- |
| `testGetSettingsReturnsDefaultSourceWhenNothingConfigured` | default `local` + local_url |
| `testGetSettingsReturnsOptionSourceWhenOptionSet` | asserts default source local when only URL set |
| `testGetSettingsReturnsConstantSourceWhenConstantDefined` | asserts residual default local |
| `testSaveSettingsWritesUrlAndKeyToOptions` | saves `recognition_source=local` |
| `testProbeDispatchHitsLocalHealthWhenLocalModeIsActive` | local probe + local_url option |
| `testProbeDispatchHonorsExplicitProbeTarget` | `probe_target=local` |
| (possibly) `testSaveSettingsRr07PreservesCodeManagedSelectorContract` | if source option removed, rewrite |

**PHP unit — ProxyRequestTest**

| method | why |
| --- | --- |
| `testProxyFallsBackToLocalhostWhenUrlNotConfigured` | source=local empty service URL |
| `testProxyUsesLocalhostWhenRecognitionSourceIsLocal` | local overrides service URL |
| `testFilteredBaseUrlBeatsSavedLocalSourceOption` | option local vs filter URL |
| `testProxyRequestUsesLocalTargetWhenConstantUrlWithoutExplicitSource` | **default local** with constant service URL |
| (setups using `acx_recognition_source`) | re-pin after default flip |

**PHP unit — AdminTest**

| method | why |
| --- | --- |
| `testLocalizeSpaConfigIncludesRecognitionSource` | sets source local |
| `testRenderRecognitionConfigNoticeAppearsWhenLocalModeIsActive` | product notice |
| `testRenderRecognitionConfigNoticeDoesNotAppearWhenServiceModeIsConfigured` | notice gating |
| `testRenderRecognitionConfigNoticeIsScopedToPluginScreens` | notice |

**TS unit — SettingsPage.test.tsx**

| test name | why |
| --- | --- |
| `saves the recognition source when the operator switches to local mode` | UI source toggle |
| `enables Check health on both configured target cards` | dual cards |
| `disables Check health when routing edits are unsaved` | includes local radio switch |
| `keeps Save enabled when only local_url is editable` | local_url option |
| `keeps tenant-pairing confirmation on the tested service target when effective mode is local` | dual-mode probe |
| `uses local network_error copy when the mutation rejects in local mode` | local probe error path |
| `disables Save when every routing field is read-only` | includes localUrlReadOnly |
| other dual-card / local fixtures | scattered fixtures |

**TS — healthStatus.test.ts** — local probe_mode cases  
**TS — settingsResponseContract.test.ts** — required `local_url` / `local_url_source`  
**e2e — wp-rest.ts helpers** — `ensureLocalRecognitionWhenProbeFails`, source option writes  
**e2e — workbench-evidence.spec.ts** — default local snapshot L228-229; local fallback L240  
**e2e — scan-runtime-evidence.spec.ts** — may still accept `local` if hatch exists  
**WorkbenchPage.test.tsx** — local recognitionSource banner fixture L404  
**scripts** — batch-run-smoke / describe-run-smoke local hard-require

### 4.2 Unaffected (or only incidental setup)

| test surface | note |
| --- | --- |
| `SyncHealthControllerTest` | pins `source=service`; not about local product UI |
| `BlobsControllerTest` | pins service; no local assertions |
| Most proxy retry/circuit tests | after setup fix |
| Tenant identity / pairing service-path tests | service auth |
| Description budget save/get tests | orthogonal |
| Analyze transport filter tests | orthogonal |
| provision_customer / manage_api_keys unit tests | minting re-scope is docs/Makefile unless new guards added |

---

## 5. Minting inventory

| entrypoint | what it does | env/DB | shares minter? | re-scope notes |
| --- | --- | --- | --- | --- |
| `make dev-mint-key` | bootstrap tenant `DEV_TENANT_ID` default `00000000-0000-4000-8000-000000000001` + site URL; mint key via CLI | **forced `--env local`** + local DSN guard | yes → `manage_api_keys` → `mint_api_key` | **fixtures-only:** document fixed UUID as local-test tenant; refuse use for customer emails; maybe rename target / add stderr banner “not for production tenants” |
| `make dev-setup` | copy `.env.example` if missing; then `dev-mint-key` | local | via dev-mint-key | same fixtures-only language in README |
| `make provision-customer` | real customer email-idempotent tenant+key; prints WP snippet with `ACX_RECOGNITION_SOURCE='service'` | `--env` default **`local`** in Makefile L172 | yes → `provision_customer` service → `mint_api_key` | **canonical real-tenant path for ops when `--env prod`**; inventory gap: Makefile default ENV=local is footgun for “real tenants” — plan should require explicit prod |
| `make admin-dev` / `admin_dev.sh` | enable `/admin`, start service, open console, smoke create/mint/list/revoke | local `.env` admin token | yes → admin router `mint_api_key` | keep as local operator console; not product plugin UI |
| `scripts/manage_api_keys.py` | low-level tenant create/list + key create/list/revoke | prod\|dev\|local with DSN host validation | `mint_api_key` | keep for both fixtures (local) and break-glass (prod); policy: prod usage = real tenants only via operator discipline |
| `scripts/provision_customer.py` | concierge UX over provision service | same env guard | `mint_api_key` | OCI/prod issuer when `--env prod` |
| `scripts/provision_demo.py` / demo service | demo tenants with expiry/quota | env-scoped | also uses mint_api_key path (demo_provisioning_service) | out of RECOG-1 product UI retire; note shared minter |
| `/admin` HTTP API | browser mint | admin token + optional prod tailnet gate | `mint_api_key` | keep; no no-auth |

**Concrete “re-scope dev-mint-key to fixtures-only” touch list:**

1. `Makefile` comments + help text L15-16, L112-123, L143  
2. `README.md` local onboarding bullets  
3. `docs/secrets-inventory.md` mint rows  
4. Optional code guard: refuse `tenant create` under `--env local` unless tenant id matches `DEV_TENANT_ID` / fixtures allowlist (**not present today — assumption**)  
5. Ensure `provision-customer` docs push `--env prod` for real customers; consider changing Makefile default ENV away from local  
6. Do **not** invent a second minter; keep `mint_api_key` single source

---

## 6. State-matrix note (Settings when local target removed)

| state | current behavior | after local card removal |
| --- | --- | --- |
| **Loading** | SettingsPage L139-145 “Loading settings…”; no form | **unchanged** |
| **Error (GET fail)** | SettingsPage L148-154 | **unchanged** |
| **Empty service URL** | Service card `configured=false` empty CTA L101-117 / L112-115 | **remains** (primary empty state); no parallel local card always-configured |
| **Service configured** | service card body with URL+key | **remains**; may become sole form body without radio group |
| **Local selected / effective local** | local card active badge; effective line “Local development service”; Workbench + WP notices | **gone from product UI**; only if constant/filter hatch → optional non-editable banner (decision: product retires toggle) |
| **Probing service** | `testPending` disables health buttons; service probe_mode service_auth | **remains** |
| **Probing local** | local_liveness chip on local card | **removed** with card; `healthStatusForTarget(LOCAL, …)` dead |
| **Unsaved routing** | compares source + localUrl + url L162-165; disables health | shrinks to **url (and maybe key)** diffs |
| **All read-only** | Save disabled when source+url+localUrl+key code-managed L226 | drop localUrl from conjunction |
| **Tenant pairing conflict** | service probe only | **unchanged** |
| **Default source** | resolver default local; UI state initial SERVICE (useSettingsPageState L37) | align resolver default **service**; UI already service-first |
| **config.ts missing effectiveTargetUrl** | defaults localhost:8000 | **should not default to local** after product flip (empty or service URL) |

---

## 7. Expanded surfaces beyond initial codemap (include in task plan)

| path | reason |
| --- | --- |
| `js/admin/api/settingsApi.ts` | types + save/test payloads |
| `js/admin/api/config.ts` | localhost effectiveTargetUrl default |
| `js/admin/pages/WorkbenchPage.tsx` | local banner |
| `js/admin/pages/workbench/WorkbenchContext.tsx` | recognitionSource plumbing |
| `js/admin/pages/settings/healthStatus.ts` | local probe mapping |
| `js/admin/pages/__tests__/SettingsPage.test.tsx` | largest FE test impact |
| `js/admin/api/__tests__/settingsResponseContract.test.ts` | field contract |
| `alt-context.php` | missing env bootstrap for SOURCE/LOCAL_URL |
| `docs/portable-packaging-runbook.md` | default + option docs |
| `docs/localwp-development-runbook.md` | hatch recipe gap |
| `scripts/localwp/*-smoke.php` | hard-require local |
| `tests/e2e/evidence/*` | source assumptions |
| `apps/prototype-description-service/README.md` + secrets-inventory | mint docs |

---

## 8. Unverified / open assumptions

1. Whether product plan keeps **GET** fields `local_url*` / `recognition_source*` for hatch diagnostics vs fully removing from API contract — **not decided in code**; inventory lists both.  
2. Whether `probe_target=local` remains as secret/API hatch after UI removal — decision context emphasizes constant/filter for routing, not probe.  
3. Whether deleting option rows on upgrade is in scope (greenfield policy says clean rewrite; no migration required).  
4. Whether `manage_api_keys --env local` will get hard fixtures allowlist or docs-only re-scope.  
5. Sibling consumers outside `apps/` (infra demo compose) not fully enumerated — **not scanned** for RECOG-1 grunt scope under `apps/`.

---

## 9. Suggested change clusters for task plan (non-implementing)

1. **Resolver defaults + drop option tiers** for local_url + source (keep constant/filter).  
2. **Settings REST + FE** remove local card/toggle/local_url writes; service-only product form.  
3. **Notices** admin + workbench + config.ts default.  
4. **Tests + e2e + smokes** mass update.  
5. **Docs** packaging runbook default service; local hatch via defines.  
6. **Minting policy** fixtures-only `dev-mint-key`; prod `provision-customer --env prod`.

---

## 10. Metrics

| metric | value |
| --- | --- |
| Inventory table rows (§1) | **58** |
| Option/constant/filter matrix rows | **17** |
| Settings UI elements inventoried | **18** |
| Must-update test methods (named) | **~35+** across PHP/TS/e2e |
| Surprises | **10** |

**Output path:** `/private/tmp/claude-501/-Users-daniel-Development-context-alt-text-monorepo/f02ac00b-778c-4444-89ae-4e8c6ebd046b/scratchpad/recog-1-inventory-OUT.md`
