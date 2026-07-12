# Security Review — `apps/prototype-wp-alt-context` (WordPress plugin)

| Field | Value |
| --- | --- |
| **Date** | 2026-07-11 |
| **Task** | `SECREV-1` (branch `feature/secrev-1`) |
| **Scope** | `apps/prototype-wp-alt-context/` — focus `src/`, `alt-context.php`, `public/`, `scripts/`, admin SPA `js/` (read-only review) |
| **Commit reviewed** | `da9a08f11221e5040aed81ebd9eb59bfd938f68d` |
| **Rubric** | heuristics-canon security lexicon (§§1–5 inlined for SECREV-1); engineering heuristics cited where reinforcing (`docs/strategy/engineering-heuristics.md`) |
| **Method** | Attack-surface enumeration → per-controller authz/SQL/SSRF/LLM/secrets/deserial/DOM/upload review → evidence-backed findings |
| **Status** | Assessment / decision input. Not a task plan. Findings live here for later decomposition; do not paste into task plans. |

---

## 1. Executive summary

**Posture verdict:** **Conditional pass for prototype / single-tenant admin use.** Privileged REST surfaces are generally gated with real `permission_callback`s (`manage_options` for nearly all mutations). No `__return_true` privileged routes, no `wp_ajax_nopriv_*`, no production `unserialize` sinks, no frontend `innerHTML`/`dangerouslySetInnerHTML` sinks found, and repository SQL is predominantly prepared via `PreparesSqlQueries` / `$wpdb->prepare`.

**Residual risk is concentrated in:** (1) admin-configurable outbound base URLs that become SSRF + API-key exfiltration vectors; (2) signed blob capability URLs that intentionally bypass session/nonce for `<img>`; (3) workbench REST capability weaker than admin UI; (4) unlimited default LLM/description budget and missing plugin-layer rate limits; (5) LLM-sourced alt text written to post meta without sanitize-on-write.

| Tier | Count | IDs |
| --- | ---: | --- |
| **Blocker** | 2 | SECREV-F01, SECREV-F02 |
| **Should** | 7 | SECREV-F03 … SECREV-F09 |
| **Judgment** | 4 | SECREV-F10 … SECREV-F13 |

**Top 5 risks**

1. **SSRF / secret reflection via recognition URL options** (F01) — admin-saved `http(s)` base URL is fetched server-side with `X-API-Key`.
2. **Unauthenticated signed blob/face-thumb proxy** (F02) — HMAC token in query string; anyone with the URL can fetch until expiry.
3. **Workbench REST authz weaker than admin menu** (F03) — `upload_files` vs `manage_options`.
4. **Plaintext API key in `wp_options`** (F04) + key sent to any configured base URL.
5. **Denial-of-wallet / expensive describe·analyze paths** (F07) — default description budget unlimited; no per-caller throttle on plugin side.

---

## 2. Attack surface map

### 2.1 REST routes (`namespace acx/v1`)

Auth legend:

- **Admin** = `current_user_can( 'manage_options' )` via `can_manage_recognition` / `can_manage_roster` / `can_manage_settings`
- **Uploader** = `current_user_can( 'upload_files' )` via `can_view_media_queue`
- **HMAC** = `verify_blob_token` (no WP session required if token valid)
- WP cookie REST clients still need `X-WP-Nonce` except blob routes (explicit nonce bypass scoped to blob path prefixes)

