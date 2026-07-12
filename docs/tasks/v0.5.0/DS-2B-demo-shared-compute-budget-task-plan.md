# DS-2B. Shared demo compute budget across analyze + scene endpoints

> **Task ref:** `DS-2B` · **Branch:** `feature/ds-2b` · **Closes:** finding `DS-2-BR-05` (deferred, medium, security — see handoff)
> **Parent:** GTM launch plan §5/§14 (`docs/gtm/altcontext-productization-launch-plan.md`, DS-2/DS-5) · **Authored:** 2026-07-12

## Objective

A demo-tenant API key draws every GPU/compute call — recognition analyze *and* scene describe — from one shared budget (`demo_instances.recognition_quota`, default 200), so the demo cap is enforceable across the whole compute surface.

## Problem Statement

`enforce_demo_quota` (DS3-BR-02) is wired only onto `recognition/analyze` and `recognition/analyze/multipart`. A provisioned demo key is an ordinary `RateLimitTier.STANDARD` key, so the `/scene/describe/*` compute surface — the most GPU-expensive endpoints — accepts it with **zero** budget. The 200-call cap is abuse insurance ([SEC-04] least privilege, [OPS-01] incentives); an uncapped compute surface defeats it entirely ([STRAT-02] invert: the fence has an open gate).

## Constraints

- Non-demo keys must be completely unaffected (no registry row → no enforcement, unchanged behavior).
- Quota consume must stay a single-statement atomic CAS ([CON-05]/[CON-11] — no check-then-act split).
- The wire-locked `/recognition/analyze` contract is untouched; scene router stays separate (per `scene/interface_adapters/http/router.py` composition note).
- One-intent diff ([REF-05] two hats, [AGT-05]): behavior fix only, no renames.

## Terminology

- **Compute endpoint**: an endpoint whose request triggers model inference (CPU or GPU). Read/lifecycle endpoints (job polling, run listing/deletion) are not compute.
- **Unit**: one image submitted for inference. Batch runs consume `len(media_ids)` units.
- **Shared budget**: the single `recognition_used`/`recognition_quota` counter pair on `demo_instances`. Naming note: after this task the columns meter all compute, not just recognition — rename to `compute_*` is an explicit follow-up ([NAME-03]), documented in docstrings meanwhile.

## Current State Analysis

- `recognition/interface_adapters/http/deps/demo_quota.py` — `enforce_demo_quota` dep: hashes the bearer key, calls `try_consume_demo_quota`, maps `DemoQuotaExceededError` → 429 `demo_quota_exceeded`. Wired at `analyze.py:284` and `analyze_multipart.py:198` only.
- `recognition/application/services/demo_provisioning_service.py` — `try_consume_demo_quota`: guarded `UPDATE … WHERE recognition_used < recognition_quota RETURNING`; on 0 rows, a fallback `SELECT` distinguishes "not a demo key" (returns False) from "at cap" (raises). Consumes exactly 1.
- `scene/interface_adapters/http/routers/describe.py` — `POST /scene/describe/multipart` (:423) and `POST /scene/describe/async` (:542) use `Depends(require_write_access)`; **no quota dep**.
- `scene/interface_adapters/http/routers/describe_run.py` — `POST /scene/describe/run` (:216) parses `media_ids` before creating the run; **no quota dep**.
- Auth composition (verified): `require_write_access` (`recognition/interface_adapters/http/deps/auth.py:317`) is `Depends(require_auth)`, so FastAPI dependency caching guarantees one auth evaluation per request when `enforce_demo_quota` (which also deps `require_auth`) is added alongside it.
- Verified: no server-side analyze→scene fan-out exists (grep of analyze router + recognition services), so no double-charging path.

## Target Outcome

| Endpoint | Units consumed | Mechanism |
|---|---|---|
| `POST /recognition/analyze` | 1 | existing dep (unchanged) |
| `POST /recognition/analyze/multipart` | 1 | existing dep (unchanged) |
| `POST /scene/describe/multipart` | 1 | add `Depends(enforce_demo_quota)` |
| `POST /scene/describe/async` | 1 | add `Depends(enforce_demo_quota)` |
| `POST /scene/describe/run` | `len(media_ids)` | inline consume after parse, before `create_run` |

Read/lifecycle endpoints (`GET /scene/describe/jobs/{id}`, `GET/DELETE /scene/describe/run/*`) consume **nothing** — quota meters compute, not polling ([RES-12]).

## Context Loading

Minimum anchors: `demo_quota.py` (dep), `demo_provisioning_service.py` (`try_consume_demo_quota`, `DemoQuotaExceededError`), `scene/.../describe.py` + `describe_run.py` (change sites), DS3-BR-02 pg concurrency tests (pattern to mirror), `docs/gtm/altcontext-productization-launch-plan.md` §5 (product intent).

## Contract and Boundary Impact

