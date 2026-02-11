## Deferred (Document as Tech Debt)

- [ ] **#4** Extract lighter session-rebind in chunk loop instead of full `cluster_service_builder` rebuild (`clustering.py`) — _Defer: perf impact is marginal; avoid new abstraction until chunking pattern stabilizes_
- [ ] **#5** Add lightweight ID-only cluster query for surfacing (avoid eager-loading reps/centroids when only IDs/labels needed) — _Defer: broader refactor; current limit=1000 is adequate; revisit when tenant cluster counts approach 500+_
- [ ] **#9** Add `typeof` guards at `wp.hooks` usage sites, not just warn-and-continue (`main.tsx` + downstream consumers) — _Defer: keep rendering, guard at usage sites only; not a regression_
- [ ] **#10** Map `quality_score` from ORM model into domain `MediaIdentity` (pre-existing gap, not a regression) — _Defer: fix belongs in the detection pipeline, not the mapping layer_
- [ ] **#11** Optimize sovereign orphan-member cleanup cadence (`delete_orphan_rows()` in `IdentityMembersRepository`) for high-member tenants — _Defer: v0.1.0 runs cleanup every sync; revisit with profiling in roadmap Phase 2 to avoid repeated full-scan LEFT JOIN cost_
