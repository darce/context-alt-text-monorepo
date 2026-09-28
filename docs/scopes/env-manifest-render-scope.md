# Scope: Env manifest + deterministic renderer (ENVMAN-1)

> **Date:** 2026-09-27
> **Status:** scoped; plan at [0003-envman-1-env-manifest-render-task-plan.md](../plans/0003-envman-1-env-manifest-render-task-plan.md)
> **Origin:** APP-1 decision 13960 (proposal); operator ask "centralize the .env files … and have them auto build, like the harnesses materialize".
> **Intake note:** operator directed continuation without further questions; open points are resolved below as explicit assumptions (A-n), each citing canon.

## Problem

One fact lives in many files and formats [REF-26]. Today:

| File | Kind | Lines |
|---|---|---|
| `apps/prototype-description-service/.env.example` | template | 95 |
| `apps/prototype-description-service/.env.prod.example` | template (prod/staging/dev) | 261 |
| `apps/prototype-description-service/.env.fir.example` | template (dev-fir) | 201 |
| `infra/oci/demo/.env.example` | template | 84 |
| `apps/prototype-wp-alt-context/.env.local.example` | template | 33 |
| `apps/app-portal/.env.example`, `infra/oci/app/env.example` | templates (APP-1 branch only) | — |
| service `.env`, app-portal `.env.local`, wp `.env.local` | hand-edited runtime (local) | — |
| `/opt/acx-backend/<env>/.env`, `/opt/acx-backend/prod/app-portal.env` | hand-edited runtime (VM) | — |

Rotating the DB password means editing `POSTGRES_PASSWORD`, `POSTGRES_DSN` and `POSTGRES_SYNC_DSN` by hand ([secrets-inventory.md § Rotation](../../apps/prototype-description-service/docs/secrets-inventory.md)) — derived data that drifts [REF-09]. The Clerk values span backend and portal files. Nothing checks templates against each other.

Existing seams this reuses, not replaces: `shared/secrets.py` `SecretProvider` (ADR-013; prod already reads secrets from OCI Vault), the ownership matrix in `secrets-inventory.md`, the `make check-agent-workflows` generate/check pattern, and the strict-loader contract of `config/estate.yaml` [rg-008].

## MVP (Phase A — this task)

1. **Manifest** `config/env/manifest.d/*.toml`: one `targets.toml` plus per-group var fragments. Each var declares `class` (`public` | `config` | `secret`), `targets`, `section`, `doc`, `example`, per-env `values` (non-secret) or per-env `secret` refs (secret), or `derive` (`${VAR}` template, e.g. DSNs from PG parts).
2. **Strict loader** `scripts/env/manifest.py`: refuses unknown/missing/wrong-type keys, duplicate names across fragments, unknown targets, derive cycles, and every secret-into-public path (see Guard) [rg-008, SECD-05].
3. **Secret refs** `scripts/env/secrets.py`: `keychain:<service>/<account>` (macOS `security`) and `env:<NAME>` (CI). Fail closed; errors name the var and scheme, never the value.
4. **Renderer** `scripts/env/render_env.py` + `mk/env.mk`:
   - `make env-render ENV=local TARGET=svc-local` writes the runtime file: generated header, 0600, atomic replace, symlink refused (matches deploy's O_NOFOLLOW rule).
   - `make env-check` byte-compares every committed template against its rendered example (CI, no secrets needed); wired into `check-all`.
   - First adoption of a hand-edited file requires `--adopt` (backup `<path>.pre-envman`, 0600) and refuses unmanaged keys unless listed.
5. **Guard** (load time, not render time): a `public_build` target (any `VITE_*` consumer) refuses `class=secret`, derived-from-secret vars, names matching the secret denylist, and literal secret shapes (`sk_test_`, `sk_live_`, `rk_`, `whsec_`, PEM) anywhere in values/examples. Lifts the intent of APP-1's `configure_clerk_production.py` boundary and APP-1 finding 15951 (secret carried into frontend env by a merge).
6. **Migration**: the five committed templates on `main` become generated artifacts of the manifest; `svc-local` and `wp-e2e` runtime files become renderable locally.

## Assumptions (resolved without operator input)

- **A-1 TOML, not YAML.** `tomllib` is stdlib (Python ≥3.11) so the renderer runs in any `python3` — laptop, VM host, lane sandbox — with zero deps [REF-21]. The proposal said YAML; the format is not load-bearing.
- **A-2 Fragments, not one file.** `manifest.d/` lets parallel lanes own disjoint files; the loader merges them in sorted filename order, so output stays deterministic.
- **A-3 Keychain for local secrets; sops/age deferred.** One local store is enough for one operator [YAGNI]; `env:` covers CI.
- **A-4 Examples show placeholders only.** Example mode never emits a real value, public or secret, so templates never leak environment identity.
- **A-5 Per-target digest in the header, no timestamp.** Editing one target does not dirty the others; output is byte-stable.
- **A-6 Phase split on APP-1.** `apps/app-portal/`, `infra/oci/app/`, `scripts/deploy/app-portal.sh` and `configure_clerk_production.py` exist only on `feature/app-1`. Everything touching them is Phase B.

## Phase B (ENVMAN-2 — after APP-1 merges; not this task)

- `app-portal-local` and `app-portal-build` (`public_build`) targets; VITE_* passed as build args to the VM build; delete `/opt/acx-backend/prod/app-portal.env` and the writer in `configure_clerk_production.py`.
- `vault:` refs: prod/staging render ships a config-only `.env` whose secrets stay in OCI Vault via `RECOGNITION_VAULT_SECRET_MAP`; deploy integration (`recognition-service.sh`) ships the rendered file.
- Demo VM runtime render.

## Success criteria → evals

Each criterion is a pytest case in `scripts/env/tests/` (this consumer repo has no `config/evals/` registry; the suite is the eval).

| # | Criterion | Eval |
|---|---|---|
| S1 | Loader refuses every malformed manifest class listed in the plan's contract | `test_manifest_loader.py` |
| S2 | No path renders a secret into a `public_build` target | `test_manifest_loader.py::*guard*` |
| S3 | Same manifest → byte-identical output across runs and fragment order | `test_render.py::*determinism*` |
| S4 | Runtime files are 0600, atomic, refuse symlinks, refuse un-headed files without `--adopt` | `test_render.py` |
| S5 | `check` exits 1 on drift and never prints a secret value | `test_render.py::*check*` |
| S6 | Missing secret fails closed naming var + scheme only | `test_secret_resolvers.py` |
| S7 | All five committed templates equal their rendered examples | `make env-check` (in `check-all`) |
| S8 | Rotating the DB password is one Keychain edit + one `make env-render` (DSNs derived) | `test_render.py::*derive*` + runbook |

## Not doing

- No SQLite/DB store: not diffable, adds a second plaintext secret copy (rejected in 13960).
- No secret values in git, ever — not encrypted, not in examples.
- No change to `SecretProvider` or how services read env at runtime; this only produces the files they already read.
- No VM writes, deploy-script changes or prod render in Phase A.
- No WP plugin API key handling (WP option, out of the env seam per secrets-consolidation scope).
- No sops/age, no 1Password/Vault CLI for local.

## Canon

[REF-26] one fact, many formats → single source. [REF-09] derived DSNs drift → derive on render. [rg-008] validate config at load time. [SECD-05] fail-safe default: refuse, never emit. [REF-21] pull complexity into the generator so consumers don't carry it.
