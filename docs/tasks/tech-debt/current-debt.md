# Deferred (Document as Tech Debt)

- [ ] **#14** Complete the post-refactor package-boundary cleanup after `_shared.py` extraction; migrate `agent-orchestrator-mcp` imports off `agent_handoff_mcp._shared` and relocate orchestration-owned bootstrap helpers that still sit on the handoff side — _Tracked by `docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md`; the focused shared modules already landed, so this item now covers only the remaining cross-package follow-on._

- [ ] **#13** Migrate ~30 deprecated-alias call sites in `test_artifact_tools.py` and `test_handoff_state.py` to successor APIs, then delete the 5 Python alias functions from `core.py` — _Plan: `docs/tasks/12.0/deprecated-alias-test-migration.md` (E12-5 follow-up; aliases are not MCP-exposed but remain as Python callables until tests are updated)_

- [ ] **#12** Add deterministic E2E/smoke automation path for sovereign WordPress flows — _Plan: `docs/tasks/tech-debt/e2e-smoke-automation-path.md` (Playwright + WP-CLI + reproducible outage testing, CI-ready)_
- [ ] **#21** Stand up operator-facing cross-tenant correlation dashboards (Grafana + Prometheus over `/metrics`, `correlation_id`-keyed log lookup) — _Plan: `docs/tasks/tech-debt/correlation-dashboards.md`; **prerequisite: E15-2b** correlation propagation must land first. Promoted to full task plan under v0.4.1 (E16 Theme A) when picked up._
- [ ] **#22** Add `attempt` column + log field so retries are queryable per-attempt instead of requiring timestamp reconstruction — _Plan: `docs/tasks/tech-debt/retry-attempt-observability.md`; **prerequisite: E15-2b** must land first. Promoted to full task plan under v0.4.1 (E16 Theme A) when picked up._
- [ ] **#15** Consolidate the startup-context surfaces (`CLAUDE.md`, `docs/agentic/instructions.md`, `docs/agentic/BOOTSTRAP.md`, `docs/agentic/rules/mcp-loading-protocol.md`) into one injected cold-start surface plus one MCP reference document — _Supersedes dashboard finding `E17-ARCH-03`; the duplication is still real, but it now lives as tracked documentation debt instead of a long-lived handoff finding._
- [ ] **#16** Collapse the `task-start` two-phase handoff write so worktree metadata lands atomically with task activation — _Supersedes dashboard finding `AHMCP-28-BR-01`; current `scripts/_task_start_inline.py` still calls `switch_task(...)` and then patches `target_worktree_path` via `set_handoff_state(...)`._
- [ ] **#17** Relax repo-slug-coupled lifecycle test assertions so worktree-name tests assert task-id semantics instead of the repo slug — _Supersedes dashboard finding `AHMCP-28-BR-02`; current `test_lifecycle_scripts.py` still encodes `context-alt-text-monorepo-...` in worktree-path assertions._
- [ ] **#18** Replace the `guard-main-branch.sh` no-task warning CLI subprocess with a direct Python API call to reduce permitted-main-edit cold-start overhead — _Supersedes dashboard finding `E17-4-BR-03`; the current warning path still shells out to `agent-handoff-mcp ... state --sections identity` on every qualifying edit._
- [ ] **#19** Decide whether task-plan checkbox sync should return as a real maintained workflow or remain retired — _Supersedes dashboard finding `E17-7-S2-BR-06`; the repo still has no `scripts/hooks/sync-task-plan-checkboxes.sh` hook and no stale-checkbox warning in the context flow._
- [ ] **#20** Default main-branch `MAINT-*` task registration to the repo root `target_worktree_path` so E17-11 fail-closed workspace resolution can disambiguate repo-root maintenance writes — _Tracked in `packages/agent-handoff-mcp/docs/tech-debt/main-branch-maintenance-target-worktree-path-default.md`; current maintenance-task hints in `scripts/hooks/guard-main-branch.sh` and `scripts/check-task-context.py` still omit `target_worktree_path`, which leaves repo-root maintenance tasks ambiguous beside linked-worktree feature tasks._
- [ ] **#4** Extract lighter session-rebind in chunk loop instead of full `cluster_service_builder` rebuild (`clustering.py`) — _Defer: perf impact is marginal; avoid new abstraction until chunking pattern stabilizes_
- [ ] **#5** Add lightweight ID-only cluster query for surfacing (avoid eager-loading reps/centroids when only IDs/labels needed) — _Defer: broader refactor; current limit=1000 is adequate; revisit when tenant cluster counts approach 500+_
- [ ] **#9** Add `typeof` guards at `wp.hooks` usage sites, not just warn-and-continue (`main.tsx` + downstream consumers) — _Defer: keep rendering, guard at usage sites only; not a regression_
- [ ] **#10** Map `quality_score` from ORM model into domain `MediaIdentity` (pre-existing gap, not a regression) — _Defer: fix belongs in the detection pipeline, not the mapping layer_
- [ ] **#11** Optimize sovereign orphan-member cleanup cadence (`delete_orphan_rows()` in `IdentityMembersRepository`) for high-member tenants — _Defer: v0.1.0 runs cleanup every sync; revisit with profiling in roadmap Phase 2 to avoid repeated full-scan LEFT JOIN cost_

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Keep active as a registry; not an implementation task and not an archive candidate by itself.
**Evaluation basis:** Current `main` app code under `apps/` plus the current tech-debt doc set.

- [x] Registry still points at live follow-up docs for correlation dashboards, retry observability, and E2E smoke automation.
- [x] Registry still includes cross-cutting process debt that is outside the app code but relevant to repository maintenance.
- [ ] During the next quarterly pass, remove entries whose implementation has landed on `main` and whose source docs have been archived.
- [ ] Promote any still-open high-priority registry item into a dated task plan before implementation starts.
- [ ] Keep this file in `docs/tasks/tech-debt/`; archive only if the registry role moves to another maintained source of truth.
