# L7-l3fix report — restore weakened assertions; derive stale 37-pins

## 1. IMPORT PROVENANCE check output

Command run from the service dir before the first pytest invocation in this lane:

```text
/home/ubuntu/w/L3-split/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The imported module starts with `/home/ubuntu/w/L3-split`. No test evidence came from the shared venv's pinned `vlm6-base` tree.

## 2. TDD evidence

### RED output (B.1) — restored original bakeoff predicates, before xfail / reported-corpus pins

Predicted failures: selection has no `>= 2` multi-person-plus-strangers entry; selection paths are not in reported golden, so the restored `present_identities` loop dies on membership.

```text
FF                                                                       [100%]
=================================== FAILURES ===================================
_____________ test_entries_present_identities_match_golden_corpus ______________
scene/tests/test_eval_harness_bakeoff.py:148: in test_entries_present_identities_match_golden_corpus
    assert entry.path in golden_by_path, (
E   AssertionError: mock_images/ccqw-antartica.jpg: not in golden corpus (new image needs README bootstrap)
E   assert 'mock_images/ccqw-antartica.jpg' in {'mock_images/Breiðamerkurjökull.jpg': GoldenEntry(...), ...}
_________________ test_manifest_covers_discriminating_classes __________________
scene/tests/test_eval_harness_bakeoff.py:162: in test_manifest_covers_discriminating_classes
    assert any(
E   AssertionError: manifest lost its multi-person-plus-strangers association entry
E   assert False
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_bakeoff.py::test_entries_present_identities_match_golden_corpus
FAILED scene/tests/test_eval_harness_bakeoff.py::test_manifest_covers_discriminating_classes
2 failed, 3 warnings in 1.28s
```

That is a finding, not a license to delete the assertions. `ccqw-candid.jpg` (4 faces, 2 named) and `mcm-planecrash.jpg` live in the reported half. The selection half does not carry them.

### RED output (B.1) — the 14 live-golden `== 37` pins, run before any count rewrite

Do not trust the brief's line numbers blindly. Actual failures on this worktree:

```text
FFFFFFFFE                                                                [100%]
=================================== FAILURES ===================================
E   AssertionError: assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_cli.py:3011
E   AssertionError: assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_cli.py:3176
E   AssertionError: assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_cli.py:2856
E   AssertionError: assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_cli.py:2856
E   assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_determinism_anchor.py:491
E   assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_determinism_anchor.py:511
E   AssertionError: assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_face_metrics.py:1478
E   AssertionError: assert 20 == 37
/home/ubuntu/w/L3-split/apps/prototype-description-service/scene/tests/test_eval_harness_report.py:3051
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_cli.py::test_score_ignore_list_cannot_defeat_wrong_name_floor
FAILED scene/tests/test_eval_harness_cli.py::test_score_recognition_disabled_corpus_fails_wrong_name_floor_vacuity
FAILED scene/tests/test_eval_harness_cli.py::test_score_persisted_verdict_not_ready_on_real_golden
FAILED scene/tests/test_eval_harness_cli.py::test_score_f1d2_control_clean_real_golden_not_ready
FAILED scene/tests/test_eval_harness_determinism_anchor.py::test_coverage_gaps_keep_under_sampled_field_after_single_population
FAILED scene/tests/test_eval_harness_determinism_anchor.py::test_coverage_gaps_meet_threshold_when_fully_populated
FAILED scene/tests/test_eval_harness_face_metrics.py::test_positional_vacuity_signal_on_real_golden_corpus
FAILED scene/tests/test_eval_harness_report.py::test_score_run_record_positional_vacuity_signal_on_real_golden
ERROR scene/tests/test_eval_harness_bakeoff.py::test_manifest_covers_discriminating_classes
8 failed, 7 warnings, 1 error in 3.16s
```

Follow-on pins behind those helpers (`len(ignore_pairs) == 37`, `ignored_wrong_names == 37`, `excluded_images == 37`, `counts.scored == 37`, `g_gaps["face_boxes"]["total"] == 37`, `must_right_defined_images == 34`) never executed until the first `len(entries) == 37` was unblocked. Decision per assertion: all of these are (a) derive from the scored manifest. None is a load-bearing literal. Blanket `37 → 20` was not used.

Unblocking the helper then revealed a genuine composition gap, not a stale 37:

- `test_score_empty_rubric_keys_on_scored_set_not_manifest` asserts `len(no_mr_ids) == 3`. Post-split reported golden has **0** empty-must_right entries (media 27/34/35 were train). The `== 3` pin is kept as an `xfail(strict=True)` (FIR-ORCH-BR-23). F1-8 itself is proved on a scratch copy that still has must_right on unscored rows.

### GREEN output (B.3) — after xfail + reported-corpus pins + derived counts

```text
x.xx.............                                                        [100%]
14 passed, 3 xfailed, 22 warnings in 3.51s
```

Nodes: restored identity-drift xfail; selection `>=2` xfail; selection planecrash xfail; live reported-corpus pins; scratch drop TEST-15; CLI ignore-list / rec-off / not_ready / f1d2; coverage-gap totals derived from `len(entries)`; truncated-list discrimination; positional vacuity 0/N; boxed scratch discrimination; report vacuity on real golden.

Later F1-8 scratch + bakeoff fixture metadata-only:

```text
x...x.                                                                   [100%]
4 passed, 2 xfailed, 7 warnings in 2.04s
```

### REVERT-RED proof (B.4)

**Defect 1.** Removed `xfail` from `test_selection_covers_multi_person_plus_strangers` (production-fix revert of the known-gap mark). Predicted message: selection lost multi-person-plus-strangers.

```text
F                                                                        [100%]
=================================== FAILURES ===================================
______________ test_selection_covers_multi_person_plus_strangers _______________
scene/tests/test_eval_harness_bakeoff.py:192: in test_selection_covers_multi_person_plus_strangers
    _assert_multi_person_plus_strangers(
scene/tests/test_eval_harness_bakeoff.py:143: in _assert_multi_person_plus_strangers
    assert any(
E   AssertionError: selection manifest lost its multi-person-plus-strangers association entry
E   assert False
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_bakeoff.py::test_selection_covers_multi_person_plus_strangers
1 failed, 1 warning in 1.14s
```

xfail restored after this proof.

**Defect 1 assertion of record.** Scratch-drop of `mcm-planecrash.jpg` and the `>=2` carrier from a copy of reported golden (shipped as `test_reported_discriminating_class_guards_go_red_on_scratch_drop`) passed: both restored predicates raise `AssertionError` matching `multi-person-plus-strangers` and `context-conflicts-pixels`.

**Defect 2 derived count.** Temporarily inverted `assert len(result.excluded_images) == len(entries)` back to `== 37`:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_____________ test_positional_vacuity_signal_on_real_golden_corpus _____________
scene/tests/test_eval_harness_face_metrics.py:1505: in test_positional_vacuity_signal_on_real_golden_corpus
    assert len(result.excluded_images) == 37
E   AssertionError: assert 20 == 37
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_face_metrics.py::test_positional_vacuity_signal_on_real_golden_corpus
1 failed in 1.11s
```

Derived form restored after this proof.

**Defect 2 scratch mutation of the manifest (copy only; golden.json untouched).** Added one `face_boxes` row on a deepcopy. Original vacuity asserts go red:

```text
RED boxed==0: assert 1 == 0
compared_images 1
excluded 19 n 20
evaluable True
RED excluded_images: assert 19 == 20
```

Shipped permanently as `test_positional_vacuity_derived_n_goes_red_when_a_face_box_appears` and `test_coverage_gaps_total_tracks_scratch_manifest_length_not_a_stale_constant` (truncated to 3 entries: `total == 3`, not a leftover 37).

**F1-8 scratch.** Inverted by leaving `must_right` populated on the scored 3:

```text
FAILED scene/tests/test_eval_harness_cli.py::test_score_empty_rubric_keys_on_scored_set_scratch_manifest
E   assert 3 == 0
1 failed, 3 warnings in 1.67s
```

Strip restored after this proof.

## 3. What changed, and the coverage gap the operator must see

The de-leak in `8b93c473` stays. This lane does not re-draw the split.

**FIR-ORCH-BR-22.** Restored `present_identities` drift check (deleted in 8b93c473 with no mention). Restored `face_count > len(present_identities) and len(present_identities) >= 2` and the `mcm-planecrash.jpg` pin as the assertion of record. Those two classes are asserted live against **reported** `golden.json`, which actually carries them (`ccqw-candid.jpg`, `mcm-planecrash.jpg`). On the **selection** half they are `xfail(strict=True)` with the finding id in the reason — loud, not a silent skip, not a lowered `>= 1`, not a swapped `rrw-mirror.jpg` pin. `rrw-mirror.jpg` remains as additional train-half coverage only.

**THE MULTI-PERSON-PLUS-STRANGERS CASE AND THE CONTEXT-CONFLICTS-PIXELS CASE ARE NOT REPRESENTED IN THE CURRENT SELECTION HALF.** That is a corpus-coverage gap. Lowering `>= 2` to `>= 1` or swapping the plane-crash pin for a mirror image hid it. This lane makes it visible.

**FIR-ORCH-BR-23.** Every listed `== 37` on the live seed is now `len(entries)` / `len(record["items"])` of the manifest being scored, plus a non-empty guard. Vacuity tests still require `face_boxes` populated == 0 on the real golden. `must_right_defined_images == 34` was the same class of leftover and is derived from the scored seed. No `37 → 20` re-pin.

## 4. Canon rules and satisfaction

### TEST-15 — verbatim (`~/lane-canon/ENGCANON.md`)

> | TEST-15<a name="test-15"></a> | Reviewing a passing test that guards an invariant, single-source count, or state property | **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01)) | If production regressed here, would this exact assertion turn red; have I seen it? | S·r | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) + [pragmatic-programmer ch-9](../SOURCES.md#src-pragmatic-programmer) |

Satisfaction: every changed assertion was seen RED, then GREEN, then RED again under revert or scratch mutation. Derived counts ship permanent discrimination guards (boxed vacuity, truncated coverage total, scratch-drop of hard cases, F1-8 without stripping must_right).

### TEST-06 — verbatim (`~/lane-canon/ENGCANON.md`)

> | TEST-06<a name="test-06"></a> | New test about to be run for the first time | **Watch it fail once / predict the failure**: a test never observed failing (with the predicted message) may assert nothing; a tautological assertion (arithmetic on the code's own output, a `const` that cannot change, a proxy that can diverge from the real behavior) certifies zero | What exact failure message do you expect before you run it? | S·w | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) |

Satisfaction: restored bakeoff predicates were run before xfail/reported pins; predicted messages matched (`not in golden corpus`, `lost its multi-person-plus-strangers`). Derived-count tests were already red at `20 == 37` before the rewrite. No first-write green was treated as evidence.

### EVAL-23 — verbatim (`~/lane-canon/EVALCANON.md`)

> | EVAL-23<a name="eval-23"></a> | Production readiness is reported as one number; a count of tests implemented, an average across categories, or an offline accuracy figure | **Readiness is the weakest category, not the total**: score data, model, infrastructure, and monitoring coverage as four separate subtotals and report the minimum as the readiness number, because the four are not substitutable and a total lets strong monitoring hide zero data tests until the untested contract fails in production (worst-unit gating on cohorts is [[FAIR-01]](ml-systems.md#fair-01); per-slice floors are [[EVAL-04]](ml-systems.md#eval-04)) | What is the lowest of the four category subtotals, and what is missing from it? | J·r | [ml-test-score sec-VI.A](../SOURCES.md#src-ml-test-score) |

Satisfaction: the prior lane's COMPLETE on one passing disjointness node hid a default-gate category that was red (`== 37` on 14 sites). This lane runs that category and does not re-pin it to 20. The unmarked suite's remaining reds (seal, freeze, fusion planecrash-on-bakeoff, golden-38 subset, stranger media 38, phrase-box media 12) are reported as the weakest remaining category, not averaged away.

### MLDATA-09 — verbatim (`~/lane-canon/EVALCANON.md`)

> | MLDATA-09<a name="mldata-09"></a> | A quality-control or outlier filter removes the hard cases (extreme pose, occlusion, low resolution) from a corpus whose claim covers those conditions | **A filter that removes the regime under test deletes the test**: when cleaning a corpus, check each exclusion rule against the conditions the claim covers and keep the hard cells as declared strata rather than contaminants, because the filter's blind spot silently becomes the benchmark's: the number goes green by deleting the cases that would have moved it, and nothing in the report shows the deletion (↔ [[MLDATA-08]](ml-systems.md#mldata-08) the same hole when the collecting tool never captured the cell; eng [[PERF-03]](engineering.md#perf-03) coordinated omission is this exact mechanism in a load generator) | Which exclusion rules ran, and does any of them remove a condition the claim covers? | S·p | [janus-benchmark-c sec-1.1](../SOURCES.md#src-janus-benchmark-c) |

Satisfaction: the HMAC split is an exclusion rule that removed `ccqw-candid.jpg` and `mcm-planecrash.jpg` from selection. This lane refuses to green the bake-off by deleting those cells from the assertion set. They remain pinned on the reported half; their absence from selection is an explicit known gap.

### AUDIT-07 — named in the brief; **absent from canon**

`grep -nE '^\|\s*(EVAL|MLDATA|TEST|FAIR|AUDIT|PROV)-[0-9]+' ~/lane-canon/EVALCANON.md` has AUDIT-04, AUDIT-05, AUDIT-06, then AUDIT-08. There is no AUDIT-07 row in `EVALCANON.md`, `ENGCANON.md`, or `RULES.md`. Not invented. Vacuity tests that cited AUDIT-07 in comments still enforce π=0 / 0/N face_boxes on the scored corpus.

## 5. Exact list of files changed (`git diff --stat HEAD~1`)

Work commit `b7115d35` (`git show --stat --format= b7115d35`):

```text
 .lane/REPORT.md                                    | 281 ++++++++++++---------
 .../scene/tests/test_eval_harness_bakeoff.py       | 121 ++++++++-
 .../scene/tests/test_eval_harness_cli.py           |  78 +++++-
 .../tests/test_eval_harness_determinism_anchor.py  |  25 +-
 .../scene/tests/test_eval_harness_face_metrics.py  |  62 +++--
 .../scene/tests/test_eval_harness_report.py        |   9 +-
 6 files changed, 411 insertions(+), 165 deletions(-)
```

`scene/tests/seed/golden.json` and `bakeoff_golden.json` were not modified. `ASSIGNMENT_RULE`, `assign_split()`, and frozen digests were not modified.

## 6. Full unmarked `scene/tests/` suite

Command: `pytest scene/tests/ -q --tb=no -m "not integration and not pg and not timing"` (Makefile:299 default gate).

```text
28 failed, 2131 passed, 5 skipped, 4 xfailed, 474 warnings, 4 errors in 269.53s (0:04:29)
```

Remaining reds are split-fallout this lane was forbidden to hide by weakening, and freeze/seal pins this lane was forbidden to regenerate:

- S2A determinism freeze digest mismatch vs live 20-entry golden (invariant: do not modify frozen digest).
- `test_pin_committed_sealed_eval_split` and sibling CLI checks: source-manifest SHA and membership still record the 37-entry seal (must stay loud).
- Fusion bake-off tests still `next(...)` `mcm-planecrash.jpg` on **selection** (StopIteration). Same coverage gap as BR-22; assertion of record now lives on reported golden in bakeoff tests. Fusion file left as-is rather than re-pinning/swapping.
- `test_golden38_subset_pin`: historical media_id set vs post-split subset (not a `== 37` pin; keep loud).
- `test_seed_corpus_has_designated_stranger_entry`: media_id 38 not in reported golden.
- phrase-boxes + identity-merge: `KeyError: 12` (`ccqw-running.jpg` is now selection-only).

4 xfailed (strict): present_identities drift vs disjoint golden; selection `>=2`; selection planecrash; live-golden F1-8 `no_mr_ids == 3`.

## 7. HONEST STATUS: PARTIAL

The two named defects are repaired: original predicates restored and kept loud; 14 (plus follow-on) `== 37` pins derived from the scored manifest; TEST-15 RED/GREEN/REVERT-RED recorded; no assertion was lowered, skipped, or deleted to obtain green.

What remains: the unmarked `scene/tests/` gate is not green. Weakest remaining category is still data/corpus-contract tests that assume the pre-split 37-entry bake-off+golden identity (freeze, seal, fusion planecrash-on-selection, golden-38 subset, stranger 38, phrase-box media 12). Fixing those without re-drawing the split or regenerating the freeze is out of this lane's two-defect contract and would be a new task. Do not treat 2131 passed as readiness.
