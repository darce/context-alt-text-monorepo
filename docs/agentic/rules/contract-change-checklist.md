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
| MCP handoff surface | `agentic-tooling` | `docs/agentic/contracts/agent-handoff-mcp.md` | `packages/agent-handoff-mcp/` API and CLI surface | Orchestrator, workers, review flows |

## Contract-Change Steps

1. Load the owning contract before editing code.
2. Confirm the canonical owner. If multiple layers adapt the shape, collapse ownership first.
3. Classify the change: payload shape, status/error semantics, enum vocabulary, pagination/provenance metadata, or runtime parity.
4. Update the owning contract in the same slice. If unchanged, record a handoff decision explaining why.
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
| MCP review modes and status values | `docs/agentic/contracts/agent-handoff-mcp.md` and `packages/agent-handoff-mcp/` |

## Remediation-Plan Finding IDs

Cited `finding_id` values must resolve to a real MCP finding or concrete code site before implementation. Fix/archive/defer existing findings through MCP. Record a decision for non-existent IDs. Do not carry unverifiable IDs as assumed debt.
