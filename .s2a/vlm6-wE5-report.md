# VLM-6 Wave E · lane wE5 — gate-prefix contract completeness

**Lane:** `wE5` · **Branch:** `fix/we5`  
**Base:** `88ed0e524bea8ee625afd405ca7f551d8ae1b5ba` (`integ/fx-wave`)  
**Owned:** `scripts/eval_harness/cli.py`, `scripts/eval_harness/README.md`,
`scene/tests/test_eval_harness_cli.py`  
**Untouched:** `report.py`, `provenance_sha.py`, `generate_determinism_anchor.py`,
`promote_atomic.py`, `face_metrics.py`, `scripts/check_lane_report_shas.py`,
`docs/tasks/vlm/bakeoff-results/**`

**Commits** (production + tests; this file is the docs commit on `fix/we5`):
sha-guard:ignore-next-block
```
9719eae4677760f9f2cf7aedc29302f7e72c2b18  fix(wE5): complete score gate-prefix contract (refuse-overwrite + run)
1dc2de8fdee922df1c0c5472c8fc25fd1fae4d99  test(wE5): bidirectional gate-prefix drift + call-site constant lock
```

Heuristics: `TEST-15`, `TEST-06`, `DBG-10`, `DBG-11`, `rg-006`, `rg-015`, `sr-001`, `RE-04`.

---

## 1. Per finding

### RF-04 — refuse-overwrite is a 17th label-varying `_score_gate_fail` class

**Reproduction (unfixed, DBG-10):**

```text
CAPTION REFUSE MSG: score refuse-overwrite: existing committed report(s) would be clobbered (...); pass --allow-overwrite-report to opt in ...
FACE REFUSE MSG: score-face refuse-overwrite: existing committed report(s) would be clobbered (...); pass --allow-overwrite-report to opt in ...
PREFIXES count: 16
Any refuse-overwrite in set? (only freeze-certification refused: matches substring "refuse")
```

Prefix varies by `label` (`score` vs `score-face`); neither stable class token in
`SCORE_GATE_PREFIXES` nor README table.

**RED (TEST-15):**

```text
$ pytest ...::test_refuse_overwrite_uses_stable_shared_prefix ...::test_score_gate_fail_call_sites_use_prefix_constants -q
FAILED test_refuse_overwrite_uses_stable_shared_prefix
  ImportError: cannot import name 'SCORE_GATE_PREFIX_REFUSE_OVERWRITE'
FAILED test_score_gate_fail_call_sites_use_prefix_constants
  L1374: _score_gate_fail arg does not reference SCORE_GATE_PREFIX_*
  names=['label', 'listed']
```

**Fix:**

```python
SCORE_GATE_PREFIX_REFUSE_OVERWRITE = "score refuse-overwrite gate:"
# message: f"{SCORE_GATE_PREFIX_REFUSE_OVERWRITE} {label}: existing committed ..."
```

Label moved to suffix (cx6 `score-face:` shape). Added to frozenset + README table.

**GREEN:**

```text
REFUSE[score]: score refuse-overwrite gate: score: existing committed report(s) would be clobbered ...
REFUSE[score-face]: score refuse-overwrite gate: score-face: existing committed report(s) would be clobbered ...
$ pytest ...::test_refuse_overwrite_uses_stable_shared_prefix -q
.  1 passed
```

Both start with `score refuse-overwrite gate:`; historical
`score-face refuse-overwrite:` does not return as class token.

---

### RF-05 — `run` multi-record wrapper emits unregistered path-interpolated prefix

**Reproduction (unfixed):**

```text
RUN EXIT: run score gates failed for 1 record(s): r1.json: score must-right failures gate: synthetic
STDERR: score gate failed for r1.json: score must-right failures gate: synthetic
score gate failed in PREFIXES? False
run score gates in PREFIXES? False
```

Stderr prefix embeds `record_path` before any fixed token; not greppable without path.

**RED:**

