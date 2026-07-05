# E15-29 — Public Demo Go-Live Smoke Log

> Live execution evidence for the public recognition demo. Handoff is the source of truth; decision IDs link the durable record. Screenshots under `apps/prototype-wp-alt-context/local/playwright/E15-29/evidence/` (gitignored; operator-local).

- **Date**: 2026-07-05
- **URL**: https://demo.altcontext.com (A-record → 129.213.40.111, valid LE TLS)
- **Backend**: `api.altcontext.com` @ `9cc85c43` (recognition-only)
- **Demo tenant**: `00000000-0000-4000-8000-000000000001` (explicit UUID; `is_auto_derived=false`)

## Provisioning (via /admin JSON API over tailscale)

- Prod upgraded to current main to ship the `/admin` surface (E15-31): `make deploy-prod` → `/health.commit_sha == 9cc85c43`. Two drift defects surfaced + fixed en route (decision 1194): greenfield schema drift (4 tables created via idempotent `create_all`) and the `scene/` packaging bug (fixed + merged as `MAINT-SCENE-DEPLOY-PKG`, decision 1196).
- `/admin` enabled on the tailnet loopback (overlay `127.0.0.1:8000`, shared admin token, `RECOGNITION_ADMIN_TAILNET_BOUND=1`); public `/admin` stays 404 by design (decision 1197).
- Tenant + key minted through the JSON API (decision 1197): `POST /admin/tenants` → 201; `POST /admin/tenants/{id}/keys` → 201, key `ea49a628-2c93-4522-914f-efa4761209dd` (STANDARD, no expiry), active per `GET /admin/tenants/{id}/keys`. Raw key spliced into the demo `WORDPRESS_CONFIG_EXTRA` (never left the VM).

## Deploy + seed

- `make deploy-demo` (tailscale): demo stack up, `bootstrap-wp` core install + plugin activate, Caddy validate + promote, four-vhost smoke. In-container constants verified: `ACX_RECOGNITION_URL=https://api.altcontext.com`, `ACX_RECOGNITION_SOURCE=service`, tenant `…0001`, API key length 43.
- Seed import: `./seed/import.sh` → **100** media items (`wp post list --post_type=attachment --format=count == 100`), 20 persons ≥5 each (jpeg content-validated, E15-29-BR-02).
- Prod CORS: appended `https://demo.altcontext.com` to `RECOGNITION_ALLOWED_ORIGINS`; preflight `OPTIONS` from the demo origin returns `Access-Control-Allow-Origin: https://demo.altcontext.com`; `api/health` stayed 200.

## Recognition + clustering (Playwright `demo-walkthrough-proof`)

- `make demo-walkthrough-proof WP_BASE_URL=https://demo.altcontext.com ACX_PLAYWRIGHT_TASK_REF=E15-29` → **2 passed**. Smoke-log fragment: scan triggered, processed-count `0 → 0 → 5` monotonic, **scan failures: none**.
- Worker pipeline (tenant `…0001`): faces detected → clustering `batch_complete … new_clusters=4`; ≥1 **multi-image cluster** confirmed in prod DB (`identity_clusters` join `identity_members`: one cluster with 2 members). Clustering acceptance gate met.
- Root-cause note: the first walkthrough failed every item with `ObjectStoreError: uri does not resolve to a file` — the deployed prod compose predated the E15-11 blob store (`RECOGNITION_BLOB_ROOT` unset → container-local `/tmp`; api/worker unshared). Hotfixed by converging the prod compose to share `acx_blobs` + set `RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs`; 0 objectstore errors after. Durable fix planned as **E15-33**.

## Sovereign boundary (E15-26) — decision 1202

- Operator stopped `acx-prod-api-1`; Playwright capture (`evidence/sovereignty-live/`): **degraded banner present** ("Working offline / recognition backend unreachable", "Suggestion service error", "Suggested names unavailable" + Retry) while **curated clusters stayed readable** (the "Name These People" panel kept rendering, incl. the 2-face cluster; labeling still available offline). `degraded_banner=true`, `local_read_still_works=true`, `local_clusters_visible=true`.
- API restarted (`docker start acx-prod-api-1`, `/health=200`); recovery capture (`evidence/sovereignty-recovered/`): `banner_cleared_on_recovery=true`, clusters visible.
- Mechanism (verified in code): `isSyncOffline = breaker.state==='open' || last_pull.ok===false` via the wp-json `acx/v1/recognition/sync/health` endpoint (server-side pull failure surfaces the honest banner).

## Success criteria

- [x] Public visitor loads the live demo over valid TLS with real recognition from `api.altcontext.com`.
- [x] Media library holds 100 seed images (≥5/person); Workbench clusters by identity (≥1 multi-image cluster).
- [x] Seed licensing dispositioned — documented fair-use demo (blocker 7); provenance table filled.
- [x] $0/mo incremental (colocated on the A1.Flex VM; inference SLO intact).
- [x] Killing the API leaves curated data readable with an honest degraded banner (E15-26).
- [x] Demo tenant minted via the `/admin` JSON API (explicit UUID).
