# E15-12. Standard Deployment Reset Workflow and Recognition Source Selector

> **Metadata**
>
> - **Date**: 2026-05-01
> - **Author**: Codex GPT-5
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-12
> - **Target Branch**: `feature/e15-12`
> - **Review Coverage Target**: 2

---

## Objective

Make deployment-state management and backend targeting explicit for day-to-day development. After this task, operators can deploy code to OCI dev with one documented workflow, intentionally reset the local and remote database state with matching safeguards, and choose from the WordPress admin whether the plugin should talk to the hosted description service or to the local development service.

## Intake

- **Scope one-pager**: [docs/scopes/e15-12-deploy-reset-and-recognition-source-scope.md](../../scopes/e15-12-deploy-reset-and-recognition-source-scope.md)
- **Not-Doing**: automatic deploy-time resets, transport-mode redesign, production data migration/preservation workflows, and any attempt to hide destructive reset semantics

## Problem Statement

The current deploy path is only half standardized. `mk/deploy.mk` and `scripts/deploy/recognition-service.sh` can build, push, restart, and liveness-check OCI environments, but there is no first-class reset command for rebuilding remote dev state. At the same time, the plugin still resolves `http://localhost:8000` through an implicit fallback path instead of an explicit operator choice, so a local developer cannot cleanly say "use local" versus "use the hosted description service" from the admin UI.

Those gaps now interact. A developer validating OCI deploys, local resets, and plugin behavior needs an honest contract for each environment: when state is wiped, how services come back, what verification proves readiness, and how the plugin should target local versus hosted recognition at each stage.

## Constraints

- Scope spans `mk/`, `scripts/deploy/`, `apps/prototype-description-service/` operator docs, and `apps/prototype-wp-alt-context/` settings/runtime surfaces. Terraform, OCI control-plane resources, and Caddy routing are out of scope unless a doc update is required for accuracy.
- Reset remains destructive by design. This is a greenfield project; the workflow should prefer clear rebuild semantics over preservation-only compatibility shims.
- Remote reset must not mutate a live environment in place. The task must define explicit stop/reset/start ownership for the selected OCI environment.
- Deployment verification must distinguish liveness from readiness. `/health` can remain the fast liveness probe, but destructive reset completion requires `/ready` plus one plugin-facing connectivity proof.
- The recognition source selector must stay separate from the existing `acx_recognition_transport` choice. Backend target selection and upload transport are different contracts.
- The selector must preserve the plugin's existing source-of-truth behavior for code-managed installs. If URL or source is locked by a constant/filter, the admin UI must render that state as read-only instead of pretending an option save can override code.

## Workflow Principles

- Keep one operator entrypoint per job: deploy via `make deploy-*`, reset via a dedicated make target that reuses the same env mapping and SSH defaults, and plugin targeting via one settings surface.
- Prefer explicit mode selection over magic fallback. If the plugin is talking to localhost, that should be a chosen state, not an accident caused by a blank URL.
- Use the existing deployment script as the source of truth for OCI env mapping, SSH defaults, and unit naming rather than inventing a parallel remote-ops tool.
- Match verification to blast radius: deploy keeps `/health` and commit parity, while destructive reset adds `/ready` and a plugin-side probe.

## Terminology

- **Recognition source**: The backend target the plugin uses for recognition requests. This task scopes two modes: `service` (configured description-service URL) and `local` (`http://localhost:8000`).
- **Transport mode**: The existing request-shape choice for image submission (`multipart` vs `url`) controlled by `acx_recognition_transport`. Not the same as recognition source.
- **Remote reset**: A destructive OCI environment reset that stops the selected systemd unit, clears the environment's Postgres state, restarts the unit, and verifies readiness before completion.
- **Bootstrap bundle**: The minimum post-reset state required before plugin verification can succeed: migrated schema, a usable dev API key, and plugin settings that point at the intended backend mode.
- **Readiness proof**: Successful `GET /ready` for the target environment plus one plugin-side authenticated settings probe when the environment is in `service` mode.

## Current State Analysis

