# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-11 EST
> - **Author**: Claude Opus 4.8
> - **Project**: `apps/prototype-description-service` (secrets-consolidation MAINT, Phase 1)
> - **Task ID**: `SECRETS-P1`
> - **Target Branch**: `feature/maint-secrets-consolidation-20260708`
> - **Review Coverage Target**: 2

---

## SECRETS-P1. Secrets hygiene MVP — ownership matrix, load-time validation, allowlist retirement

## Objective

Ship the no-new-infra hygiene slice of the secrets-consolidation scope: one authoritative secrets-ownership matrix, one annotated `.env.example` per deployable, load-time fail-fast on missing required secrets (rg-008), and full retirement of the static dev-key allowlist (`RECOGNITION_ALLOWED_API_KEYS`) so tenant API keys are DB-only via `/admin`. When complete, a new dev onboards with one command, every secret has one documented owner, every service errors clearly on a missing required secret, and the plaintext dev-key bypass no longer exists in any runtime path.

## Intake

- **Scope one-pager**: `docs/scopes/secrets-consolidation.md` (Phase 1 section is the source of truth for scope).
- **Key Q&A decisions**: intake `claude_scope_intake_secrets_consolidation` (decision `#1717`); operator allowlist decision (decision `#1882`) — ALLOWLIST = option (a) **remove entirely**; add `make dev-mint-key` to offset lost dev ergonomics. Both read live via `search_handoff`.
- **Carried-in finding**: `SC-R3-01` (the allowlist retirement touches four runtime sites plus a test surface; the scope doc originally missed the real auth bypass site). Referenced by id per the Review Findings Placement rule — not duplicated here.
- **Not-Doing (Phase 1 boundary / YAGNI [REF-12])**: the `SecretProvider` seam (Phase 2), the OCI Vault backend (Phase 3), any secrets manager for local dev, merging human WP accounts into the machine-key system, and re-architecting the plugin's WP-option key storage. Phase 1 introduces **no new infrastructure**.

## Problem Statement

Secrets are smeared across files with no ownership map: there is not one secrets problem but five trust domains (infra creds, service root-of-trust, tenant API keys, human accounts, test creds). Three concrete gaps block clean onboarding and rotation: (1) no documented source-of-truth per secret; (2) missing/partial `.env.example` annotations and silent empty defaults that let a service boot mis-configured instead of failing fast; (3) the static `RECOGNITION_ALLOWED_API_KEYS` dev-key bypass is a second, plaintext authentication code path alongside the DB-backed `/admin` keys. Per operator decision `#1882` the bypass is removed entirely (delete-over-flag, greenfield) rather than kept gated, leaving exactly one tenant-key authority: the service DB via `/admin`.

## Constraints

- **Plugin boundary**: edit only under `apps/prototype-description-service/`, `infra/oci/demo/`, `apps/prototype-wp-alt-context/` (env-example + gitignore surfaces only), `docs/`, and the root `.gitignore`. No WordPress core, no LocalWP, no `~/Local Sites/`.
- **Greenfield / delete-over-flag**: no back-compat shim for the removed allowlist. Removing `dev_api_keys` makes `validate_production_security()` and the `_check_dev_key_guard()` startup guard moot (there is nothing left to guard). Per decision `#1882` recommendation and [REF-20] ("define errors out of existence") they are **deleted together with their prod-block tests**, not kept as defense-in-depth.
- **Shared exception must survive**: `InsecureProductionConfigError` (`recognition/config/security.py:InsecureProductionConfigError`) is also raised by `validate_admin_config()` — delete `validate_production_security()` but **keep the exception class** and its `__all__` entry.
- **rg-008 (config validated at load time)**: required secrets fail fast with a clear message at startup; no silent empty default. The new validation must not break local dev, where the `context/context` Postgres defaults in `db/settings.py` are intentional — validation gates on `RECOGNITION_RUNTIME_MODE=production` only.
- **No new runtime dependency**: `make dev-mint-key` / `make dev-setup` wrap the existing `scripts/manage_api_keys.py` CLI; no new Python packages, no HTTP-server requirement for local minting.
- **Test creds & human accounts are doc-only** ([REF-12]): a human login is not a machine key — consolidation here is documentation + gitignore verification, not merging them into the key system.

