# Offload Brief — DS-2: Demo Slug Router + Enforcement (folds DS-4 job, DS-5 hardening, DS3-BR-02 quota)

> **Purpose:** the critical path after DS-3. `make provision-demo` (shipped, main) mints
> `https://demo.altcontext.com/x/<slug>` URLs that resolve to nothing until this router
> exists. This slice ships the **server-side slug resolution + enforcement** in the
> recognition service. Demo WP container / Caddy / demo.altcontext.com hosting stay E15-28.
> **Backend:** `grok-cli` · **Model:** `grok-4.5` (mandatory pin) · **Effort:** high.
> Plan: `docs/gtm/altcontext-productization-launch-plan.md` §5 (verbatim contract), §14 rows DS-2/DS-4/DS-5.

## Objective (end-state contract)

A public-safe resolution surface over the `demo_instances` registry (shipped in `001_identity_schema.py`):

1. **Resolution endpoint** in the recognition service: `GET /x/{slug}` (or `/demo/v1/resolve/{slug}` if router-prefix conflicts — document the choice). Valid slug → demo context `{tenant_id, seed_bundle, branding_json, expires_at, quota_remaining}` for the demo WP to consume **server-side**. The **raw API key is never in any response** — the registry stores only `api_key_ref` (hash) [E15-24: never URL-derived identity; browser never sees the key].
   - Unknown slug → **404** (uniform body; no existence oracle).
   - Expired (`expires_at < now`) or `revoked=true` → **410** with a `demo_ended` signal (the "demo ended, sign up" CTA hook per §5).
2. **Rate limiting on `/x/*`** (DS-5): per-IP bounded lookups so slug guessing is blocked; scripted enumeration test proves 429 after threshold. Slug space is 58^7 (CSPRNG, shipped) — rate limit is the second layer.
3. **Quota enforcement** (deferred finding **DS3-BR-02**, task DS-3): recognition request path increments `recognition_used` for demo-tenant keys (keyed off `api_key_ref` → demo row) and rejects with a quota-exceeded error at `recognition_used >= recognition_quota`. This makes the stored 200-cap real instead of advertised-but-inert.
4. **Daily expiry job** (DS-4 remainder): scheduled sweep (systemd timer or in-service scheduler — match existing worker patterns) that revokes instances past `expires_at`, **calling the same path as `expire_demo`** so the underlying `api_keys.revoked_at` is set (see DS3-BR-01 lesson: flag-only revocation is a security no-op — auth gates on `api_keys.revoked_at`).

## Scoped TEST_CMD

```
cd apps/prototype-description-service && .venv/bin/python -m pytest recognition/tests -q -k "demo_router or demo_quota or demo_expiry"
```
**Assertions to encode:** valid slug resolves context without any key material in the body; unknown → 404; expired/revoked → 410 + `demo_ended`; enumeration burst → 429; demo key at quota → rejected + `recognition_used` incremented atomically (no lost-update under concurrency); sweep revokes both the row AND the api_key (assert `revoked_at` set + `get_by_hash` returns None).

## Known-red baseline

- No route serves `/x/<slug>` (404 from router absence, not from lookup) — red.
- `recognition_used` never increments; over-quota demo key still authorizes — red (DS3-BR-02).
- No expiry sweep exists — red.

## Out of scope (do not build)

Demo WP container, Caddy vhost, demo.altcontext.com DNS/hosting, frontend demo UI, seed-media ingestion (all E15-28 / DS-6). No new tables — `demo_instances` is the substrate; migration edits only if a column is genuinely missing (greenfield: edit `001` directly, NO inspect()-based ALTER shims — see AP-7 lesson).

## Heuristics to cite (canon: docs/reference/engineering-heuristics-canon.md)

[SEC-04] least privilege on the public surface · [RES-13] fail-fast over degraded · [AGT-02] no unresolved anchors (verify plan §5 symbols against the shipped DS-3 code) · [AGT-03] make the enumeration/quota tests fail before passing · rg-015 (no invented contract metadata in the resolve envelope) · rg-007 (bounded stall detection in the sweep job).

## Lane mechanics (per DS-3/AP-7 session lessons)

Worktree `context-alt-text-monorepo-ds-2` on `feature/ds-2` from main. Reset the local DB (`ALLOW_DEV_DB_RESET=1 make db-reset` in the service dir) **before** self-verify — stale schema is the #1 false-failure. Per-slice `/branch-review` + `/auto-fix`; branch-complete adversarial `/review-parallel` (≥2 lenses) before merge; no auto-merge.
