# Lane `fx5` report — anchor corpus coverage, freeze regen, oracle independence

**Lane:** `fx5` (Wave B)  
**Branch:** `fix/fx5`  
**Base:** `7d868a34a86b3b9d25eb6a84b6dc909eb2185ccf`  
**HEAD:** four commits on top of base (corpus / oracle / freeze / report)

Heuristics: `TEST-15`, `AUDIT-07`, `EVAL-13`, `EVAL-23`, `rg-005`, `rg-015`, `sr-001`.

---

## 1. HARM-05 — corpus extension + discrimination proof

### What was added

Face synthetic corpus lives in `generate_face_determinism_anchor.py` (not
`golden.json`). Extended `build_synthetic_face_manifest` /
`build_face_anchor_run_record`:

| media_id | path | GT | detections | purpose |
| --- | --- | --- | --- | --- |
| 9 | `localwp/uploads/stranger-fn-miss.jpg` | 1 anonymous box | 0 | pure unmatched stranger GT |
| 10 | `localwp/uploads/mixed-fn-miss.jpg` | 1 named Alice + 1 anonymous | 0 | mixed named+anonymous miss |

Items: 8 → 10. Pre-extension the only stranger (media 3) was **matched**, so
`missed_stranger_gt=0` and `fn = missed_gt` agreed with
`fn = missed_gt + missed_stranger_gt`.

### **LOUD:** generator edit required for HARM-05

Lane brief said edit generators only if RV3-01 requires it. HARM-05 corpus
source **is** the face generator — no external seed file. Edited
`generate_face_determinism_anchor.py` for corpus body only (promote protocol /
CLI / scoring path untouched). fx6 imports from that neighbourhood for promote
tests only; no API renames.

### Discrimination proof (mandatory RED #1)

**Pre-extension (control):** post and pre-HARM-01 formulas both produce
`detection={tp:6, fp:1, fn:1}` — freeze cannot detect the bug.

**Post-extension + regenerated freeze:**

```
freeze detection:     {'fn': 4, 'fp': 1, 'precision': 0.857…, 'recall': 0.6, 'tp': 6}
freeze missed_stranger_gt: 2
pre-HARM-01 detection: {'fn': 2, 'fp': 1, 'precision': 0.857…, 'recall': 0.75, 'tp': 6}
RED (differs from freeze)? True
pre_fn=2 < post_fn=4? True
```

Pre-HARM-01 formula: `fn = int(assignment.missed_gt)` (named only).  
Post-HARM-01: `fn = missed_gt + missed_stranger_gt` → 2 named + 2 stranger = 4.

Permanent pin:
`test_pre_harm01_detection_formula_goes_red_on_extended_freeze` (PASSED).
Also: `test_face_anchor_corpus_includes_unmatched_stranger_gt` (PASSED).

---

## 2. RV3-01 — independent oracle

### What the oracle now computes

- **Inlined** seed predicates (`_oracle_predicted_face_count`,
  `_oracle_predicted_identity_names`) from the golden corpus alone.
- Does **not** import `_predicted_face_count` / `_identity_rows` from the
  generator under test.
- Score path always uses real `score_run_record` (no hardwired scorer).
- Shared `_assert_scored_matches_oracle` pins lower bounds **and** exact
  equality (lower bounds alone let exaggerated records stay green).

Generator itself **not** edited for RV3-01.

### Mutant RED capture (mandatory RED #2)

Reviewer mutant: `face_count = max(0, gt-2)` + inject `ALWAYS-WRONG` on every item.

```
MUTANT real scorer det= {'precision': 1.0, 'recall': 0.19298…, 'tp': 11, 'fp': 0, 'fn': 46}
MUTANT wrong_names= 41
ORACLE expected= {'det_tp': 51, 'det_fp': 3, 'det_fn': 6, 'wrong_name_count': 4, …}
RED CAPTURE (AssertionError): detection fp=0 below oracle lower bound 3 (scorer may be GT-echoing; VLM6-S4-01)
```

Matches reviewer control (their wrong_names=37 → 41 after corpus drift; same RED class).

Permanent pin:
`test_exaggerated_record_mutant_goes_red_against_independent_oracle` (PASSED —
asserts the AssertionError).

Green path: `test_seeded_predictions_are_not_pure_gt_echo` (PASSED).

---

## 3. Freeze regen

### Path

1. HARM-05 corpus + RV3-01 oracle first.
2. `python -m scripts.eval_harness.generate_face_determinism_anchor` (pin
   head_sha/started_at sentinels).
3. Caption generator re-run — **byte-identical** (digests unchanged; not rewritten).
4. `_FROZEN_DIGESTS` from `sha256sum` of generator output — never hand-typed.
5. Manifest content-digest prefix assert updated to match generation-time
   `manifest_sha256` of the extended corpus (was pre-extension prefix).

No pre-namespace `.vlm-anchor-promote.journal` found in bakeoff-results.

### Digests (face)

Content digests (file sha256sum — not git objects). Full 64-hex from generator output:

sha-guard:ignore-next-block
```
# face freeze file digests (old → new)
manifest   sha256:1209733ed2b62e837449855690c15931dc0e76fcb24be8a715668020e05c8958
        →  sha256:67685bb703a516f7a0651fdae90cc3f316b6929831f293030f5b6aa67d766103
run        sha256:a5264540eb1fe7aa12227d8c8da5776a4ae2790cf9b6f606899a0fc48c3685c5
        →  sha256:43d160d63b188eb0f5b3b04deef48c17fe60af958e134421a1816bb098f86ef5
report.json sha256:fbea3c228f527d657d85c511a093ec8c0959cbeed0850fe5f996b95b85037449
        →   sha256:faf72705b708e77b57ec9255c7c5d9292b7d366f77348cac7a657db7ff394e52
report.md  sha256:537446ccc8f96704a93aaeb9e027662b9995bc5daffddf4c876cb48ae97be760
        →  sha256:cc60073dd1f126517370e5832cae142201b89df22b8fe49d6aec2e299bc06b7d

# caption freeze — byte-identical (not rewritten)
run        sha256:d105f3adccb2f5745e221d518649217562b836436569889b19a2c2471156dbe9
report.json sha256:c2fcfa3407ff62254556201cc35dfcb25eb4a46105e0764fe4b25a347423b0e6
report.md  sha256:dc7bf05496e37883bbe3e4cdf336f63a4e5bd489ed14aaf7bfcf439e04e14f3b
```

### Metric deltas (face report)

| field | old freeze | new freeze |
| --- | --- | --- |
| detection.fn | 1 | **4** |
| detection.recall | 0.857 | **0.6** |
| detection.tp/fp | 6 / 1 | 6 / 1 |
| unknown_rejection.missed_stranger_gt | *(key absent)* | **2** |
| unknown_rejection.n / rate | 1 / 1.0 | **3 / 0.333…** |
| full_corpus_id.fn / missed_gt | 2 / 1 | **3 / 2** |
| counts.total / scored | 8 / 8 | **10 / 10** |

### Anchor suite after regen

`36 passed` across face + caption determinism anchor tests (incl. the three
formerly-RED freeze tests).

---

## 4. Findings disagreed with

None. Both HARM-05 and RV3-01 reproduced as stated.

Note: RV3-01 equality pins already made the mutant fail on HEAD before this
lane; independence was still incomplete (generator helper imports). Fixed both
the import coupling and the permanent mutant pin.

---

## 5. Full suite result

```
7 failed, 1299 passed, 4 skipped, 32 warnings in 173.14s
```

Command:
`./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly`
from `apps/prototype-description-service/`.

### Expected-red (fx6 owns — not touched)

All 7 in `test_eval_harness_cli.py` (category-vacuity gate / sample-size):

1. `test_cmd_score_public_audience_emits_redacted_public_artifact`
2. `test_cmd_score_default_local_emits_no_public_artifact`
3. `test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures`
4. `test_cli_score_check_determinism_runs_cross_process_guard`
5. `test_cli_score_determinism_certifies_written_rubric_gate`
6. `test_cli_score_audience_public_check_determinism_covers_both_labels`
7. `test_score_freeze_certification_exits_nonzero_on_anchor_mismatch`

### Unexpected red

**None.**

### Formerly-red fx5 anchors — now green

- `test_face_generator_regenerates_byte_identical_committed_anchor`
- `test_face_expect_report_matches_committed_freeze_green`
- `test_cli_score_face_expect_report_end_to_end_green`

---

## 6. `git diff --stat` vs base

```
 .../tests/test_eval_harness_determinism_anchor.py  | 189 +++++++++++++++------
 .../test_eval_harness_face_determinism_anchor.py   | 106 +++++++++++-
 .../generate_face_determinism_anchor.py            |  67 +++++++-
 ...-face-determinism-anchor-manifest-20260811.json |  69 ++++++++
 ...eterminism-anchor-run-20260811-face-report.json |  35 ++--
 ...-determinism-anchor-run-20260811-face-report.md |  25 +--
 .../S2A-face-determinism-anchor-run-20260811.json  |  26 ++-
 7 files changed, 429 insertions(+), 88 deletions(-)
```

sha-guard:ignore-next-block
```
b91722b7 fix(fx5): HARM-05 extend face anchor corpus with unmatched stranger GT
191bef58 fix(fx5): RV3-01 make S4-01 oracle independent of generator helpers
7d4afdb4 fix(fx5): regenerate face determinism freeze after HARM-05 corpus extension
```

---

## 7. What could not be verified

- Live MCP handoff write (lane worktree; no `make context` target in this
  checkout). Report is the transport.
- End-to-end ANCHOR_MISMATCH CLI path under monkeypatched pre-HARM-01 formula
  (discrimination proven via direct re-score of detection dict + permanent unit
  test; full CLI cross-process under patch not required for the bar).
- Whether fx6's 7 CLI failures are solely category-vacuity (looks that way;
  not investigated further).

---

## 8. Cross-lane requests

- **fx6:** do not re-freeze face digests; our freeze already includes
  HARM-01/HARM-09 + extended corpus. CLI fixtures that hardcode face
  detection `fn=1` or `missed_stranger_gt` absence need their own update.
- **Coordinator:** face generator corpus body changed — if any parallel lane
  imported item counts (==8) or media_id layout, rebase onto this freeze.
- **No request to edit** `cli.py` / `describe_baseline.py` / `promote_atomic.py`
  from this lane.
