# Scope: Occlusion-Scoped FIR and Description Bake-Offs

> **Metadata**
>
> - **Date**: 2026-08-19
> - **Task ID**: `FIR-12`
> - **Target Branch**: `feature/fir-12`
> - **Project**: `apps/prototype-description-service`
> - **Intake mode**: questions answered from heuristics canon + `distilled/` corpus per operator instruction, not asked of the operator. Every answer cites the rule or distilled source it came from.
> - **Epic**: E22 Commercial Face Identity Replacement

---

## Problem

Two bake-offs are wanted, in order:

1. **CPU bake-off** measuring FIR (face identity recognition) performance.
2. **GPU bake-off** measuring description/caption quality.

The corpus that both run against was believed lost. It is not: 640 of 643 manifest entries were recovered by sha256 against `/Volumes/Butter/WP/vlm/app/public/wp-content/uploads`. The question this scope answers is *what can honestly be measured on what was recovered*, and in what order.

---

## Corpus state (measured 2026-08-19, not assumed)

| Fact | Value | Source |
| --- | --- | --- |
| Manifest entries | 646 (643 consented + 3 `license: unassigned`) | `benchmarks/manifests/corpus646-interleave-manifest-20260716.json` |
| Recovered at pinned sha256 | **640 / 643** | hash sweep over 697 originals on Butter |
| Unrecoverable | 3 (`media_id` 260, 261, 262) | 5 on-disk variants each, none matching the pinned hash |
| Entries with `face_count > 0` | 530 | manifest (operator ground truth) |
| Entries with `face_boxes` | 530 | manifest |
| `reference_facts` / `spatial_facts` populated | **0 / 646** | manifest; keys absent from the v3 entry schema |
| Roster subjects | 130 declared, 130 present | manifest |
| Filenames carrying an Instagram scrape signature | 357 / 646 | `_<9+digits>_` family |
| **Exact-duplicate images** (identical bytes, distinct `media_id`) | **3 pairs** | 486≡488, 196≡471, 93≡468 |

The 3 unrecoverable entries are all `ryannalexandria_*` scrape-signature files that FIR-11's provenance remediation excludes regardless, so the loss costs no coverage.

**Duplicate policy.** Two of the three duplicate pairs carry identities (`Saffron Cypress` at 196≡471; `Gilded Cypress` + `Indigo Pennant` at 93≡468). Duplicated probes double-count a subject and break the independent-paired-subject unit any interval or sizing is computed in. The selection manifest keys on unique sha256, so each pair is collapsed to a single retained `media_id`; this is now an explicit rule, and the dropped `media_id`s (468, 471, 488) are recorded in the artifact rather than silently absent.

### Caption source for cell assignment

`docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3.json` — Qwen3-VL-30B-A3B-Instruct (Q4_K_M), prompt variant v3, two-pass, GPU, 646 items / 6 errors. Carries full `alt_text_long` plus structured `people[].appearance` facts. This is a **prior GPU run**, used here only as metadata to assign strata; it is not the phase-2 benchmark.

### Occlusion cells actually available

Tagged from the captions above; `faces>0` uses manifest ground truth.

| Cell | images | faces>0 | unique subjects |
| --- | --- | --- | --- |
| `sunglasses` | 55 | 48 | 34 |
| `eyeglasses` | 30 | 24 | 23 |
| `occluded_by_object` | 23 | 19 | 17 |
| `hand_occl` | 7 | 5 | 4 |
| `mask` | 3 | 3 | 3 |
| `helmet_visor` | 2 | 0 | 0 |
| `veil` / `goggles` / `hair_occl` | **0** | 0 | 0 |
| `profile_pose` | 27 | 15 | 13 |
| `eyes_closed` | 19 | 16 | 11 |
| `blur` | 15 | 11 | 11 |
| `lowlight` | 98 | 73 | 36 |
| `small_face` | 10 | 9 | 7 |
| `crowd` | 39 | 33 | 23 |

