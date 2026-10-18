# Lane `vlm6-fx` R8 — named exit-2 for decode + --check artifact read

**Task:** VLM-6  
**Lane:** vlm6-fx  
**Findings closed:** VLM6-RV8-Q1-01 (medium), VLM6-RV8-L-02 (low)  
**Heuristics cited (IDs only):** TEST-15, AGT-21, AGT-10, REF-37, CARD-07  

Prior art (not redone): RV7-Q4-01 missing/directory exposure-file → exit 2; RV7-L-01 fail-closed non-canonical recorded exposure.

---

## Scope

| File | Change |
| --- | --- |
| `scripts/eval_harness/cli.py` | `_collect_exposure_notes`: `except (OSError, UnicodeDecodeError)`; `_cmd_draw_eval_split --check`: guard `json.loads(out.read_text())` with `except (OSError, ValueError)` → named exit 2 |
| `scene/tests/test_eval_harness_eval_split.py` | 3 tests: non-UTF8 exposure-file; --check missing out; --check malformed JSON |
| `.s2a/vlm6-fx-r8-report.md` | This report |

No freeze regen. No scoring edits. Existing assertions untouched (sr-001).

Verified anchors (mandate e): `_collect_exposure_notes` ~L2660; `--check` read ~L2703 (pre-fix). Brief line numbers matched.

---

## VLM6-RV8-Q1-01 — non-UTF-8 `--exposure-file`

**Defect:** `Path.read_text()` guarded with `except OSError` only. Bytes `b'\xff\xfe...'` raise uncaught `UnicodeDecodeError` → traceback exit 1, never named exit 2.

**Fix:** `except (OSError, UnicodeDecodeError)` → same stderr `draw-eval-split: exposure file not found/unreadable: <path>` + `SystemExit(2)`.

**Test:** `test_cli_draw_non_utf8_exposure_file_exits_2` (reuses `_draw_with_exposure_file`).

### RED (pre-fix)

```
FAILED ...::test_cli_draw_non_utf8_exposure_file_exits_2 - UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
```

### GREEN (post-fix)

```
.....                                                                    [100%]
5 passed, 5 warnings in 1.07s
```

(new + prior RV7-Q4-01 missing/directory)

### KILLED MUT[oserror_only_guard]

Revert `except (OSError, UnicodeDecodeError)` → `except OSError` only:

```
FAILED scene/tests/test_eval_harness_eval_split.py::test_cli_draw_non_utf8_exposure_file_exits_2 - UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte
1 failed, 1 warning in 1.00s
```

**KILLED.** Guard restored after mutation.

---

## VLM6-RV8-L-02 — unguarded `--check` artifact read

**Defect:** `artifact = json.loads(out.read_text())` unguarded. Missing `--out` → `FileNotFoundError` traceback exit 1; malformed JSON → `JSONDecodeError` traceback exit 1.

**Fix:** wrap read/parse in `except (OSError, ValueError)` → stderr `draw-eval-split: sealed split not found/unreadable: <path>` + `SystemExit(2)`. (`JSONDecodeError` ⊂ `ValueError`.)

**Tests:** `test_cli_check_missing_out_exits_2`, `test_cli_check_malformed_out_json_exits_2` (reuse `_check_cli_args`).

### RED (pre-fix)

```
FAILED ...::test_cli_check_missing_out_exits_2 - FileNotFoundError: [Errno 2] No such file or directory: '.../no-such-sealed-split.json'
FAILED ...::test_cli_check_malformed_out_json_exits_2 - json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
```

### GREEN (post-fix)

Same 5-pass battery as above (includes both new --check tests).

### KILLED MUT[unguarded_check_read]

Drop the try/except; missing-path test:

```
FAILED scene/tests/test_eval_harness_eval_split.py::test_cli_check_missing_out_exits_2 - FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-gate/pytest-2069/test_cli_check_missing_out_exi0/no-such-sealed-split.json'
1 failed, 1 warning in 1.02s
```

**KILLED.** Guard restored after mutation.

---

## Full TEST_CMD

```
cd apps/prototype-description-service && ./.venv/bin/python -m pytest scene/tests/test_eval_harness_eval_split.py -q -p no:randomly
```

```
123 passed, 110 warnings in 1.62s
```

---

## In-lane /branch-review (no fan-out)

- Scope confined to two sites + three tests + this report.
- Named exit 2 + stderr strings match RV7-Q4-01 pattern (AGT-21 / AGT-10 / CARD-07).
- Catch tuples are intentional and non-silent (REF-37): errors mapped to operator-visible stderr + exit 2.
- TEST-15: RED → GREEN → both mutations KILLED with pasted output.
- No assertion relaxation; no freeze/scoring edits.

**Verdict:** pass_with_findings closed by this slice (Q1-01, L-02). Ready for orchestrator review.