## Workflow Principles

- **Smallest shippable cut** ([TEST-01]): each slice ships behavior plus proof and is independently reviewable; doc slices land before the code slices that depend on their decisions.
- **Watch it fail once** ([TEST-06], [AGT-03]): every new test is observed failing with the predicted message before it is made to pass; the allowlist-removal proof and the load-time-validation proof both start red.
- **No unresolved anchors** ([AGT-02]): every code site named below was grep/read-verified in this planning session.
- **Don't relitigate settled decisions** ([AGT-13]): the allowlist is removed (option a), not kept-and-gated; the decision is recorded as `#1882`.

## Terminology

- **Allowlist / dev-key bypass**: the `RECOGNITION_ALLOWED_API_KEYS` env var → `SecuritySettings.dev_api_keys` list → the `if api_key in settings.dev_api_keys` branch in `auth._lookup_api_key`. A plaintext bearer string that authenticates without a DB `api_keys` row. Retired in this task.
- **Required secret**: a secret with no safe default in production (DB password, admin token when admin enabled). Distinct from local-dev conveniences that legitimately default.
- **Deployable**: an independently deployed unit with its own env surface — description-service, `infra/oci/demo`, and the WP plugin's Playwright test-cred file.

## Current State Analysis

- **Works**: DB-backed tenant keys via `/admin` (`recognition/interface_adapters/http/routers/admin.py`) minted through `scripts/manage_api_keys.py` (`create` + `tenant create` subcommands); `SecuritySettings`/`validate_admin_config` config surface; `.env.example`, `.env.prod.example`, `infra/oci/demo/.env.example`, and `apps/prototype-wp-alt-context/.env.local.example` all already exist; `.gitignore` already ignores `.env`/`.env.*`, allowlists `!.env*.example`, and explicitly ignores `apps/prototype-wp-alt-context/.env.local` while allowlisting its `.example`.
- **Broken / drifting**: the allowlist is a live second auth path (`auth._lookup_api_key` returns `(None, None, "enterprise", True)` for any string in `dev_api_keys`); `db/settings.py` renders a `context/context@localhost` DSN with **no fail-fast** when production creds are unset (silent default, violates rg-008); `.env.example` vars carry a partial "Consumed by" note but no per-var domain / source-of-truth annotation; `.env.example:RECOGNITION_ALLOWED_API_KEYS=acx-local-dev-key` and `.env.prod.example` still document the retired var.
- **Misleading / already-clean**: the scope's "delete dead root `.env`" item is a **no-op deletion** — a root `.env` is **not tracked and not on disk** (verified: `git ls-files` and disk check both empty), and the description-service loader only reads `ENV_FILE = <service-dir>/.env` (`db/settings.py:_load_env_file`), never a repo-root `.env`. The item becomes: confirm absence + assert the gitignore guard so it cannot silently reappear.

## Target Outcome

`apps/prototype-description-service/docs/secrets-inventory.md` is the living ownership matrix for all five trust domains. Every deployable's `.env.example` annotates each var with domain + source-of-truth + consumer. In `RECOGNITION_RUNTIME_MODE=production`, the service refuses to boot with a clear message when a required secret is unset instead of falling back to a dev default. The `RECOGNITION_ALLOWED_API_KEYS` allowlist is gone from config, startup, and the auth path; a non-DB key is rejected in a prod-mode runtime. `make dev-mint-key` mints a real DB key via the CLI, and `make dev-setup` runs the whole onboarding in one command.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Heuristics (authoritative, current): `docs/reference/engineering-heuristics-canon.md` — cite rules by stable ID (`REF-15`, `SEC-06`, `rg-008`). This is the canonical lexicon; ignore any stale `docs/workbay/rules/engineering-heuristics.md`.
- Scope: `docs/scopes/secrets-consolidation.md` (Phase 1).
- Code sites (read before editing): `recognition/config/security.py`, `api/main.py`, `recognition/interface_adapters/http/deps/auth.py`, `db/settings.py`, `recognition/config/settings.py`.
- Handoff/MCP: decisions `#1717`, `#1882`; finding `SC-R3-01`. Read live via `search_handoff` / `review_findings(operation="list")`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Recognition tenant-key authentication | backend | two paths: DB `api_keys` row **or** `RECOGNITION_ALLOWED_API_KEYS` plaintext bypass (`auth._lookup_api_key`) | Remove the bypass; DB row is the sole authority | no — greenfield, prod already DB-only (bypass hard-blocked in prod today) | new auth test: non-DB key → 403 in prod-mode |
| Service startup config | backend | boots on silent `context/context` default; dev-key guards run at `create_app` | Add fail-fast on missing required secret in production; delete the now-moot dev-key guards | no | startup test: missing required secret aborts boot with clear message |
| Deployable env surface | backend / infra (in-app) | `.env.example` partially annotated; `RECOGNITION_ALLOWED_API_KEYS` documented | Per-var domain/source/consumer annotation; retired var removed from examples | no | grep: every inventory var appears in exactly one example; retired var absent |

