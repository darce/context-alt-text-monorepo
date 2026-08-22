# L2-roster report

## IMPORT PROVENANCE check output (A.1)

Command, run from `/home/ubuntu/w/L2-roster/apps/prototype-description-service`:

```bash
PY=/home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python
PYTHONPATH=$PWD $PY -c "import scripts.eval_harness.strata as m; print(m.__file__)"
```

Verbatim output:

```text
/home/ubuntu/w/L2-roster/apps/prototype-description-service/scripts/eval_harness/strata.py
```

The resolved path starts with `/home/ubuntu/w/L2-roster`, so all test evidence below imports this worktree rather than the shared venv's pinned base checkout.

## RED output (B.1)

The regression test was the only scoring-path change when this command was run:

```bash
PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest scripts/eval_harness/tests/test_eval_harness_report.py::test_caption_quality_metrics_ignore_identity_spelling -q
```

Verbatim output:

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____________ test_caption_quality_metrics_ignore_identity_spelling _____________

    def test_caption_quality_metrics_ignore_identity_spelling() -> None:
        def _score_identity_variant(present_identity: str, caption: str, objects: list[str]) -> tuple[tuple, tuple]:
            record = {
                "schema": "acx-eval/v1",
                "kind": "run_record",
                "provenance": {
                    "manifest_sha256": "m" * 64,
                    "base_url": "x",
                    "head_sha": "0" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 1,
                        "path": "mock_images/cake.jpg",
                        "describe": {
                            "alt_text_draft": caption,
                            "visual_facts": {"objects": objects},
                            "adapter": "seeded",
                            "model_id": "seeded-fixtures",
                            "model_version": "1",
                            "cached": False,
                        },
                        "identities": [{"name": present_identity, "unpositioned": True}],
                        "face_count": 1,
                        "error": None,
                    }
                ],
            }
            entry = _stamp_entry(
                {
                    "path": "mock_images/cake.jpg",
                    "media_id": 1,
                    "face_count": 1,
                    "present_identities": [present_identity],
                    "must_right": [],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "face_boxes": [_named_box(present_identity)],
                },
                "exhaustive",
            )
            scored = score_run_record(record, [entry])
            per_image = scored["per_image"][0]
            return (
                (
                    per_image["fkre"],
                    per_image["repetition_ratio"],
                    per_image["tag_coverage"],
                ),
                (
                    scored["quality"]["mean_fkre"],
                    scored["quality"]["mean_repetition_ratio"],
                    scored["quality"]["mean_tag_coverage"],
                ),
            )
    
        real_style = _score_identity_variant(
            "Alexandria Cunningham",
            "Alexandria smiles while Alexandria holds a cake.",
            ["Alexandria", "Cunningham", "cake"],
        )
        pseudonym = _score_identity_variant(
            "Nimbus",
            "Nimbus smiles while Nimbus holds a cake.",
            ["Nimbus", "cake"],
        )
    
>       assert pseudonym[0] == real_style[0]
E       assert (42.62, 0.1429, 1.0) == (18.44, 0.142...6666666666666)
E         
E         At index 0 diff: 42.62 != 18.44
E         Use -v to get more diff

