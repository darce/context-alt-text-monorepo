# UML Change Checklist

> Checklist for architecture-diagram changes. Use when a change affects architecture, runtime boundaries, controller namespaces, page composition, workflow flow, or state-machine behavior represented in `docs/workbay/diagrams/`.

## Diagram Ownership Registry

| Diagram Surface | Canonical Owner | Diagram Set | Adaptation Point | Primary Consumers |
| --- | --- | --- | --- | --- |
| Top-level system architecture | `architecture` | `docs/workbay/diagrams/system-overview.mmd` | Cross-stack routes, controllers, service boundaries, admin pages | Agents, reviewers, onboarding |
| WordPress admin frontend architecture | `wp-proxy` | `docs/workbay/diagrams/frontend-uml/` | `apps/prototype-wp-alt-context/js/admin/` and `apps/prototype-wp-alt-context/src/api/` | Frontend and plugin contributors |
| Recognition backend architecture | `backend` | `docs/workbay/diagrams/backend-uml/` | `apps/prototype-description-service/recognition/` | Backend contributors, review flows |
| Sovereign sync/data projection flow | `wp-proxy` | `docs/workbay/diagrams/sovereign-data-flow.mmd` | WordPress sync pipeline and recognition export surfaces | Sync/debugging work |

## UML-Change Triggers

Run this checklist before marking a slice complete if the change touches: REST route namespaces, controller/adapter ownership, React page inventory, workflow sequencing, state-machine flow, service/repository boundaries, or new top-level runtime surfaces.

## UML-Change Steps

1. Load the owning Mermaid files before editing code.
2. If the diagram is already stale, update it in the same slice.
3. Classify: named components/classes, route/namespace labels, workflow sequencing, state ownership, boundary arrows, page/controller inventory.
4. Update the owning diagram in the same slice. If unchanged, record why.
5. Update related map/contract docs when diagrams depend on renamed surfaces.
6. Add verification: code-path references, rendered Mermaid sanity check, review-ready note.
7. Log a handoff finding if a diagram cannot be updated in the current slice.
8. Slice not review-ready until diagram, map/contract docs, and verification all agree.

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

- One diagram, one concern, one owner.
- Labels use live code names, not historical aliases.
- Route namespaces must match runtime paths exactly.
- Sequence diagrams model current flow, not deprecated steps.
- High-level is fine; misleading is not.
- If too volatile for a stable diagram, document that and point to the authoritative map/contract.

## Review-Ready Expectations

- Relevant Mermaid files compared against code.
- New pages/controllers/routes/transitions represented.
- Removed/renamed surfaces no longer shown.
- Related `docs/workbay/maps/` and `docs/workbay/contracts/` references still match.
- If no diagram changed, handoff decision explains why.