Rolled into strata over the 640 unique-sha256 entries (authoritative values are `strata_counts` in `benchmarks/manifests/fir12-selection-v1.json`): **A** true occluder (32 img / 20 subj), **B** eyewear (80 / 47), **C** pose (34 / 15), **D** capture conditions (87 / 40), **E** clean control (407 / 109). Cells overlap — an image tagged both `sunglasses` and `lowlight` is assigned by strata precedence A > B > C > D > E, so the stratum totals do not equal the sum of the tag rows above.

This distribution is *expected*, not defective: the occluded-FR survey records that "sunglasses and scarves dominate real sets" (§VII.A).

---

## Intake answers (from canon, not from the operator)

**Q1 — What is the CPU bake-off's metric contract?**
Open-set 1:N identification with **disjoint galleries**, reporting **FNIR against FPI at a fixed score threshold** (IET-style), not Rank-1/CMC alone (`janus-benchmark-c` §2.2, §2.3.4). CMC may be reported for diagnosis. FPI is reported as a **count**, not a rate, because a rate normalised by non-mated search volume improves when the detector emits more false detections (same source, §2.3.4).

**Q2 — Is detection inside or outside the error budget?**
Inside. The shipped path is detect → embed → search, so a failed detection of the subject of interest **counts as an identification miss** (`janus-benchmark-c` end-to-end mechanism; occluded-FR survey §II names occluded detection an OFR precondition, not a solved upstream). Stage-isolated recognition-on-GT-crops is kept for diagnosis only and must not be substituted for the operational number.

**Q3 — Which gallery × probe cell?**
**Clean gallery × occluded probe.** The survey states this is the normal OFR production configuration and that clean–clean operating points must not be transferred to it without re-measure (§I). Concretely: gallery templates drawn from stratum E, probes from A/B/C/D.

**Q4 — Can this corpus support an occlusion-robustness claim?**
Partly, and the boundary is sharp. EVAL-28 asks which real or realistic-accessory occlusion cells support the claim; MLDATA-07 requires per-intersection unique-subject counts before any global claim. Only **B eyewear** (80 img / 47 subj) is populated enough to carry a comparative claim. **A true-occluder** (32 / 20) is descriptive-only. `mask`, `veil`, `goggles`, `hair_occl` are **declared empty cells** — reported as such, never silently absorbed into an aggregate.

**Q5 — May the empty cells be filled synthetically to unblock the claim?**
No. EVAL-28 rules that synthetic rectangles, noise, and unrelated-image fills are not representative of real accessory occlusion, and the survey's five-scenario ladder ranks them least real (§VII.A). Our corpus sits at scenario (1), real occlusions — the strongest tier — and must not be diluted down to preserve a claim. Synthetic occlusion remains legitimate as *training* augmentation (ORFE, §III.B.4); that is a different question from eval.

**Q6 — May thin cells be dropped to clean up the report?**
No. MLDATA-09: a filter that removes the regime under test deletes the test; keep hard cells as declared strata rather than contaminants. IJB-C's unconstrained-variation mechanism says the same for pose and occlusion covariates.

**Q7 — Does the pipeline's current occlusion handling get to be called occlusion handling?**
No. EMB-11 states occlusion is spatial support, not a scalar penalty: scaling a global similarity by a quality/confidence score with no estimate of *which* support is occluded does not qualify. The CPU bake-off therefore **measures** the occluded cell; it does not certify occlusion handling. If a cross-occlusion strategy is later claimed, the survey requires naming the branch (ORFE / OAFR / ORecFR) and matching the ablations to it.

**Q8 — Why CPU-FIR first, then GPU-descriptions?**
Because descriptions bind names to faces by left-to-right face-box position, description-naming correctness is downstream of identity correctness: a description bake-off run before FIR is pinned measures two coupled error sources as one number. The survey's ordering agrees at pipeline level (detection → recognition precedes downstream consumption). FIR also runs on CPU and is the cheaper leg, so the expensive GPU leg is not spent on a moving identity baseline.