```text
FAILED test_cmd_run_scores_all_records_despite_gate_failure
  ImportError: cannot import name 'SCORE_GATE_PREFIX_RUN_RECORD'
FAILED test_score_gate_fail_call_sites_use_prefix_constants
  L1771: print gate wrapper missing SCORE_GATE_PREFIX_*; static='score gate failed for : '
  L1774: sys.exit gate summary missing SCORE_GATE_PREFIX_*; static='run score gates failed for  record(s): '
```

**Fix:**

```python
SCORE_GATE_PREFIX_RUN_RECORD = "run score gate failed:"
SCORE_GATE_PREFIX_RUN_SUMMARY = "run score gates failed:"
print(f"{SCORE_GATE_PREFIX_RUN_RECORD} {record_path}: {exc}", file=sys.stderr)
sys.exit(f"{SCORE_GATE_PREFIX_RUN_SUMMARY} {len(gate_failures)} record(s): {summary}")
```

Both registered in frozenset + README.

**GREEN:**

```text
RUN EXIT: run score gates failed: 1 record(s): r1.json: score must-right failures gate: synthetic
STDERR: run score gate failed: r1.json: score must-right failures gate: synthetic
$ pytest ...::test_cmd_run_scores_all_records_despite_gate_failure -q
.  1 passed
```

---

### RF-06 — README drift test one-directional; floor tolerates deletion

**Reproduction (unfixed, while RF-04 open):**

```text
$ pytest ...::test_score_gate_prefixes_documented_in_readme -q
.  1 passed in 1.54s   # GREEN while refuse-overwrite / run wrappers unregistered
# old body: missing = [p for p in SCORE_GATE_PREFIXES if p not in readme]
#           assert len(SCORE_GATE_PREFIXES) >= 15
```

**RED after rewrite (mutations against fixed production):**

Stale README row:

```text
inserted stale README row
FAILED test_score_gate_prefixes_documented_in_readme
  stale in README table: ['score stale-ghost gate:']
```

Delete one frozenset member (no `>= 15` slack):

```text
removed CATEGORY_VACUITY from frozenset
FAILED test_score_gate_prefixes_documented_in_readme
FAILED test_score_gate_fail_call_sites_use_prefix_constants
  (assignments ≠ frozenset; category-vacuity only in assignments)
```

**Fix:** Parse operator table under `### Score non-zero exit prefixes` (bounded
before "Integrity gates" / "Pre-gate hard failures"); assert
`set(table) == SCORE_GATE_PREFIXES` and `len(table) == len(SCORE_GATE_PREFIXES)`
(floor-free, count derived from frozenset).

**GREEN:**

```text
$ pytest ...::test_score_gate_prefixes_documented_in_readme -q
.  1 passed
# table count 19 == frozenset 19; missing=[]; stale=[]
```

---

### RE-04 — drift test does not lock call-site use of constants

**Reproduction (unfixed / pre-call-site-test):**

```text
# hardcode divergent aborted-record prefix at first call site; constants unchanged
$ pytest ...::test_score_gate_prefixes_documented_in_readme -q
GREEN (rc 0)
```

**RED (scratch mutation after lock lands):**

```text
mutated aborted-record call site to hardcoded divergent literal
FAILED test_score_gate_fail_call_sites_use_prefix_constants
  L1559: _score_gate_fail arg does not reference SCORE_GATE_PREFIX_*
  names=['json_path']
PASSED test_score_gate_prefixes_documented_in_readme   # still green alone
```

**Fix:** `test_score_gate_fail_call_sites_use_prefix_constants` AST-scans
`cli.py`:

1. Every `SCORE_GATE_PREFIX_*` assignment value ≡ `SCORE_GATE_PREFIXES`.
2. Every `_score_gate_fail(...)` arg references `SCORE_GATE_PREFIX_*`, an
   allowed prebuilt (`schema_exit` / `relabel_exit` / …), or
   `_score_schema_error_message(...)`.
3. `print` / `sys.exit` run-wrapper lines that look like gate messages must
   also reference the constants.

**GREEN:**