## Proposed Solution

Five slices in dependency order. Slice 1 (docs) records the ownership decisions the later slices depend on. Slice 2 (load-time validation) and Slice 3 (allowlist retirement) are independent code+test slices. Slice 4 annotates the env examples **after** the retired var is removed in Slice 3 (no rework). Slice 5 adds the onboarding command that consumes Slice 3's `make dev-mint-key`. Each code slice starts from a red test ([TEST-06]).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| docs (new) | `apps/prototype-description-service/docs/secrets-inventory.md` | Authoritative five-domain ownership matrix; each secret: domain, owner, source-of-truth, consumer, prod target. Records test-cred + human-account ownership (doc-only). |
| config | `.gitignore` (repo root) | Confirm/keep `.env` + `.env.*` ignore with `!.env*.example` allowlist; add a comment anchoring "no repo-root `.env` — description-service reads `<service-dir>/.env` only". |
| backend | `apps/prototype-description-service/recognition/config/security.py` | Delete `SecuritySettings.dev_api_keys` field; delete `validate_production_security()`; **keep** `InsecureProductionConfigError`; drop `validate_production_security` from `__all__`. |
| backend | `apps/prototype-description-service/api/main.py` | Delete `_check_dev_key_guard()` and its call in `create_app`; remove the `validate_production_security()` call + import. Add call to the new required-secret validator in `create_app`. |
| backend | `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | Delete the bypass branch `if api_key in settings.dev_api_keys: return None, None, "enterprise", True` in `_lookup_api_key`; update the docstring's "Dev-key fallback" note. |
| backend (new fn) | `apps/prototype-description-service/db/settings.py` **or** `recognition/config/security.py` | Add `validate_required_secrets(runtime_mode: str | None = None) -> None`: in production, raise `InsecureProductionConfigError` with a named-var message when a required secret (DB password) is unset/defaulted; no-op in local/dev. |
| tests (delete) | `apps/prototype-description-service/recognition/tests/config/test_security_validation.py` | Delete entire file — all five tests target the removed `validate_production_security`. |
| tests (rewrite) | `apps/prototype-description-service/recognition/tests/api/test_rate_limiting.py` | Delete the three `_check_dev_key_guard` fail-closed tests (`test_fail_closed_guard_*`); remove the `dev_keys` param from the `_client` helper and its call sites. |
| tests (rewrite) | `apps/prototype-description-service/recognition/tests/api/test_authentication.py` | Remove `dev_api_keys=[]` kwargs (`test_lookup_api_key_*`); rewrite `test_dev_key_returns_503_when_optional_session_is_unavailable` to drop the dev-key env framing while keeping the 503-session-unavailable assertion. |
| tests (rewrite) | `apps/prototype-description-service/recognition/tests/api/test_key_rotation.py` | Remove `dev_api_keys=[]` kwargs from the `SecuritySettings(...)` constructions. |
| tests (rewrite) | `apps/prototype-description-service/recognition/tests/api/test_cors.py` | Remove the dead `monkeypatch.delenv("RECOGNITION_ALLOWED_API_KEYS", ...)` line. |
| tests (new) | `apps/prototype-description-service/recognition/tests/api/test_authentication.py` (or new module) | Add: a key with no DB `api_keys` row is rejected (403) even when a value that would formerly have matched the allowlist is presented — the bypass is gone. |
| tests (new) | `apps/prototype-description-service/recognition/tests/config/` (new module) | Add: `validate_required_secrets` aborts boot with a clear, var-named message when a required secret is unset in production; no-op in local mode. |
| config | `apps/prototype-description-service/.env.example`, `.env.prod.example` | Remove `RECOGNITION_ALLOWED_API_KEYS` lines (Slice 3); annotate every remaining var with domain/source/consumer (Slice 4). |
| config | `infra/oci/demo/.env.example`, `apps/prototype-wp-alt-context/.env.local.example` | Annotate every var with domain/source/consumer (Slice 4). |
| tooling | `apps/prototype-description-service/Makefile` | Add `dev-mint-key` target (wraps `scripts/manage_api_keys.py tenant create` + `create`); add `dev-setup` target (copies examples, prompts, invokes `dev-mint-key`). |

## Related Files

| File | Note |
| --- | --- |
| `recognition/config/security.py:validate_admin_config` | Also raises `InsecureProductionConfigError` — the reason the exception class must survive the deletion. |
| `scripts/manage_api_keys.py:_cmd_create` / `_cmd_tenant_create` | The real DB-minting path `make dev-mint-key` wraps (`create` + `tenant create` subparsers). |
| `apps/prototype-description-service/Makefile:test` / `test-integration` | Verification entry points: `uv run --locked --extra dev pytest -m "not integration and not pg and not timing"` (fast) and `-m "integration or pg or timing"` (serial). |
| `db/settings.py:_load_env_file` | Confirms `ENV_FILE = <service-dir>/.env`; a repo-root `.env` is never read (grounds the "dead root `.env`" no-op). |

## Verification Strategy

> All pytest commands run from `apps/prototype-description-service/`.

- Deterministic tests:
  - `make test` — fast unit lane (`uv run --locked --extra dev pytest -m "not integration and not pg and not timing"`). Covers the new required-secret validation test, the new bypass-removed auth test, and the rewritten config/auth tests.
  - `make test-integration` — serial lane (`-m "integration or pg or timing"`); the `@pytest.mark.timing` key-rotation cases live here.
  - `make check` — full gate (`lint typecheck test test-integration`) before slice close.
- rg-008 proof (Slice 2): run the new `validate_required_secrets` test and **watch it fail first** ([TEST-06]) with the predicted var-named message, then pass.
- Allowlist-removed proof (Slice 3): run the new auth test asserting a non-DB key → 403 in prod-mode; confirm `grep -rn "dev_api_keys\|RECOGNITION_ALLOWED_API_KEYS" recognition/ api/ --include=*.py` returns **only** intentional test references (or zero) after the sweep.
- Env-annotation proof (Slice 4): for every var listed in `secrets-inventory.md`, assert it appears in exactly one deployable `.env.example` with its annotation; assert `RECOGNITION_ALLOWED_API_KEYS` is absent from all examples.
- Root `.env` proof (Slice 1): `git ls-files | grep -c '(^|/)\.env$'` → `0`; `test ! -e .env`.
- Onboarding proof (Slice 5): `make dev-mint-key` prints a raw key resolvable by `manage_api_keys.py list`; `make dev-setup` runs end-to-end against a local DB and mints a usable key.

## Slice Delivery

### Slice 1: Secrets-ownership matrix + root `.env` retirement + doc-only ownership

**Goal**: One authoritative ownership matrix exists; the dead root `.env` is confirmed absent and guarded; test-cred and human-account ownership is documented.

Changes:
- Create `apps/prototype-description-service/docs/secrets-inventory.md`: the five-domain table (infra, service root-of-trust, tenant API keys, human accounts, test creds), each secret annotated with domain / owner / source-of-truth / consumer / prod target. Record that tenant keys are DB-only via `/admin` (allowlist retired), that `ACX_E2E_WP_ADMIN_*` test creds live in gitignored `apps/prototype-wp-alt-context/.env.local` (example shipped), and that human accounts (`WP_ADMIN_*`, `acx-demo-admin`) live in the WordPress user store / demo bootstrap and are never committed.
- Confirm no repo-root `.env` is tracked or on disk; add an anchoring comment near the `.env` rules in root `.gitignore` noting the description-service reads `<service-dir>/.env` only.

Proof:
- `git ls-files | grep -c '(^|/)\.env$'` → `0`; `test ! -e .env` passes.
- `secrets-inventory.md` lists every var surfaced by `grep -rhoE 'RECOGNITION_[A-Z_]+|APP_PG[A-Z]+|PG[A-Z]+|ACX_E2E_WP_ADMIN_[A-Z]+|WP_ADMIN_[A-Z]+'` across the deployable examples.

### Slice 2: Load-time required-secret validation (rg-008)

**Goal**: In production, a missing required secret aborts boot with a clear, var-named message instead of a silent dev default.

Changes:
- Add `validate_required_secrets(runtime_mode: str | None = None) -> None` (raising `InsecureProductionConfigError`) that, when `runtime_mode == "production"`, refuses to boot if the DB password resolves to the `context/context` dev default or is unset — naming the offending env var in the message. No-op in local/development.
- Call it from `api/main.py:create_app` at startup (alongside `validate_admin_config`).

Proof:
- New config test: assert the validator raises with the predicted var-named message when the required secret is unset in production, and is a no-op in local mode. **Watch it fail once** ([TEST-06]) before wiring the call, then `make test` green.

### Slice 3: Retire the allowlist (four runtime sites + test surface) + `make dev-mint-key`

**Goal**: The `RECOGNITION_ALLOWED_API_KEYS` dev-key bypass no longer exists in any runtime path; DB keys via `/admin` are the sole tenant-key authority; lost dev ergonomics are offset by `make dev-mint-key`.

Changes (the four verified sites, per finding `SC-R3-01`):
1. `recognition/config/security.py` — delete `SecuritySettings.dev_api_keys`; delete `validate_production_security()`; **keep** `InsecureProductionConfigError`; drop `validate_production_security` from `__all__`.
2. `api/main.py` — delete `_check_dev_key_guard()` and its `create_app` call; remove the `validate_production_security()` call + import.
3. `recognition/interface_adapters/http/deps/auth.py` — delete the bypass branch in `_lookup_api_key` (`if api_key in settings.dev_api_keys: return None, None, "enterprise", True`); update the docstring's dev-key-fallback note.
4. Env examples — remove `RECOGNITION_ALLOWED_API_KEYS` from `.env.example` and `.env.prod.example`.
- Tests: delete `test_security_validation.py`; delete the `test_fail_closed_guard_*` tests and the `dev_keys` helper param in `test_rate_limiting.py`; strip `dev_api_keys=[]` kwargs from `test_authentication.py` and `test_key_rotation.py`; rewrite `test_dev_key_returns_503_...` to drop dev-key framing; remove the dead `delenv` in `test_cors.py`. Add a new test: a non-DB key is rejected (403) in a prod-mode runtime (bypass gone).
- Add `make dev-mint-key` wrapping `scripts/manage_api_keys.py tenant create` + `create` against the local DB, printing the raw key once.

Proof:
- New auth test (non-DB key → 403 in prod-mode) — **watch it fail** against the current bypass first, then pass after removal ([TEST-06], [AGT-03]).
- `grep -rn "dev_api_keys\|RECOGNITION_ALLOWED_API_KEYS" recognition/ api/ --include=*.py` returns only intentional references (target: zero in runtime code).
- `make test` + `make test-integration` green.
- `make dev-mint-key` prints a key that `manage_api_keys.py list` resolves.

### Slice 4: Annotate `.env.example` per deployable

**Goal**: Every deployable env template documents each var's domain, source-of-truth, and consumer — matching the inventory, with the retired var already gone.

Changes:
- Annotate every var in `apps/prototype-description-service/.env.example`, `.env.prod.example`, `infra/oci/demo/.env.example`, and `apps/prototype-wp-alt-context/.env.local.example` with `# domain: <n> | source: <owner> | consumer: <who reads it>`, cross-referenced to `secrets-inventory.md`.

