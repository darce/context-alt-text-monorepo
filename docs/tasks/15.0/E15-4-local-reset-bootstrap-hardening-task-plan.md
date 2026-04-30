# E15-4. Local Reset and Bootstrap Hardening

> **Metadata**
>
> - **Date**: 2026-04-06
> - **Author**: GPT-5.4 high
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-4
> - **Target Branch**: `feature/e15-4-local-reset-bootstrap-hardening`
> - **Review Coverage Target**: 2

---

## Objective

Make the local description-service reset path work from a clean checkout without hidden manual bootstrap steps. Close the open handoff finding `INVEST-reset-env-contract-mismatch` by aligning the reset script, env template, Make targets, docs, and regression evidence around one consistent local bootstrap contract.

## Problem Statement

The local reset flow currently drifts across multiple operator surfaces. The open handoff finding `INVEST-reset-env-contract-mismatch` shows that `make reset` and `make reset-local` were failing on a fresh checkout because `reset_dev_db.sh` expected `PGUSER` and `PGPASSWORD` in `.env` while the shipped `.env.example` only documented `APP_PGUSER` and `APP_PGPASSWORD`. That mismatch turns a nominally local-only recovery path into a brittle workflow that depends on undocumented manual setup and leaves the finding open until end-to-end proof is captured.

## Constraints

- Scope is local bootstrap and reset behavior inside `apps/prototype-description-service/`; no OCI, Terraform, SSH, or remote deployment changes belong in this task.
- The direct reset script remains destructive and must keep an explicit confirmation gate; convenience in `make reset` must not silently remove safety for ad hoc script invocation.
- The fix must preserve greenfield assumptions: reset is allowed to recreate the local database rather than layering compatibility shims over stale local state.
- Verification commands for Python work should use the `description-service` pyenv environment.

## Workflow Principles

- One documented local reset contract wins; script behavior, env template, Make targets, and README guidance must all describe the same bootstrap path.
- Operator-facing docs are part of the behavior surface here. A reset flow is not complete until the copy-paste path and the code path match.
- The open handoff finding is not resolved by code alone; the task is done only when the finding can be closed with deterministic proof.

## Terminology

- **Reset contract**: The complete local operator workflow spanning `.env.example`, `.env`, `make reset`, `make reset-local`, and `scripts/reset_dev_db.sh`.
- **Bootstrap path**: The first-run path from a clean checkout to a usable local database reset without undocumented manual edits.
- **Finding closure bundle**: The code, docs, tests, and verification evidence required to mark `INVEST-reset-env-contract-mismatch` fixed.

## Current State Analysis

- `apps/prototype-description-service/scripts/reset_dev_db.sh` is the canonical local database reset entrypoint and enforces `ENV_MODE` plus `ALLOW_DEV_DB_RESET` safeguards.
- `apps/prototype-description-service/.env.example` is the checked-in local template and is the first surface a clean checkout relies on.
- `make reset` in `apps/prototype-description-service/Makefile` and the repo-root `make reset-local` both route operators into `reset_dev_db.sh`, so drift in the script/template boundary breaks both workflows.
- The open handoff finding records the original mismatch between the reset script and the env template. Even if a partial code fix exists, the task remains incomplete until the full reset contract is verified and the finding is closed with evidence.
- [dynamic-ip-ssh-access.md](../tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md) documents OCI SSH ingress drift, but that remote access issue is explicitly unrelated to the local reset/bootstrap failure and is out of scope for this task.

## Target Outcome

