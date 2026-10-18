# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-11 EST
> - **Author**: Claude Opus 4.8
> - **Project**: `apps/prototype-description-service` (description-service, Python)
> - **Task ID / Work Ref**: `SECRETS-P2`
> - **Parent MAINT task**: `MAINT-secrets-consolidation-20260708`
> - **Target Branch**: `feature/maint-secrets-consolidation-20260708`
> - **Depends on**: `SECRETS-P1` (Phase 1 — allowlist retired, `.env` hygiene, load-time validation). Phase 2 must land **after** P1.
> - **Review Coverage Target**: 2
>
> Review counts and finding totals are DB-owned; query live via `list_review_runs(task_ref="SECRETS-P2")` / `review_findings(review={"operation":"list","status":"open","task_ref":"SECRETS-P2"})`.

---

## SECRETS-P2. SecretProvider seam for the description-service

## Objective

Introduce a `SecretProvider` port (`get_secret(name) -> str`, with a not-found failure mode) plus a default `EnvSecretProvider` adapter in the description-service, and route **every** service secret read through it so no `os.getenv`/`os.environ` reads a secret outside the provider. This is a **pure refactor with zero behavior change** ([REF-05]): the seam lets Phase 3 swap an `OciVaultSecretProvider` behind it without touching a single consumer.

## Intake

- **Scope one-pager**: `docs/scopes/secrets-consolidation.md` (Phase 2 section).
- **Key decision**: scope-intake decision `#1882` (read live via `search_handoff`); intake decision `#1717` (`claude_scope_intake_secrets_consolidation`).
- **Not-Doing** (confirmed in scope): the OCI Vault backend itself (Phase 3); the WP plugin (its tenant key is a WP option `acx_recognition_api_key`, **not** fetched from Vault — plugin is out of the seam entirely); any secrets manager for local dev (env stays); any provider registry / backend-selection wiring (`RECOGNITION_SECRET_BACKEND` selection is Phase 3 — [REF-12] YAGNI, one adapter today).

## Problem Statement

Secret reads are scattered across the service as inline `os.getenv`/`os.environ` calls inside pydantic `default_factory` lambdas and `@lru_cache`d settings factories — DB credentials in `db/settings.py`, the admin root-of-trust token in `recognition/config/security.py`, GPU/hosted-provider API keys in `scene/`, and an eval API key in offline tooling. Every one is a hard-coded call to `os` — a forfeited seam ([REF-15]). There is no single insulation point at which a production backend (OCI Vault) could supply secrets, so Phase 3 cannot swap the source without editing each consumer. Phase 2 creates that seam once, with zero behavior change, so Phase 3 is a backend addition rather than a scatter-gather rewrite.

## Constraints