| Route | Methods | Permission | Verdict |
| --- | --- | --- | --- |
| `/workbench/media` | GET | Uploader | Weaker than admin UI — see F03 |
| `/workbench/media/detail` | GET | Uploader | Same — see F03 |
| `/dashboard/stats` | GET | Admin | OK |
| `/roster/persons` | POST | Admin | OK |
| `/roster/persons/(id)` | PUT, DELETE | Admin | OK |
| `/roster/entries` | GET | Admin | OK |
| `/roster/clusters/(cluster_id)/commit` | POST | Admin | OK |
| `/settings` | GET, POST | Admin | OK authz; URL validation weak — F01 |
| `/settings/test` | POST | Admin | OK authz; probes configured URL — F01 |
| `/recognition/analyze` | POST | Admin | OK; expensive — F07 |
| `/recognition/batch-runs` | GET | Admin | OK |
| `/recognition/batch-runs/(run_id)` | GET | Admin | OK |
| `/recognition/batch-runs/(run_id)/client-failures` | POST | Admin | OK |
| `/recognition/jobs/(job_id)` | GET | Admin | OK |
| `/recognition/jobs/(job_id)/stream` | GET | Admin | OK |
| `/recognition/jobs/(job_id)/cancel` | POST | Admin | OK |
| `/recognition/jobs/(job_id)/acknowledge-projection` | POST | Admin | OK |
| `/recognition/blobs/(job_id)/(media_id)` | GET | HMAC | By design; risk F02 |
| `/recognition/face-thumbs/(job_id)/(media_id)` | GET | HMAC | By design; risk F02 |
| `/recognition/cluster` | POST | Admin | OK |
| `/recognition/clusters/reassign` | POST | Admin | OK |
| `/recognition/clusters/(cluster_id)` | GET, PATCH | Admin | OK |
| `/recognition/clusters/(cluster_id)/dismiss` | POST, DELETE | Admin | OK |
| `/recognition/clusters/(source_id)/merge` | POST | Admin | OK |
| `/recognition/clusters/(cluster_id)/split` | POST | Admin | OK |
| `/recognition/clusters/create-for-identity` | POST | Admin | OK |
| `/recognition/clusters/revert-merge` | POST | Admin | OK |
| `/recognition/clusters/(cluster_id)/assign` | POST | Admin | OK |
| `/recognition/clusters/(cluster_id)/representatives/(id)/pin` | PATCH | Admin | OK |
| `/recognition/clusters` | GET | Admin | OK |
| `/recognition/clusters/top-unlabeled` | GET | Admin | OK |
| `/recognition/clusters/labels` | GET | Admin | OK |
| `/recognition/clusters/(cluster_id)/members` | GET | Admin | OK |
| `/recognition/conflicts` | GET | Admin | OK; tenant-scoped in repo |
| `/recognition/conflicts/(id)` | GET | Admin | OK; `find_conflict_by_id(..., tenant_id)` |
| `/recognition/conflicts/(id)/resolve` | POST | Admin | OK |
| `/recognition/outbox` | GET | Admin | OK |
| `/recognition/outbox/failed` | GET | Admin | OK |
| `/recognition/outbox/(id)/retry` | POST | Admin | OK |
| `/recognition/outbox/(id)/discard` | POST | Admin | OK |
| `/recognition/describe` | POST | Admin | OK; LLM path F06/F07/F10 |
| `/recognition/describe/candidates` | GET | Admin | OK |
| `/recognition/describe/history` | GET | Admin | OK |
| `/recognition/describe/history/(media_id)/correction` | POST | Admin | OK |
| `/recognition/describe/runs` | POST | Admin | OK |
| `/recognition/describe/runs/(run_id)` | GET | Admin | OK |
| `/recognition/describe/runs/(run_id)/cancel` | POST | Admin | OK |
| `/recognition/describe/runs/(run_id)/items` | GET | Admin | OK |
| `/recognition/describe/runs/(run_id)/apply` | POST | Admin | OK; persists drafts F06 |
| `/recognition/media-identities` | GET | Admin | OK |
| `/recognition/identities/(identity_id)/suggestions` | GET | Admin | OK |
| `/recognition/suggestions` | GET | Admin | OK |
| `/recognition/suggestions/merge` | GET | Admin | OK |
| `/recognition/suggestions/(id)/accept` | POST | Admin | OK |
| `/recognition/suggestions/merge/(id)/accept` | POST | Admin | OK |
| `/recognition/suggestions/(id)/reject` | POST | Admin | OK |
| `/recognition/suggestions/merge/(id)/reject` | POST | Admin | OK |
| `/recognition/suggestions/name` | GET | Admin | OK |
| `/recognition/suggestions/name/(id)/accept` | POST | Admin | OK |
| `/recognition/suggestions/name/(id)/reject` | POST | Admin | OK |
| `/recognition/suggestions/bulk-accept` | POST | Admin | OK |
| `/recognition/sync/health` | GET | Admin | OK |
| `/recognition/sync-status` | GET | Admin | OK |
| `/recognition/sync/trigger` | POST | Admin | OK |
| `/recognition/sync/reset-mirror` | POST | Admin | Destructive — F05 |
| `/recognition/xmp/embed` | POST | Admin | OK; writes original files in place |
| `/retention/status` | GET | Admin | OK |
| `/retention/policy` | PATCH | Admin | OK |
| `/retention/policy/preset` | POST | Admin | OK |
| `/retention/export` | POST | Admin | OK |
| `/retention/export/(job_id)/status` | GET | Admin | OK |
| `/retention/export/(job_id)/data` | GET | Admin | OK |
| `/retention/purge` | POST | Admin | Has `confirm` body flag |
| `/retention/import` | POST | Admin | OK |
| `/retention/audit` | GET | Admin | OK |

