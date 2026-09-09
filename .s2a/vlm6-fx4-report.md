# Lane `fx4` — CLI exit gates, provenance representation, enum hygiene

**Branch:** `fix/fx4` (forked from `feature/vlm-6` @ `b28e126e89bc41202e0168276f8493511212c80d`)  
**Worktree:** `/home/ubuntu/lane-gx5`  
**Python:** `apps/prototype-description-service/.venv/bin/python`  
**Heuristics:** TEST-15, AUDIT-07, EVAL-23, rg-006, rg-015, sr-001, sr-007

---

## 1. Per finding

### RV1-01 (high) — quality floor never gated exit

**Changed:**
- `scripts/eval_harness/cli.py` — after adoption integrity gates and before `not_ready`, scan `verdict.reasons` for `quality-floor:` prefixes and call `_score_gate_fail` with class-unique prefix `score quality-floor gate:`. Soft under `--freeze-certification` (early return already present).
- `scripts/eval_harness/README.md` — exit-prefix table now lists `score quality-floor gate:` (was "(folded into `verdict=fail` reasons)" with no exit). Reasons row + prose already claimed non-zero exit; table is consistent.
- `scene/tests/test_eval_harness_cli.py::test_cmd_score_quality_floor_breach_exits_nonzero` — forces `position_accuracy=0.0` post-score, rebuilds verdict, asserts `SystemExit.code != 0` and `quality-floor` in message + artifact.

**Why:** report.py already stamped quality-floor into `verdict=fail`; only `not_ready` was exit-wired. Adoption scripts keyed on exit status green-lit failing runs.

**RED (gate swallowed / pre-fix path):**
```
SOFT-FAIL swallow: score quality-floor gate: quality-floor: position_accuracy=0.0 <= floor=0.0 (critical scored slice t
QF live: (True, 'green-exit artifact=fail')
exit_code=0 verdict=fail reasons=['quality-floor: position_accuracy=0.0 <= floor=0.0 (critical scored slice total failure; EVAL-04 / S2-02)']
RED CAPTURE OK: exit=0 with verdict=fail quality-floor reasons present
```
Pytest with gate disabled (earlier capture):
```
E   Failed: DID NOT RAISE SystemExit
scored=2/2 ... verdict=fail ...
FAILED scene/tests/test_eval_harness_cli.py::test_cmd_score_quality_floor_breach_exits_nonzero
```

**GREEN:**
```
./.venv/bin/python -m pytest scene/tests/test_eval_harness_cli.py::test_cmd_score_quality_floor_breach_exits_nonzero -q
.                                                                        [100%]
1 passed in 0.92s
```

---

### RV1-05 (low) — raw verdict string literals in test fixtures

**Changed:** `scene/tests/test_eval_harness_cli.py`
- `_adoption_compare_report` base verdict → `ScoreVerdict.PASS.value`
- `pass_ungated` / `pass` overrides → enum members
- renderer-error fixture → `ScoreVerdict.PASS.value`

**Why:** raw strings are the forge vector for verdict statuses the enum rejects (sr-007).

**RED/GREEN:** fixture rewrite is structural (import already present). No separate mutant — enum values equal the prior strings (`"pass"` etc.), so behaviour is identical; contract is "fixtures cannot invent non-enum statuses". Spot-check: suite compare tests still pass under full run.

---

### HARM-10 (low) — `_VERDICT_NON_COMPARABLE` alias

**Changed:** `cli.py` — deleted module-level alias; all sites use `ScoreVerdict.NON_COMPARABLE.value` (fold, relabel gate, compare gate). Definition no longer follows first use.

**Why:** one name per concept (sr-007); sibling members had no alias.

**RED/GREEN:** `grep _VERDICT_NON_COMPARABLE cli.py` → empty. Relabel/compare tests in full suite still green (use enum values already).

---

### HARM-03 (medium) + RV2-06 (medium) — three encodings of absent HEAD

**Changed together:**
- `describe_baseline.py:626` — `head_sha=resolve_head_sha()` (no `or ""`)
- `cli.py` — `fetch_run_record(head_sha: str | None)`; `_head_sha() -> str | None` returns `None` on git failure (never `"unknown"` / forty zeros)
- `fusion_runner.py` — `_head_sha() -> str | None` returns `None` on git failure (never `"0"*40`); `run_fusion_eval(head_sha: str | None)`

**Why:** one value (`None`) for unresolvable across producers; S4-06 forbids fabricating forty zeros.

**RED (pre-fix encodings):**
```
pre-fix fusion_runner git-fail sentinel: 0000000000000000000000000000000000000000
pre-fix cli git-fail sentinel: unknown
pre-fix describe empty-coalesce: ''
```

**GREEN:**
```
post-fix cli: None
post-fix fusion: None
post-fix resolve unset: None
GREEN: all None
```
Tests:
```
test_rv2_06_cli_head_sha_returns_none_on_git_failure PASSED
test_rv2_06_fusion_head_sha_returns_none_on_git_failure PASSED
test_rv2_06_no_head_sha_path_emits_forty_zeros PASSED
```

