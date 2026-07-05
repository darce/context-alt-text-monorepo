# E15-33. Durable Prod-Deploy Runtime-Contract Convergence

> **Metadata**
>
> - **Date**: 2026-07-05
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-33`
> - **Target Worktree**: `/Users/daniel/Development/context-alt-text-monorepo-e15-33`
> - **Review Coverage Target**: 2

## Objective

Make a prod deploy converge the **entire runtime contract** — container image, `docker-compose.env.yml`, systemd unit, and DB schema — with the repo, and catch a bad artifact **before** it restarts prod. Today `make deploy-prod` ships only the image against whatever compose/unit/schema already sit on the VM, so silent drift (missing volumes, missing tables, missing packages) reaches prod and is only discovered by a crash-looping container taking the public API down.

## Problem Statement

Four independent drift classes each caused a prod outage or silent failure during E15-29 (see decisions 1194, 1197; blocker 10). All share one root cause: **the deploy path treats the image as the only versioned artifact, and verification runs only after the live restart.**

1. **Compose/unit drift.** `scripts/deploy/recognition-service.sh` `do_restart` runs `docker compose -f docker-compose.env.yml pull api && systemctl restart acx-$env`. It never ships `docker-compose.env.yml` or the unit — that is a *separate*, manually-run `apps/prototype-description-service/scripts/deploy-env.sh`. Prod's deployed compose predated the E15-11 blob store, so `RECOGNITION_BLOB_ROOT` was unset (→ container-local `/tmp` default) and api/worker shared no `acx_blobs` volume; the worker could not read images the api uploaded (`ObjectStoreError: uri does not resolve to a file`, `recognition/application/scan/service.py:249`).
2. **Greenfield schema drift.** `db/migrations/versions/001_identity_schema.py` is edited **in place** under a constant revision id (`001_identity_schema`), so the container entrypoint's `alembic upgrade head` is a no-op on an already-stamped DB. Four tables added to the schema since the last prod init (`assignment_decisions`, `clustering_job_reports`, `image_descriptions`, `worker_capabilities`) never existed on prod; `scripts/verify_identity_schema.py` fail-closed the boot → crash-loop → 502.
3. **Packaging omission.** `apps/prototype-description-service/Dockerfile` runtime stage copies `api/ db/ recognition/ roster/ shared/ scripts/` and `pyproject.toml` `[tool.setuptools.packages.find].include` lists them, but a new top-level package (`scene/`, imported unconditionally at `api/main.py:48`) was in neither → `ModuleNotFoundError: No module named 'scene'` at uvicorn boot. Fixed reactively in `MAINT-SCENE-DEPLOY-PKG`; nothing prevents the next such omission.
4. **Post-hoc verify.** `recognition-service.sh` `do_verify` polls `/health` only **after** `systemctl restart`. A bad image is already live (and prod already 502ing) before the failure is detected; recovery is a manual image retag + restart.

## Constraints

- **Greenfield policy holds** (`CLAUDE.md`): schema stays in `001_identity_schema.py`; no incremental alembic revisions per change. The durable fix must make in-place schema edits **apply to existing DBs** without abandoning the single-file model.
- **$0/mo, single A1.Flex VM**: no new managed services; solutions run on the existing VM + OCIR.
- **No public-API downtime as the failure mode**: a bad build must fail the deploy *before* it can restart `acx-prod`.
- **Additive to the existing kit**: reuse `recognition-service.sh` / `deploy-env.sh` / `sync-compose.sh`; do not introduce a parallel deploy mechanism (rg-009).
- **Idempotent + safe on live data**: schema self-heal must be additive (`create_all`-style), never `DROP`/`downgrade base` (prod holds the real `…0000` tenant + demo `…0001`).

## Current State Analysis

- **Works**: image build+push+restart+`/health` verify (`recognition-service.sh` `do_build_remote`, `do_push`, `do_restart`, `do_verify`); `deploy-env.sh` *can* converge compose+unit+Caddy but is out-of-band and operator-triggered; `verify_identity_schema.py` correctly fail-closes (it caught #2, just too late).
- **Not done**: no single command converges image+compose+unit+schema; no pre-restart boot smoke; no packaging-completeness guard; the entrypoint cannot self-heal in-place schema additions.
- **Misleading if unchecked**: a green `make deploy-prod` verify only proves `/health` came back — it says nothing about compose/volume/schema parity with the repo.

## Context Loading

- **Rules**: `docs/workbay/rules/development-workflow.md` (pre-merge gate), `infra/oci/README.md` (env layout, deploy SOP), `CLAUDE.md` Greenfield Policy.
- **Deploy anchors**: `scripts/deploy/recognition-service.sh` (`do_build_remote`, `do_restart`, `do_verify`, `preflight_ssh`), `apps/prototype-description-service/scripts/deploy-env.sh`, `scripts/deploy/sync-compose.sh`, `apps/prototype-description-service/systemd/acx-env.service.template`.
- **Runtime anchors**: `apps/prototype-description-service/Dockerfile` (runtime COPY + `pip install -e .`), `pyproject.toml` `[tool.setuptools.packages.find]`, `db/migrations/versions/001_identity_schema.py` (`EXPECTED_SCHEMA_TABLES`, `upgrade`), `scripts/verify_identity_schema.py`, `db/base.py` (`Base`), `db/models/__init__.py`, `docker-compose.env.yml`.
- **Handoff**: E15-29 decisions 1194 (schema drift + rollback), 1197 (admin + mint), blocker 10 (resolved); `MAINT-SCENE-DEPLOY-PKG` decision 1196 (scene fix).

## Contract and Boundary Impact

| Boundary | Owner | Current | Expected change | Compatibility | Verification |
| --- | --- | --- | --- | --- | --- |
| Deploy CLI | `recognition-service.sh` | image-only restart + post-hoc verify | converge compose+unit; pre-promote boot smoke; drift gate | additive flags; default-on | new `deploy prod` run over VM shows compose/unit/schema converged + smoke-before-promote |
| Container entrypoint | `Dockerfile` CMD | `alembic upgrade head && verify_identity_schema && uvicorn` | insert idempotent schema self-heal before verify | additive; no-op when in sync | fresh + drifted DB both boot; verify passes |
| Image packaging | `Dockerfile` + `pyproject.toml` | manual COPY/include list | test asserts every `api.main` top-level import is packaged | none (test only) | test red on a deliberately-omitted package |

## Proposed Solution

Four independent, individually-shippable slices, ordered by outage-prevention value. Each is behavior + proof.

## Slice Delivery

### Slice 1 — Entrypoint schema self-heal (closes greenfield drift; highest recurrence risk)

**Goal**: In-place `001_identity_schema.py` additions apply to existing DBs at boot, before the fail-closed verify.

- Add `apps/prototype-description-service/scripts/sync_identity_schema.py` (`main()`): opens a sync engine from `db.settings` DSN, imports `db.models` (registers all tables on `db.base.Base.metadata`), runs `Base.metadata.create_all(engine, checkfirst=True)` (additive; never alters/drops), logs created tables. Reuses the exact mechanism used to repair prod in E15-29 (decision 1194).
- Wire it into the Dockerfile CMD **between** `alembic upgrade head` and `python -m scripts.verify_identity_schema`, so verify then passes.
- **Error path**: on any DDL error, exit non-zero (entrypoint fails closed — no worse than today's verify failure, but now self-heal is attempted first).

**Proof**: unit test seeds a DB missing one table, runs `sync_identity_schema.main()`, asserts the table exists and existing rows untouched; a second run is a clean no-op. Compose/boot test: a DB stamped at `001` but missing a table boots green after the entrypoint runs.

### Slice 2 — Packaging-completeness guard (closes `scene/`-class omissions)

**Goal**: A missing runtime package fails a test, not a prod boot.

- Add `apps/prototype-description-service/recognition/tests/deploy/test_runtime_packaging.py`: parse `api/main.py` top-level `import`/`from X import` statements for first-party top-level packages; assert each is in **both** the `Dockerfile` runtime `COPY` list and `pyproject.toml` `[tool.setuptools.packages.find].include`. Fail with the offending package name.
- Optionally assert the reverse (COPY list ⊆ actual top-level dirs) to catch typos.

**Proof**: test is green on current `main`; temporarily removing `scene/` from either list turns it red with an actionable message. Runs in `make check-all`.

### Slice 3 — Deploy-time compose+unit convergence (closes silent infra drift)

**Goal**: `make deploy-prod` guarantees the deployed `docker-compose.env.yml` + unit match the repo, or fails.

- In `recognition-service.sh` `do_restart` (or a new `converge_runtime()` called before it): before `systemctl restart`, `scp` the repo `docker-compose.env.yml` (+ prod overlay `docker-compose.admin.yml`) and re-render/install the unit from `systemd/acx-env.service.template` — i.e., fold the essential convergence of `deploy-env.sh` into the mainline deploy so it is not a separate manual step. Guard behind `ACX_CONVERGE_RUNTIME` (default `1`); `=0` preserves image-only for hotfixes.
- **Do not** reship the Caddy edge here (E15-29 hazard: a Caddy restart can drop it off `acx-demo-net`); Caddy convergence stays owned by `sync-compose.sh`/`sync-demo.sh`. Document the seam.
- Add a `deploy … --check` mode: diff deployed compose/unit vs repo and exit non-zero on drift without mutating (operator triage).

**Proof**: on a VM whose compose is intentionally stale, `deploy prod` converges it (post-check shows the `acx_blobs` volume + `RECOGNITION_BLOB_ROOT` present) and API vhosts stay green; `--check` reports drift red before any change.

### Slice 4 — Pre-promote boot smoke (stops bad images taking prod down)

**Goal**: A new image is booted and health-checked in a throwaway container **before** `:latest` is retagged/restarted.

- In `recognition-service.sh` between `do_push` and `do_restart`, add `do_boot_smoke()`: `docker run` the freshly-built `:SHA` on the VM against the target env (`--env-file`, `--network <env>-net`, `--entrypoint python … -c "import api.main"` for a fast import smoke, then a short-lived full-boot `/health` probe on an ephemeral port). Abort the promote (do not retag `:latest`, do not restart) on failure; leave the running prod untouched.
- Preserve a rollback tag before promote: `docker tag <current :latest> :rollback-<prevSHA>` (formalize the manual E15-29 step).

**Proof**: a deliberately-broken build (e.g., missing package) is caught by the smoke and the deploy aborts with prod **still serving the old image** (public `/health` never 502s); a good build promotes normally.

## Rollback Strategy

- **Slice 1**: entrypoint change is additive; if self-heal misbehaves, revert the CMD line — verify-only behavior returns. `create_all` is non-destructive, so no data rollback needed.
- **Slice 3**: `converge_runtime` backs up the prior compose/unit (`*.bak`) before overwrite; restore + `systemctl restart` on failure. `ACX_CONVERGE_RUNTIME=0` disables it entirely.
- **Slice 4**: smoke runs a throwaway container only; nothing to roll back. The `:rollback-<sha>` tag is the promote rollback.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Schema self-heal (new) | `apps/prototype-description-service/scripts/sync_identity_schema.py` | idempotent `create_all` runner |
| Entrypoint | `apps/prototype-description-service/Dockerfile` | CMD: insert `python -m scripts.sync_identity_schema` before verify |
| Packaging guard (new) | `apps/prototype-description-service/recognition/tests/deploy/test_runtime_packaging.py` | COPY/include vs `api.main` imports |
| Deploy convergence | `scripts/deploy/recognition-service.sh` | `converge_runtime()` + `do_boot_smoke()` + `--check`; call sites in `run_deploy` |
| Docs | `infra/oci/README.md` | document the converge seam + Caddy carve-out |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/deploy-env.sh` | convergence logic to fold in / reuse |
| `scripts/deploy/sync-compose.sh`, `scripts/deploy/sync-demo.sh` | Caddy edge ownership (unchanged) |
| `scripts/verify_identity_schema.py` | fail-closed gate the self-heal precedes |
| `db/base.py`, `db/models/__init__.py` | `Base.metadata` the self-heal drives |