**Route count:** ~80 registered REST operations. **All privileged routes set a non-trivial `permission_callback`** (WP-06). No route uses `__return_true`.

### 2.2 AJAX handlers

| Surface | Result |
| --- | --- |
| `wp_ajax_*` / `wp_ajax_nopriv_*` | **None** in plugin PHP/JS (grep empty) |

### 2.3 Admin pages

| Slug | Capability (menu) | Renderer |
| --- | --- | --- |
| `alt-context-dashboard` | `manage_options` | `Menu::render_dashboard_page` |
| `alt-context-workbench` | `manage_options` | workbench SPA host |
| `alt-context-roster` | `manage_options` | roster SPA host |
| `alt-context-description-history` | `manage_options` | description history |
| `alt-context-settings` | `manage_options` | settings SPA host |

SPA bootstrap (`Admin::localize_spa_config`) injects `wp_rest` nonce + REST endpoint map — **no API key** in client config. Mutations from JS attach `X-WP-Nonce` (`js/admin/utils/http.ts`).

### 2.4 Outbound network

| Caller | Destination source | Notes |
| --- | --- | --- |
| `AbstractRecognitionProxyController::proxy_request` | effective recognition base URL (constant → filter → option) | Adds `X-API-Key`, `X-Tenant-ID` |
| `BlobsController::serve_recognition_image` | same base + fixed path segments | HMAC gate only |
| `SettingsController::test_connection` | service/local URL + `/health*` / whoami | Admin |
| `Admin::is_dev_server_reachable` | `ACX_VITE_DEV_SERVER` | Dev-only; `sslverify => false` (F13) |

### 2.5 Secrets surface

| Asset | Tracked? | Notes |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/.env.local` | **gitignored** (`.gitignore:71`) | Not present in this worktree at review time; `.env.local.example` is tracked placeholders for Playwright |
| `acx_recognition_api_key` option | DB | Full key on write; GET returns mask last4 only |
| Client bundle | N/A | No hardcoded provider keys found in `src/` / `js/` |

---

## 3. Findings

### Blockers

#### SECREV-F01 — Recognition base URL options enable server-side request forgery and API-key exfiltration

| | |
| --- | --- |
| **Rules** | [WEB-07], [PHP-16]; eng [RES-02] (bounded outbound), [AGT-02] verified anchors |
| **Tier** | **Blocker** |
| **Files** | `src/api/class-settings-controller.php:128-170`, `:579-585`; `src/api/class-recognition-endpoint-resolver.php:138-148`; `src/api/class-abstract-recognition-proxy-controller.php:69-99`, `:156`; `src/api/class-blobs-controller.php:230-252` |

**Scenario.** An administrator (or any code path that can call `POST /acx/v1/settings` with a valid admin session + REST nonce) sets `url` or `local_url` to an internal target (`http://169.254.169.254/…`, `http://127.0.0.1:…`, cloud metadata, intranet admin UIs). Subsequent `settings/test`, proxy, blob, describe, and analyze traffic `wp_remote_*` that host **and attach the recognition API key**.

