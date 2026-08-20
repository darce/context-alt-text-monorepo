# FIR-12 search adapter — design note (closes BR-26)

**Finding:** `FIR-12-BR-26` — the open-set measurement layer has no producer.

`scripts/eval_harness/fir_bakeoff_run.py` opens with:

> Does not run detect→embed→search. Callers inject `SearchResult` lists.

There is no such caller. Repo-wide, every reference to `SearchResult` outside
`open_set_identification.py` (the definition) and `fir_bakeoff_run.py` (the consumer)
is a test. The FIR-12 scoring layer — IET curves, FNIR/FPI, the F27 completeness gate,
the frozen-frame pins — is currently unreachable from real measurement data. Everything it
publishes is published about hand-built fixtures.

This note specifies the missing adapter so a lane can implement it without re-deriving the
seams. It does **not** specify running the bake-off; the downscaled 640-image root is lost
(rebuild from `sha256_source` is separate work). The adapter is a pure function of stored
§B run-records plus manifest GT, exactly like `face_assignment.py`, so it is fully
implementable and testable today.

## The score source already exists

The path from pixels to a similarity score is `face_assignment.py`, not `face_pass.py`.
`FacePassRow` carries `names: list[str]` and no scores at all — that is why the naive
"adapt face_pass" reading of BR-26 was rejected.

    §B face run-records (face_bakeoff.py | buffalo_bench.py)
      → collect_matched_faces(run_items, gt_by_media)
          → matched: list[MatchedFace]        # embedding, true_name, media_id, box_index, det_index
          → associations: dict[int, AssociationResult]
      → build_loo_gallery(probe, by_identity) → {name: prototype}
      → argmax_gallery(embedding, gallery)    → (s_max, name_star)

`argmax_gallery` is the 1:N search. `(s_max, name_star, true_name, media_id)` is four of
`SearchResult`'s six fields. The adapter's whole job is the remaining two — `gallery` and
`detected` — and the unit reduction.

## Four seams the adapter must get right

### 1. Gallery restriction, not leave-one-out

`build_loo_gallery` enrolls the entire matched corpus and excludes only the probe face.
FIR-12 declares something different: `GallerySplit` gives two **disjoint** enrollments
`g1` / `g2` keyed subject_id → `Template`, and `probes_for(split, gallery=...)` returns the
mated and non-mated `Template`s for a search against one of them.

The adapter must build gallery prototypes from that gallery's `Template.media_ids` only.
Under a disjoint split the probe is never enrolled in the gallery it searches, so the LOO
exclusion becomes an **assertion**, not a filter:

    assert probe.media_id not in gallery_media_ids

A probe whose media_id appears in the searched gallery means the split is broken. Filtering
it out silently — which is what reusing `build_loo_gallery` would do — converts a
construction bug into a slightly-optimistic score. Raise `FirBakeoffRunError`.

Non-mated probes come from `probes_for`, which promotes other-gallery enrollments to
non-mated at search time. Do not re-derive that rule; call `probes_for`.

### 2. Failure-to-acquire must be emitted, not dropped

`FaceDecision` exists only for probes that were §C-matched to a GT box. A GT face the
detector missed produces no decision — it survives only as `AssociationResult.unmatched_gt`
(GT indices) and the `AssignmentResult.missed_gt` count.

`open_set_identification._is_fnir_miss` counts `detected=False` as a miss. So an adapter
built from decisions alone silently omits every FTA from the FNIR numerator *and*
denominator, which deflates FNIR by exactly the detector's miss rate. That is the MLDATA-09
failure this module guards against everywhere else.

The adapter must walk `associations[media_id].unmatched_gt`, resolve each index against
`gt_by_media[media_id]` for its name, and emit:

    SearchResult(detected=False, top1_score=None, top1_name=None,
                 true_name=<gt name>, gallery=..., media_id=...)

**An unnamed (stranger) GT box that was missed must be dropped, not emitted with
`true_name=None`.** A non-mated search that never fired cannot produce a false positive
identification at any τ; emitting it inflates the FPI denominator with impossible searches.
Mated FTAs are real misses; non-mated FTAs are nothing. Encode that asymmetry explicitly
and test it — it is the one place where "be consistent" gives the wrong answer.