- **Plugin boundary**: edits are confined to `apps/prototype-description-service/**` and `docs/**`. The WP plugin (`apps/prototype-wp-alt-context/`) is **not touched** — its tenant key is a WordPress option, never a Vault/provider secret ([scope §Phase 2]).
- **Zero behavior change** ([REF-05] two hats): each migration slice is a pure refactor. No new env var, no changed default, no altered resolution order. The full test suite is green **before and after** every slice — that green-to-green invariant is the proof of zero behavior change.
- **Scope the seam to secrets only** ([REF-16] don't leak, [REF-12] YAGNI): only credentials/tokens/keys route through the provider. Non-secret config (ports, feature flags, model names, pool sizes, header names, DB host/user/name, timeouts) keeps reading `os.getenv` directly. Over-migrating non-secrets would leak config-plumbing into the secrets seam.
- **Minimal port** ([REF-18] deep module): the port surfaces one abstract method (`get_secret`); the optional/defaulted read convenience is a concrete base method, so an adapter (env today, Vault tomorrow) implements exactly one method. Complexity is pulled down into the base ([REF-21]).
- **`SECRETS-P1` landed first**: `RECOGNITION_ALLOWED_API_KEYS` (`security.py:61` `dev_api_keys`) is **removed by P1** and is therefore **not** migrated here. If P1 has not landed, stop and resolve the dependency before starting.
- **Preserve DSN side effects**: `db/settings.py` writes the resolved DSN back to `os.environ` (`db/settings.py:223,235`) as a documented side effect consumed by Alembic (`db/migrations/env.py`). The migration changes only the **read** of the secret; the write-back and every non-secret read stay byte-for-byte.

## Workflow Principles

- **Characterization before change** ([TEST-03], [TEST-01]): before touching any secret read, pin the current observable behavior of its settings factory with a test asserting the value it resolves today (actual, not intended). Only then swap the read.
- **Find the seam** ([TEST-04]): the injection point is a module-level accessor `get_secret_provider()` (default `EnvSecretProvider` singleton) overridable via `set_secret_provider(...)` — the object seam tests and Phase 3 use to substitute a fake/Vault provider. This mirrors the existing `get_security_settings()` / `get_database_settings()` accessor convention ([NAME-04] consistency).
- **One cohesive group per slice** ([AGT-05] one-intent diffs): DB creds, then the admin token, then scene/tooling keys — each its own reviewable slice with its own green suite.
- **Watch it fail once** ([TEST-06]): the not-found path and each characterization test must be observed failing with the predicted message before being made to pass.

## Terminology

- **Secret**: a value that grants authority or access — a credential, token, API key, or DSN carrying embedded credentials. Contrast with *config* (ports, flags, model names, timeouts, header names), which is non-secret and stays on `os.getenv`.
- **Port** (`SecretProvider`): the minimal interface the service depends on to fetch a secret by name.
- **Adapter** (`EnvSecretProvider`): the default implementation reading process environment. Phase 3 adds `OciVaultSecretProvider` behind the same port.
- **Provider accessor** (`get_secret_provider`): the module-global seam returning the active provider; the single substitution point.

## Current State Analysis

- **Works today**: every secret resolves from the environment via inline `os` calls inside settings factories. Behavior is correct; the problem is purely structural (no seam).
- **Enumerated secret reads** (grep-grounded — see Files and Surfaces): **7 distinct secret env vars across 8 read sites** in service source, plus the P1-removed allowlist.
- **Misleading / notable**:
  - `APP_PGUSER` / `APP_PGPASSWORD` appear **only** in `.env.example:28-29` as `${PGUSER}`/`${PGPASSWORD}` aliases and in a test asserting that example content (`recognition/tests/unit/test_database_settings.py:102-103`). They are **never read** via `os.getenv` in service Python — so despite the scope table naming `APP_PG*`, there is no service-Python read site to migrate. Do not invent one.
  - `db/settings.py:_render_default_async_dsn`/`_render_default_sync_dsn` mix a secret (`PGPASSWORD`) with non-secrets (`PGUSER`/`PGHOST`/`PGPORT`) in one f-string. Only the password moves to the provider; the rest stay on `os.getenv` ([REF-16] scope the seam). Post-migration these functions read from two sources — that is correct and intended.
  - `db/settings.py` mutates `os.environ["POSTGRES_DSN"]`/`["POSTGRES_SYNC_DSN"]` (`:223,235`) after resolving. This side effect is load-bearing for Alembic and **must be preserved** by the migration.
  - `RECOGNITION_ALLOWED_API_KEYS` (`security.py:61`) is a P1 deletion — absent by the time this task runs.

## Target Outcome

A new dependency-free module `shared/secrets.py` exposes `SecretProvider` (ABC, one abstract `get_secret`), `EnvSecretProvider` (default), `SecretNotFound` (the not-found failure mode), and the `get_secret_provider()` / `set_secret_provider()` accessor seam. Every secret read in `db/settings.py`, `recognition/config/security.py`, `scene/config/settings.py`, `scene/infrastructure/provider/hosted_provider_adapter.py`, and `scripts/eval_harness/cli.py` resolves through `get_secret_provider()`. A guard test proves no secret env var is read via `os.getenv`/`os.environ` anywhere outside the provider module. The full suite is green; no runtime behavior differs from before the task. Phase 3 can register an `OciVaultSecretProvider` via `set_secret_provider` with zero consumer edits.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Heuristics (authoritative, current): `docs/reference/engineering-heuristics-canon.md` — cite rules by stable ID (`REF-15`, `REF-05`, `TEST-03`). This is the canonical lexicon; ignore any stale `docs/workbay/rules/engineering-heuristics.md`.
- Scope: `docs/scopes/secrets-consolidation.md` (Phase 2 + Testability + Not-doing).
- Heuristics cited: [REF-15] ports & adapters, [REF-05] two hats, [REF-18] deep modules, [REF-21] pull complexity down, [REF-12] YAGNI, [REF-16] leaky abstraction, [TEST-03] characterization, [TEST-04] find the seam, [TEST-06] watch it fail, [NAME-04] consistency.
- Handoff/MCP: decisions `#1882`, `#1717`; task ref `SECRETS-P2` (findings queried live). Confirm `SECRETS-P1` is merged before starting.
- Existing accessor pattern to mirror: `recognition/config/security.py:88` `get_security_settings()`, `db/settings.py:210` `@lru_cache get_database_settings()`.

## Contract and Boundary Impact

> This task is **internal to the description-service**. It introduces no cross-service, cross-language, or tool/client contract change. The WP plugin boundary is **untouched**. No HTTP schema, REST contract, or wire format changes. The only new surface is an in-process Python module (`shared/secrets.py`) consumed by the same service's own settings factories.

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Service ↔ WP plugin | backend / plugin | `acx/v1/` REST; plugin key is a WP option | `none` | no — plugin not touched | existing API tests unchanged |
| Service ↔ Postgres | backend | DSN/creds from env | `none` (same DSN resolved; only the read path is insulated) | no | `test_database_settings` green |
| Internal secret access | backend | scattered `os.getenv` | new in-process `SecretProvider` seam | no — greenfield internal module | new unit tests + guard test |

## Proposed Solution

Five slices. Slice 1 builds and unit-tests the port + adapter + seam (a real, usable, tested unit — not scaffold). Slices 2–4 migrate the secret reads one cohesive group per slice, each preceded by characterization tests ([TEST-03]) and each proven by a green full suite ([REF-05]). Slice 5 adds the guard test that locks the seam closed. The port stays minimal ([REF-18]); no backend-selection logic ships (Phase 3, [REF-12]).

## Files and Surfaces to Change

**Secret read sites migrated (grep-verified — 7 distinct secret vars, 8 read sites):**

| # | Secret env var | Read site(s) | Slice |
| --- | --- | --- | --- |
| 1 | `POSTGRES_DSN` | `db/settings.py:216` (write-back at `:223` preserved) | 2 |
| 2 | `POSTGRES_SYNC_DSN` | `db/settings.py:228` (write-back at `:235` preserved) | 2 |
| 3 | `PGPASSWORD` | `db/settings.py:127`, `db/settings.py:139` | 2 |
| 4 | `RECOGNITION_ADMIN_TOKEN` | `recognition/config/security.py:75` | 3 |
| 5 | `ACX_GPU_ENDPOINT_API_KEY` | `scene/config/settings.py:56` | 4 |
| 6 | `ACX_HOSTED_PROVIDER_API_KEY` | `scene/infrastructure/provider/hosted_provider_adapter.py:51` | 4 |
| 7 | `ACX_EVAL_API_KEY` | `scripts/eval_harness/cli.py:336` (offline tooling) | 4 |

> `RECOGNITION_ALLOWED_API_KEYS` (`security.py:61`) is removed by `SECRETS-P1` — **not** migrated. `APP_PG*` has no service-Python read site — **not** migrated.

**New / edited files:**

| Surface | File | Change |
| --- | --- | --- |
| backend (new) | `apps/prototype-description-service/shared/secrets.py` | `SecretNotFound(RuntimeError)`; `SecretProvider` (ABC, abstract `get_secret(name: str) -> str`; concrete `get_secret_optional(name, default=None) -> str \| None` via try/except); `EnvSecretProvider(get_secret → os.environ[name] else raise SecretNotFound)`; module-global `get_secret_provider()` (lazy default `EnvSecretProvider` singleton) + `set_secret_provider(p)` / `reset_secret_provider()` seam. Depends on stdlib only — no import of `recognition`/`scene`/`db` (keeps `shared/` cycle-free, as it is today). |
| tests (new) | `apps/prototype-description-service/recognition/tests/unit/test_secret_provider.py` | port/adapter unit tests: present→value; absent→`SecretNotFound` (predicted message, [TEST-06]); `get_secret_optional` returns default when absent and `""` when env is set-empty (mirrors `os.getenv` semantics); `set_secret_provider` swaps a fake and `reset_secret_provider` restores. |
| backend | `apps/prototype-description-service/db/settings.py` | `_render_default_async_dsn`/`_render_default_sync_dsn`: `PGPASSWORD` read via `get_secret_provider().get_secret_optional("PGPASSWORD", DEFAULT_PGPASSWORD)`. `get_database_settings`: `POSTGRES_DSN`/`POSTGRES_SYNC_DSN` reads via `get_secret_optional(...)`; **preserve** the `os.environ[...] =` write-backs and all `PGUSER`/`PGHOST`/`PGPORT`/`DB_*` non-secret reads. |
| backend | `apps/prototype-description-service/recognition/config/security.py` | `admin_token` field factory: `get_secret_provider().get_secret_optional("RECOGNITION_ADMIN_TOKEN", "")`. Non-secret fields (`api_key_header`, hash algo, header, rate limits, origins, `admin_enabled`, `admin_header`) unchanged. |
| backend | `apps/prototype-description-service/scene/config/settings.py` | `gpu_endpoint_api_key` factory via `get_secret_optional("ACX_GPU_ENDPOINT_API_KEY")` (preserve `or None`). |
| backend | `apps/prototype-description-service/scene/infrastructure/provider/hosted_provider_adapter.py` | `api_key` read via `get_secret_optional("ACX_HOSTED_PROVIDER_API_KEY", "")`. |
| backend | `apps/prototype-description-service/scripts/eval_harness/cli.py` | `api_key` read via `get_secret_optional("ACX_EVAL_API_KEY", "")`. |
| tests (new) | `apps/prototype-description-service/recognition/tests/unit/test_no_raw_secret_reads.py` | guard: walk service source, assert no `os.getenv`/`os.environ[...]`/`os.environ.get` reads a name in the SECRET allowlist outside `shared/secrets.py` and tests. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/shared/__init__.py` | existing cycle-free `shared` package (only `health.py`) — safe neutral home importable by `db/`, `scene/`, `recognition/`, `scripts/` without a dependency cycle. |
| `db/migrations/env.py:39` | Alembic reads `POSTGRES_DSN` from `os.environ` — the write-back side effect at `db/settings.py:223,235` must remain so Alembic keeps working. |
| `recognition/tests/unit/test_database_settings.py` | existing characterization surface for DSN rendering; extend here for Slice 2. |
| `recognition/tests/unit/test_recognition_settings_env.py:19` | notes `default_factory` captures `os.environ` at construction — provider swap must preserve this evaluation timing. |
| `api/main.py:116` `_check_dev_key_guard`, `:164` `validate_production_security` | startup guards read security settings; unaffected (they consume the settings object, not the env directly for the migrated secret). |

## Verification Strategy

Run from `apps/prototype-description-service/`.

- **Deterministic tests (fast suite)** — the green-to-green invariant ([REF-05]):
  - `make test` → `uv run --locked --extra dev pytest -n 4 -m "not integration and not pg and not timing" --durations=25`. **Must be green before starting each migration slice and green after it.** A red delta on a pure-refactor slice = a behavior change and must be fixed before the slice closes.
  - Slice-scoped: `uv run --locked --extra dev pytest recognition/tests/unit/test_secret_provider.py` (Slice 1); `... test_database_settings.py` (Slice 2); the guard `... test_no_raw_secret_reads.py` (Slice 5).
- **Integration / DB-marked tests** (DSN path): `make test-integration` → `uv run --locked --extra dev pytest -m "integration or pg or timing" --durations=25` — run after Slice 2 to confirm real DB connectivity is unchanged.
- **Lint/type parity**: `make lint && make typecheck` (ruff + mypy) — the new module and every edit pass clean ([sr-001] no relaxing gates).
- **Characterization ([TEST-03])**: each migration slice adds/extends a test that pins the pre-change resolved value (observed failing first per [TEST-06]), so the swap is proven inert.
- **Guard ([TEST-04] closure)**: `test_no_raw_secret_reads.py` fails if any future edit reads a secret var outside the provider.

## Slice Delivery

### Slice 1: `SecretProvider` port + `EnvSecretProvider` adapter + seam

**Goal**: A minimal, tested secret-access port and default env adapter exist behind a swappable accessor.

Changes:
- Add `shared/secrets.py`: `SecretNotFound`; `SecretProvider` ABC (abstract `get_secret(name) -> str`; concrete `get_secret_optional(name, default=None)` calling `get_secret` and catching `SecretNotFound`); `EnvSecretProvider`; `get_secret_provider()`/`set_secret_provider()`/`reset_secret_provider()`. Stdlib-only imports.
- Add `test_secret_provider.py` covering the port/adapter/seam.

Proof:
- `uv run --locked --extra dev pytest recognition/tests/unit/test_secret_provider.py` green; not-found raises `SecretNotFound` with the predicted message ([TEST-06]); `get_secret_optional` matches `os.getenv` semantics (default-when-absent, `""`-when-set-empty); `set/reset_secret_provider` swap/restore verified.
- `make test` still green (no consumer touched yet).

### Slice 2: Migrate DB credential reads (`db/settings.py`)

**Goal**: `POSTGRES_DSN`, `POSTGRES_SYNC_DSN`, and `PGPASSWORD` resolve through the provider; DSN write-back and non-secret reads unchanged.

Changes:
- Characterization first: extend `test_database_settings.py` to pin the resolved async/sync DSN for (a) explicit `POSTGRES_DSN` set and (b) default-render path with `PGPASSWORD` set/unset, **and** assert the `os.environ["POSTGRES_DSN"]` write-back still occurs.
- Swap the three secret reads to `get_secret_provider().get_secret_optional(...)`; leave `PGUSER`/`PGHOST`/`PGPORT`/`DB_*` and the `os.environ[...] =` write-backs byte-for-byte.

Proof:
- `make test` green before and after; `make test-integration` green (real DB connect unchanged); the new characterization assertions pass with identical resolved DSNs.

### Slice 3: Migrate the admin root-of-trust token (`security.py`)

**Goal**: `RECOGNITION_ADMIN_TOKEN` resolves through the provider; all non-secret security fields unchanged.

Changes:
- Characterization first: a test pinning `SecuritySettings().admin_token` for env-set and env-unset (`""`) cases.
- Swap `admin_token` field factory to `get_secret_optional("RECOGNITION_ADMIN_TOKEN", "")`. (`RECOGNITION_ALLOWED_API_KEYS` already gone via P1 — confirm its absence, do not re-add.)

Proof:
- `make test` green before and after; admin-auth tests (`recognition/tests/api/test_admin_auth.py`) unchanged and green; characterization test confirms identical token resolution.

### Slice 4: Migrate scene provider + eval-tooling keys

**Goal**: `ACX_GPU_ENDPOINT_API_KEY`, `ACX_HOSTED_PROVIDER_API_KEY`, and `ACX_EVAL_API_KEY` resolve through the provider.

Changes:
- Characterization first: pin current resolution for each (set / unset → `None` or `""` as today).
- Swap the three reads to `get_secret_optional(...)`, preserving each site's exact default/`or None` semantics. `ACX_EVAL_API_KEY` is offline tooling but is migrated so the Slice-5 guard has zero exceptions.

Proof:
- `make test` green before and after; scene tests unchanged and green; characterization tests confirm identical resolution incl. the `or None` case for the GPU key.

### Slice 5: Seam-closure guard test

**Goal**: Prove no secret env var is read outside the provider.

Changes:
- Add `test_no_raw_secret_reads.py`: a SECRET-name allowlist (the 7 vars above) plus a walk over service source (`db/`, `recognition/`, `scene/`, `scripts/`, `api/`, `roster/`, `shared/`), asserting no `os.getenv("<SECRET>")` / `os.environ["<SECRET>"]` / `os.environ.get("<SECRET>")` occurs outside `shared/secrets.py` and `**/tests/**` (test conftest may set env to configure fixtures — that is not a production read).

Proof:
- `uv run --locked --extra dev pytest recognition/tests/unit/test_no_raw_secret_reads.py` green; observed failing first by temporarily reverting one Slice-2 read ([TEST-06]), then green.
- `make test` green.

## Consolidated Checklist

## Context and Ownership

- [ ] Confirmed `SECRETS-P1` is merged (allowlist removed, settings consolidated) before starting.
- [ ] Loaded backend-python + testing-python rules, the scope Phase-2 section, and decision `#1882`.
- [ ] Confirmed no cross-service contract or plugin file is in scope (internal-only refactor).

### Checklist for Slice 1: Port + adapter + seam

- [ ] `shared/secrets.py`: `SecretNotFound`, `SecretProvider` (one abstract method), `EnvSecretProvider`, `get_secret_provider`/`set_secret_provider`/`reset_secret_provider`; stdlib-only.
- [ ] `test_secret_provider.py`: present→value, absent→`SecretNotFound` (predicted msg), `get_secret_optional` matches `os.getenv`, swap/reset seam.
- [ ] `make test` green.

### Checklist for Slice 2: DB credentials

- [ ] Characterization test pins async/sync DSN resolution + `os.environ` write-back before the swap.
- [ ] `PGPASSWORD` (2 sites), `POSTGRES_DSN`, `POSTGRES_SYNC_DSN` read via provider; non-secret reads + write-backs preserved.
- [ ] `make test` and `make test-integration` green before and after.

### Checklist for Slice 3: Admin token

- [ ] Characterization test pins `admin_token` resolution.
- [ ] `RECOGNITION_ADMIN_TOKEN` read via provider; non-secret security fields unchanged; allowlist absence confirmed.
- [ ] `make test` + admin-auth API tests green before and after.

### Checklist for Slice 4: Scene + tooling keys

- [ ] Characterization tests pin GPU / hosted-provider / eval key resolution (incl. `or None`).
- [ ] Three reads migrated with exact default semantics preserved.
- [ ] `make test` + scene tests green before and after.

### Checklist for Slice 5: Guard

- [ ] `test_no_raw_secret_reads.py` walks service source against the SECRET allowlist, excludes `shared/secrets.py` + tests.
- [ ] Observed failing once (revert a migrated read), then green.
- [ ] `make test` green.

## Review Readiness

- [ ] Every migration slice shows a green full suite before and after (zero behavior change proven, [REF-05]).
- [ ] Each migrated read has a characterization test pinning pre-change resolution ([TEST-03]).
- [ ] Guard test locks the seam closed; no secret read remains outside the provider.
- [ ] `make lint` + `make typecheck` clean on all new/edited files.
- [ ] Handoff decision records the seam, the 7 migrated secrets, and the green-to-green evidence.

## Stretch Goals

- [ ] Docstring in `shared/secrets.py` pointing Phase 3 at `set_secret_provider` as the `OciVaultSecretProvider` registration point (doc-only; no backend code).

## Success Criteria

- [ ] `shared/secrets.py` exists with a minimal `SecretProvider` port, `EnvSecretProvider` default, and the accessor seam; unit-tested.
- [ ] All 7 secret env vars (8 read sites) resolve through the provider; `APP_PG*` and the P1-removed allowlist correctly excluded.
- [ ] `test_no_raw_secret_reads.py` passes: no secret is read via `os.getenv`/`os.environ` outside the provider.
- [ ] `make test` and `make test-integration` green — identical runtime behavior to pre-task.
- [ ] Phase 3 can register an alternate provider via `set_secret_provider` with zero consumer edits.