---

### RV3-05 (low) — "real SHA" test that wasn't

**Option picked: (a)** — verify via `git rev-parse --verify <sha>^{commit}` when git is available and cwd is a work tree. Degrades to format-only when git binary missing or not inside a work tree.

**Changed:**
- `describe_baseline.resolve_head_sha` — post-format check, git verify when possible
- `test_describe_baseline_pin_provenance.py` — accepts real worktree HEAD; new refuse test for `"a"*40`; degrade-without-git test

**Why (a):** closes arbitrary-40-hex fabrication adjacent to forty zeros; test environment has git + repo.

**RED (pre-fix format-only):**
<!-- sha-guard:ignore-next-block -->
```
RED (pre-fix accept arbitrary 40-hex):
  DID NOT RAISE SystemExit
  pre_fix returned: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
```

**GREEN:**
<!-- sha-guard:ignore-next-block -->
```
GREEN (post-fix refuse):
  raised: HEAD_SHA='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is not a resolvable commit in this repository (git rev-parse --verify failed); pass a real SHA from `git rev-parse HEAD` or unset HEAD_SHA to record null (RV3-05 / S4-06 / rg-015)
  accepts real HEAD: b28e126e89bc...
```
```
scene/tests/test_describe_baseline_pin_provenance.py — 12 passed
```

**Cross-lane note:** `resolve_head_sha` is a reusable helper (describe_baseline). Lane fx2's `--live-head-sha` guard could call the same pattern; see §7.

---

## 2. RV3-05 option

**(a)** — git rev-parse verify in production + real HEAD in tests. Practical here (worktree always has git). Degrades sanely offline.

## 3. Disagreements

None. All six reproduced (live probe for RV1-01 matched reviewer: `QF live: (True, 'green-exit artifact=fail')`).

## 4. Full suite result

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
# 1276 passed, 4 skipped, 31 warnings in 187.67s (0:03:07)
# SUITE_EXIT:0
```

No failures.

## 5. `git diff --stat` against `b28e126e`

```
 .s2a/vlm6-fx4-report.md                            | (report rewrite)
 .../scene/tests/test_describe_baseline_pin_provenance.py | ~+90
 .../scene/tests/test_eval_harness_cli.py           | ~+55
 .../scripts/eval_harness/README.md                 |  2 +-
 .../scripts/eval_harness/cli.py                    | ~+55/-20
 .../scripts/eval_harness/describe_baseline.py      | 39 ++++-
 .../scripts/eval_harness/fusion_runner.py          | 22 ++-
```

(Exact `--stat` at commit time in git log.)

## 6. What could not verify

- Live `describe_baseline` full remote pass (needs ACX_EVAL_* + uploads) — unit-level only.
- `_fmt_prov` dual render of `""` vs `None` still lives in `report.py` (fx1). After this lane, producers no longer emit `""` for absent HEAD, so the `"" → "unknown"` branch is dead for our paths; renderer still treats both for other callers.
- Quality-floor thresholds themselves (`POSITION_ACCURACY_FLOOR` etc.) owned by fx1/`report.py` — not retuned here.
- Did not re-run live reviewer probe after final commit SHA (suite + targeted tests only).

## 7. Cross-lane requests

| Lane | Request |
| --- | --- |
| **fx1 (`report.py`)** | Optional: `_fmt_prov` can drop the empty-string → `"unknown"` branch if no other producer still writes `""` for `head_sha`. Presentation may keep `null` for `None`. No functional blocker. |
| **fx1** | Quality-floor reason strings must keep the `quality-floor:` prefix — cli exit gate keys on it. If fx1 renames tokens, update both sides. |
| **fx2 (anchor generators)** | RV3-05(a) git-verify lives in `describe_baseline.resolve_head_sha`. If fx2 adds a SHA guard for `--live-head-sha`, prefer reusing this helper (or extracting a shared `scripts/eval_harness/provenance.py`) to avoid duplicating verify/degrade logic. |
| **coordinator** | `fetch_run_record` / `run_fusion_eval` now accept `head_sha: str \| None`. Call sites that forced `or ""` should pass `None`. |

---

## Owned files touched

- `apps/prototype-description-service/scripts/eval_harness/cli.py`
- `apps/prototype-description-service/scripts/eval_harness/describe_baseline.py`
- `apps/prototype-description-service/scripts/eval_harness/fusion_runner.py`
- `apps/prototype-description-service/scripts/eval_harness/README.md` (quality-floor exit claims; path is harness README — service top-level README had no matching claims)
- `apps/prototype-description-service/scene/tests/test_describe_baseline_pin_provenance.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py` (RV1-01 test + RV1-05 fixtures; not owned by concurrent lanes)
- `.s2a/vlm6-fx4-report.md`