Proof:
- For each var in `secrets-inventory.md`, assert it appears in exactly one deployable example carrying its annotation; assert `RECOGNITION_ALLOWED_API_KEYS` is absent from all examples.

### Slice 5: `make dev-setup` onboarding command

**Goal**: One command onboards a new dev end-to-end.

Changes:
- Add `make dev-setup` (description-service Makefile): copy `.env.example` → `.env` if absent, prompt for/echo the values a dev must set, then invoke `make dev-mint-key` (Slice 3) to mint a usable DB key. Idempotent — safe to re-run.

Proof:
- On a clean checkout with a local DB up, `make dev-setup` produces a working `.env` and a mintable key; re-running does not clobber an existing `.env`.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the scope Phase 1 section, `backend-python-guidelines.md`, `testing-python.md`, decisions `#1717`/`#1882`, and finding `SC-R3-01` before editing.
- [ ] Recorded tenant-key-auth, startup-config, and env-surface boundary ownership; confirmed no external client depends on the retired allowlist.

### Checklist for Slice 1: Ownership matrix + root `.env` retirement

- [ ] `apps/prototype-description-service/docs/secrets-inventory.md` created with all five trust domains and per-secret domain/owner/source/consumer/prod-target.
- [ ] Root `.env` confirmed absent (`git ls-files` + disk); `.gitignore` anchoring comment added.
- [ ] Test-cred (`ACX_E2E_WP_ADMIN_*`) and human-account (`WP_ADMIN_*`, `acx-demo-admin`) ownership documented; `.env.local` gitignore + shipped `.env.local.example` verified.