**Evidence.**

```579:585:apps/prototype-wp-alt-context/src/api/class-settings-controller.php
	private function is_valid_url( string $url ): bool {
		$parts = parse_url( $url );
		if ( false === $parts || ! is_array( $parts ) ) {
			return false;
		}
		return isset( $parts['scheme'], $parts['host'] ) && in_array( $parts['scheme'], array( 'http', 'https' ), true );
	}
```

```138:148:apps/prototype-wp-alt-context/src/api/class-recognition-endpoint-resolver.php
	private function is_valid_base_url( string $url ): bool {
		// ...
		return in_array( $scheme, array( 'http', 'https' ), true ) && '' !== $host;
	}
```

No blocklist for private/link-local/loopback/metadata hosts; no allowlist of production recognition hosts.

**Remediation shape.**

1. Split **operator URL validation** into: scheme allowlist + host allowlist (prod) OR explicit “allow private networks” constant for local-only installs.
2. Reject link-local / RFC1918 / metadata IPs unless `ACX_ALLOW_PRIVATE_RECOGNITION_URL=1` (or env-type `local`).
3. Never send `X-API-Key` on health probes to non-allowlisted hosts; prefer separate probe credential policy.
4. Log and surface “SSRF-blocked host” distinctly from network errors.

---

#### SECREV-F02 — Signed blob/face-thumb URLs are bearer capability tokens (no session)

| | |
| --- | --- |
| **Rules** | [WEB-08], [WEB-09] (capability in URL), [WP-10] spirit (anonymous surface); eng [RES-13] |
| **Tier** | **Blocker** (PII: face crops / uploaded media bytes) |
| **Files** | `src/api/class-blobs-controller.php:77-198`, `:118-140`; `src/api/class-blob-url-rewriter.php:28-45`, `:136-148`, `:191-243` |

**Scenario.** Recognition responses rewrite blob paths to WP REST URLs carrying `expires` + `token` (HMAC-SHA256 over `wp_salt('auth')`, TTL **3600s**). Anyone who obtains the URL (Referer leakage, shared screen, proxy logs, browser history, support ticket) can `GET` the bytes **without** being logged in. Face-thumb routes include crop params in the signature but still require no session.

Nonce bypass is intentional and path-scoped (`maybe_bypass_nonce_for_blob_route`) so `<img>` works — correct engineering for the UX constraint, but it creates a **public capability endpoint**.

**Evidence.**

```148:153:apps/prototype-wp-alt-context/src/api/class-blobs-controller.php
	 * `<img src>` requests cannot carry the `X-WP-Nonce` header, so the
	 * standard cookie+nonce REST permission check fails for thumbnails
	 * embedded in admin pages. The signed URL is the capability that
	 * authorizes this specific GET; no session check is required because
	 * the token is unforgeable without `wp_salt('auth')`, which is server
	 * side only.
```

**Remediation shape.**

1. Shorten TTL (e.g. 5–15 min) and/or bind token to `user_id` + optional IP subnet for admin-only views.
2. Prefer same-origin WP attachment URLs when `media_id` is a WP attachment (already done for some blob rewrites — extend aggressively).
3. Add `Cache-Control: private, no-store` (partially via `nocache_headers`) and consider `Content-Disposition` / CSP on binary response.
4. Document that blob URLs are secret-equivalent for the TTL window; never log full signed URLs.
5. Optional: cookie-authenticated img proxy using short-lived session cookie set by admin SPA (complex; trade carefully).

