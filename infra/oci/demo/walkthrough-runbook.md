# E15-28 public demo walkthrough runbook

Operator-facing steps to capture Slice 3 proof on `https://demo.altcontext.com`.
Reuse E15-5 / E15-22 evidence headings in `docs/tasks/15.0/E15-28-demo-smoke-log.md`.

## Preconditions

- [ ] E15-3a LocalWP → OCI round-trip gate passed
- [ ] E15-22 Workbench avatar / review-drawer proof captured
- [ ] `make deploy-demo` succeeded (stack + bootstrap + Caddy)
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

## 4. CORS + rate-limit spot checks

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' \
  -X OPTIONS 'https://staging.api.altcontext.com/recognition/health' \
  -H 'Origin: https://demo.altcontext.com' \
  -H 'Access-Control-Request-Method: GET'
```

Expect `204`/`200` with `Access-Control-Allow-Origin: https://demo.altcontext.com`.

## 5. Record evidence

Fill `docs/tasks/15.0/E15-28-demo-smoke-log.md` and link handoff decision IDs.
