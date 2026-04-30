# Contract Change Checklist

> Checklist for cross-boundary changes. Use when a change touches a payload, status code, envelope, enum, or boundary behavior shared across services, languages, or MCP surfaces.

## Boundary Ownership Registry

| Boundary | Canonical Owner | Contract | Adaptation Point | Primary Consumers |
| --- | --- | --- | --- | --- |
| Recognition cluster snapshot API | `backend` | `docs/agentic/contracts/cluster-snapshot-api.md` | FastAPI snapshot export in `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | WordPress sovereign projector, frontend via local projection |
| Recognition cluster delta API | `backend` | `docs/agentic/contracts/cluster-delta-api.md` | FastAPI delta export in `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | WordPress sovereign projector |
| WordPress recognition REST proxy | `wp-proxy` | `docs/agentic/contracts/clustering-api.md` | WordPress REST controllers under `apps/prototype-wp-alt-context/src/api/` | React admin UI |
| Curation replay API | `backend` | `docs/agentic/contracts/curation-sync-api.md` | Recognition-service replay/topology routes | WordPress outbox drain |
| Recognition HTTP API | `backend` | `docs/agentic/contracts/recognition-clustering.md` | FastAPI routes under `apps/prototype-description-service/recognition/interface_adapters/http/routers/` | WordPress proxy |
| Suggestion extension API | `backend` | `docs/agentic/contracts/suggestion-extensions-api.md` | Recognition-service suggestion routes | WordPress proxy, React review UI |
| Recognition media XMP mapping | `wp-proxy` | `docs/agentic/contracts/recognition-media-xmp-mapping.md` | WordPress XMP persistence flow under `apps/prototype-wp-alt-context/src/media/` | XMP writer, retention/export surfaces |
| Conflict resolution and sync contract | `wp-proxy` | `docs/agentic/contracts/conflict-resolution-sync-contract.md` | WordPress sync/conflict response mappers | React workbench conflict UI |
| MCP handoff surface | `agentic-tooling` | `docs/agentic/contracts/agent-handoff-mcp.md` | Installed `agent-handoff-mcp` API and CLI surface | Orchestrator, workers, review flows |

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
| `sync_status` / sync-health vocabulary | `docs/agentic/contracts/conflict-resolution-sync-contract.md` plus PHP sync-status response surface |
| `conflict_type` / `conflict_code` | `docs/agentic/contracts/conflict-resolution-sync-contract.md` |
| MCP review modes and status values | `docs/agentic/contracts/agent-handoff-mcp.md` and installed `agent-handoff-mcp` |
| `correlation_id` header / log field / `correlation_source` enum | `recognition/interface_adapters/http/middleware/correlation.py` — `X-Request-ID` header, `CorrelationSource` StrEnum (`api`, `worker`), JSON log `correlation_id` field |

## E15-2b Scan-Queue Correlation Propagation

No external HTTP contract shape changed for E15-2b. The `/recognition/analyze` request/response payloads are byte-identical. Internal persistence added two nullable columns on `identity_scan_job_items` (`correlation_id`, `correlation_source`) so the async worker can log against the same id as the enqueueing request. The `CorrelationSource` StrEnum is the canonical vocabulary and lives in `recognition/interface_adapters/http/middleware/correlation.py`. Handoff decisions: `claude_slice_complete_E15-2b_correlation_persistence`, `claude_slice_complete_E15-2b_worker_correlation_binding`.

## MAINT-PDS-LINT-CLEANUP-20260429 Adapter Lint Cleanup

No external HTTP, worker, or persistence contract shape changed for MAINT-PDS-LINT-CLEANUP-20260429. The branch only fixes internal lint regressions in adapter timeout helpers, scan-task type imports, and formatter-altered import/whitespace surfaces under `apps/prototype-description-service/recognition/`. Downstream consumers may continue to assume byte-identical request/response payloads, unchanged job-status vocabulary, and unchanged worker/runtime semantics. Verification stays local to unit coverage plus lint/diagnostic checks; no shared schema or contract fixture changes are required for this maintenance slice.

## Remediation-Plan Finding IDs

Cited `finding_id` values must resolve to a real MCP finding or concrete code site before implementation. Fix/archive/defer existing findings through MCP. Record a decision for non-existent IDs. Do not carry unverifiable IDs as assumed debt.