---

### Should

#### SECREV-F03 — Workbench REST allows `upload_files` while admin UI requires `manage_options`

| | |
| --- | --- |
| **Rules** | [WP-03], [WEB-08] |
| **Tier** | **Should** |
| **Files** | `src/api/class-api.php:75-94`, `:183-188`; `src/admin/class-menu.php:33-86` |

**Scenario.** Roles with `upload_files` (Author+) can call `GET /acx/v1/workbench/media` and `/workbench/media/detail` with a valid REST nonce, even though they cannot open Alt Context admin pages. Listing returns titles, alt text, edit URLs, tags for **all** image attachments (no author ownership filter).

**Remediation.** Align REST permission with menu (`manage_options`) **or** document intentional multi-role workbench and enforce `edit_post` / author ownership on each media id.

---

#### SECREV-F04 — Recognition API key stored as plaintext WordPress option

| | |
| --- | --- |
| **Rules** | [WEB-16], [SEC-06] |
| **Tier** | **Should** |
| **Files** | `src/api/class-settings-controller.php:154-157`, `:97-121`, `:572-576` |

**Scenario.** `update_option( 'acx_recognition_api_key', $key )` stores the full secret. DB dumps, compromised backups, or `manage_options` SQL browsers recover it. GET correctly returns only `api_key_last4` + `api_key_set` (good).

**Remediation.** Prefer constants / env / secrets manager for production; if option-stored, encrypt-at-rest with keys outside DB; never echo full key; rotate on compromise. Document `ACX_RECOGNITION_API_KEY` as preferred.

---

#### SECREV-F05 — `reset-mirror` is destructive without body-level confirmation

| | |
| --- | --- |
| **Rules** | [SEC-05], [WP-02] (defense in depth beyond nonce) |
| **Tier** | **Should** |
| **Files** | `src/api/class-sync-status-controller.php:86-132`, `:178-208` |

**Scenario.** `POST /recognition/sync/reset-mirror` with admin nonce deletes projection tables (`acx_clusters`, `acx_identity_members`, `acx_sync_outbox`) then re-syncs. Retention purge requires `confirm: true` (good contrast); reset-mirror does not.

**Remediation.** Require explicit `confirm: true` (and optional typed phrase) in body; UI modal already is UX-only — enforce server-side.

---

#### SECREV-F06 — LLM / service `alt_text_draft` persisted without sanitize-on-write

| | |
| --- | --- |
| **Rules** | [SEC-01], [SEC-02], [WP-04], [WP-05] (downstream) |
| **Tier** | **Should** |
| **Files** | `src/api/services/class-describe-media-service.php:258-293`; `src/api/class-describe-controller.php:560` (apply path) |

**Scenario.** Upstream description envelope field `alt_text_draft` is `update_post_meta( ..., '_wp_attachment_image_alt', $draft )` without `sanitize_text_field` / length clamp / control-char strip. Core themes usually `esc_attr` on output, but custom themes/plugins reading raw meta can XSS; also pollutes SEO/a11y fields with markup or bidirectionality attacks.

**Remediation.** Treat draft as untrusted: `sanitize_text_field`, max length, strip tags; refuse HTML; keep human correction path under same sanitizer.

---

#### SECREV-F07 — Expensive recognition/describe paths lack plugin-side per-caller rate limits

| | |
| --- | --- |
| **Rules** | [SEC-08], [WEB-17]; eng [RES-09], [RES-15] |
| **Tier** | **Should** |
| **Files** | `src/api/services/class-description-budget-service.php:25-33` (default limit `-1` = unlimited); analyze/describe controllers under `manage_options` |

**Scenario.** Compromised admin session or buggy SPA loop can hammer `/recognition/describe`, bulk runs, and `/recognition/analyze`, driving recognition-service GPU/CPU cost (denial-of-wallet). Circuit breaker exists for **downstream failures**, not for caller spend. Description budget is opt-in.

