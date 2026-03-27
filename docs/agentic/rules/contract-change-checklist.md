# Contract Change Checklist

> **Purpose:** Canonical checklist for cross-boundary changes so contract ownership, schema evolution, fixture evidence, and handoff proof stay in the same slice.

Use this checklist whenever a change touches a payload, status code, envelope, enum, or boundary behavior shared across services, languages, or MCP surfaces.

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
| MCP handoff surface | `agentic-tooling` | `docs/agentic/contracts/agent-handoff-mcp.md` | `packages/agent-handoff-mcp/` API and CLI surface | Orchestrator, workers, review flows |

## Contract-Change Steps

1. Identify the boundary being changed and load its owning contract before editing code.
2. Confirm the canonical owner. If more than one layer appears to adapt the shape, stop and collapse ownership before proceeding.
3. Decide whether the change affects:
   - payload shape
   - status/error semantics
   - enum/value vocabulary
   - pagination/provenance metadata
   - runtime/parity behavior
4. Update the owning contract in the same slice as the implementation. If no contract text changes, record a handoff decision explaining why.
5. Update the shared schema or fixture in the same slice when the boundary payload changes.
6. Add or update deterministic proof:
   - fixture/schema assertion
   - backend/PHP/TS contract tests
   - runtime-parity proof when applicable
7. Record a handoff decision with:
   - boundary changed
   - owning contract
   - verification path
   - compatibility stance
   - downstream assumptions that remain valid
8. Do not mark the slice review-ready until contract, schema/fixture, tests, and handoff proof all exist together.

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

Whenever a shared boundary payload changes, attach a short note in the owning contract or the implementation decision:

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

- Greenfield default is `Compatibility required: no`.
- Do not add backward-compatibility shims unless the task explicitly documents an exception.
- Downstream consumers validate the canonical shape; they do not silently support multiple contradictory shapes.

## Healthy Data Patterns

- One writer per fact: every boundary field has a single authoritative source.
- Explicit provenance for derived metadata: if a field is computed locally, document the derivation and local authority path.
- No silent dual-write drift: when two layers can write related state, document which one is canonical and which one mirrors.
- Read-after-write expectations must be named: immediate, eventual, or best-effort.
- Boundary adapters must not invent pagination, provenance, or status metadata from convenience guesses.
- Empty success is not an overload strategy: unavailability and malformed payloads must stay distinct from true empty results.

## Canonical Enum and Constant Surfaces

| Concept | Canonical Surface |
| --- | --- |
| `curation_state` | Python enum in backend domain, PHP backed enum in plugin domain, TypeScript exported const/type in admin API types |
| `sync_status` / sync-health vocabulary | `docs/agentic/contracts/conflict-resolution-sync-contract.md` plus PHP sync-status response surface |
| `conflict_type` / `conflict_code` | `docs/agentic/contracts/conflict-resolution-sync-contract.md` |
| MCP review modes and status values | `docs/agentic/contracts/agent-handoff-mcp.md` and `packages/agent-handoff-mcp/` |

## Remediation-Plan Finding IDs

If a remediation plan cites an existing `finding_id`, that id must resolve to a real MCP finding or a concrete code site before implementation starts.

- If the finding exists, fix/archive/defer it through MCP.
- If the finding does not exist, record a handoff decision documenting the absence.
- Do not carry unverifiable finding IDs forward as assumed technical debt.