## Verification Strategy

- **Deterministic**: `pytest` for `sync_identity_schema` (missing-table seed → created; rerun no-op) and `test_runtime_packaging` (red on omitted package); `make check-all`.
- **Runtime-parity**: on the VM (or staging if recovered), a stale-compose `deploy … --check` reports drift; a full `deploy` converges + boot-smokes + promotes; a broken build aborts pre-promote with prod green throughout.
- **Contract**: four-vhost curl matrix stays green across a convergence deploy.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded `recognition-service.sh`, `deploy-env.sh`, `Dockerfile`, `001_identity_schema.py`, `verify_identity_schema.py`, `docker-compose.env.yml`, unit template.
- [ ] Confirmed Caddy edge stays owned by `sync-compose.sh`/`sync-demo.sh` (not this task).
- [ ] Recorded deploy-CLI + entrypoint boundary ownership in slice-close decisions.

### Slice 1: Schema self-heal

- [ ] `sync_identity_schema.py` authored; additive `create_all`; logs created tables; non-zero on error.
- [ ] Dockerfile CMD runs it before `verify_identity_schema`.
- [ ] Tests: missing-table seed → created + no-op rerun; drifted-DB boot green.

### Slice 2: Packaging guard

- [ ] `test_runtime_packaging.py` cross-checks `api.main` top-level imports vs Dockerfile COPY + pyproject include.
- [ ] Green on main; red when a package is removed from either list; in `make check-all`.

