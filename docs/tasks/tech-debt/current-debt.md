# Deferred (Document as Tech Debt)

- [ ] **#14** Complete the post-refactor package-boundary cleanup after `_shared.py` extraction; migrate `agent-orchestrator-mcp` imports off `agent_handoff_mcp._shared` and relocate orchestration-owned bootstrap helpers that still sit on the handoff side — _Tracked by `docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md`; the focused shared modules already landed, so this item now covers only the remaining cross-package follow-on._

- [ ] **#13** Migrate ~30 deprecated-alias call sites in `test_artifact_tools.py` and `test_handoff_state.py` to successor APIs, then delete the 5 Python alias functions from `core.py` — _Plan: `docs/tasks/12.0/deprecated-alias-test-migration.md` (E12-5 follow-up; aliases are not MCP-exposed but remain as Python callables until tests are updated)_

- [ ] **#12** Add deterministic E2E/smoke automation path for sovereign WordPress flows — _Plan: `docs/tasks/tech-debt/e2e-smoke-automation-path.md` (Playwright + WP-CLI + reproducible outage testing, CI-ready)_
- [ ] **#4** Extract lighter session-rebind in chunk loop instead of full `cluster_service_builder` rebuild (`clustering.py`) — _Defer: perf impact is marginal; avoid new abstraction until chunking pattern stabilizes_
- [ ] **#5** Add lightweight ID-only cluster query for surfacing (avoid eager-loading reps/centroids when only IDs/labels needed) — _Defer: broader refactor; current limit=1000 is adequate; revisit when tenant cluster counts approach 500+_
- [ ] **#9** Add `typeof` guards at `wp.hooks` usage sites, not just warn-and-continue (`main.tsx` + downstream consumers) — _Defer: keep rendering, guard at usage sites only; not a regression_
- [ ] **#10** Map `quality_score` from ORM model into domain `MediaIdentity` (pre-existing gap, not a regression) — _Defer: fix belongs in the detection pipeline, not the mapping layer_
- [ ] **#11** Optimize sovereign orphan-member cleanup cadence (`delete_orphan_rows()` in `IdentityMembersRepository`) for high-member tenants — _Defer: v0.1.0 runs cleanup every sync; revisit with profiling in roadmap Phase 2 to avoid repeated full-scan LEFT JOIN cost_
