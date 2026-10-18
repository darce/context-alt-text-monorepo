# DESCQUAL-2 — fact-annotation pilot: implementation report

**Branch:** `feature/descqual-2` · **Scope:** [`docs/scopes/descqual-2-fact-annotation-pilot.md`](../../scopes/descqual-2-fact-annotation-pilot.md)

DESCQUAL-2 builds the measurement instrument for description quality: a design-based
sampling core, a pre-registered full-study n, and a cost-and-instrument pilot that draws
from the frozen FIR-12 640-image frame. It does not measure description quality yet — it
makes that measurement sizeable, auditable, and reproducible.

## What shipped

| Surface | What it is |
| --- | --- |
| `scripts/eval_harness/audit_sampling.py` | Design-based sampling core: frame projections, Kish effective cluster size, design effect, `size_for_margin`, proportional `allocate` with precision floors, `draw` / `draw_two_stage`, `estimate_icc` with a Fisher-z interval. |
| `scripts/eval_harness/pilot_draw.py` | The pilot instrument: `draw_pilot`, `emit_annotation_packet`, `select_gold_items`, `PilotDraw.report_rows`. ICC-blind and deff-blind by construction. |
| `docs/scopes/descqual-2-fact-annotation-pilot.md` | The pre-registered design: n table, precision floors, MVP pilot definition, gold scheme, Not-Doing list. Every published number is executable and pinned. |
| `scene/tests/test_eval_harness_audit_sampling.py` | Sampling-core pins, including the scope-doc fence pins. |
| `scene/tests/test_eval_harness_pilot_draw.py` | 23 pilot-instrument pins. |

## Design decisions worth recording

**The design effect's `a` must come from a PSU partition of the frame being sized (AUDIT-11).**
This is the decision the task kept re-learning. The whole frame partitions into 241 PSUs with
`Σm = 640`, `Σm² = 6942`, so `a = 6942/640 = 10.846875`. The `B_eyewear` slice partitions into
55 PSUs with `Σm = 80`, `Σm² = 168`, so `a = 2.1`, `deff = 1.2213`, and the precision floor is
`n = 48`. An earlier revision instead took `a = 2.36` from a labeled-membership join over 47
overlapping subjects — whose `Σm` is 75, not 80 — and applied it to `population = 80`. That is
illegal: the join is a legitimate diagnostic *at population 75* (where it gives `n = 47`), and
nowhere else. Both are now computed, both are sized against their own frames, and a test
asserts the two answers differ so they can never be conflated again.

**The pilot does not produce the number the full study is sized by.** The ~30-image draw is a
cost-and-instrument pilot: minutes per image, rubric α, per-annotator gold accuracy, and the
nonresponse rate. It is explicitly *not* the source of the ICC or the design effect. An ICC
point estimate from 30 images carries a Fisher-z interval whose implied n spans 84..397 — the
entire planning table — so feeding it into `size_for_margin` is cargo-cult precision (AUDIT-11).
The planning n is pre-registered at the ICC=0.30 sensitivity point (`n = 239`). `pilot_draw`
enforces this structurally: the module has no ICC or deff estimator, and a test goes RED if one
is added.

**Gold is drawn from the frame *outside* the probability sample, in addition to it.** Selecting
gold from within the drawn sample would consume design-based n — the QC scheme would eat the
measurement it exists to protect. Gold known answers may not come from the caption pool being
judged, and may not be authored by anyone on the live annotation queue (HITL-03); the `GoldItem`
constructor refuses both.

**Unannotatable images are nonresponse to report, never a slot to refill (AUDIT-13).** There is
no replacement-draw path, and a test goes RED if one is added.

**`declared_empty_cells` is passed through verbatim, never recomputed (MLDATA-09, rg-015).** The
manifest declares `mask_sufficient_n`, `veil`, `goggles`, `hair_occl` as empty. A projector that
re-derived "empty" from observed counts would silently disagree with the declaration the frame
was frozen under.

**Every number the scope doc publishes is executable and pinned.** The doc's fenced blocks are
collected, `exec`'d against the shipped module, and their published values asserted — so a doc
that drifts from the code fails the suite rather than quietly misleading an operator (rg-006).

## Verification

Full `scene/tests` on the remote VM against the merged tree
`28891fbdc379e1eae5cb6790e3beb2d729f95df5`: **1318 passed, 4 skipped, 4 failed**. The four
failures are the pre-existing `test_describe_route` / `test_describe_run_reclaim` PGPASSWORD
production-boot failures, unrelated to this task.

Every fix lane was verified by independent coordinator mutants rather than accepted on its own
report. The pilot module took 13 of them; 12 went RED, including the two that matter most —
appending a real ICC estimator, and appending a real replacement-draw path — which proves the
BR-17 and AUDIT-13 absence tests are behavioural pins rather than grep-shaped decoration. The
sampling cells were re-derived from `benchmarks/manifests/fir12-selection-v1.json` by hand,
bypassing the module: whole-frame `n` = 84 / 114 / 198 / 239 / 261 / 397 at ICC 0 / 0.044 / 0.2 /
0.3 / 0.361 / 1.0; `B_eyewear` `n = 48`; unclustered at population 80, `n` = 44 / 36 / 29 for
margins 0.10 / 0.125 / 0.15. All matched.

The MVP pilot was run end to end at n = 30, seed 0: allocation
`{A:1, B:4, C:2, D:4, E:19}`, 30 dual-annotator packets, 3 gold items (one hard, one
batch-matched, one random), gold disjoint from the sample at every seed 0..23, and every one of
the 32 `A_true_occluder` frame units reachable across 200 seeds.

## Open threads

Tracked live in the handoff DB, not here — query with
`review_findings(review={"operation":"list","status":"open","task_ref":"DESCQUAL-2"})`. In
summary: the scope-doc fence pin generalises over fences but not over every published number;
`draw_pilot`'s frame-size parity guard is unpinned; and `select_gold_items` truncates its arm
mix by list prefix when fewer than three gold items are selected.

The pilot has not been *run* against real annotators — that is the next slice, and the outputs
it owes are minutes per image, cost per image, rubric α, and the nonresponse rate.
