# L3-split report — selection leakage in the reported corpus

## 1. IMPORT PROVENANCE check output

Command run before the first pytest invocation in this lane:

```text
/home/ubuntu/w/L3-split/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The imported module starts with `/home/ubuntu/w/L3-split`; no test evidence came from the shared venv's pinned `vlm6-base` tree.

## 2. TDD evidence

### RED output (test written before manifest changes)

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______________ test_selection_and_reported_corpora_are_disjoint _______________

    def test_selection_and_reported_corpora_are_disjoint() -> None:
        selection = json.loads(BAKEOFF_MANIFEST.read_text(encoding="utf-8"))
        reported = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
        selection_sha256 = {entry["sha256"] for entry in selection["entries"]}
        reported_sha256 = {entry["sha256"] for entry in reported["entries"]}
        overlap = selection_sha256 & reported_sha256
        overlap_percent = 100 * len(overlap) / len(reported_sha256)
>       assert not overlap, (
            "selection/report leakage: "
            f"{len(overlap)}/{len(reported_sha256)} reported images overlap selection "
            f"({overlap_percent:.1f}%); shared sha256={sorted(overlap)}"
        )
E       AssertionError: selection/report leakage: 10/37 reported images overlap selection (27.0%); shared sha256=['34271e1e49ba12f01a0494b6b560709d45c4941a95c88faef929092a0a33dd27', '3a51b1ce34db0bc33c0aa89b224c284af087cdc2099e1b9e9053335450fc4fda', '431bcbcf8e6d1f8122e86b4f6aaf1f0dbbdb6072259dcbcfd4a1ac31e5696f90', '4b98847d196ea19d6fc1181f0f16533c61ef6dfe8ba0da18bfc13d77afc404c1', '4dd4c1ddb589fce8335891680a18367e4e8e9db449569de889826b692f0ca053', '4e9ecee469b6a48a55c95e6a32688498d7065b2ba403eb697f06ddb65a541416', '88e91c52269a49d7176ddac5e40aa91295cb055565f34129b9e1e4bdfac8f603', 'a3bba8687c958f4a4c61bee2db4c154fb435fe3d8e2ceee835a3ac46b22a7a4f', 'dbbf96ca265c69610b3974ba2a58920224af83130613ccd13e6a41fd7886e05e', 'e7081767186f95d469cbd8792a0361d6580e14637688beab9914ec55eb158740']
E       assert not {'34271e1e49ba12f01a0494b6b560709d45c4941a95c88faef929092a0a33dd27', '3a51b1ce34db0bc33c0aa89b224c284af087cdc2099e1b9e...91680a18367e4e8e9db449569de889826b692f0ca053', '4e9ecee469b6a48a55c95e6a32688498d7065b2ba403eb697f06ddb65a541416', ...}

scene/tests/test_eval_harness_bakeoff.py:105: AssertionError
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_bakeoff.py::test_selection_and_reported_corpora_are_disjoint
1 failed in 1.26s
```

An earlier setup-only attempt hit `GOLDEN_IMAGES_DIR` before reaching the assertion. It is deliberately excluded from RED evidence; the metadata-only test above is the first valid assertion RED.

### GREEN output after the production manifest fix

```text
.                                                                        [100%]
1 passed in 1.08s
```

### REVERT-RED proof (TEST-15)

Only the production `scene/tests/seed/golden.json` fix was stashed. That restored the original 37 reported entries while leaving the new selection and assertion in place:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
_______________ test_selection_and_reported_corpora_are_disjoint _______________

    def test_selection_and_reported_corpora_are_disjoint() -> None:
        selection = json.loads(BAKEOFF_MANIFEST.read_text(encoding="utf-8"))
        reported = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))
        selection_sha256 = {entry["sha256"] for entry in selection["entries"]}
        reported_sha256 = {entry["sha256"] for entry in reported["entries"]}
        overlap = selection_sha256 & reported_sha256
        overlap_percent = 100 * len(overlap) / len(reported_sha256)
>       assert not overlap, (
            "selection/report leakage: "
            f"{len(overlap)}/{len(reported_sha256)} reported images overlap selection "
            f"({overlap_percent:.1f}%); shared sha256={sorted(overlap)}"
        )