- **429 payload gains `quota_remaining`**: `DemoQuotaExceededError` grows a `remaining: int` attribute (populated from the row the existing fallback `SELECT` already loads); `enforce_demo_quota` surfaces it in the 429 detail dict. Additive to the error envelope — existing consumers keyed on `code: demo_quota_exceeded` unaffected ([API-09] add, don't change). Enables the demo WP to size a smaller retry ([AIPX-12] refine over restart).
- No schema change, no public-API removals, no `/x/{slug}` change (`quota_remaining` there already reflects the shared counter).

## Design Decision (settles the deferred question on DS-2-BR-05)

**Shared budget.** One counter covers all demo compute. Rationale: one demo, one budget — matches the public `quota_remaining` field and the cap-message story ([BOOT-06] one forcing number); a separate scene budget is a config knob with no consumer ([REF-21], YAGNI). Batch semantics are **all-or-nothing**: a run needing 12 units against 5 remaining is rejected whole — no partially-captioned batch a user believes succeeded ([RLSE-05] silent failure is the worst failure). Quota is consumed at *submission*, not completion — a failed run still burns units; acceptable for abuse insurance, not billing ([REF-21]; documented in docstring). Rollback: additive behavior, no schema change — revert the commit ([RLSE-08]).

## Files and Surfaces to Change

| File | Function | Change |
|---|---|---|
| `recognition/application/services/demo_provisioning_service.py` | `try_consume_demo_quota` | add `units: int = 1` (validate ≥1); CAS becomes `SET recognition_used = recognition_used + :units WHERE recognition_used + :units <= recognition_quota`; fallback SELECT logic unchanged (row exists + 0 rows updated → insufficient headroom → raise), now populating `DemoQuotaExceededError(remaining=quota - used)` |
| same | `DemoQuotaExceededError` | add `remaining: int` attribute |
| `recognition/interface_adapters/http/deps/demo_quota.py` | `enforce_demo_quota` | include `quota_remaining` in 429 detail; export a callable `consume_demo_quota_units(session, api_key_hash, units)` for non-dep call sites |
| `scene/interface_adapters/http/routers/describe.py` | `describe_image_multipart`, `describe_async` | add `_demo_quota=Depends(enforce_demo_quota)` |
| `scene/interface_adapters/http/routers/describe_run.py` | `create_describe_run` | after `media_ids` parse + tenant validation, before `repo.create_run`: consume `len(media_ids)` units; 429 same envelope |

Ordering rule at every site: consume AFTER auth/tenant validation, BEFORE any inference dispatch or run persistence (mirrors the S3A-05 ordering note in `describe.py`).

## Related Files

DS3-BR-02 quota tests under `recognition/tests/` (concurrency pattern), `scene/tests/` API tests (fixture patterns), `api/main.py` (router mounting — no change expected).

## Verification Strategy

- Scoped: `cd apps/prototype-description-service && uv run pytest -q -k "demo_quota or describe"` green.
- Full: `uv run pytest recognition/tests scene/tests -q` green (baseline 1283 passed / 2 skipped).
- Lint: `ruff format --check && ruff check` clean.
- Red-before-green ([AGT-03]): the scene-bypass regression test must be observed failing against current code before S2 wiring lands.

## Slice Delivery

### Slice 1: `try_consume_demo_quota(units)` + error payload

Extend the CAS with `units`, add `remaining` to `DemoQuotaExceededError`, surface `quota_remaining` in the dep's 429 detail. Unit + pg-concurrency tests (two concurrent consumes near cap never overshoot `recognition_quota`).

### Slice 2: Scene wiring + test matrix

Wire the two deps and the inline batch consume. Tests: (1) demo key on `/scene/describe/multipart` at cap → 429, below cap → consumes 1 (**this is the red-first bypass regression test**); (2) same for `/describe/async`; (3) `/describe/run` with N media_ids: budget N−1 → 429 whole, `recognition_used` unchanged; budget ≥ N → exactly N consumed, run created; (4) shared-pool proof: interleaved analyze + scene calls drain one counter; (5) non-demo key unaffected on all scene endpoints; (6) read/lifecycle endpoints consume nothing.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded quota dep, provisioning service, scene routers, and DS3-BR-02 test patterns before editing.
- [ ] 429-envelope addition documented as additive in the slice decision (no consumer breakage).

### Checklist for Slice 1: units CAS + error payload

- [ ] `try_consume_demo_quota(units)` single-statement CAS + `units >= 1` validation
- [ ] `DemoQuotaExceededError.remaining` populated; dep surfaces `quota_remaining` in 429 detail
- [ ] Unit + pg-concurrency tests green; no overshoot at cap boundary

### Checklist for Slice 2: scene wiring

- [ ] Bypass regression test observed failing red against pre-wiring code
- [ ] `Depends(enforce_demo_quota)` on `/scene/describe/multipart` + `/describe/async`
- [ ] Inline `len(media_ids)` consume in `create_describe_run` (post-auth, pre-persist)
- [ ] Test matrix (6 cases) green; full suite + ruff green

## Review Readiness

- [ ] No boundary-touching change without matching test evidence (429 envelope, batch all-or-nothing).
- [ ] Runtime-parity: pg-backed concurrency test included (fakes can mask CAS behavior).
- [ ] Handoff decision records the change, verification, and the shared-budget design decision.

## Stretch Goals

- [ ] Docstring note on `demo_instances` model marking `recognition_*` columns as shared-compute (pre-rename breadcrumb).

## Success Criteria

- [ ] A demo key at quota receives 429 `demo_quota_exceeded` (with `quota_remaining: 0`) on **every** compute endpoint — recognition and scene.
- [ ] A batch run larger than remaining budget is rejected whole with zero units consumed.
- [ ] Non-demo tenants show zero behavior change across the full suite.

## Out of Scope

- `recognition_*` → `compute_*` rename (follow-up; greenfield policy permits whenever taken up).
- Per-endpoint weighting (scene = k units): no cost data justifying it ([PERF-06]); 1 image = 1 unit.
- Refund-on-failure for async runs (billing-grade complexity, no demo-tier consumer).
- Per-IP limits on authenticated scene routes (per-key limiter covers; DS-5 scoped to unauthenticated surfaces).