- `mk/deploy.mk` already wraps `scripts/deploy/recognition-service.sh` for `deploy`, `promote`, `verify`, and compose-sync workflows.
- `scripts/deploy/recognition-service.sh` already owns the canonical OCI host/user defaults, env-to-unit mapping, remote directory mapping, and `/health`-plus-commit verification.
- The OCI compose stack stores Postgres data at `ACX_PGDATA_PATH` in `apps/prototype-description-service/docker-compose.env.yml`, so the repo already has a concrete environment-scoped state root that can be reset without ad hoc SQL against a live service.
- `/ready` already exists as the dependency/readiness contract from E15-2, but the deploy script does not currently use it.
- The plugin settings surface already supports an authenticated connection probe with structured outcomes via `SettingsController`, `settingsApi.ts`, and `SettingsPage.tsx`.
- The settings UI already distinguishes constant/option/filter/default sources for URL and API-key fields, so any new selector has to define the same precedence instead of introducing a parallel override model.
- The plugin does not yet expose a first-class recognition source choice. Runtime URL resolution still falls back to `http://localhost:8000` in `class-abstract-recognition-proxy-controller.php`, and admin/workbench surfaces still warn about a local fallback rather than rendering "local mode" as intentional state.
- No scope doc or task plan previously tied the remote reset workflow and the admin source selector together; the closest deployment docs are archived E14 plans that describe a completed multi-environment rollout, not the current reset/operator ergonomics task.

## Target Outcome

Operators should be able to move between local and OCI development without hidden state:

- `make deploy-dev` continues to deploy code to OCI dev using the existing script and SSH defaults.
- `make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET` performs a documented destructive remote reset using the environment's existing compose/systemd contract, then runs the dev bootstrap bundle before verifying `/ready`.
- `make reset-local ... CONFIRM_LOCAL_RESET=RESET` remains the local destructive path and is documented as the local counterpart to `reset-remote`.
- In the plugin admin UI, the operator chooses `Service` or `Local` recognition source explicitly.
  - `Service` mode uses the configured service URL and API key, keeps the authenticated settings probe, and surfaces service-specific errors.
  - `Local` mode intentionally targets `http://localhost:8000`, suppresses the "fallback" framing, and makes the workbench/settings surfaces describe localhost as selected local mode instead of missing configuration.
  - Constant/filter-managed installs render the selector and dependent fields as read-only when code owns the effective mode.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/planning-review-guide.md`
- Contracts: `docs/scopes/e15-12-deploy-reset-and-recognition-source-scope.md`
- Contracts: `docs/tasks/15.0/E15-2-observability-baseline-task-plan.md`
- Historical context: `docs/archive/tasks/14.0/E14-2-multi-environment-deployment-task-plan.md`
- Historical context: `docs/archive/tasks/14.0/E14-1-deploy-description-service-to-oci-task-plan.md`
- Runtime surfaces: `mk/deploy.mk`, `scripts/deploy/recognition-service.sh`, `apps/prototype-description-service/docker-compose.env.yml`
- Plugin settings/runtime surfaces: `apps/prototype-wp-alt-context/src/api/class-settings-controller.php`, `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php`, `apps/prototype-wp-alt-context/src/admin/class-admin.php`, `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts`, `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`
- External docs via `ctx7` only if: none; this task is repo-local shell, docs, and plugin/runtime work

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Deploy/reset operator surface | tooling/backend | `mk/deploy.mk` + `scripts/deploy/recognition-service.sh` deploy/restart/verify via `/health` only | Add a reset command and readiness-aware verification for destructive resets | Yes; existing deploy targets stay intact while reset becomes a new explicit path | Shell smoke + `/ready` proof |
| OCI environment state root | backend/ops | `docker-compose.env.yml` stores Postgres data at `ACX_PGDATA_PATH` | Treat the env-specific PGDATA path as the destructive reset boundary | Yes; reset must not wipe unrelated envs | Remote dry-run/logged command proof |
| Plugin settings API | frontend/plugin | GET/POST `/acx/v1/settings` exposes URL + API-key configuration only | Add recognition-source field, persistence semantics, and source precedence rules | Yes; existing service URL/API-key surfaces remain valid in service mode and code-managed installs stay read-only | PHPUnit + Vitest |
| Plugin runtime target resolution | frontend/plugin | Proxy controller silently falls back to `http://localhost:8000` when no valid service URL exists | Make `local` vs `service` explicit and shared across admin/runtime/workbench surfaces | Yes; local development still works, but the chosen mode becomes visible | PHPUnit + manual admin smoke |
| Post-reset auth/bootstrap | backend/plugin | Resetting DB state deletes service-side API-key rows and leaves plugin verification without credentials | Add a documented dev bootstrap step after reset before plugin smoke runs | Yes; reset remains destructive, but verification becomes executable instead of aspirational | Shell proof + plugin probe |