**Q9 — What can the GPU description bake-off actually score?**
Identity-grounded metrics only: `must_right` (530/646), `hallucinated_names`, `missing_identities`, `wrong_name_hits`, `tag_coverage`. **Fact-level hallucination is not scoreable**: `reference_facts` is absent from the v3 entry schema and non-empty on 0/646 (the `golden150-draft` has the field but only 1/150 annotated). Any hallucination-first ranking over facts needs a v4 schema plus an operator annotation pass — out of this scope.

Two corrections to the naive reading of that limit:

- `easy_wrong` is **also 0/646**. This does not disable wrong-name scoring: `bakeoff.py` builds the trap set as `present_identities ∪ must_right ∪ easy_wrong ∪ roster`, so the 130-name roster supplies the distractors. What is lost is only the ALTQ-1 `context_distractor` transform, which injects an entry's first `easy_wrong` name into the context pack — that specific adversarial condition cannot run.
- Spatial placement is **partly derivable, not absent**. `export_identities.spatial_facts_from_regions` synthesises `left_of` facts from named face-box centres with no human annotation. Over this manifest that yields **17 images / 23 pairs** (only 17 entries carry ≥2 distinctly named boxes). Report as a diagnostic; 17 images cannot carry a placement claim (MLDATA-07).

**Q10 — Noisy ground-truth boxes?**
Report under an explicit include/exclude policy, ideally both tables (`janus-benchmark-c` ignore-flags mechanism). The 116 entries with `face_count = 0` serve as natural non-mated / distractor media for the open-set leg.

**Non-functional triggers**: none of the question-bank triggers fire. Both bake-offs are offline batch evaluation with no user-facing latency target, no external write path, no spike surface. Determinism and cost are the operative constraints, not p95.

---

## MVP scope

**Phase 1 — CPU FIR bake-off**

1. Freeze a selection manifest over the recovered 640 with the five strata declared as first-class fields.
2. Build disjoint galleries G1/G2 from stratum E (one template per subject), probes from A/B/C/D plus non-mated probes.
3. Run end-to-end detect → embed → search on CPU. Failed detection of the subject counts as an ID miss.
4. Report paired **FNIR / FPI at fixed t**, per stratum, with unique-subject counts per cell and both ignore-policy tables.

**Phase 2 — GPU description bake-off**

5. Re-run descriptions on the frozen selection with FIR identities pinned from Phase 1.
6. Score identity-grounded metrics only; report per stratum.
7. Report cost and cost per image.

## Success criteria

- Every reported cell carries its unique-subject count; no aggregate hides a cell (MLDATA-07).
- `mask`, `veil`, `goggles`, `hair_occl` appear in the report as **declared empty**, not omitted (MLDATA-09).
- The operational FIR number is end-to-end; any GT-crop number is labelled diagnosis-only (`janus-benchmark-c`).
- Open-set errors are reported as FNIR/FPI at a declared threshold, never Rank-1 alone.
- Phase 2 runs against identities pinned by Phase 1, not re-derived.
- No claim of "occlusion handling" is made from a scalar-quality path (EMB-11).

## Not doing

- No mask / veil / goggles robustness claim — cells are empty.
- No synthetic occlusion to fill eval cells (EVAL-28). Training-side augmentation is a separate question.
- No fact-level hallucination scoring — `reference_facts` is 0/646 and absent from the v3 schema; needs a v4 schema + operator annotation pass.
- No placement *claim* — the 17 derivable-pair images are reported as a diagnostic only.
- No re-litigation of the 357 scrape-signature provenance entries — FIR-11 owns that remediation.
- No recovery attempt on `media_id` 260/261/262 — pinned bytes are gone and FIR-11 excludes them anyway.
- No new image sourcing in this task.
- No GPU spend before Phase 1 is green.

## Assumptions

- `/Volumes/Butter` stays mounted for both phases; if not, the pixel root must be re-pinned before any run.
- The manifest's `face_count` / `face_boxes` are treated as operator ground truth; caption-derived strata tags are **not** ground truth and are marked as such in the selection artifact.
- Phase 2 hands off to a `VLM-*` task ref rather than continuing under `FIR-12`.
