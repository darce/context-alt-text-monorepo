# E15-12. Deploy Reset and Recognition Source Selector

> **Status**: scope (intake recorded 2026-05-01)
> **Task ref**: `E15-12`
> **Parent epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../epics/v0.4.0/public-demo-launch-readiness-epic.md) (E15)
> **Branch**: `feature/e15-12`
> **Worktree**: `context-alt-text-monorepo-e15-12`

## Problem

The repo now has a working OCI deploy path and a working plugin-side authenticated probe, but the operator workflow still splits across two awkward gaps:

1. There is no first-class destructive reset workflow for the remote dev environment. Operators can deploy new code, but resetting the environment still requires ad hoc SSH commands and undocumented sequencing.
2. The plugin still treats `http://localhost:8000` as an implicit fallback instead of an explicit operator choice. That is fine for local development, but it is poor ergonomics once the same plugin can talk either to a local description service or to the hosted OCI service.

This scope note defines one bounded task that makes those two surfaces explicit and usable together.

## MVP scope

- Standardize the dev deployment/reset operator workflow around the existing `make deploy-*` / `scripts/deploy/recognition-service.sh` surfaces.
- Add a documented destructive remote reset command for OCI environments with hard guards, explicit sequencing, and post-reset verification.
- Replace the plugin's implicit local-URL fallback as the primary UX with an explicit admin selector for recognition source:
  - `service` = use the configured description-service URL and API key.
  - `local` = intentionally target the local development service at `http://localhost:8000`.
- Keep the selector scoped to plugin settings/runtime behavior only. This is a backend-target choice, not a transport-mode choice.
- Keep local and remote reset destructive. This is still a greenfield system, so resetting environment state is acceptable when it reduces operator ambiguity.

## Decisions

- **Reset contract is stop/reset/start/verify, not SQL against a live stack.** The operator flow must stop the selected OCI environment, reset its database state, restart the normal unit, and verify readiness before declaring success.
- **Remote reset is dev/staging-first and prod-guarded.** The task may define a prod code path, but prod must remain behind an additional confirmation gate and does not need to be the primary verification target for completion.
- **Recognition source is distinct from upload transport.** The existing `acx_recognition_transport` filter remains the transport selector for multipart vs URL submission. The new source selector chooses which backend the plugin talks to.
- **Local mode is explicit, not accidental.** The UI should stop framing localhost as merely a fallback warning when the operator has intentionally selected local mode.
- **Service mode owns URL/API key validation.** Local mode may bypass service-auth probing; service mode must keep the existing authenticated probe and error taxonomy.

## Success criteria

1. The follow-on task plan defines an operator-proof remote reset workflow with code ownership, safety gates, and readiness verification.
2. The follow-on task plan defines the plugin surfaces that store, resolve, and render the recognition source selector without conflating it with transport mode.
3. A local developer can intentionally choose local mode from the admin UI instead of relying on an empty-URL fallback path.

## Not-doing

- No automatic reset as part of every deploy.
- No retirement of the existing multipart-vs-URL transport switch.
- No production data preservation or migration workflow; destructive reset remains allowed in this greenfield stage.
- No multi-host backend discovery, SSH orchestration daemon, or cloud control-plane automation beyond the existing OCI/Tailscale shell workflow.

## Assumptions

- `deploy-dev` and the OCI systemd units remain the canonical code deployment path.
- `/ready` is the correct dependency/readiness gate after destructive reset; `/health` alone is not enough.
- The plugin can keep one service URL field and one API key field while adding a separate source selector.

## Next step

Draft the `E15-12` task plan on `feature/e15-12`, using this scope note to pin the remote reset contract and the plugin source-selector boundaries before implementation starts.