## Proposed Solution

Keep deployment/reset and recognition-source work in one task because they solve the same developer workflow, but split them into reviewable slices.

On the deploy side, extend the existing OCI deploy script with a dedicated reset subcommand and expose it through `mk/deploy.mk`. The reset contract should reuse the existing env mapping (`dev|staging|prod` -> remote dir, systemd unit, health URLs) and reset only the selected environment's Postgres state root. The operator flow is:

1. Validate env and confirmation flags.
2. SSH to the host and stop `acx-<env>`.
3. Remove or recreate the selected environment's `ACX_PGDATA_PATH`.
4. Start `acx-<env>` through the normal systemd unit so container startup and Alembic follow the existing runtime contract.
5. Run a documented dev bootstrap step that recreates one usable service-mode credential after reset (for example via the existing API-key CLI flow) and captures the value/operator destination needed by the plugin.
6. Verify `/ready`, then run one plugin-side connectivity smoke against the selected service URL.

On the plugin side, add an explicit recognition-source selector to settings and runtime resolution. The selector owns one new persisted mode field (for example `acx_recognition_source`) with two allowed values: `service` and `local`. Its precedence must mirror the existing settings model:

- code-managed constant/filter source wins and renders the selector read-only
- saved option is used only when no code-managed override exists
- default resolution is explicit local mode only when no valid service configuration or code-managed source is present

- `service` mode:
  - uses the configured URL and API key
  - keeps the existing authenticated settings probe
  - keeps workbench copy focused on service connectivity
- `local` mode:
  - intentionally resolves to `http://localhost:8000`
  - does not present localhost as an accidental fallback warning
  - updates settings/admin/workbench copy to reflect chosen local mode

