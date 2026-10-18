# FIR-12 Phase 1 — CPU FIR bake-off harness: implementation report

> **Metadata**
>
> - **Date**: 2026-08-20
> - **Task ID**: `FIR-12`
> - **Branch**: `feature/fir-12` @ `dbcd785a808d4bb1fdf53d48734f7bfc68a3a75b`
> - **Base**: `b499ed3721...` (pre-wave)
> - **Scope note**: [docs/scopes/occlusion-scoped-bakeoffs.md](../../scopes/occlusion-scoped-bakeoffs.md)
> - **Epic**: E22 Commercial Face Identity Replacement

## What shipped

Three eval-harness modules and their tests — the measurement layer for the CPU FIR bake-off.
No bake-off has been run; this is the instrument, not a result.

| Module | Responsibility |
| --- | --- |
| `scripts/eval_harness/open_set_identification.py` | FNIR / FPI at a fixed score threshold (IET), per `janus-benchmark-c` §2.3.4 |
| `scripts/eval_harness/gallery_split.py` | Disjoint G1/G2 gallery construction plus non-mated probe sets |
| `scripts/eval_harness/strata_join.py` | Joins run records to the frozen FIR-12 selection strata and renders per-cell rows |

1,562 lines added across 6 files. No production code outside `scripts/eval_harness/` was touched.

## Design decisions worth recording

**FPI is an integer count, never a rate.** A rate normalised by non-mated search volume
improves when the detector emits *more* false detections, so the metric would reward the
failure it exists to catch. The count is pinned by a dedicated anti-gaming test.

**The `>` / `>=` asymmetry between FPI and FNIR is source convention, not a defect.** It comes
from `janus-benchmark-c` §2.3.4 and was declared an accepted non-finding in every review brief
so reviewers would not spend budget re-deriving it.

**Detection failure counts as an identification miss.** The shipped path is detect → embed →
search, so a failed detection of the subject of interest is inside the error budget (scope Q2).
Stage-isolated recognition-on-GT-crops remains available for diagnosis and must not be
substituted for the operational number.

**Unmeasured cells are structurally distinguishable from perfect cells.** `IETPoint` carries a
`measured: bool` and `fnir: float | None`, and `__post_init__` rejects both
`fnir=0.0`-when-unmeasured and `fnir=None`-when-measured. The invariant is enforced by
construction rather than by a test, so a stratum with zero mated probes cannot render `0.000`
alongside genuinely measured cells (MLDATA-09, EVAL-18).

**Coverage is reported, not assumed.** `strata_join` carries `manifest_images` per stratum
alongside the joined count and exposes `coverage_gaps()`; a truncated run marks its rows
`incomplete` instead of rendering the same shape as a full run (MLDATA-07).

**Unique-subject counts come from the manifest, not the run record.** `FaceRunItem` carries no
subject field, so subject resolution goes sha256 → media_id → record, keyed off the selection
manifest's `present_identities`. Unknown keys raise rather than silently resolving to zero.

**`probes_for` does not raise on an empty mated set.** FPI over the non-mated probes is
independently meaningful even when FNIR is not measurable; suppressing the whole cell would
discard a real number. `ProbeSet.fnir_measurable` carries that distinction instead. Empty
*non-mated* still raises.

## Verification

Adversarial two-round `/review-parallel` against the heuristics canon: 1 local Claude reviewer
plus 4 remote grok-4.6-high reviewers on the OCI VM per round.

- **Round 1** raised 6 findings (`FIR-12-BR-01` … `BR-06`) — two HIGH, three MEDIUM, one LOW.
  Two were test-strength gaps found by mutation, not by reading.
- **Fix wave** ran as two parallel remote lanes (F1: `strata_join`; F2: `open_set_identification`
  + `gallery_split`), consolidated at `dbcd785a8`.
- **Round 2** returned **pass with zero new findings**. Closure was audited by exercising the
  production path — real `FaceRunItem` instances, not dict stand-ins — and by re-running every
  named mutant on `/tmp` copies. A regression reviewer confirmed all seven round-1-correct
  properties still hold, that the FPI anti-gaming test is byte-identical to its pre-wave form,
  and that no test was deleted or weakened.

All 6 findings are `resolved_on_branch` at `dbcd785a8`. Findings live in the handoff DB; query
them with `review_findings(review={"operation":"list","task_ref":"FIR-12"})`.

Suite evidence at this HEAD (remote VM, per the full-suite-on-remote mandate): **1232 passed,
4 failed, 4 skipped**. The 4 failures reproduce identically at the pre-wave base `b499ed372`
and are unrelated to this branch.

## Open threads

- **Phase 1 step 3 is not built.** `fir_bakeoff_run.py` — the runner that composes gallery
  split, embedding, search, and strata join into the reported table — is the next slice. It is
  the component that must render an unmeasured cell as "not measured" rather than `0.000`.
- **No bake-off has been run.** Every number in this report is about the harness, not about
  face recognition performance.
- **Phase 2 (GPU descriptions) hands off to a `VLM-*` task ref**, not to `FIR-12`.
