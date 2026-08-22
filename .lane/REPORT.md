# L6-baseline report — EVAL-01 zero-rule arm + anti-straddle Δ guard

## 1. IMPORT PROVENANCE check output

Command, from `/home/ubuntu/w/int9/apps/prototype-description-service`, before the first pytest:

```text
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -c "import scripts.eval_harness.strata as m; print(m.__file__)"
```

Verbatim output:

```text
/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The imported module starts with `/home/ubuntu/w/int9`. No test evidence came from the shared venv `.pth` pin of `/home/ubuntu/vlm6-base/...`.

## 2. RED output (B.1)

T1 tests written before production. Collection failed because `compare_scored_runs` did not exist:

```text
==================================== ERRORS ====================================
___ ERROR collecting scripts/eval_harness/tests/test_anti_straddle_delta.py ____
ImportError while importing test module '/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/tests/test_anti_straddle_delta.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../../../.local/share/uv/python/cpython-3.12.7-linux-aarch64-gnu/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
scripts/eval_harness/tests/test_anti_straddle_delta.py:14: in <module>
    from scripts.eval_harness.report import (
E   ImportError: cannot import name 'compare_scored_runs' from 'scripts.eval_harness.report' (/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/report.py)
=========================== short test summary info ============================
ERROR scripts/eval_harness/tests/test_anti_straddle_delta.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 2.33s
```

Stamp test, same moment, production `_stamp_pipeline_provenance` still omitted `roster_epoch`:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______ test_provenance_stamp_records_variant_and_enabled_pipeline_flags _______

    def test_provenance_stamp_records_variant_and_enabled_pipeline_flags() -> None:
        provenance: dict = {}
        _stamp_pipeline_provenance(
            provenance, prompt_variant="v2", two_pass=True, dual_length=False, face_gate=True, eval_mode="standard"
        )
>       assert provenance == {
            "prompt_variant": "v2",
            "two_pass": True,
            "face_gate": True,
            "roster_epoch": "post-priv1",
        }
E       AssertionError: assert {'face_gate':...o_pass': True} == {'face_gate':...o_pass': True}
E
E         Omitting 3 identical items, use -vv to show
E         Right contains 1 more item:
E         {'roster_epoch': 'post-priv1'}
E         Use -v to get more diff

scene/tests/test_eval_harness_pipeline.py:165: AssertionError
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_pipeline.py::test_provenance_stamp_records_variant_and_enabled_pipeline_flags
1 failed in 1.10s
```

T2/T3 tests written before `zero_rule_baseline.py`:

```text
==================================== ERRORS ====================================
____ ERROR collecting scripts/eval_harness/tests/test_zero_rule_baseline.py ____
ImportError while importing test module '/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/tests/test_zero_rule_baseline.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../../../.local/share/uv/python/cpython-3.12.7-linux-aarch64-gnu/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
scripts/eval_harness/tests/test_zero_rule_baseline.py:11: in <module>
    from scripts.eval_harness.zero_rule_baseline import (
E   ModuleNotFoundError: No module named 'scripts.eval_harness.zero_rule_baseline'
=========================== short test summary info ============================
ERROR scripts/eval_harness/tests/test_zero_rule_baseline.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.96s
```

## 3. GREEN output (B.3)

After production (anti-straddle guard, roster-epoch stamp, zero-rule arm, markdown Δ):

```text
...............                                                          [100%]
15 passed, 7 warnings in 1.30s
```

Command (literal paths, `PYTHONPATH=$PWD`):

```text
python -m pytest scripts/eval_harness/tests/test_anti_straddle_delta.py scripts/eval_harness/tests/test_zero_rule_baseline.py scene/tests/test_eval_harness_pipeline.py::test_provenance_stamp_records_variant_and_enabled_pipeline_flags scene/tests/test_eval_harness_pipeline.py::test_v3_provenance_stamp_matches_v1_v2_mechanism -q
```

Characterization of *today* (pre-extension) is locked: `score_run_record` still emits caption metrics when fetch/score SHAs differ (`manifest_matches_fetch=False`); mixed `annotation_mode` already raises `ReportError` naming both stamps. The new `compare_scored_runs` is the comparison refusal.

## 4. REVERT-RED proof (B.4 / TEST-15)

### 4a. Stash of production `report.py` + `bakeoff.py` (tests kept)

```text
==================================== ERRORS ====================================
___ ERROR collecting scripts/eval_harness/tests/test_anti_straddle_delta.py ____
ImportError while importing test module '/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/tests/test_anti_straddle_delta.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../../../../.local/share/uv/python/cpython-3.12.7-linux-aarch64-gnu/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
scripts/eval_harness/tests/test_anti_straddle_delta.py:14: in <module>
    from scripts.eval_harness.report import (
E   ImportError: cannot import name 'compare_scored_runs' from 'scripts.eval_harness.report' (/home/ubuntu/w/int9/apps/prototype-description-service/scripts/eval_harness/report.py)
=========================== short test summary info ============================
ERROR scripts/eval_harness/tests/test_anti_straddle_delta.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.21s
```

Stamp test while stashed:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______ test_provenance_stamp_records_variant_and_enabled_pipeline_flags _______

    def test_provenance_stamp_records_variant_and_enabled_pipeline_flags() -> None:
        provenance: dict = {}
        _stamp_pipeline_provenance(
            provenance, prompt_variant="v2", two_pass=True, dual_length=False, face_gate=True, eval_mode="standard"
        )
>       assert provenance == {
            "prompt_variant": "v2",
            "two_pass": True,
            "face_gate": True,
            "roster_epoch": "post-priv1",
        }
E       AssertionError: assert {'face_gate':...o_pass': True} == {'face_gate':...o_pass': True}
E
E         Omitting 3 identical items, use -vv to show
E         Right contains 1 more item:
E         {'roster_epoch': 'post-priv1'}
E         Use -v to get more diff

scene/tests/test_eval_harness_pipeline.py:165: AssertionError
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_pipeline.py::test_provenance_stamp_records_variant_and_enabled_pipeline_flags
1 failed in 1.05s
```

### 4b. Invert the mismatch guard (`if mismatches:` → `if False and mismatches:`)

The refuse assertions themselves went red (not merely an import error):

```text
FFF                                                                      [100%]
=================================== FAILURES ===================================
________ test_compare_refuses_mismatched_score_manifest_sha_naming_both ________

    def test_compare_refuses_mismatched_score_manifest_sha_naming_both() -> None:
        candidate = _score(score_sha="c" * 64)
        baseline = _score(score_sha="b" * 64)
        delta = compare_scored_runs(candidate, baseline)
>       assert delta["refused"] is True
E       assert False is True

scripts/eval_harness/tests/test_anti_straddle_delta.py:166: AssertionError
___________ test_compare_refuses_mismatched_roster_epoch_naming_both ___________

    def test_compare_refuses_mismatched_roster_epoch_naming_both() -> None:
        candidate = _score(roster_epoch="post-priv1")
        baseline = _score(roster_epoch="pre-priv1")
        delta = compare_scored_runs(candidate, baseline)
>       assert delta["refused"] is True
E       assert False is True

scripts/eval_harness/tests/test_anti_straddle_delta.py:178: AssertionError
__________ test_compare_refuses_missing_roster_epoch_as_a_named_stamp __________

    def test_compare_refuses_missing_roster_epoch_as_a_named_stamp() -> None:
        candidate = _score(roster_epoch="post-priv1")
        baseline = _score(roster_epoch=None)
        delta = compare_scored_runs(candidate, baseline)
>       assert delta["refused"] is True
E       assert False is True

scripts/eval_harness/tests/test_anti_straddle_delta.py:190: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_anti_straddle_delta.py::test_compare_refuses_mismatched_score_manifest_sha_naming_both
FAILED scripts/eval_harness/tests/test_anti_straddle_delta.py::test_compare_refuses_mismatched_roster_epoch_naming_both
FAILED scripts/eval_harness/tests/test_anti_straddle_delta.py::test_compare_refuses_missing_roster_epoch_as_a_named_stamp
3 failed in 0.87s
```

### 4c. Invert zero-rule caption (`return ""`) and skip `baseline_delta` attach

```text
FFF                                                                      [100%]
=================================== FAILURES ===================================
____________ test_zero_rule_caption_is_context_echo_in_field_order _____________

    def test_zero_rule_caption_is_context_echo_in_field_order() -> None:
        """The rule is metadata-only: title, then caption, then description. No pixels."""
>       assert (
            zero_rule_caption(
                {
                    "title": "Title name",
                    "caption": "Caption line.",
                    "description": "Longer description.",
                }
            )
            == "Title name Caption line. Longer description."
        )
E       AssertionError: assert '' == 'Title name C... description.'
E
E         - Title name Caption line. Longer description.

scripts/eval_harness/tests/test_zero_rule_baseline.py:24: AssertionError
_______________ test_delta_markdown_surfaces_baseline_and_delta ________________
...
>       assert delta.get("refused") is not True
               ^^^^^^^^^
E       AttributeError: 'NoneType' object has no attribute 'get'
...
_________ test_delta_markdown_refuses_straddle_in_place_of_the_number __________
...
>       assert delta["refused"] is True
               ^^^^^^^^^^^^^^^^
E       TypeError: 'NoneType' object is not subscriptable
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_zero_rule_caption_is_context_echo_in_field_order
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_delta_markdown_surfaces_baseline_and_delta
FAILED scripts/eval_harness/tests/test_zero_rule_baseline.py::test_delta_markdown_refuses_straddle_in_place_of_the_number
3 failed, 2 warnings in 1.09s
```

Production restored after each invert. Final combined run: **15 passed**.

## 5. What shipped

**Zero-rule (stated):** for each held-out golden entry, `alt_text_draft` is the concatenation of non-empty `context_pack` fields `title`, `caption`, `description` in that order, joined by a space. Empty pack → empty caption. No pixels, no VLM, no identity claims. Same `acx-eval/v1` `run_record` shape as a bake-off fetch; scored by unmodified `score_run_record`. Split is L3's `golden.json` (20 held-out images). `assign_split` is not called.

**Anti-straddle:** `compare_scored_runs` refuses with `refused=True`, `metrics=None`, and a reason naming both stamps when `score_manifest_sha256` or `roster_epoch` disagree or either is missing. Markdown prints `REFUSED (...)` in place of the Δ. Never a silent omit, never a footnoted number.

**Roster epoch:** `_stamp_pipeline_provenance` always stamps `roster_epoch=post-priv1` (this tree is post-PRIV-1).

## 6. HEADLINE FINDING (honest-number mandate)

**There is no candidate VLM run-record on the L3 20-image held-out split in this branch, so there is no live model Δ to publish.** Publishing a confident Δ against a pre-L3 / pre-PRIV-1 artifact is exactly the straddle the guard now refuses.

Zero-rule **absolute** scores on the current 20-image held-out `golden.json` (metadata-only, `n_scored=20`, `n_failed=0`, `roster_epoch=post-priv1`, `score_manifest_sha256=8608ee9f9484d17f6a59a8855deac658fe62a1c4f62da7b4b4e4f376e8967aa6`):

| metric | zero-rule |
|---|---|
| insertion_rate | 1.0 |
| name_precision | 0.9545 |
| wrong_name_image_rate | 0.05 |
| must_right_failed_images | 0 / 20 defined |
| policy_violations | 0 |
| wrong_name_images | 1 |
| mean_gated_score | 0.95 |

Domain mix (imbalanced): faces 12, crowds 5, mirrors 1, low_light 1, people 1.

Context-echo scores this high because the rubric names already live in the WP `context_pack`. That is the product zero-rule: "republish the metadata." A VLM insertion_rate of 0.89 on the old 10-image selection looked like success; versus this floor it is not an improvement.

Identical-arm Δ on these 20 images is **undistinguished** (`n_paired=20`, Δ mean_gated_score=0, 95% CI includes 0). Headline from the guard: **we cannot tell yet at n=20.** A future candidate on this same split must beat 0.95 gated / 1.0 insertion with a CI that excludes 0, or the honest report is still "cannot tell."

## 7. Canon rules (verbatim) and satisfaction

### EVAL-01

> | EVAL-01<a name="eval-01"></a> | A model metric is reported with no random / heuristic / human / production baseline | **Require offline baselines**: compare to random, zero-rule, a simple heuristic, a human, and the existing solution on the same split; without them the number is uninterpretable | What is Δ versus zero-rule and versus current production? | S·r | [designing-ml-systems](../SOURCES.md#src-designing-ml-systems) |

Satisfaction: a zero-rule arm now exists on the **same** 20-image held-out split L3 established. Reports that attach it get per-metric baseline + Δ. Pre-L3 / pre-PRIV-1 numbers are marked SUPERSEDED rather than Δ'd. Human and production baselines are still missing — named as remaining, not faked.

### EVAL-23

> | EVAL-23<a name="eval-23"></a> | Production readiness is reported as one number; a count of tests implemented, an average across categories, or an offline accuracy figure | **Readiness is the weakest category, not the total**: score data, model, infrastructure, and monitoring coverage as four separate subtotals and report the minimum as the readiness number, because the four are not substitutable and a total lets strong monitoring hide zero data tests until the untested contract fails in production (worst-unit gating on cohorts is [[FAIR-01]](ml-systems.md#fair-01); per-slice floors are [[EVAL-04]](ml-systems.md#eval-04)) | What is the lowest of the four category subtotals, and what is missing from it? | J·r | [ml-test-score sec-VI.A](../SOURCES.md#src-ml-test-score) |

Satisfaction: Δ is per-metric, not one averaged readiness number. A refused comparison occupies the number's place. Weakest category here is **data**: n=20, severely imbalanced, no candidate on this split — that is the headline, not a hidden hole behind a caption score.

### MLDATA-09

> | MLDATA-09<a name="mldata-09"></a> | A quality-control or outlier filter removes the hard cases (extreme pose, occlusion, low resolution) from a corpus whose claim covers those conditions | **A filter that removes the regime under test deletes the test**: when cleaning a corpus, check each exclusion rule against the conditions the claim covers and keep the hard cells as declared strata rather than contaminants, because the filter's blind spot silently becomes the benchmark's: the number goes green by deleting the cases that would have moved it, and nothing in the report shows the deletion (↔ [[MLDATA-08]](ml-systems.md#mldata-08) the same hole when the collecting tool never captured the cell; eng [[PERF-03]](engineering.md#perf-03) coordinated omission is this exact mechanism in a load generator) | Which exclusion rules ran, and does any of them remove a condition the claim covers? | S·p | [janus-benchmark-c sec-1.1](../SOURCES.md#src-janus-benchmark-c) |

Satisfaction: the baseline consumes L3's `golden.json` as-is. `assign_split` is not re-run. Hard cells L3 left in held-out stay in the scored set. A nicer Δ was not obtained by redrawing.

### PROV-01 / PROV-02

**Genuinely absent** from `~/lane-canon/EVALCANON.md`, `~/lane-canon/RULES.md`, and `~/lane-canon/ENGCANON.md`. Table-row grep `^\|\s*PROV-0[12]` returned no hits. The only PROV row in those files is PROV-09 (prompt configuration lineage) in EVALCANON.md. This lane did not invent PROV-01/02 text. The change still stamps `roster_epoch` and `score_manifest_sha256` on run records / scored reports so a Δ can name both corpus identity and roster-spelling epoch.

### TEST-15

> | TEST-15<a name="test-15"></a> | Reviewing a passing test that guards an invariant, single-source count, or state property | **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01)) | If production regressed here, would this exact assertion turn red; have I seen it? | S·r | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) + [pragmatic-programmer ch-9](../SOURCES.md#src-pragmatic-programmer) |

Satisfaction: RED before production, GREEN after, then source-stash / line-invert revert-RED with the exact assertions (`refused is True`, caption equality, stamp dict). Restored.

## 8. T4 superseded figures

Banner inserted after the H1 of 20 markdown reports (numbers kept, not deleted). Reason: pre-L3 corpus and/or pre-PRIV-1 roster spelling → not Δ-comparable to the 20-image held-out split.

10-image selection (contamination): `docs/tasks/vlm/VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-report.md`, `...CapRL-Qwen3VL-4B-report.md`, `...MiniCPM-V-4.5-report.md`, `docs/tasks/20.0/E20-FUSION-staged-report.md`, `...E20-FUSION-adhoc-report.md`.

37-image reported (contaminated): `docs/tasks/vlm/VLM-2A-baseline-20260706-report.md`, `...VLM-2C-seeded-stub-score-20260707-report.md`, `docs/tasks/vlm/bakeoff-results/S0-determinism-anchor-report-20260714.md`, eleven `docs/tasks/altq/bakeoff-results/run-altq-*.md` files except the 646-interleave.

Other non-held-out caption reports: `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.md` (39/39), `docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3-report.md` (640/646, pre-PRIV-1 names).

Not marked: `S2A-face-determinism-anchor-run-20260811-face-report.md` (face bake-off, not caption-quality). Companion JSON report files were not edited (schema consumers); they are the same superseded artifacts as the marked markdown.

## 9. Exact list of files changed

`git diff --cached --stat` immediately before this commit:

```text
 .lane/REPORT.md                                    | 356 +++++++++++++++++++++
 .../scene/tests/test_eval_harness_pipeline.py      |  16 +-
 .../scripts/eval_harness/bakeoff.py                |   4 +-
 .../scripts/eval_harness/build_bakeoff_report.py   |  37 +++
 .../scripts/eval_harness/report.py                 | 215 +++++++++++++
 .../eval_harness/tests/test_anti_straddle_delta.py | 209 ++++++++++++
 .../eval_harness/tests/test_zero_rule_baseline.py  | 161 ++++++++++
 .../scripts/eval_harness/zero_rule_baseline.py     | 171 ++++++++++
 docs/tasks/20.0/E20-FUSION-adhoc-report.md         |   2 +
 docs/tasks/20.0/E20-FUSION-staged-report.md        |   2 +
 .../run-altq-646-interleave-v3-report.md           |   2 +
 ...n-altq-dual_length-context_distractor-report.md |   2 +
 .../run-altq-dual_length-standard-report.md        |   2 +
 .../run-altq-two_pass-context_distractor-report.md |   2 +
 .../run-altq-two_pass-standard-report.md           |   2 +
 .../run-altq-v1-context_distractor-report.md       |   2 +
 .../run-altq-v1-name_ablation-report.md            |   2 +
 .../bakeoff-results/run-altq-v1-standard-report.md |   2 +
 .../run-altq-v2-context_distractor-report.md       |   2 +
 .../run-altq-v2-name_ablation-report.md            |   2 +
 .../bakeoff-results/run-altq-v2-standard-report.md |   2 +
 docs/tasks/vlm/VLM-2A-baseline-20260706-report.md  |   2 +
 .../vlm/VLM-2B-bakeoff-CapRL-Qwen3VL-4B-report.md  |   2 +
 .../vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.md     |   2 +
 .../VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-report.md  |   2 +
 .../VLM-2C-seeded-stub-score-20260707-report.md    |   2 +
 .../S0-determinism-anchor-report-20260714.md       |   2 +
 .../S2A-determinism-anchor-run-20260811-report.md  |   2 +
 mk/evals.mk                                        |  16 +
 29 files changed, 1221 insertions(+), 4 deletions(-)
```

Working-tree paths:

- `apps/prototype-description-service/scripts/eval_harness/report.py`
- `apps/prototype-description-service/scripts/eval_harness/bakeoff.py`
- `apps/prototype-description-service/scripts/eval_harness/build_bakeoff_report.py`
- `apps/prototype-description-service/scripts/eval_harness/zero_rule_baseline.py` (new)
- `apps/prototype-description-service/scripts/eval_harness/tests/test_anti_straddle_delta.py` (new)
- `apps/prototype-description-service/scripts/eval_harness/tests/test_zero_rule_baseline.py` (new)
- `apps/prototype-description-service/scene/tests/test_eval_harness_pipeline.py`
- `mk/evals.mk` (new; baseline target only)
- 20 superseded caption-report markdown files listed in §8
- `.lane/REPORT.md`

`bakeoff_candidates.py` / YAML: not edited. Zero-rule is not a VLM registry row.

## 10. Findings (not this lane's regression)

`scene/tests/test_eval_harness_bakeoff.py` fixture `load_manifest(str(BAKEOFF_MANIFEST))` errors here without `GOLDEN_IMAGES_DIR` (`ManifestError` hash verification). The metadata-only L3 disjointness test still passes (`1 passed in 0.97s`). Assertions in that file were not weakened.

Root `Makefile` does not `include mk/evals.mk` (L4-surf's include is not on `int/round9`; editing `Makefile` is out of allowlist). Target is reachable as `make -f mk/evals.mk eval-zero-rule-baseline`.

## 11. HONEST STATUS: PARTIAL

T1 guard, T2 zero-rule arm, T3 Δ surface, and T4 superseded banners are in tree and tested. Remaining:

1. No candidate VLM run on the 20-image held-out split, so no live model Δ. The honest number is the zero-rule floor above plus "we cannot tell yet at n=20" until a same-split candidate exists whose CI excludes 0.
2. `make eval-zero-rule-baseline` is not on the root Makefile include graph until an allowlisted Makefile edit (or L4 merge) lands.
3. Human and current-production baselines from EVAL-01 are still absent.
4. Companion JSON reports were not bannered.

A confident-looking Δ on 20 images would have been the failure mode. This lane does not emit one.