The selector must not absorb transport concerns. `acx_recognition_transport` remains the upload-path control for E15-11.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tooling | `mk/deploy.mk` | Add `reset-remote` help text and target wiring |
| tooling | `scripts/deploy/recognition-service.sh` | Add reset subcommand, confirmation guards, and `/ready` verification path |
| backend/docs | `infra/oci/README.md` | Document deploy/reset operator workflow and post-reset verification |
| backend/tooling/docs | `apps/prototype-description-service/README.md` or `infra/oci/README.md` | Document the post-reset dev bootstrap step that recreates service-mode credentials |
| backend/config context | `apps/prototype-description-service/docker-compose.env.yml` | Treat `ACX_PGDATA_PATH` as the reset boundary; doc/comment updates if needed |
| plugin API | `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` | Add recognition-source read/write fields and local-mode-aware probe behavior |
| plugin runtime | `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Replace implicit localhost fallback with explicit mode resolution |
| plugin admin | `apps/prototype-wp-alt-context/src/admin/class-admin.php` | Change fallback notice/localized config to reflect explicit local mode |
| plugin frontend | `apps/prototype-wp-alt-context/js/admin/api/settingsApi.ts` | Extend settings types with recognition source |
| plugin frontend | `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx` | Render source selector and mode-specific help/probe behavior |
| plugin frontend | `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` | Replace fallback warning copy with explicit local-mode/service-mode state |
| tests | `apps/prototype-wp-alt-context/tests/Unit/SettingsControllerTest.php` | Cover selector persistence, service-mode probe, and local-mode behavior |
| tests | `apps/prototype-wp-alt-context/tests/Unit/ProxyRequestTest.php` | Cover runtime mode resolution and localhost targeting semantics |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/__tests__/SettingsPage.test.tsx` | Cover selector UX and mode-dependent notices |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx` | Cover explicit local-mode banner/copy |

## Related Files

| File | Note |
| --- | --- |
| `docs/tasks/15.0/E15-1b-plugin-settings-ux-task-plan.md` | Current plugin probe/settings contract already landed; do not regress its authenticated probe outcomes |
| `docs/tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md` | Stronger local-to-OCI integration proof remains adjacent context |
| `docs/tasks/15.0/E15-4-local-reset-bootstrap-hardening-task-plan.md` | Local reset contract is the local-side counterpart to this remote reset work |
| `apps/prototype-wp-alt-context/src/api/class-analysis-jobs-controller.php` | Existing `acx_recognition_transport` contract must remain distinct from recognition-source selection |
| `apps/prototype-description-service/scripts/manage_api_keys.py` | Existing credential/bootstrap surface for recreating a dev API key after reset |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test -- --filter=SettingsControllerTest`
  - `cd apps/prototype-wp-alt-context && composer test -- --filter=ProxyRequestTest`
  - `cd apps/prototype-wp-alt-context && npm run test -- SettingsPage`
  - `cd apps/prototype-wp-alt-context && npm run test -- WorkbenchPage`
- Runtime-parity / environment checks:
  - `make deploy-dev`
  - `make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET`
  - `cd apps/prototype-description-service && PYENV_VERSION=description-service pyenv exec python scripts/manage_api_keys.py create --tenant-id <dev-tenant> --name e15-12-reset-smoke`
  - `curl -fsS https://dev.api.altcontext.com/ready`
  - `make reset-local WP_PATH="${LOCAL_WP_ROOT:-$HOME/Development/wp-context-alt-text}/app/public" CONFIRM_LOCAL_RESET=RESET`
- Contract/fixture verification:
  - Assert the deploy script still verifies `/health` for normal deploys and `/ready` for destructive reset completion.
  - Assert `service` vs `local` selector values are the only accepted persisted modes.
  - Assert selector source precedence matches the existing constant/option/filter behavior.
- Manual verification:
  - In WP admin Settings, switch between `Service` and `Local` and confirm the workbench/status copy matches the chosen mode.
  - In `service` mode against OCI dev after reset and dev-key bootstrap, run the settings connection probe and confirm it succeeds.

## Slice Delivery

### Slice 1: Scope the Recognition Source Contract

**Goal**: Replace accidental localhost fallback with an explicit plugin mode contract before touching OCI reset automation.

Changes:

- Add a persisted recognition-source field with `service|local` semantics to the settings API and admin UI.
- Move proxy target resolution to one explicit mode resolver instead of blank-URL fallback.
- Update admin/workbench messaging so localhost is presented as selected local mode, not missing service configuration.
- Preserve constant/filter/option precedence for the selector so code-managed installs stay read-only and deterministic.
- Keep the existing authenticated service probe behavior in `service` mode and define local-mode probe behavior explicitly in the same slice.

Proof:

- PHPUnit covers selector persistence and runtime resolution.
- Vitest covers selector rendering and mode-specific notices.

### Slice 2: Add Remote Reset as a First-Class Operator Workflow

**Goal**: Standardize remote destructive reset using the existing deploy script and OCI env mapping.

Changes:

- Add `reset-remote` target wiring in `mk/deploy.mk`.
- Extend `scripts/deploy/recognition-service.sh` with a reset subcommand that:
  - requires `CONFIRM_REMOTE_RESET=RESET`
  - blocks prod unless an additional prod confirmation is supplied
  - stops `acx-<env>`
  - clears the selected environment's `ACX_PGDATA_PATH`
  - restarts the unit through systemd
  - runs the documented dev bootstrap bundle needed to recreate service-mode credentials after reset
  - verifies `/ready`