### Checklist for Slice 2: Load-time required-secret validation

- [ ] `validate_required_secrets` added, raising `InsecureProductionConfigError` with a var-named message; no-op in local/dev.
- [ ] Wired into `api/main.py:create_app`.
- [ ] New config test watched-fail-then-pass; `make test` green.

### Checklist for Slice 3: Retire the allowlist + `make dev-mint-key`

- [ ] `security.py`: `dev_api_keys` + `validate_production_security` deleted; `InsecureProductionConfigError` kept; `__all__` updated.
- [ ] `api/main.py`: `_check_dev_key_guard` + call + `validate_production_security` call/import removed.
- [ ] `auth.py`: `_lookup_api_key` bypass branch deleted; docstring updated.
- [ ] Test surface: `test_security_validation.py` deleted; fail-closed-guard tests + `dev_keys` helper param removed; `dev_api_keys=[]` kwargs stripped; `test_dev_key_returns_503_...` rewritten; `test_cors.py` dead `delenv` removed.
- [ ] New auth test: non-DB key → 403 in prod-mode (bypass gone), watched-fail-then-pass.
- [ ] `make dev-mint-key` added and verified against a local DB.
- [ ] `make test` + `make test-integration` green.

### Checklist for Slice 4: Annotate `.env.example` per deployable