**Remediation.** Default finite budget in production; per-user / per-tenant rate limits (transients or action scheduler); hard caps on concurrent jobs; surface 429 consistently.

---

#### SECREV-F08 — PHP includes under `src/` lack `ABSPATH` guards

| | |
| --- | --- |
| **Rules** | [WP-13] |
| **Tier** | **Should** |
| **Files** | `alt-context.php:42-44` has guard; **~129** files under `src/` — only lifecycle references `ABSPATH` for upgrade include |

**Scenario.** If web server mis-maps `src/*.php` as directly executable (unusual on modern WP layouts but common in legacy shared hosting mistakes), files without `defined('ABSPATH') || exit` may run outside bootstrap.

**Remediation.** Standard plugin pattern: top-of-file ABSPATH guard on every loadable PHP file, or ensure only `alt-context.php` is web-reachable (document + release zip layout check).

---

#### SECREV-F09 — Person names and attachment context enter LLM/description prompts when policy allows

| | |
| --- | --- |
| **Rules** | [SEC-06], [SEC-03], [SEC-07] |
| **Tier** | **Should** (privacy / compliance, not classic RCE) |
| **Files** | `src/api/services/class-describe-media-service.php:164-171`, `:422-571` |

**Scenario.** `context_pack` includes attachment metadata, parent post fields, taxonomy, optional product SKU/price, and **roster-confirmed person names** when `acx_description_allow_person_names` is truthy. Images (biometric-adjacent) are uploaded multipart to the recognition service. This is product intent but expands GDPR/biometric/PII surface.

**Remediation.** Keep person-naming default off (already default `false`); document DPA; redaction modes; never log full context packs; ensure remote retention class is honored (field present on envelope).

---

### Judgment

#### SECREV-F10 — Filters can override recognition URL and API key (supply-chain / confused deputy)

| | |
| --- | --- |
| **Rules** | [SEC-04], [WEB-07] |
| **Tier** | **Judgment** |
| **Files** | `class-recognition-endpoint-resolver.php:30-33`; `class-abstract-recognition-proxy-controller.php:224-227`; `class-settings-controller.php:552-554` |

Any other plugin/theme calling `add_filter( 'acx_recognition_base_url' | 'acx_recognition_api_key', … )` can redirect traffic or inject keys. Expected for WP extensibility; high trust in installed plugins required.

**Remediation.** Document as privileged hooks; optional “lock config to constants only” mode that ignores filters/options in production.

---

#### SECREV-F11 — Tenant UUID auto-derived from site URL is predictable

| | |
| --- | --- |
| **Rules** | [WEB-08] (cross-tenant only if remote auth weak) |
| **Tier** | **Judgment** |
| **Files** | `src/api/class-tenant-identity.php:105-118` |

`sha1( 'acx-site-tenant:' . site_url )` shaped into UUID. Predictable tenant IDs are acceptable if **API key + server-side tenant bind** are mandatory (they are for proxy). Risk rises if recognition service ever authorizes by tenant header alone.

**Remediation.** Keep pairing/API-key as sole authority (current pairing flow); never accept client-supplied tenant override on privileged routes.

---

#### SECREV-F12 — XMP embed rewrites original media files in place

| | |
| --- | --- |
| **Rules** | [WP-11], [WEB-12] (integrity, not exec upload) |
| **Tier** | **Judgment** |
| **Files** | `src/api/class-xmp-embed-controller.php:49-69`; `src/media/class-image-xmp-writer.php:54-127` |

Admin can batch-write XMP into original JPEG/PNG binaries. Integrity/backup concern more than RCE (mime allowlist jpeg/png; uses attachment paths from WP).

**Remediation.** Optional write-to-copy; audit log of media_ids; confirm dialog; checksum before/after.

---

