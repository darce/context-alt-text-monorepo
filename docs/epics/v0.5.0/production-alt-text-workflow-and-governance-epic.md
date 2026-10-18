# E20. Production Alt-Text Workflow and Governance (v0.5.0)

> **Epic Short ID**: E20
> **Status**: active - planning
> **Source roadmap**: [context-aware-image-description-roadmap-2026-06-13.md](../../roadmaps/context-aware-image-description-roadmap-2026-06-13.md)
> **Predecessor**: [context-aware-image-description-epic.md](context-aware-image-description-epic.md) (E19 - headless visual-facts route, WordPress describe proxy/UI stub, seeded/local profile switch)

## Objective

Turn the E19 headless image-description foundation into an operator-safe alt-text workflow: intentional writes, dry-run and bulk processing, review/history, context-aware output, and hosted-provider governance. The work keeps E19's contract/provenance discipline while adding WordPress product surfaces that protect existing human-authored alt text.

## Product Positioning

Alt Context remains a context-aware, auditable description system rather than a generic hosted alt-text wrapper. E20 makes the first production workflow useful by preserving non-empty alt text by default, storing provenance next to writes, and exposing operator review and retry controls before any provider-backed generation is allowed.

## Epic-to-Task Decomposition

| E20 task | Scope | Roadmap source |
| --- | --- | --- |
| **E20-1** | Single-attachment alt-text write + provenance guard | Phase 3 / D4 |
| **E20-2** | Missing-alt query, preview, and dry-run selection | Phase 3 / D4 |
| **E20-3** | WP-CLI generate/status surface | Phase 4 / D5 |
| **E20-4** | Bounded bulk generation and retry ledger | Phase 4 / D5 |
| **E20-5** | Review/history workspace for generated descriptions | Phase 4 / D5 |
| **E20-6** | Post/page/WooCommerce alt-text refresh propagation | Phase 4 / D5 |
| **E20-7** | Error logs, usage accounting, and site budgets | Phase 4 / D5 |
| **E20-9** | WordPress context-pack contract and backend enrichment | Phase 5 / D6 |
| **E20-10** | Roster-bound identity context guardrails | Phase 5 / D6 |
| **E20-11** | Hosted-provider benchmark and governance decision | Phase 6 / D7 |

E20-8 is intentionally not authored in this packet; the requested implementation set skips that task number.

## Strict Dependency Order

1. **E20-1** must land before any bulk or CLI write path; it owns the write guard and provenance meta.
2. **E20-2** builds the selection/dry-run substrate used by **E20-3** and **E20-4**.
3. **E20-3** and **E20-4** provide automation; **E20-5** provides review/edit after generated results exist.
4. **E20-6** depends on successful writes/history; refresh must not mutate generated provenance.
5. **E20-7** must land before public beta or provider tasks because usage/budget controls are a governance prerequisite.
6. **E20-9** and **E20-10** add context to the existing E19 contract without changing E19 response provenance semantics.
7. **E20-11** is last; hosted providers require usage controls, disclosure, and benchmark evidence.

## Success Metrics

- A missing-alt attachment can be previewed, written intentionally, and re-read with generated provenance.
- Non-empty human alt text is never overwritten without an explicit force path.
- A bounded media-library backlog can be dry-run, processed, reviewed, retried, and corrected.
- Generated descriptions expose context/provenance and provider disclosure consistently.
- Hosted-provider mode is either rejected or scoped behind opt-in, cost, retention, and subprocessor evidence.

## Out of Scope

- No direct extension of `/recognition/analyze`.
- No direct third-party provider calls until E20-11.
- No automatic person naming without roster-confirmed context and E20-10 guardrails.
- No unbounded background queue, unbounded cache, or hidden write path.

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Public recognition/description data policy | Product + Legal | Draft needed | E20-11 provider decision |
| LocalWP media fixture with missing alt | Engineering | Available by assumption | E20-1 through E20-4 smoke proof |
| E19 image-description route/proxy | Engineering | Implemented in current codebase | All E20 tasks |
| Provider/subprocessor terms | Product + Legal | Not started | E20-11 |

# Consolidated Checklist

## Planning

- [ ] E20 task plans reviewed with planning verdict `pass`.
- [ ] Accepted plan baselines landed on `main`.
- [ ] Worktrees provisioned for requested E20 task plans.

## Workflow

- [ ] E20-1 protects non-empty alt text and stores provenance.
- [ ] E20-2 provides deterministic missing-alt dry-run selection.
- [ ] E20-3 and E20-4 provide bounded automation.
- [ ] E20-5 and E20-6 provide review/history and content refresh.
- [ ] E20-7 provides usage/error governance.
- [ ] E20-9 and E20-10 add context-aware differentiation safely.
- [ ] E20-11 decides hosted-provider scope with benchmark and policy evidence.
