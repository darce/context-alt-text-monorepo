# Lane N11 — DESCQUAL-2 BR-35 + BR-40

**Branch:** `lane/n11` @ `f9aada4e` (BR-40) on `7742c432` (BR-35) on `774f8178`.
**Scope:** tests only. Did not touch `pilot_draw.py` guards or any other file.

## Canon (RULES.md / JANUS.md)

Relied on:
- **AUDIT-08** — design-based π requires a known frame; declared `strata_counts` must match entries or `N_h`/`inclusion_probability` is a lie.
- **AUDIT-11** — ICC/deff belong to the cluster design, not a 30-image cost-and-instrument pilot (BR-17).
- **AUDIT-13** — nonresponse is bias, not a replacement draw that grows `n`.
- Finding tags: **rg-005**, **rg-015**, **TEST-15**.

JANUS.md read (open-set galleries / IET / E2E identification). None of those rows fire on this sampling-pilot pin.

## BR-35 — pin frame-size parity guard

Parametrized test `test_draw_pilot_rejects_declared_vs_entry_count_mismatch` builds a mini-manifest then mutates `B_eyewear` declared images in both directions (declared > observed, declared < observed). Asserts the guard's own message (`entry counts per stratum do not match declared strata_counts`) plus both dict dumps. Guard itself unchanged.

### Mutants (TEST-15)

- **m1** `if False and frame_sizes != declared_counts:` — **RED** `2 failed, 42 passed in 0.54s`
- **m2** `if any(frame_sizes[k] > declared_counts[k] for k in frame_sizes):` (one-directional; catches observed>declared only) — **RED** `1 failed, 43 passed in 0.52s`

Restored: `git diff --exit-code -- scripts/eval_harness/pilot_draw.py` after each.

Commit: `7742c432` `test(eval): DESCQUAL-2 BR-35 pin frame-size parity guard`

## BR-40 — allowlist + behaviour, not name theatre

Kept the cheap token denylist. Added fail-closed allowlist of every public module-level callable and every public method on every public class. Failure message names the set as the review checkpoint (do not silently append). Added `test_drawn_unit_set_never_grows_and_entrypoints_return_no_icc`: draw is a subset of the frame, exactly n distinct shas, same seed → same set, no public entrypoint returns a proper superset, `report_rows` keys have no ICC/deff fields.

### Mutants (TEST-15)

Each appended real working code to `pilot_draw.py`, then restored.

- **m3** genuine one-way ANOVA ICC named `one_way_rho` (returns `0.8823529411764706` on `[(1,2),(3,4),(5,6)]`; no `estimate_icc` token in source) — **RED** `2 failed, 43 passed in 0.64s`
- **m4** genuine replacement draw `top_up_nonresponse` (n=30 → 33, extras disjoint) — **RED** `2 failed, 43 passed in 0.59s`
- **m5** same replacement as `PilotDraw.fill_gaps` (getmembers hole) — **RED** `2 failed, 43 passed in 0.59s`
- **m6** same estimator named `estimate_icc` (no-regression) — **RED** `2 failed, 43 passed in 0.57s`

No survivor. Restored after each: `git diff --exit-code -- scripts/eval_harness/pilot_draw.py`.

Commit: `f9aada4e` `test(eval): DESCQUAL-2 BR-40 allowlist pilot public surface`

## Full-suite gate

```
4 failed, 1340 passed, 4 skipped, 10 warnings in 47.95s
```

The 4 failures are the pre-existing PGPASSWORD production-boot tests (`test_describe_route::test_create_app_registers_route_and_upload_cap` and three `test_describe_run_reclaim` startup tests). Not ours. Baseline at 774f8178 was 4 failed / 1337 passed / 4 skipped; +3 tests (2 BR-35 params + 1 BR-40 behaviour).

## Noticed, not fixed

- `_write_manifest` always derives `strata_counts` from entries, so the parity guard cannot be exercised through the helper without post-write mutation. Left the helper alone.
- MCP tools unavailable this session; Python-API handoff not recorded (lane report is the deliverable).