scripts/eval_harness/tests/test_eval_harness_report.py:550: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_harness_report.py::test_caption_quality_metrics_ignore_identity_spelling
1 failed in 2.17s
```

The test was subsequently strengthened, before final verification, so the real-style caption uses the full two-token name twice and all three quality fields diverge when the production helper is inverted. That exact final-form failure is recorded under REVERT-RED below.

## GREEN output (B.3)

Final regression and directly affected report module, run after restoring the production fix:

```text
.                                                                        [100%]
1 passed in 0.81s
..................                                                       [100%]
18 passed in 0.82s
```

An optional run of the entire `scripts/eval_harness/tests` directory emitted 66 passing progress dots, then stopped producing output for several minutes and was interrupted. It produced no final count and is not presented as green evidence. The literal regression and its containing module both completed with the counts above.

## REVERT-RED proof (B.4 / TEST-15)

I temporarily changed only `_caption_scores_without_identity_spelling(...)` in `report.py` to return the original `scores`, ran the final committed-form regression, observed this RED, and restored the fixed `dataclasses.replace(...)` block.

```text
F                                                                        [100%]
=================================== FAILURES ===================================
____________ test_caption_quality_metrics_ignore_identity_spelling _____________

    def test_caption_quality_metrics_ignore_identity_spelling() -> None:
        def _score_identity_variant(present_identity: str, caption: str, objects: list[str]) -> tuple[tuple, tuple, tuple]:
            record = {
                "schema": "acx-eval/v1",
                "kind": "run_record",
                "provenance": {
                    "manifest_sha256": "m" * 64,
                    "base_url": "x",
                    "head_sha": "0" * 40,
                    "started_at": "t",
                },
                "items": [
                    {
                        "media_id": 1,
                        "path": "mock_images/cake.jpg",
                        "describe": {
                            "alt_text_draft": caption,
                            "visual_facts": {"objects": objects},
                            "adapter": "seeded",
                            "model_id": "seeded-fixtures",
                            "model_version": "1",
                            "cached": False,
                        },
                        "identities": [{"name": present_identity, "unpositioned": True}],
                        "face_count": 1,
                        "error": None,
                    }
                ],
            }
            entry = _stamp_entry(
                {
                    "path": "mock_images/cake.jpg",
                    "media_id": 1,
                    "face_count": 1,
                    "present_identities": [present_identity],
                    "must_right": [],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "face_boxes": [_named_box(present_identity)],
                },
                "exhaustive",
            )
            scored = score_run_record(record, [entry])
            per_image = scored["per_image"][0]
            return (
                (
                    per_image["fkre"],
                    per_image["repetition_ratio"],
                    per_image["tag_coverage"],
                ),
                (
                    scored["quality"]["mean_fkre"],
                    scored["quality"]["mean_repetition_ratio"],
                    scored["quality"]["mean_tag_coverage"],
                ),
                (
                    per_image["inserted_identities"],
                    per_image["missing_identities"],
                    per_image["gated_score"],
                ),
            )
    
        real_style = _score_identity_variant(
            "Alexandria Cunningham",
            "Alexandria Cunningham smiles while Alexandria Cunningham holds a cake.",
            ["Alexandria", "Cunningham", "birthday cake"],
        )
        pseudonym = _score_identity_variant(
            "Nimbus",
            "Nimbus smiles while Nimbus holds a cake.",
            ["Nimbus", "birthday cake"],
        )
    
        expected_quality = (42.62, 0.1429, 0.0)
>       assert pseudonym[0] == real_style[0] == expected_quality
E       assert (66.79, 0.1429, 0.5) == (0.3, 0.2222,...6666666666666)
E         
E         At index 0 diff: 66.79 != 0.3
E         Use -v to get more diff

