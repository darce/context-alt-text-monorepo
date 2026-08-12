# VLM-6 S2A F2b — out-of-band determinism payload (C-04 / E-08 / D-08)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F2b only (assignment #534) — `scripts/eval_harness/cli.py` + `scene/tests/test_eval_harness_cli.py`  
**Did not touch:** `report.py`, `test_eval_harness_pipeline.py`, `describe_baseline.py`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F2b. In-band `---MD---` stdout framing replaced with a structured out-of-band payload file (`{"json": ..., "md": ...}` dict). ERROR taxonomy preserved with three named payload-fault sub-cases. Full `eval_harness` selection: **671 passed, 4 skipped, 0 failed** (baseline at F2a host: 667 passed, 4 skipped).

## Defect

`_run_determinism_children` framed child docs as `json_doc + '---MD---' + md_doc` on stdout and recovered with `out.split("---MD---", 1)`. Three silent failure modes:

1. **Content collision** — free-form text re-emitted into report docs (identity names; also any future caption/draft field) that contains the literal `---MD---` splits at the wrong offset → false FAILED.
2. **Prefix contamination** — import banners / warnings prepended to stdout become part of `sub_json` → false FAILED on every host that prints them.
3. **Absence ≡ emptiness** — a child that never produced a payload but exited 0 with `---MD---` somewhere in a log line parsed as two junk halves.

## Fix (single-site — C-08 substrate)

Parent allocates a tempfile path per seed (not under `artifact_dir`), appends it as the final argv entry, unlinks so absence is real, runs the child, then:

| Condition | Operator string (OBS-04) |
|---|---|
| payload missing | `determinism check ERROR [{label}]: payload file missing ...` |
| payload unreadable | `determinism check ERROR [{label}]: payload file unreadable ...` |
| payload unparseable / wrong shape | `determinism check ERROR [{label}]: payload file unparseable ...` |
| genuine byte mismatch | `determinism check FAILED [{label}]: ... document=... artifact=...` (unchanged taxonomy) |
| clean match | `determinism check passed [{label}]: ...` |

Child scripts (score + score-face) write:

```python
Path(sys.argv[N]).write_text(json.dumps({"json": j, "md": m}))
```

Dict (not 2-tuple) so F2c can add a `build_reports_file` provenance field without redesign. Child stdout is unused for comparison. `json.JSONDecodeError` is caught and mapped to ERROR — never a traceback. `cwd=str(Path.cwd())` left as-is for F2c.

## Tests (sr-001: migrate mechanism, keep assertion; net count up)

| Test | Intent preserved |
|---|---|
| `test_cli_score_determinism_guard_detects_mutated_persisted_anchor` | real-subprocess FAILED (no change needed) |
| `test_cli_score_determinism_guard_errors_on_child_nonzero_rc` | ERROR on rc!=0 |
| `test_cli_score_determinism_guard_errors_on_malformed_output` | ERROR on missing payload (was: missing `---MD---` framing) |
| `test_cli_score_determinism_guard_errors_on_unparseable_payload` | **new** — ERROR unparseable |
| `test_cli_score_determinism_guard_errors_on_unreadable_payload` | **new** — ERROR unreadable |
| `test_cli_score_determinism_guard_survives_sentinel_in_freeform_text` | **new** — collision green path |
| `test_cli_score_determinism_guard_ignores_stdout_prefix_banner` | **new** — prefix green path |
| `test_cli_determinism_guard_labels_distinguish_score_and_face` | label identity |
| `test_cli_score_face_determinism_guard_detects_nondeterminism` | face FAILED via payload dict (migrated off stdout sentinel) |

No test skipped, xfailed, or weakened.

## Evidence

### Gate (verbatim)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
671 passed, 4 skipped, 408 deselected, 9 warnings in 35.54s
```

Determinism subset:

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_cli.py -k 'determinism' -q
11 passed, 69 deselected, 3 warnings in 13.00s
```

### COLLISION — free-form `---MD---` in report docs (TEST-15 + content safety)

Report JSON/MD re-emit identity names (not raw caption drafts). Name `Alice ---MD--- Example` lands in both documents.

**OLD transport simulation** (identical content framed on stdout, recovered with `split("---MD---", 1)`):

```text
---MD--- in json? True
---MD--- in md? True
OLD false-RED? True
json match? False md match? False
```

**NEW live gate** (same record/manifest):

```text
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED
NEW live: PASS
```

### PREFIX CONTAMINATION

```text
OLD transport false-RED from stdout banner: True
NEW transport ignores stdout: True (parent reads payload file only)
```

Live mock: child writes correct payload and prints `WARNING: onnxruntime CUDA EP unavailable\n` → `determinism check passed [score]` (pytest: `test_cli_score_determinism_guard_ignores_stdout_prefix_banner`).

### THREE ERROR SUB-CASES + CONTROL (live)

```text
MISSING:     determinism check ERROR [score]: payload file missing seed=0 path=...
UNPARSEABLE: determinism check ERROR [score]: payload file unparseable seed=0 path=...: Expecting value...
UNREADABLE:  determinism check ERROR [score]: payload file unreadable seed=0 path=...: [Errno 13] Permission denied...
FAILED mismatch: determinism check FAILED [score]: cross-process re-score differs under PYTHONHASHSEED=0 (document=JSON+MD; artifact=...; stderr='')
CONTROL clean (real children): determinism check passed [score]: ... PASS
```

### TEST-15 discrimination control

- Clean / collision-safe free-form text → exit 0, `determinism check passed [score]`
- Mutated persisted anchor / divergent payload → exit 1, `determinism check FAILED [score]` with `document=` + artifact
- Infra faults → `determinism check ERROR [score]` only (never FAILED)

### DBG-11 (causation by absence)

Sandbox history is stripped to a single base commit that does not exist in this
repository, so a literal `git checkout ec493295 -- cli.py` is impossible here.
<!-- history-stripped sandbox clone; the base object does not exist here -->

Equivalent proof:

1. **With the OLD framing logic** (reproduced inline on the same free-form identity name that lands in report docs): `split("---MD---", 1)` yields `sub != base` → false-RED class of FAILED.
2. **With the NEW payload path** (current `cli.py`): same input exits 0 with `determinism check passed [score]`.
3. **Prefix banner**: OLD prepends banner into `sub_json` (false-RED); NEW ignores stdout.

## Heuristics cited

| ID | How satisfied |
|---|---|
| **OBS-04** | ERROR vs FAILED retained; missing / unreadable / unparseable each name the remedy; no `JSONDecodeError` traceback |
| **TEST-15** | Clean control passes; genuine mismatch still FAILED; collision/prefix no longer false-RED |
| **DBG-11** | Old framing logic re-applied to free-form content restores false-RED; new transport removes it |
| **sr-001** | Existing tests migrated (malformed → missing payload; face nondeterminism → payload dict); no skip/xfail/weakening; net tests up |

## Not done / residual

- F2c owns import-root pin + payload provenance field (`build_reports_file`).
- Full `git checkout ec493295 -- cli.py` DBG-11 not runnable in this history-stripped sandbox; logical re-application of the old framing is the substitute evidence above.
- Caption drafts alone do **not** re-emit into report JSON/MD under current `report.py`; the load-bearing free-form collision surface today is identity names (and any future field that re-embeds model text). The transport fix still closes the class for all free-form content.
)