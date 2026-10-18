# E15-28 public demo walkthrough runbook

Operator-facing steps to capture Slice 3 proof on `https://demo.altcontext.com`.
Reuse E15-5 / E15-22 evidence headings in `docs/tasks/15.0/E15-28-demo-smoke-log.md`.

## Preconditions

- [ ] E15-3a LocalWP → OCI round-trip gate passed
- [ ] E15-22 Workbench avatar / review-drawer proof captured
- [ ] `make deploy-demo` succeeded (stack + bootstrap + Caddy) — or laptop-free via CI: `gh workflow run deploy-demo.yml -f confirm=PROMOTE` (see `docs/runbooks/deploy-demo-cicd.md`)
- [ ] Tenant/key minted with **explicit UUID** (`tenant-mint-runbook.md`)
- [ ] `RECOGNITION_ALLOWED_ORIGINS` includes `https://demo.altcontext.com`
- [ ] Seed media imported (`seed/import.sh`) with provenance table filled

## 1. Settings + pairing proof

1. Open `https://demo.altcontext.com/wp-admin/` (edge gate creds if enabled).
2. ACX Settings → confirm URL/key/tenant show **constant provenance** (read-only).
3. Run **Test Connection** → expect `connected` against configured API (staging first).

## 2. Scan → recognition → curation

1. Upload or confirm seeded media visible in Media Library.
2. Trigger scan from Workbench; record correlation IDs + timestamps.
3. Capture representative avatar evidence (Top Cluster + Review drawer).
4. Curate at least one cluster; save screenshot paths to the smoke log.

## 3. Sovereign / degraded boundary (E15-26)

On **staging** first:

1. `docker stop` the staging API container (not prod).
2. Reload demo Workbench — curated data still readable, degraded banner honest.
3. Restart API container; confirm recovery banner clears.

Repeat against prod only after staging proof is filed.

## 4. CORS spot check

`-D -` dumps response headers so the asserted header is actually visible:

```bash
curl -fsS -D - -o /dev/null \
  -X OPTIONS 'https://staging.api.altcontext.com/recognition/health' \
  -H 'Origin: https://demo.altcontext.com' \
  -H 'Access-Control-Request-Method: GET'
```

Expect a `204`/`200` status line and
`Access-Control-Allow-Origin: https://demo.altcontext.com` in the dumped headers.

## 5. Record evidence

Automated capture: `make demo-walkthrough-proof` drives the browser steps above
(settings provenance + Test Connection, Workbench scan, cluster avatar, and an
opportunistic degraded-banner grab — attempted both before and after the scan — if
the API was stopped per §3) and emits screenshots, an evidence manifest, and a
paste-ready `demo-walkthrough-smoke-log-fragment.md`. First-time setup:
`(cd apps/prototype-wp-alt-context && npm ci && npm run e2e:install)`. Auth needs
`ACX_E2E_WP_ADMIN_USER` / `ACX_E2E_WP_ADMIN_PASS`. Runs against the demo origin by
default; for LocalWP (no wp-config constants) use
`WP_BASE_URL=http://localhost:10010 ACX_E2E_REQUIRE_CONSTANT_PROVENANCE=0 ACX_E2E_REQUIRE_SERVICE_TARGET=0 make demo-walkthrough-proof` (the second flag keeps the RECOG-1 service-target gate from false-failing when the wp-config dev hatch is active).

Playwright nests artifacts in a per-test subdir under
`apps/prototype-wp-alt-context/local/playwright/<task-ref>/evidence/`; locate the
fragment with `find apps/prototype-wp-alt-context/local/playwright/<task-ref>/evidence -name demo-walkthrough-smoke-log-fragment.md`.
Paste it into `docs/tasks/15.0/E15-28-demo-smoke-log.md`, fill the manual sections
(correlation IDs, recovery screenshot), and link handoff decision IDs.