E       AssertionError: selection/report leakage: 10/37 reported images overlap selection (27.0%); shared sha256=['013bca0b2b1ebb367445ec1783e76b48fe1c13a2ab56f2f19f4335ceeb21feaa', '2b57b7a7d498cafbad6b5587ddabeb8d4c2fc8d1c4763f120d7374df188644f4', '431bcbcf8e6d1f8122e86b4f6aaf1f0dbbdb6072259dcbcfd4a1ac31e5696f90', '4b98847d196ea19d6fc1181f0f16533c61ef6dfe8ba0da18bfc13d77afc404c1', '4e0ce9a2ccc7ace3de4a8968c9badd75d5ae3c83c9ea81082ca44a9658b9bc98', '4e9ecee469b6a48a55c95e6a32688498d7065b2ba403eb697f06ddb65a541416', '88e91c52269a49d7176ddac5e40aa91295cb055565f34129b9e1e4bdfac8f603', 'a3bba8687c958f4a4c61bee2db4c154fb435fe3d8e2ceee835a3ac46b22a7a4f', 'cb5adbad2760babea68a7317800f9f2e3abe9d7e21e327f8d2c5f36e2b799ac6', 'd77b26f9e20d222ee8d578e619b91db4af106f8811c106e33d4cfbd3a1f41f1a']
E       assert not {'013bca0b2b1ebb367445ec1783e76b48fe1c13a2ab56f2f19f4335ceeb21feaa', '2b57b7a7d498cafbad6b5587ddabeb8d4c2fc8d1c4763f12...8968c9badd75d5ae3c83c9ea81082ca44a9658b9bc98', '4e9ecee469b6a48a55c95e6a32688498d7065b2ba403eb697f06ddb65a541416', ...}