#### SECREV-F13 — Vite dev-server probe disables TLS verification

| | |
| --- | --- |
| **Rules** | [WEB-07] partial |
| **Tier** | **Judgment** |
| **Files** | `src/admin/class-admin.php:118-148` |

Only when `wp_get_environment_type() === 'development'` and `ACX_VITE_DEV_SERVER` set. Acceptable for local DX; ensure never reachable in production env type.

---

## 4. Non-findings / verified-safe

| Control | Evidence |
| --- | --- |
| **WP-06 real permission callbacks** | All `register_rest_route` sites set `permission_callback` to capability or HMAC verifier; no `__return_true` |
| **No nopriv AJAX** | Zero `wp_ajax` / `wp_ajax_nopriv` handlers |
| **Admin menu capability** | All Alt Context pages require `manage_options` (`class-menu.php`) |
| **REST CSRF (cookie clients)** | SPA sends `X-WP-Nonce` (`js/admin/utils/http.ts:30-32`); WP REST cookie auth enforces nonce except scoped blob bypass |
| **SQL prepare discipline** | Sovereign layer uses `PreparesSqlQueries` (`trait-prepares-sql-queries.php`) with `%i` identifier handling; API person CRUD uses `$wpdb->prepare` / `$wpdb->insert|update|delete` format arrays |
| **Tenant scoping on conflicts/outbox** | `ConflictRepository::find_conflict_by_id( $id, $tenant_id )` and list APIs pass `TenantIdentity::resolve()` |
| **No production unserialize / phar / extract / dynamic `new $class` from request** | Grep clean under `src/` (test-only `shell_exec`) |
| **No DOM XSS sinks in SPA** | No `innerHTML` / `dangerouslySetInnerHTML` / `document.write` under `js/` |
| **API key not returned full to client** | Settings GET masks last4 (`mask_key`) |
| **Secrets not committed** | `.env.local` gitignored; only `.env.local.example` placeholders tracked |
| **Blob path segments constrained** | Route regex `[A-Za-z0-9._-]+`; face-thumb query ints bounded |
| **Retention purge confirmation** | Server requires `confirm` boolean (`class-retention-controller.php:270-278`) |
| **Describe envelope validation** | Required provenance fields enforced; rejects malformed 2xx (rg-015) |
| **Person naming default off** | `acx_description_allow_person_names` defaults false |
| **Postgres surface in this plugin** | Plugin does **not** open direct Postgres connections; identity DB is remote via recognition proxy. PG-0x checklist applies to description-service / infra, not this PHP tree (out of SECREV-1 code scope) |
| **ABSPATH on bootstrap** | Main plugin file exits if `ABSPATH` undefined |

**Not security defects (noted for planners):**

- Identifier-only SQL concatenation for **fixed** lifecycle table drops / CLI truncate of allowlisted suffixes — operator/CLI context, not request-driven.
- Proxy retries with exponential backoff exist (`AbstractRecognitionProxyController`) — good [RES-06]/[RES-15] alignment.

---

## 5. Task-plan decomposition

Proposed shippable units for later planning (not started here). Dependency order top → bottom.

### TP-A — Outbound URL / SSRF hardening  
**Findings:** F01, F10  
**Effort:** M (2–4 days)  
**Scope:** Centralize `RecognitionEndpointResolver` validation; private-IP policy; production allowlist; lock-to-constants mode; tests for blocked hosts; settings UI error copy.  
**Deps:** none  
**Acceptance:** unit tests for metadata/loopback rejection; integration test that proxy refuses non-allowlisted hosts.

### TP-B — Blob capability token redesign  
**Findings:** F02  
**Effort:** M–L  
**Scope:** TTL policy, optional user binding, log redaction, expand WP-attachment URL short-circuit, security docs for operators.  
**Deps:** none (can parallel TP-A)  
**Acceptance:** unauthenticated fetch without valid token still 401; expired token 401; documented residual risk.