- Update `infra/oci/README.md` with the operator flow and safety contract.

Proof:

- Logged shell proof shows stop/reset/start sequencing for `dev`.
- `curl -fsS https://dev.api.altcontext.com/ready` succeeds after reset.

### Slice 3: Align Local and Remote Verification Ergonomics

**Goal**: Make the local reset path and OCI reset path feel like matching tools, then prove the plugin can target the intended backend after reset.

Changes:

- Cross-link the local reset docs/runbooks with the new remote reset workflow so operators know when to use each.
- Recheck `make reset-local` guidance against the new remote-reset docs and selector copy.
- Capture one plugin-side service-mode connectivity smoke after `reset-remote` plus bootstrap, and one local-mode smoke after `reset-local`.

Proof:

- Local reset command still works with explicit confirmation.
- Settings/workbench verification shows `service` mode reaching OCI dev after remote reset and `local` mode intentionally targeting localhost after local reset.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the deploy, readiness, and plugin settings/runtime surfaces before editing.
- [x] Confirmed no external dependency lookup is required.
- [x] Kept transport-mode work out of this task except where needed to preserve contract boundaries.

### Checklist for Slice 1: Scope the Recognition Source Contract

- [x] Settings API exposes the persisted recognition-source field with only `service|local` values.
- [x] Proxy/runtime resolution no longer relies on an accidental blank-URL fallback.
- [x] Settings and workbench UI copy reflect explicit local mode versus service mode.
- [x] Constant/filter-managed installs keep deterministic read-only precedence for the selector and dependent fields.
- [x] Service-mode probe behavior remains covered by tests in the same slice.

### Checklist for Slice 2: Add Remote Reset as a First-Class Operator Workflow

- [x] `mk/deploy.mk` exposes `reset-remote` with clear help text and confirmation requirements.
- [x] The deploy script owns env validation, stop/reset/start sequencing, and `/ready` verification.
- [x] The remote reset flow includes an executable post-reset dev bootstrap step before plugin-side service verification.
- [x] Reset scope is environment-specific and does not touch unrelated OCI stacks.
- [x] Operator docs describe the destructive contract and prod guardrails.

### Checklist for Slice 3: Align Local and Remote Verification Ergonomics

- [x] Local and remote reset docs point to each other and describe when each tool should be used.
- [x] Operator smoke procedure exists at [`docs/operations/reset-smoke-runbook.md`](../../operations/reset-smoke-runbook.md) (no content duplicated from the destructive reset docs; both reset docs back-link into it).
- [x] At least one plugin-side service-mode smoke is captured per the runbook after OCI dev reset (filed under `docs/tasks/15.0/E15-12-slice3-reset-smoke-proofs.md`).
- [x] At least one local-mode smoke is captured per the runbook after local reset (filed in the same proof file).

## Review Readiness

- [x] No reset workflow change lands without matching operator documentation.
- [ ] No plugin mode change lands without matching runtime-resolution and UI tests.
- [x] Destructive reset completion is proven with `/ready`, not `/health` alone.
- [ ] The final handoff records the selector contract, reset verification, and any prod guard decision.

Validation note: the implementation surfaces are present, but this checkout still has two follow-up validation gaps before the remaining review-readiness boxes can close: `js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx` currently fails in the workbench test harness (`useJobStateMachine` reads an undefined query object), and `scripts/test_make_reset_remote_target.py` still expects dry-run success without the now-required `ACX_RESET_SITE_URL` bootstrap input.

## Stretch Goals

- [ ] Add a non-destructive remote preflight subcommand only if the implementation shows operators need a dry-run beyond the existing confirmation gates.

## Success Criteria

- [x] Operators can deploy code to OCI dev and reset OCI dev state through explicit, documented commands.
- [x] The plugin can intentionally target either the hosted description service or the local development service from the admin UI.
- [x] Localhost is no longer framed as an accidental fallback when the operator has intentionally selected local mode.
- [x] Post-reset verification proves dependency readiness and plugin connectivity, not just process liveness.
