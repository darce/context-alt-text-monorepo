# GTM — Productization & Launch

**Single source of truth:** [`altcontext-productization-launch-plan.md`](altcontext-productization-launch-plan.md)

The previously-split `00`–`05` docs were merged into that one file after a heuristics-canon review pass (2026-07-09). It covers, in order:

1. What already exists (don't re-plan)
2. Launch thesis & moat
3. Launch phases (gated, timed to the Sep–Oct window)
4. Minimal-friction path to first paying clients
5. Demo provisioning (per-prospect + short-slug URLs)
6. **User-management infrastructure, CRM & data ownership** (build-vs-buy, field-by-field in-house-vs-outsourced, CRM options)
7. Payments & the money pipeline
8. Marketing site direction (time-boxed ASCII sketch)
9. Analytics & observability (PostHog + Sentry)
10. Launch strategy using your social network
11. WordPress.org marketplace + platform-landlord posture
12. Risks & falsifiers
13. Decision log
14. Implementation Slices (offload-ready, tagged Atomic vs Epic)
15. Offload division of labor (straight-to-implementation vs decompose-first)

## Relationship to existing work (do not duplicate)
- **E15** (`docs/epics/v0.4.0/…`) makes `demo.altcontext.com` live — §5 builds on it.
- **E16 / SaaS-ops** (`docs/roadmaps/roadmap-saas-operations.md`) chose the vendor stack — §6/§7 sequence and connect it; the field-ownership map (§6.3) and CRM guidance (§6.4) are new.

## Canon grounding
Strategy cites the [heuristics-canon](https://github.com/darce/heuristics-canon) lexicons by stable ID (`[GTM-01]`, `[DATA-14]`, `[COL-10]`). §0 of the plan lists what the canon review changed.