scripts/eval_harness/tests/test_eval_harness_report.py:556: AssertionError
=========================== short test summary info ============================
FAILED scripts/eval_harness/tests/test_eval_harness_report.py::test_caption_quality_metrics_ignore_identity_spelling
1 failed in 0.88s
```

## Canon rules and satisfaction

### EVAL-01

Verbatim table row from `~/lane-canon/EVALCANON.md`:

> | EVAL-01<a name="eval-01"></a> | A model metric is reported with no random / heuristic / human / production baseline | **Require offline baselines**: compare to random, zero-rule, a simple heuristic, a human, and the existing solution on the same split; without them the number is uninterpretable | What is Δ versus zero-rule and versus current production? | S·r | [designing-ml-systems](../SOURCES.md#src-designing-ml-systems) |

This patch makes a scorer-validity claim, not a new model-quality claim. It compares the pre-fix scorer, fixed scorer, and existing frozen baseline on the same deterministic 39-image inputs. The fixed re-score returns `mean_tag_coverage` to the existing baseline `0.6838`; no random/human/model baseline is relabelled or re-frozen. The controlled one-image regression separately holds semantic caption content constant while varying only identity spelling.

### MLDATA-09

Verbatim table row from `~/lane-canon/EVALCANON.md`:

> | MLDATA-09<a name="mldata-09"></a> | A quality-control or outlier filter removes the hard cases (extreme pose, occlusion, low resolution) from a corpus whose claim covers those conditions | **A filter that removes the regime under test deletes the test**: when cleaning a corpus, check each exclusion rule against the conditions the claim covers and keep the hard cells as declared strata rather than contaminants, because the filter's blind spot silently becomes the benchmark's: the number goes green by deleting the cases that would have moved it, and nothing in the report shows the deletion (↔ [[MLDATA-08]](ml-systems.md#mldata-08) the same hole when the collecting tool never captured the cell; eng [[PERF-03]](engineering.md#perf-03) coordinated omission is this exact mechanism in a load generator) | Which exclusion rules ran, and does any of them remove a condition the claim covers? | S·p | [janus-benchmark-c sec-1.1](../SOURCES.md#src-janus-benchmark-c) |

No example, image, or hard rename cell is filtered out. Both roster spellings remain scored in the regression. The local scoring pass removes only roster surface tokens from the inputs to `fkre`, `repetition_ratio`, and `tag_coverage`; the original caption remains the input for identity coverage, wrong-name, and hallucinated-name scoring.

### TEST-15

`grep -nE '^\|\s*TEST-15' ~/lane-canon/EVALCANON.md ~/lane-canon/RULES.md` returned no table row. `TEST-15` is genuinely absent as a standalone rule from both supplied canon files, so no text is invented. It appears only as a cross-reference inside EVAL-22. The requested behavior was nevertheless executed: the production replacement was inverted, the final regression went RED with `1 failed`, and the fix was restored and rerun GREEN.

## Metric deltas (T3)

Controlled regression fixture, raw pre-fix scoring to fixed scoring:

- Real-style `Alexandria Cunningham`: `fkre 0.30 -> 42.62`, `repetition_ratio 0.2222 -> 0.1429`, `tag_coverage 0.6667 -> 0.0`.
- Pseudonym `Nimbus`: `fkre 66.79 -> 42.62`, `repetition_ratio 0.1429 -> 0.1429`, `tag_coverage 0.5 -> 0.0`.
- Both spellings now produce the identical tuple `(42.62, 0.1429, 0.0)` at per-image and one-image aggregate levels.
- Identity coverage remains deliberately sensitive: the matching captions receive insertion credit `1.0`; scoring the real-style caption against roster name `Nimbus` yields inserted `[]`, missing `["Nimbus"]`, gated score `0.0`.

The fixed scorer was also run against the checked-out 39-image caption determinism inputs, writing only to `/tmp`:

- `mean_fkre = 65.12`
- `mean_repetition_ratio = 0.0567`
- `mean_tag_coverage = 0.6838`
- media `2`: `fkre=92.97`, `repetition_ratio=0.125`, `tag_coverage=1.0`
- media `24`: `fkre=50.67`, `repetition_ratio=0.0`, `tag_coverage=1.0`
- media `25`: `fkre=50.67`, `repetition_ratio=0.0`, `tag_coverage=1.0`
- `count_advisory_images = 3`

Relative to the broken figures in the brief, this is `mean_tag_coverage 0.6068 -> 0.6838` (`+0.0770`), media `2/24/25` `0.0 -> 1.0`, and advisory count `6 -> 3`. The helper itself only replaces the three named quality fields; a controlled bypass on the currently checked-out inputs showed advisory count `3 -> 3`, so the advisory movement is reported but is not falsely attributed to this patch. The current manifest digest differs from the run record's fetch-time digest after the rename, as expected; no frozen digest or determinism anchor was changed or re-frozen.

## Exact files changed (`git diff --stat HEAD~1`)

The required commit could not be created because the real Git index is read-only. The exact intended commit stat below was computed against `HEAD` using a temporary alternate index/object store in `/tmp`; it is the stat that `git diff --stat HEAD~1` would show after the blocked commit, and no other worktree file was staged into that calculation.

```text
 .lane/REPORT.md                                    | 283 +++++++++++++++++++++
 .../scripts/eval_harness/report.py                 |  77 ++++++
 .../eval_harness/tests/test_eval_harness_report.py |  87 +++++++
 3 files changed, 447 insertions(+)
```

## HONEST STATUS

BLOCKED

Implementation, tests, metric deltas, and this report are complete. Exactly one deliverable remains: stage and commit the three files above after granting write access to `/home/ubuntu/l1/r7-int/.git/worktrees/L2-roster`; `git add ...` currently fails with `fatal: Unable to create '/home/ubuntu/l1/r7-int/.git/worktrees/L2-roster/index.lock': Read-only file system`. No invariant or frozen anchor was modified.
