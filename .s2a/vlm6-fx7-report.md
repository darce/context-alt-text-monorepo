# Lane `fx7` — fixture measurability + one-shot anchor regeneration

**Branch:** `feature/vlm-6-fx7` (this lane's branch)  
**Base:** `e2575b5ef09ed75de7f792546439d53624c9d344`  
**Prior lanes on merge:** fx1–fx6 (reports under `.s2a/`)

Heuristics: `TEST-15`, `EVAL-04`, `EVAL-19`, `EVAL-23`, `AUDIT-07`, `rg-002`, `rg-005`, `rg-009`, `rg-015`, `sr-001`, `sr-007`.

---

## Job 1 — make test corpora measurable (gate unchanged)

### Diagnosis

fx4 made `fabricated_fact_rate → None` when traps=0; fx6 folds that into `verdict=not_ready` + non-zero exit. Shared clean fixtures already had face_boxes + spatial_facts but **no `reference_facts` trap**, so 11 tests about other subjects went red on an unrelated vacuity reason.

### Fix (fixtures only; gate not weakened)

- **`test_eval_harness_cli.py`**: `_single_name_measurable_fields` now authors one false-polarity trap (`purple zebra balloon`) that clean captions never assert → `fabricated_fact_rate=0.0`, `images_with_traps≥1`. Shared by `_clean_score_manifest_and_record`, `_w1_audience_manifest_and_record`, `_corpus_entries`.
- **`test_eval_harness_report.py`**: same trap on the three pass/control fixtures that built their own entries.
- **Not touched:** `scene/tests/seed/golden.json` (real corpus gaps stay honest).

### Per-test classification (a / b / c)

| Test | Class | Justification |
| --- | --- | --- |
| `test_score_run_record_emits_verdict_pass_when_no_wrong_names` | **(a)** | Subject is clean wrong-name pass path; needed full measurable corpus, not vacuity. |
| `test_cmd_score_public_audience_emits_redacted_public_artifact` | **(a)** | PUBLIC redaction happy path; needs honest exit-0 pass. |
| `test_cmd_score_default_local_emits_no_public_artifact` | **(a)** | LOCAL audience artifact shape; needs honest pass. |
| `test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures` | **(a)** | Exit-0 complement of wrong-name floor; needs measurable clean run. |
| `test_cli_score_check_determinism_runs_cross_process_guard` | **(a)** | Cross-process determinism guard; vacuity was unrelated. |
| `test_cli_score_determinism_certifies_written_rubric_gate` | **(a)** | Rubric-gate flag persistence under determinism; needs writeable pass. |
| `test_cli_score_audience_public_check_determinism_covers_both_labels` | **(a)** | Dual-label determinism; needs measurable public fixture. |
| `test_score_guard_rubric_gate_skip_bypasses_must_right_gate` | **(a)** | skip → `pass_ungated` subject; requires measurable categories. |
| `test_score_report_records_rubric_gate_flag` | **(a)** | Flag stamped on report; needs honest pass under enforce. |
| `test_score_run_record_positional_vacuity_absent_when_measurable` | **(c)** | fx6 control: prove gate goes green when **every** category measurable (was missing fab trap). |
| `test_score_verdict_pass_when_positional_and_placement_measurable` | **(c)** | fx6 control: same — extended with fab trap so name matches behaviour. |

No **(b)** among the 11: real-golden `not_ready` tests were already reconciled by fx6.

### RED → GREEN (TEST-15)

**RED (unfixed, 11/11 same class):**
```
AssertionError: ['category-vacuity: fabricated_fact — claim unit=image with reference_facts trap; fabricated_fact_rate=None images_with_traps=0 (not measurable; AUDIT-07)']
assert 'not_ready' == 'pass'
  - pass
  + not_ready
```
CLI variants:
```
SystemExit: score category-vacuity gate: verdict=not_ready (category-vacuity: fabricated_fact — claim unit=image with reference_facts trap; fabricated_fact_rate=None images_with_traps=0 (not measurable; AUDIT-07); not adoption-eligible; …)
```

**GREEN:**
```
11 passed in 18.18s
```
Control assertions after fix:
```
assert scored["hallucination"]["fabricated_fact_rate"] == pytest.approx(0.0)
assert scored["hallucination"]["images_with_traps"] >= 1
assert scored["verdict"]["verdict"] == ScoreVerdict.PASS.value
```

**Job 1 acceptance battery** (`scene/tests/ -q -p no:randomly`):
```
5 failed, 1227 passed, 4 skipped
```
Exactly the five freeze tests (expected-red until job 2).

**Commit:** `fix(vlm-6): make score fixtures measurable for fabricated_fact (fx7)` (this lane's branch).

---

## Job 2 — one-shot anchor regeneration

Commands (typed fixture fields — **not** forty zeros in `head_sha`; closes F-04):

```bash
cd apps/prototype-description-service
.venv/bin/python -m scripts.eval_harness.generate_determinism_anchor \
  --manifest scene/tests/seed/golden.json \
  --out-dir ../../docs/tasks/vlm/bakeoff-results \
  --stem S2A-determinism-anchor-run-20260811 \
  --fixture-revision 0000000000000000000000000000000000000000 \
  --canonical-timestamp 2026-08-11T00:00:00Z

.venv/bin/python -m scripts.eval_harness.generate_face_determinism_anchor \
  --out-dir ../../docs/tasks/vlm/bakeoff-results
```

Updated `_FROZEN_DIGESTS` in both anchor test modules.

### Caption freeze — before / after vs fx4 prediction

| Field | Old freeze | After regen | fx4 predicted | Notes |
| --- | --- | --- | --- | --- |
| `faces.detection` P/R | 1.0 / 1.0 | **0.944 / 0.895** | ~0.94 / ~0.89 | Matches (seeded under/over-count). |
| `faces.identification` P/R | 1.0 / 1.0 | **0.879 / 0.806** | ~0.88 / ~0.81 | Matches (seeded drop/inject). |
| wrong_names n | 0 | **4** (`Fixture-Wrong-*`) | (implied by seed) | Seeded deviation reaches metric — not a 1.000 tautology. |
| `hallucination.fabricated_fact_rate` | **0.0** | **`None`** | **`None`** | **Intended honesty (EVAL-19)** — not a regression. |
| `verdict` | `pass_ungated` | **`fail`** | `not_ready` | **Differs from fx4:** seeded wrong names are a hard gate failure and outrank vacuity (`fail` carries wrong-name + positional/placement/fabricated vacuity reasons). Vacuity alone would be `not_ready`; with wrong_names>0 the honest verdict is `fail`. |
| `provenance.coverage_gaps` | 3 string fields | 4 structured records + `demographic_cohort` | structured | Matches C-01/C-02. |
| `provenance.head_sha` | 40 zeros | **`null`** | null | F-04. |
| `provenance.fixture_revision` | absent | 40-zero sentinel | set | Byte-stability only. |
| `predictions_source` / `face_metrics_evidential` | absent | `ground_truth_derived_fixture` / `false` | set | C-04. |
| identity `bbox` | invented | absent; `unpositioned=true` | absent | C-09. |
| report MD | no coverage block | `## Coverage gaps` + non-evidential note + "byte-stability only" | has block | E-04 / E-08. |

**MD does not read as adoption certification:** verdict=**fail**, fabricated/placement/positional null, coverage-gap block, non-evidential face note, "certifies scoring-path byte-stability only" (VLM6-E-08).

### Face freeze — before / after

| Field | Change |
| --- | --- |
| `provenance.head_sha` | 40 zeros → **`null`**; `fixture_revision` added |
| `coverage_gaps` list | still `failures`, `occlusion.occlusion_other`, `occlusion.sunglasses` (perfect ID/detection not falsely listed — B-05) |
| manifest digest | **unchanged** (truncated prefix omitted; corpus body byte-identical) |
| run / report / md digests | all moved |

### New frozen digests

**Caption:**
- run: `3166ab64fdbfa4a0b68d3375cd00de6344dd743c8679f2bf9d5e96a6581bfef4`
- report.json: `d33c340f39fb6c7cdd998ea2eba6e48abe84eb02b45316e90ad0061352b5a184`
- report.md: `4d7154e2f2d55f0c56ebd44655d155b3268cb5c51a195d7cdcb175da659c9c8a`

**Face:**
- manifest: `1209733ed2b62e837449855690c15931dc0e76fcb24be8a715668020e05c8958` (unchanged)
- run: `de8d00edb4458e7bce9c22a5831c7e65bb2a225f5ebff1e0b37e42c7badbcde4`
- face-report.json: `50dd3c2a8fab1153015c431067394ef12c6114283a038c4b8850b6d368fdd041`
- face-report.md: `6452cc66134ec07d24fed6aed8b863b64b31c4cbfb3bb9e34b7dca3937898701`

### Verification

```
# Full suite
.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
# 1232 passed, 4 skipped, 0 failed

# Anchor modules alone
# 33 passed

# Determinism certification (documented equivalent of make eval-anchor-check)
# Caption: "determinism check passed [score]: … matches --expect-report …"
# Face:    "determinism check passed [score-face]: … matches --expect-report …" exit 0
```

**Caption process exit after determinism:** still **1** — wrong-name floor fires on the intentional seeded imperfect fixture (`wrong_name_rate=0.1081`, n=4). Determinism itself is green; process exit is adoption quality. See Cross-lane.

**README:** no stale hardcoded manifest digest literal survived (fx4 F-06/E-06). No edit required.

---

## Cross-lane requests

1. **`cli.py` / `Makefile` `eval-anchor-check` (fx6 owners or follow-up):** After fx4 seeded wrong names + fx6 vacuity exit, the caption half of `make eval-anchor-check` prints `determinism check passed` then exits **1** on `score wrong-name floor gate` (and would also hit category-vacuity/`not_ready` without the wrong names). README still documents `EXIT_CODE:0` for byte-stability certification. Need either:
   - after successful `--check-determinism --expect-report`, treat process exit as the determinism outcome only (do not re-apply adoption quality gates to a non-evidential freeze), **or**
   - document non-zero exit as expected when the freeze is deliberately imperfect / vacuous, and split a pure determinism-only target.
   Do **not** weaken the wrong-name floor for live adoption runs (`sr-001`). Scope is freeze-certification path only.

2. **Generator (fx4) optional:** if the make target must stay exit-0 without cli change, stop injecting roster-foreign names into the caption anchor **or** route them through a presentation channel that does not breach the floor — but that would soften TEST-15 on the freeze itself. Prefer cli separation of byte-stability vs adoption exit.

---

## Deferred

| Item | Reason |
| --- | --- |
| Real golden `verdict=pass` | Requires Golden-100 population of `face_boxes` / `spatial_facts` / `reference_facts` (π>0). Gate is honest today via `not_ready`/`fail` + non-zero exit. |
| Caption `eval-anchor-check` process exit 0 | Blocked on cli/Makefile ownership (see Cross-lane). Determinism match is already green. |

---

## Commits (this lane's branch)

1. `fix(vlm-6): make score fixtures measurable for fabricated_fact (fx7)`
2. `fix(vlm-6): regenerate determinism anchors after vacuity wave (fx7)`
3. `docs(vlm-6): fx7 lane TEST-15 fix report`
