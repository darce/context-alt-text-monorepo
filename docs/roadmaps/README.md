# Roadmaps

Product and architecture roadmaps for the Alt Context monorepo.

## Contents

| File                                                                             | Purpose                                                                                                 | Status                                        |
| -------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| [local-ai-managed-default-roadmap-2026-07-31.md](local-ai-managed-default-roadmap-2026-07-31.md) | **Active product direction:** managed default + private worker option; WP workflow/trusted records moat; delta vs ADR-011/GTM/E14/FIR to avoid traps | **Active (2026-07-31)** |
| [roadmap-v3.hybrid.md](roadmap-v3.hybrid.md) | Architectural vision — hybrid on-device + backend recognition, sovereign clusters, assisted labeling UX | Vision reference, superseded |
| [roadmap-v4.md](roadmap-v4.md)             | Product and architecture roadmap for the next recognition UX wave                                        | Historical roadmap draft      |
| [roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md) | PostgreSQL upgrade evaluation and phased migration planning                                      | Technical roadmap             |
| [roadmap-pg-durable-evaluation.md](roadmap-pg-durable-evaluation.md) | pg_durable vendoring evaluation — verdict: do not vendor; close durability gaps in place; revisit triggers | Decision document (2026-07-10) |
| [context-aware-image-description-roadmap-2026-06-13.md](context-aware-image-description-roadmap-2026-06-13.md) | Roadmap seed for context-aware image description, visual facts, WordPress alt-text workflow, and provider adapters | Roadmap seed (pre-epic); reframe under local-AI roadmap |
| [public-mvp-ux-polish-roadmap-2026-07-04.md](public-mvp-ux-polish-roadmap-2026-07-04.md) | Impact-ordered UX/UI/design polish roadmap for the public MVP demo, grounded in the WBUX-1/WBUX-2 assessments; includes planning-surface realignment | Roadmap seed (pre-epic) |

## How to use

- **Starting new work?** Start with [docs/epics/README.md](../epics/README.md) and the newest active epic, not the roadmaps folder.
- **Need current product direction (compute placement, moat, what to stop)?** Read [local-ai-managed-default-roadmap-2026-07-31.md](local-ai-managed-default-roadmap-2026-07-31.md) first.
- **Need architectural context?** Read `roadmap-v3.hybrid.md` for long-term design principles (historical hybrid vision).
- **Need a large-shape planning document?** Use the roadmap that matches the topic, then translate current execution into an epic or task plan.