### 3. τ stays out

`SearchResult` is deliberately pre-threshold: `top1_score` plus `top1_name`, no decision.
`open_set_identification` sweeps τ to build the IET curve.

The adapter must therefore read `s_max` / `name_star` and must **not** read
`FaceDecision.decision`, `.predicted_name`, or `.tau_k`. Using `predicted_name` would bake
the k-fold operating point into the curve and collapse the sweep to one point that reports
0 FPI everywhere below τ_k. If the adapter calls `assign_open_set_kfold` at all it is only
for provenance (`tau_fit_status`, `effective_k`), never for the score.

Corollary: an empty gallery makes `argmax_gallery` return `(-inf, None)`. `-inf` is not a
score — it never fires at any τ and would count as a silent FNIR miss at every point on the
curve. Raise on an empty gallery instead.

### 4. One search per (media_id, gallery, subject_id)

F27's completeness gate keys mated units on `(media_id, gallery, subject_id)` and foil units
on `(media_id, gallery)`. `MatchedFace` is per **box** — `(media_id, box_index, det_index)`.
A still containing two boxes of the same subject yields two matched faces but is **one**
search unit.

Emitting both would make the F27 shortfall arithmetic count them as one submitted unit while
the FNIR denominator counts two — the completeness gate would read complete while the rate
is computed over an inflated denominator.

Reduction rule: group matched faces by `(media_id, gallery, subject_id)` and take the
**maximum** `s_max` over the group, carrying that face's `name_star`. A 1:N search over a
still returns the still's best candidate. `detected` is True if any box in the group was
acquired. Make this an explicit named function with its own test; do not inline it.

## Deliverable

New module `scripts/eval_harness/fir_search_adapter.py` exporting one entry point:

    def searches_from_run_records(
        run_items: Sequence[Mapping[str, Any]],
        gt_by_media: Mapping[int, Sequence[Any]],
        *,
        plan: RunPlan,
    ) -> tuple[dict[str, dict[str, list[SearchResult]]], list[SearchResult]]:
        """(searches keyed by stratum, overall_nonmated) — the exact score_run contract."""

The return shape is `score_run`'s two arguments, so the caller is a two-line composition.
Recall the exclusivity rule in `score_run`: per-stratum `nonmated` is legal **only** when
`overall_nonmated` is also supplied, and the adapter must populate both consistently — a
foil counted per-stratum and omitted from `overall_nonmated` trips the duplicate/coverage
guards.

New test file `scene/tests/test_eval_harness_fir_search_adapter.py` over synthetic
run-records. Minimum coverage, each proven RED against a stated mutant:

1. probe media_id present in the searched gallery → raises (seam 1)
2. missed named GT box → one `detected=False` mated search (seam 2)
3. missed stranger GT box → **no** search emitted (seam 2, the asymmetry)
4. adapter output uses `s_max`, not `predicted_name` — a fixture whose τ_k would reject
   still publishes the raw score (seam 3)
5. empty gallery → raises, never `-inf` (seam 3)
6. two boxes of one subject in one still → one search, score = max (seam 4)
7. round-trip: adapter output fed to `score_run` publishes `incomplete=False` on a
   fixture built to match a `RunPlan`'s declared units

## Explicitly not in scope

- Running the bake-off. The corpus root is lost; rebuild is separate.
- Changing `face_assignment.py`. The adapter composes it; it does not edit it.
- Changing `fir_bakeoff_run.py` or `open_set_identification.py`. If a seam above appears to
  require editing either, that is a finding to file, not a change to make.

## Canon

EVAL-18 (open-set stratum must be non-empty), EVAL-19 (FPI normalized by enrolled subjects),
MLDATA-09 (an unmeasured cell must never render as a number), JANUS 2.2 (mated-ness is per
gallery, not per still), rg-015 (a boundary adapter must not invent contract metadata),
TEST-15 (every test proven able to fail).
