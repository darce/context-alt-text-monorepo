# Contract Change Checklist

> Checklist for cross-boundary changes. Use when a change touches a payload, status code, envelope, enum, or boundary behavior shared across services, languages, or MCP surfaces.

## Boundary Ownership Registry

| Boundary | Canonical Owner | Contract | Adaptation Point | Primary Consumers |
| --- | --- | --- | --- | --- |
| Recognition cluster snapshot API | `backend` | `docs/workstate/contracts/cluster-snapshot-api.md` | FastAPI snapshot export in `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | WordPress sovereign projector, frontend via local projection |
| Recognition cluster delta API | `backend` | `docs/workstate/contracts/cluster-delta-api.md` | FastAPI delta export in `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | WordPress sovereign projector |
| WordPress recognition REST proxy | `wp-proxy` | `docs/workstate/contracts/clustering-api.md` | WordPress REST controllers under `apps/prototype-wp-alt-context/src/api/` | React admin UI |
| Curation replay API | `backend` | `docs/workstate/contracts/curation-sync-api.md` | Recognition-service replay/topology routes | WordPress outbox drain |
| Recognition HTTP API | `backend` | `docs/workstate/contracts/recognition-clustering.md` | FastAPI routes under `apps/prototype-description-service/recognition/interface_adapters/http/routers/` | WordPress proxy |
| Suggestion extension API | `backend` | `docs/workstate/contracts/suggestion-extensions-api.md` | Recognition-service suggestion routes | WordPress proxy, React review UI |
| Recognition media XMP mapping | `wp-proxy` | `docs/workstate/contracts/recognition-media-xmp-mapping.md` | WordPress XMP persistence flow under `apps/prototype-wp-alt-context/src/media/` | XMP writer, retention/export surfaces |
| Conflict resolution and sync contract | `wp-proxy` | `docs/workstate/contracts/conflict-resolution-sync-contract.md` | WordPress sync/conflict response mappers | React workbench conflict UI |
| MCP handoff surface | `workstate-tooling` | `docs/workstate/contracts/workstate-handoff-mcp.md` | Installed `workstate-handoff-mcp` API and CLI surface | Orchestrator, workers, review flows |

## Contract-Change Steps

1. Load the owning contract before editing code.
2. Confirm the canonical owner. If multiple layers adapt the shape, collapse ownership first.
3. Classify the change: payload shape, status/error semantics, enum vocabulary, pagination/provenance metadata, or runtime parity.
4. Update the owning contract in the same slice. If unchanged, record a handoff decision explaining why.
   For test-only cleanup on boundary-touching files, add a same-slice checklist or contract note that explicitly states the runtime contract is unchanged.
5. Update shared schema/fixture in the same slice.
6. Add deterministic proof: fixture/schema assertion, contract tests, runtime-parity proof.
7. Record a handoff decision: boundary, owning contract, verification path, compatibility stance, valid downstream assumptions.
8. Slice is not review-ready until contract, schema/fixture, tests, and handoff proof all exist together.

## Contract Intake Template

Use this template when opening or implementing a cross-boundary slice:

```md
Boundary changed:
Owning contract:
Canonical owner:
Compatibility required: yes/no
Changed fields/status semantics:
Shared schema or fixture touched:
Verification proof:
Downstream adapters allowed to assume:
Handoff decision id:
```

## Schema-Evolution Notes

Attach to the owning contract or implementation decision when a shared payload changes:

```md
Schema evolution:
- What changed:
- Why it changed:
- Compatibility required: yes/no
- Canonical owner:
- Downstream consumers affected:
- Fixture/schema/test updated:
```

Rules:

- Greenfield default: `Compatibility required: no`.
- No backward-compatibility shims unless explicitly documented.
- Downstream consumers validate the canonical shape only.

## Healthy Data Patterns

- One writer per fact.
- Explicit provenance for derived metadata.
- No silent dual-write drift: document which layer is canonical.
- Name read-after-write expectations: immediate, eventual, or best-effort.
- Adapters must not invent pagination, provenance, or status metadata.
- Unavailability and malformed payloads stay distinct from true empty results.

## Canonical Enum and Constant Surfaces

| Concept | Canonical Surface |
| --- | --- |
| `curation_state` | Python enum in backend domain, PHP backed enum in plugin domain, TypeScript exported const/type in admin API types |
| `sync_status` / sync-health vocabulary | `docs/workstate/contracts/conflict-resolution-sync-contract.md` plus PHP sync-status response surface |
| `conflict_type` / `conflict_code` | `docs/workstate/contracts/conflict-resolution-sync-contract.md` |
| MCP review modes and status values | `docs/workstate/contracts/workstate-handoff-mcp.md` and installed `workstate-handoff-mcp` |
| `correlation_id` header / log field / `correlation_source` enum | `recognition/interface_adapters/http/middleware/correlation.py` — `X-Request-ID` header, `CorrelationSource` StrEnum (`api`, `worker`), JSON log `correlation_id` field |