scene/tests/test_eval_harness_bakeoff.py:108: AssertionError
=========================== short test summary info ============================
FAILED scene/tests/test_eval_harness_bakeoff.py::test_selection_and_reported_corpora_are_disjoint
1 failed in 1.13s
```

After `git stash pop`, the same test was re-run and restored to:

```text
.                                                                        [100%]
1 passed in 0.99s
```

## 3. Split decision, quantification, and existing leak assertion

The split uses the already frozen rule, seed, and fraction:

- rule: `hmac-sha256(seed, image_sha256)[:8]/2**64 < held_out_fraction`
- seed: `vlm6-s1-sealed-eval-split-20260818`
- held-out fraction: `0.5`
- `assign_split(...)` implementation and `ASSIGNMENT_RULE` are unchanged.

The test independently calls `assign_split` for every entry and requires all selection entries to be `train` and all reported entries to be `held_out`. Because assignment keys on image SHA-256, identity renames cannot move an image between sets.

Corpus sizes:

| Corpus | Before | After | Unique present identities after |
|---|---:|---:|---:|
| Bake-off selection | 10 | 10 | 6 |
| Reported golden corpus | 37 | 20 | 8 |
| Shared image SHA-256 | 10 | 0 | n/a |

The selection and reported corpora share four identity labels (`Auburn Current`, `Linen Kestrel`, `Russet Fathom`, `Slate Willow`) across different images. This is expected for the pre-registered image-hash split and is not image-selection leakage. It would not be an acceptable identity-disjoint face-identification split; this lane only establishes an image-disjoint description-evaluation split.

Selection entries retained because `assign_split` places them in train: media IDs 3 (`ccqw-antartica.jpg`), 23 (`auburn-daniel-sunglasses.jpg`), 30 (`slate-pool.jpg`), 27 (`linen-kestrel-painting.jpg`), and 34 (`nina-machiavelli.jpeg`).

Selection entries moved out because `assign_split` places them in held-out:

| Removed selection media ID | Path | Train-half replacement | Reason for replacement |
|---:|---|---|---|
| 2 | `mock_images/quiet-nye.jpg` | 26 `mock_images/linen-kestrel-home.jpg` | Retains a labeled single-person/context case. |
| 5 | `mock_images/ccqw-candid.jpg` | 17 `mock_images/tidal-1.jpg` | Retains a roster-plus-strangers, multi-person crowd case. |
| 37 | `mock_images/muted-group-party.jpg` | 12 `mock_images/ccqw-running.jpg` | Retains a multi-person/partial-roster case with sunglasses. |
| 36 | `mock_images/muted-bar.jpg` | 31 `mock_images/mcm-eye-blocked.jpg` | Adds a hard, explicitly occluded face case. |
| 33 | `mock_images/mcm-planecrash.jpg` | 35 `mock_images/rrw-mirror.jpg` | Adds a reflection-heavy hard case without leaking held-out media 33. |

All 17 train-assigned images were removed from the reported manifest: media IDs `3, 6, 7, 8, 9, 10, 12, 17, 23, 26, 27, 30, 31, 32, 34, 35, 38`. The 20 retained reported media IDs are `1, 2, 4, 5, 11, 13, 14, 15, 16, 18, 19, 20, 21, 24, 25, 28, 29, 33, 36, 37`.

The overlap-enforcing assertion was at `apps/prototype-description-service/scene/tests/test_eval_harness_bakeoff.py:98` in the parent commit, named:

```python
def test_entries_reuse_golden_corpus_images(manifest: GoldenManifest) -> None:
```

At parent line 102 it explicitly required selection membership in the reported corpus:

```python
assert entry.path in golden_by_path, f"{entry.path}: not in golden corpus (new image needs README bootstrap)"
```

It then pinned SHA-256, media ID, face count, and identities to the corresponding reported entry. That was wrong because it made model-selection images mandatory members of the corpus used for reported quality. It has been replaced, not silently deleted, by SHA disjointness plus frozen-half assertions.

### Underpowered honest result — global claims are not supported

**THE REPORTED CORPUS SHRANK FROM 37 TO 20 IMAGES (−45.9%) AND IS SEVERELY STRATUM-IMBALANCED. IT DOES NOT SUPPORT A GLOBAL MODEL-QUALITY, FAIRNESS, OR ADOPTION CLAIM.**

Post-split reported domain counts are: faces 12, crowds 5, mirrors 1, low-light 1, people 1. There are no explicitly tagged occlusion or art entries in the reported half. The unique plane-crash context-conflict case is now correctly reported-only and cannot remain a selection discriminator. These are findings, not gaps papered over by changing the seed, fraction, hashing rule, or frozen digest. A future adequately powered, balanced holdout must be procured under the existing forward split before a broad claim is made.

Structural metadata validation succeeded for both manifests. The historical `test_pin_committed_sealed_eval_split` check now fails (`1 failed, 1 warning`) because it correctly detects that the 37-entry source manifest recorded in the 2026-08-18 seal is no longer the 20-entry reported manifest. Its first violation is the source-manifest SHA mismatch. Per the invariant, the frozen artifact/digest was not re-frozen. This expected historical-anchor drift must remain visible to the coordinator.

## 4. Canon rules and satisfaction

### MLDATA-09 — verbatim

> | MLDATA-09<a name="mldata-09"></a> | A quality-control or outlier filter removes the hard cases (extreme pose, occlusion, low resolution) from a corpus whose claim covers those conditions | **A filter that removes the regime under test deletes the test**: when cleaning a corpus, check each exclusion rule against the conditions the claim covers and keep the hard cells as declared strata rather than contaminants, because the filter's blind spot silently becomes the benchmark's: the number goes green by deleting the cases that would have moved it, and nothing in the report shows the deletion (↔ [[MLDATA-08]](ml-systems.md#mldata-08) the same hole when the collecting tool never captured the cell; eng [[PERF-03]](engineering.md#perf-03) coordinated omission is this exact mechanism in a load generator) | Which exclusion rules ran, and does any of them remove a condition the claim covers? | S·p | [janus-benchmark-c sec-1.1](../SOURCES.md#src-janus-benchmark-c) |

Satisfaction: membership is determined only by the unchanged HMAC of image content, never by quality, label, difficulty, or observed score. Hard cases assigned held-out remain in reporting (including media 33); selection cannot reclaim them. The post-split holes are enumerated and broad claims are prohibited instead of retuning the draw or hiding lost strata.

### MLDATA-07 — verbatim

> | MLDATA-07<a name="mldata-07"></a> | Benchmark composition shows one intersection cell ≪ the others while a global claim is made | **Intersectional balance before a global claim**: report unique-subject counts per intersection; if severely imbalanced versus deployment, build or adopt a balanced holdout (the PPB pattern) and re-measure (↔ biz [[AIPX-04]](business-marketing.md#aipx-04) an aggregate claim over a hiding cell is the same global-clear failure at ship review) | What percentage of unique subjects falls in each intersection cell? | S·p | [gender-shades](../SOURCES.md#src-gender-shades) |

Satisfaction: selection has 6 unique labeled subjects; reporting has 8; four labels span the halves on distinct images. Domain counts are reported above. The manifests contain no demographic/phenotype intersection fields, so percentages for those intersections cannot honestly be computed. The report therefore explicitly prohibits a global/fairness claim and calls for a balanced, annotated holdout rather than emitting an aggregate claim over unknown cells.

### MLDATA-08 — verbatim

> | MLDATA-08<a name="mldata-08"></a> | A fairness-sensitive dataset is built solely by running a face detector over web images | **Detector-harvested sets need a post-hoc stratum audit**: measure the resulting demographic/phenotype mix and supplement the missing cells; the detector's blind spots otherwise become the benchmark's | Did the detector's blind spots become the benchmark's? | S·w | [gender-shades](../SOURCES.md#src-gender-shades) |

Satisfaction: the post-hoc audit exposes the available domain mix and the absence of demographic/phenotype labels; no detector-derived absence is treated as ground truth and no fairness claim is permitted. Missing cells must be supplemented and annotated before any fairness-sensitive use. This lane does not invent demographic labels or silently call unlabeled cells balanced.

### EVAL-01 — verbatim

> | EVAL-01<a name="eval-01"></a> | A model metric is reported with no random / heuristic / human / production baseline | **Require offline baselines**: compare to random, zero-rule, a simple heuristic, a human, and the existing solution on the same split; without them the number is uninterpretable | What is Δ versus zero-rule and versus current production? | S·r | [designing-ml-systems](../SOURCES.md#src-designing-ml-systems) |

Satisfaction: this change reports no model-quality metric. It invalidates the contaminated 37-image numbers. Any later candidate, zero-rule/heuristic, human, or production comparison must be re-run on the same 20-image held-out manifest; results from the old 37-image corpus are not comparable evidence. Even with those baselines, the 20-image imbalance bars a global/adoption claim.

### TEST-15 — verbatim

> | TEST-15<a name="test-15"></a> | Reviewing a passing test that guards an invariant, single-source count, or state property | **Prove the green can go red**: a passing test that cannot fail certifies nothing; before trusting it, mutate the production path (break the invariant, inject a second/zero case, corrupt an input) and confirm the assertion catches it; for invariant/count tests, ship the mutation as a permanent discrimination guard (e.g. mis-wire → asserts 2, drop → asserts 0). Watch for assertions on the code's own output rather than observed behavior, and DOM/count checks that never query the real surface (see [[TEST-11]](engineering.md#test-11), [[DBG-01]](engineering.md#dbg-01)) | If production regressed here, would this exact assertion turn red; have I seen it? | S·r | [modern-software-engineering ch-8](../SOURCES.md#src-modern-software-engineering) + [pragmatic-programmer ch-9](../SOURCES.md#src-pragmatic-programmer) |

Satisfaction: the report includes both the original RED and the source-only REVERT-RED. Restoring only the old reported manifest made the exact shipped assertion fail at 10/37 overlap; restoring the fix returned it to GREEN.

## 5. Exact list of files changed (`git diff --stat HEAD~1`)

```text
 .lane/REPORT.md                                    | 192 ++++++++
 .../scene/tests/seed/bakeoff_golden.json           | 231 +++------
 .../scene/tests/seed/golden.json                   | 545 ---------------------
 .../scene/tests/test_eval_harness_bakeoff.py       |  62 ++-
 4 files changed, 308 insertions(+), 722 deletions(-)
```

## 6. HONEST STATUS: COMPLETE

The requested image-level de-leak is complete: selection and reporting are SHA-disjoint, every entry is on the correct side of the frozen `assign_split` draw, the old leak-enforcing assertion was replaced, valid RED/GREEN/REVERT-RED evidence is recorded, and the work is committed. Nothing remains for this lane.

The operator must not mistake task completion for adequate evaluation power: the resulting 20-image reported corpus is underpowered and imbalanced, the historical 37-entry seal-pin check intentionally reports drift, and new balanced held-out procurement plus same-split baselines are prerequisites for any broad quality/fairness/adoption claim.