### Slice 3: Compose+unit convergence

- [ ] `converge_runtime()` ships compose+overlay+unit before restart, backed up, gated by `ACX_CONVERGE_RUNTIME`.
- [ ] `deploy … --check` reports drift non-zero without mutating.
- [ ] Caddy edge explicitly not reshipped here; seam documented in `infra/oci/README.md`.

### Slice 4: Pre-promote boot smoke

- [ ] `do_boot_smoke()` boots `:SHA` in a throwaway container against target env; aborts promote on failure.
- [ ] `:rollback-<prevSHA>` tag created before promote.
- [ ] Broken-build test: deploy aborts, prod stays on old image (no public 502).

### Review Readiness

- [ ] Deploy-CLI + entrypoint changes have matching runtime-parity evidence (converge deploy + aborted-bad-build run).
- [ ] Self-heal proven additive (existing rows untouched) and idempotent.
- [ ] Handoff decisions record each slice close.

## Success Criteria

- [ ] A single `make deploy-prod` converges image + compose + unit + schema; a drifted VM ends matching the repo.
- [ ] An in-place `001_identity_schema.py` addition applies to an existing DB on deploy (no manual `create_all`).
- [ ] A missing runtime package fails `make check-all`, not a prod boot.
- [ ] A broken image is caught pre-promote; the public API never 502s from a bad deploy.
- [ ] `handoff_close_check(enforce=True)` passes; the four E15-29 drift modes cannot silently recur.