### TP-C — Capability & object authz alignment  
**Findings:** F03, F11 (docs)  
**Effort:** S (0.5–1 day)  
**Scope:** Raise workbench REST to `manage_options` **or** add per-attachment caps + product decision ADR; document tenant derivation assumptions.  
**Deps:** product decision on Author-role workbench  
**Acceptance:** Author role cannot list full media queue unless product explicitly allows + ownership filters.

### TP-D — Secrets handling  
**Findings:** F04  
**Effort:** S–M  
**Scope:** Prefer constant/env; optional encrypted option storage; rotation runbook; ensure settings UI never echoes full key (already masked).  
**Deps:** deploy env conventions  
**Acceptance:** production install guide uses constant; DB dump without app secret cannot recover key (if encryption chosen).

### TP-E — Destructive action confirmations  
**Findings:** F05, F12 (confirm UX)  
**Effort:** S  
**Scope:** `confirm` body on reset-mirror; optional confirm on XMP embed batch; mirror retention purge pattern.  
**Deps:** none  
**Acceptance:** missing confirm → 400; tests updated.

### TP-F — LLM output trust boundary + rate limits  
**Findings:** F06, F07, F09  
**Effort:** M  
**Scope:** sanitize/clamp alt text on all write paths (REST + CLI); production default budget; per-admin rate limit middleware for describe/analyze; privacy copy for person-naming.  
**Deps:** TP-A for where data is sent  
**Acceptance:** HTML-bearing drafts stored sanitized; default budget not unlimited in `production` env type.

### TP-G — Defense-in-depth PHP packaging  
**Findings:** F08, F13  
**Effort:** S  
**Scope:** ABSPATH guards or release packaging assert; ensure Vite TLS bypass cannot run when env ≠ development.  
**Deps:** none  
**Acceptance:** direct HTTP to a sample `src/` file does not execute app logic (or packaging omits web exposure).

### Suggested sequence

1. **TP-A** (SSRF) → 2. **TP-B** (blobs) + **TP-C** (caps) in parallel → 3. **TP-F** (LLM) → 4. **TP-D/E/G** polish.

---

## 6. Review coverage checklist (method §)

| Step | Done |
| --- | --- |
| Enumerate REST + permission_callback | Yes (§2.1) |
| AJAX / admin pages | Yes (§2.2–2.3) |
| Controllers: authz, IDOR, sanitize | Yes (conflicts tenant-scoped; workbench F03) |
| SQL prepare / sovereign layer | Yes (§4) |
| Outbound proxy / SSRF | Yes (F01) |
| LLM data flow / settings keys | Yes (F04, F06, F07, F09) |
| Secrets / `.env.local` | Yes (gitignored; example only) |
| Deserialization / phar | Yes (clean) |
| Frontend DOM sinks | Yes (clean) |
| XMP / uploads | Yes (F12) |
| Postgres identity DB in plugin | N/A direct — noted §4 |

---

## 7. Appendix — key symbols

| Symbol | Path |
| --- | --- |
| Plugin bootstrap | `apps/prototype-wp-alt-context/alt-context.php` |
| Route registration hub | `src/api/class-api.php` + `RecognitionController` composition |
| Proxy + circuit breaker | `src/api/class-abstract-recognition-proxy-controller.php` |
| Endpoint resolution | `src/api/class-recognition-endpoint-resolver.php` |
| Blob HMAC | `src/api/class-blob-url-rewriter.php`, `class-blobs-controller.php` |
| SQL prepare trait | `src/sovereign/repositories/trait-prepares-sql-queries.php` |
| SPA nonce injection | `src/admin/class-admin.php` (`localize_spa_config`) |
| SPA fetch | `js/admin/utils/http.ts` |

---

*End of SECREV-1 assessment. Decompose via TP-A…TP-G; record implementation findings in workbay-handoff-mcp, not by pasting into task-plan markdown.*