```text
$ pytest ...::test_score_gate_fail_call_sites_use_prefix_constants -q
.  1 passed
```

---

## 2. Disagreements

**None.** All four findings reproduced on base `88ed0e52…` before any fix.

Notes (not disagreements):

- RF-05 severity in rev-RF is low; still fixed as registered contract surface so
  scrapers watching `run` match without path knowledge.
- RF-06's "substring match on whole README" was real; table-column parse is
  stricter (prose mention alone no longer satisfies).

---

## 3. New findings (not owned)

| Id | Note | Owner |
| --- | --- | --- |
| — | None that require a cross-lane code change. | — |

Observation only: post-write integrity gates (aborted / failed-items / …) still
lack per-gate behavioural twins for *every* class; RE-04 AST lock covers the
hardcoding gap for all of them without one behavioural test each. Face
failed-items behavioural twin (cx6) retained as the model for the one class
that historically diverged.

---

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1340 passed, 4 skipped, 33 warnings in 324.44s`

| Class | Tests | Owner |
| --- | --- | --- |
| **Expected-red** | `test_generator_regenerates_byte_identical_committed_anchor` | regeneration stage (anchor freeze) |
| **Expected-red** | `test_expect_report_matches_committed_freeze_green` | regeneration stage |
| **Expected-red** | `test_face_generator_regenerates_byte_identical_committed_anchor` | regeneration stage |
| **Expected-red** | `test_face_expect_report_matches_committed_freeze_green` | regeneration stage |
| **Expected-red** | `test_cli_score_face_expect_report_end_to_end_green` | regeneration stage |
| **Unexpected-red** | *(none)* | — |

Baseline was `5 failed, 1338 passed, 4 skipped`. Net `+2` passes = the two new
tests (`call_sites_use_prefix_constants`, `refuse_overwrite_uses_stable_shared_prefix`);
existing run/README tests rewritten in place. **No new anchor fields published**
— freeze reds unchanged (not Expected-red growth from this lane).

---

## 5. `git diff --stat` vs base

```text
 .../scene/tests/test_eval_harness_cli.py           | 268 +++++++++++++++++++--
 .../scripts/eval_harness/README.md                 |  20 +-
 .../scripts/eval_harness/cli.py                    |  27 ++-
 3 files changed, 289 insertions(+), 26 deletions(-)
```

(Plus this report file in the report commit.)

---

## 6. Could not verify

- Live operator log scrapers that already key on the old
  `score gate failed for ` / `{label} refuse-overwrite:` strings — no in-repo
  consumers found (grep of scripts/Makefiles/CI); external scrapers outside
  this monorepo were not exercised.
- Did not re-run the full suite under a deliberate hardcode mutation (only the
  targeted gate-prefix tests) — full suite under mutation would also RED the
  new call-site test and is redundant for incidence.

---

## 7. Cross-lane requests

| To | Request |
| --- | --- |
| — | None. All fixes confined to owned files. |

---

## Contract after fix (`SCORE_GATE_PREFIXES` = 19)

| Prefix | Path |
| --- | --- |
| `score schema error:` | caption |
| `score aborted-record gate:` | caption + face |
| `score zero-scored gate:` | caption + face |
| `score failed-items gate:` | caption + face |
| `score truncation gate:` | caption |
| `score manifest-mismatch gate:` | caption |
| `score manifest-drift gate:` | caption |
| `score manifest-relabel gate:` | caption |
| `score empty-rubric gate:` | caption |
| `score must-right failures gate:` | caption |
| `score wrong-name floor vacuity gate:` | caption |
| `score wrong-name floor gate:` | caption |
| `score quality-floor gate:` | caption |
| `score category-vacuity gate:` | caption |
| `score freeze-certification refused:` | caption |
| `score face-report-readback gate:` | face |
| `score refuse-overwrite gate:` | caption + face (pre-write; label suffix) |
| `run score gate failed:` | `run` per-record stderr |
| `run score gates failed:` | `run` multi-record SystemExit |
