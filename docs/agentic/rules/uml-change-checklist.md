# UML Change Checklist

> **Purpose:** Canonical checklist for architecture-diagram changes so Mermaid UML stays in the same slice as the code, route, workflow, or boundary updates it describes.

Use this checklist whenever a change affects architecture, runtime boundaries, controller namespaces, page composition, major workflow flow, or state-machine behavior that is represented in `docs/agentic/diagrams/`.

## Diagram Ownership Registry

| Diagram Surface | Canonical Owner | Diagram Set | Adaptation Point | Primary Consumers |
| --- | --- | --- | --- | --- |
| Top-level system architecture | `architecture` | `docs/agentic/diagrams/system-overview.mmd` | Cross-stack routes, controllers, service boundaries, admin pages | Agents, reviewers, onboarding |
| WordPress admin frontend architecture | `wp-proxy` | `docs/agentic/diagrams/frontend-uml/` | `apps/prototype-wp-alt-context/js/admin/` and `apps/prototype-wp-alt-context/src/api/` | Frontend and plugin contributors |
| Recognition backend architecture | `backend` | `docs/agentic/diagrams/backend-uml/` | `apps/prototype-description-service/recognition/` | Backend contributors, review flows |
| Sovereign sync/data projection flow | `wp-proxy` | `docs/agentic/diagrams/sovereign-data-flow.mmd` | WordPress sync pipeline and recognition export surfaces | Sync/debugging work |

## UML-Change Triggers

Run this checklist before marking a slice complete if the change touches any of:

- REST route namespaces or endpoint families
- controller or adapter ownership
- React page inventory or navigation destinations
- major workflow sequencing
- state-machine or orchestration flow
- service or repository boundaries
- new top-level runtime surfaces such as retention, sync, review, export, or worker flows

## UML-Change Steps

1. Identify the owning diagram set before editing code. Load the specific Mermaid files that describe the surface you are changing.
2. Confirm diagram parity with implementation. If the diagram is stale before your change, update it in the same slice instead of leaving pre-existing drift behind.
3. Decide whether the change affects:
   - named components/classes
   - route or namespace labels
   - workflow sequencing
   - state ownership
   - boundary direction or dependency arrows
   - top-level page or controller inventory
4. Update the owning diagram in the same slice as the code change. If no diagram text changes, record why the architecture representation remains valid.
5. Update any nearby map or contract doc when the diagram depends on renamed surfaces or newly introduced responsibilities.
6. Add verification proof:
   - direct code-path references for the changed surface
   - rendered Mermaid sanity check when practical
   - review-ready note that diagrams were updated or explicitly confirmed unchanged
7. Log a handoff finding if a required diagram cannot be updated accurately in the current slice. Do not silently ship known diagram drift.
8. Do not mark the slice review-ready until the architecture diagram, related map/contract docs, and verification notes all agree.

## UML Intake Template

Use this template when opening or implementing a slice that changes architecture documentation:

```md
Diagram surface changed:
Owning diagram:
Canonical owner:
Changed routes/components/workflows:
Related map or contract docs:
Verification proof:
Diagram updated or confirmed unchanged:
Handoff finding/decision id:
```

## Healthy UML Patterns

- One diagram has one clear concern and one owner.
- Diagram labels should use live names from code, not historical aliases.
- Route namespaces and endpoint families must match runtime paths exactly.
- Sequence diagrams should model current user-visible or runtime-critical flow, not deprecated intermediate steps.
- A diagram can be high level, but it cannot be misleading.
- If a surface is too volatile for a stable diagram, document that explicitly and point reviewers to the authoritative map or contract instead.

## Review-Ready Expectations

Before a slice is review-ready, confirm all of the following:

- The relevant Mermaid files were opened and compared against code.
- New pages, controllers, routes, or state-machine transitions are represented.
- Removed or renamed surfaces are no longer shown.
- Any related `docs/agentic/maps/` or `docs/agentic/contracts/` references still match the diagram.
- If no diagram changed, the handoff decision explains why existing UML remains correct.