- [ ] All four deployable examples annotate every var with domain/source/consumer.
- [ ] `RECOGNITION_ALLOWED_API_KEYS` absent from all examples; every inventory var present in exactly one example.

### Checklist for Slice 5: `make dev-setup`

- [ ] `make dev-setup` copies examples, prompts, mints a dev key via `make dev-mint-key`; idempotent.

## Review Readiness

- [ ] No boundary-touching change without matching test/doc evidence (allowlist removal ↔ new prod-mode auth test; startup config ↔ required-secret test; env surface ↔ inventory grep).
- [ ] rg-008 and allowlist-removal tests were each observed failing with their predicted messages before passing.
- [ ] Handoff decision records each slice, its verification, and the allowlist-removal contract change.

## Success Criteria

- [ ] `secrets-inventory.md` documents one owner + source-of-truth per secret across all five trust domains.
- [ ] Every deployable `.env.example` annotates each var; no repo-root `.env`; retired var gone from examples.
- [ ] In `RECOGNITION_RUNTIME_MODE=production`, a missing required secret aborts boot with a clear, var-named message.
- [ ] `RECOGNITION_ALLOWED_API_KEYS` / `dev_api_keys` exist in no runtime path; a non-DB key is rejected (403) in a prod-mode runtime.
- [ ] `make dev-mint-key` mints a usable DB key; `make dev-setup` onboards a new dev in one command.