From a clean local checkout, an operator can follow one documented path to reset the backend database without first reverse-engineering which env variables belong in `.env`. The reset script either bootstraps from the checked-in template or fails with precise local guidance; the template exposes the variables the script and compose stack actually consume; `make reset` and `make reset-local` both exercise the same validated local contract; and the handoff finding `INVEST-reset-env-contract-mismatch` is closed with deterministic proof.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/testing-python.md`
- Context map: `docs/agentic/maps/backend.md`
- Handoff/MCP state: `AHMCP-6`, especially finding `INVEST-reset-env-contract-mismatch` and any later decision that references the local reset audit
- External docs via `ctx7` only if: none; this task is repo-local shell, Makefile, and env-contract work

## Contract and Boundary Impact

| Boundary             | Owner           | Current Contract                                                                                                                                            | Expected Change                                                   | Compatibility Needed?                                                                                                 | Verification                                                |
| -------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Local reset workflow | backend/tooling | `apps/prototype-description-service/scripts/reset_dev_db.sh`, `apps/prototype-description-service/Makefile`, `apps/prototype-description-service/README.md` | Align env bootstrap semantics and operator instructions           | Yes; direct script invocation must retain explicit destructive-action confirmation while `make reset` stays ergonomic | Script-level regression tests and manual `make reset` proof |
| Local env template   | backend/tooling | `apps/prototype-description-service/.env.example`                                                                                                           | Document the actual local variables consumed by reset and compose | Yes; preserve a clear path for customized credentials while default local bootstrap remains copy-pasteable            | Template assertions plus reset bootstrap verification       |

## Proposed Solution

Harden the local reset contract around one canonical env shape. The script should accept the variables the template publishes, the template should publish the variables the script and compose stack actually use, and the Make target should provide the correct local confirmation behavior without weakening the direct-script safety gate. Add a narrow regression test surface for env-template and DSN expansion behavior, then run the smallest realistic local reset proof needed to close the open finding.

## Files and Surfaces to Change

| Surface         | File                                                                                  | Change                                                                                     |
| --------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| backend/tooling | `apps/prototype-description-service/scripts/reset_dev_db.sh`                          | Normalize first-run `.env` bootstrap and align accepted env vars with the shipped template |
| backend/tooling | `apps/prototype-description-service/Makefile`                                         | Ensure `make reset` drives the local destructive confirmation path consistently            |
| docs/config     | `apps/prototype-description-service/.env.example`                                     | Publish the canonical local variables used by reset and docker compose                     |
| docs            | `apps/prototype-description-service/README.md`                                        | Update the local reset/bootstrap instructions to match the live behavior                   |
| docs            | `apps/prototype-description-service/scripts/README.md`                                | Clarify direct-script safety semantics versus `make reset` convenience                     |
| tests           | `apps/prototype-description-service/recognition/tests/unit/test_database_settings.py` | Add regression coverage for env-template expansion and reset prerequisites                 |

## Related Files

| File                                                       | Note                                                                                        |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/docker-compose.db.yml` | Consumes the same DB env variables as the local reset path                                  |
| `apps/prototype-description-service/db/settings.py`        | Expands env-driven DSNs and is the narrowest stable regression seam for template validation |
| `Makefile`                                                 | Repo-root `reset-local` delegates into the app-local `make reset` path                      |
| `docs/tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md` | Explicitly unrelated remote access issue; keep out of scope                                 |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && PYENV_VERSION=description-service pyenv exec python -m pytest recognition/tests/unit/test_database_settings.py -q`
- Runtime-parity / environment checks:
  - `cd apps/prototype-description-service && cp .env.example .env && ALLOW_DEV_DB_RESET=1 ./scripts/reset_dev_db.sh --help` is not applicable; use the real reset path instead
  - `cd apps/prototype-description-service && PYENV_VERSION=description-service make reset`
- Contract/fixture verification:
  - Assert `.env.example` contains the variables the reset script and compose stack consume (`PGUSER`, `PGPASSWORD`, `DB_NAME`, DSN expansions)
- Manual verification:
  - From repo root, run `make reset-local WP_PATH="<local-wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"` after backend proof succeeds, to confirm the root wrapper no longer fails on missing `.env`

## Slice Delivery

### Slice 1: Canonicalize the Local Reset Contract

**Goal**: Remove the env-shape mismatch between the reset script, Make target, and checked-in local template.

Changes:

- Align `reset_dev_db.sh` with the variables published by `.env.example`
- Preserve explicit destructive-action confirmation for direct script usage
- Make `make reset` exercise the intended local confirmation path without extra undocumented setup

Proof:

- `cd apps/prototype-description-service && pyenv activate description-service && python -m pytest recognition/tests/unit/test_database_settings.py -q`

### Slice 2: Sync Operator Docs and Bootstrap Guidance

**Goal**: Ensure every operator-facing reset instruction matches the live local contract.

Changes:

- Update README and scripts README to document the first-run bootstrap path and safety semantics
- Remove references to obsolete env keys or stale reset prerequisites
- Call out that OCI dynamic-IP SSH drift is not part of the local reset problem space

Proof:

- Manual doc-to-code audit across `.env.example`, `README.md`, `scripts/README.md`, and `reset_dev_db.sh` shows one consistent local reset path

### Slice 3: Close the Handoff Finding with End-to-End Proof

**Goal**: Capture the verification bundle needed to mark `INVEST-reset-env-contract-mismatch` fixed.

Changes:

- Run the narrowest realistic reset proof from the app directory
- Run the repo-root wrapper proof if local WordPress is available
- Update the open handoff finding with root cause, fix summary, and verification evidence

Proof:

- `cd apps/prototype-description-service && pyenv activate description-service && make reset`
- `make reset-local WP_PATH="<local-wordpress>/app/public" CONFIRM_LOCAL_RESET="RESET"`

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, backend context, and handoff finding state before editing.
- [x] Confirmed no external dependency lookup (`ctx7`) is needed.
- [x] Confirmed the task is limited to local reset/bootstrap behavior and does not overlap OCI SSH access drift.

### Checklist for Slice 1: Canonicalize the Local Reset Contract

- [x] `reset_dev_db.sh` accepts the env shape documented by `.env.example`.
- [x] `make reset` provides the intended local confirmation behavior without weakening direct script safety.
- [x] Regression coverage exists for the template and DSN expansion seam.

### Checklist for Slice 2: Sync Operator Docs and Bootstrap Guidance

- [x] README and scripts README describe the same first-run reset/bootstrap path as the live code.
- [x] `.env.example` documents the actual local variables used by reset and docker compose.
- [x] No local reset doc implies OCI, SSH, or remote-access prerequisites.

### Checklist for Slice 3: Close the Handoff Finding with End-to-End Proof

- [x] App-local `make reset` is run successfully from a clean local bootstrap state.
- [x] Repo-root `make reset-local` is rechecked when local WordPress is available.
- [x] `INVEST-reset-env-contract-mismatch` is updated to `fixed` with verification evidence recorded in MCP.

## Review Readiness

- [x] No reset/bootstrap behavior change is left without matching doc or template updates.
- [x] Verification includes both deterministic regression coverage and at least one real reset-path proof.
- [x] Handoff decision records the fix scope, verification evidence, and finding-closure status.

## Stretch Goals

- [x] Deferred: add a dedicated non-destructive preflight mode for `reset_dev_db.sh` only if repeated operator use shows the real reset proof is too heavyweight for routine validation.

## Success Criteria

- [x] A clean checkout can reach a working local reset path without manually inventing `.env` contents.
- [x] `make reset` and `make reset-local` no longer fail because of the `.env` contract mismatch captured in `INVEST-reset-env-contract-mismatch`.
- [x] The handoff finding `INVEST-reset-env-contract-mismatch` is closed as fixed with recorded proof.