## E15-2b Scan-Queue Correlation Propagation

No external HTTP contract shape changed for E15-2b. The `/recognition/analyze` request/response payloads are byte-identical. Internal persistence added two nullable columns on `identity_scan_job_items` (`correlation_id`, `correlation_source`) so the async worker can log against the same id as the enqueueing request. The `CorrelationSource` StrEnum is the canonical vocabulary and lives in `recognition/interface_adapters/http/middleware/correlation.py`. Handoff decisions: `claude_slice_complete_E15-2b_correlation_persistence`, `claude_slice_complete_E15-2b_worker_correlation_binding`.

## MAINT-PDS-LINT-CLEANUP-20260429 Adapter Lint Cleanup

No external HTTP, worker, or persistence contract shape changed for MAINT-PDS-LINT-CLEANUP-20260429. The branch only fixes internal lint regressions in adapter timeout helpers, scan-task type imports, and formatter-altered import/whitespace surfaces under `apps/prototype-description-service/recognition/`. Downstream consumers may continue to assume byte-identical request/response payloads, unchanged job-status vocabulary, and unchanged worker/runtime semantics. Verification stays local to unit coverage plus lint/diagnostic checks; no shared schema or contract fixture changes are required for this maintenance slice.

## HARNESS-BASH-STALL-20260512 Agent Chat Test Wrapper

No cross-service API, shared schema, REST, PHP runtime, or frontend runtime contract changed for HARNESS-BASH-STALL-20260512. The retained `apps/prototype-wp-alt-context/package.json` change adds an agent-chat-only `test:agent` npm script for local Vitest execution under the VS Code terminal harness; it does not alter app dependencies, bundled output, WordPress plugin runtime behavior, or CI test semantics. Downstream consumers may continue to assume the existing WordPress admin build and REST contracts. Verification stays limited to operator-doc regression coverage and captured command output because the slice concerns agent workflow behavior, not product payload shape.

## E15-17 Roster Person Workspace Default Shell

No cross-service API contract changed for E15-17. The branch ships the person-first roster workspace shell, the deterministic default-workspace selector, and projection-status gating in the React admin UI, plus a small `formatTimestamp` helper. All consumed `RosterEntry` fields (`person_uuid`, `name`, `tags`, `cluster_count`, `projection_status`, `projection_refreshed_at`, `source_version`) already exist in `packages/shared-contracts/schemas/roster-entry.schema.json`, and the WordPress `acx/v1/roster` REST contract is unchanged. The new `defaultWorkspaceRoute` predicate respects the existing `?personFilter=...` query-param contract that `RosterEntriesSection` owns. Compatibility required: no — frontend-only consumer changes against a stable upstream payload. Handoff decisions: `copilot_slice_complete_e15_17_default_workspace_shell`, `copilot_slice_complete_e15_17_default_workspace_branch_review_findings`, `copilot_slice_complete_e15_17_deterministic_default_workspace`, `copilot_slice_complete_e15_17_person_workspace_summary_enrichment`, `copilot_slice_complete_e15_17_close_prep`.

## E15-18 LocalWP Smoke Proof

No cross-service API contract changed for E15-18. The branch is limited to the LocalWP smoke harness under `apps/prototype-wp-alt-context/scripts/localwp/` and its adjacent focused tests. The operator-facing smoke JSON payload remains local to the WordPress proof gate; this branch hardens it by reporting effective arguments, adding a stable `child_job_statuses` list shape for timeout diagnostics, and keeping the timeout message text centralized in one helper. Downstream consumers may assume the field remains a JSON array of objects on both timeout and terminal paths, while shared backend, REST, and MCP contracts remain unchanged.

## BUG-STOP-BACKEND-20260516 Prototype Stop Cleanup

No external HTTP, worker, or persistence contract changed for BUG-STOP-BACKEND-20260516. The branch is limited to `apps/prototype-description-service/scripts/start_prototype_local.sh` and focused regression coverage in `apps/prototype-description-service/recognition/tests/scripts/test_start_prototype_local.py`. The stop helper now scopes uvicorn cleanup to project-local processes and ensures the scan-worker log directory exists before shutdown logging, but it does not change CLI arguments, request/response payloads, environment-variable names, or downstream service assumptions.

## Remediation-Plan Finding IDs

Cited `finding_id` values must resolve to a real MCP finding or concrete code site before implementation. Fix/archive/defer existing findings through MCP. Record a decision for non-existent IDs. Do not carry unverifiable IDs as assumed debt.
