# VLM-6 fx6 — CLI sample-size fixtures + SHA provenance de-dupe

Lane: `fx6` · Branch: `fix/fx6` · Base: `7d868a34a86b3b9d25eb6a84b6dc909eb2185ccf`

Commits:
sha-guard:ignore-next-block
```
d33b66aa fix(fx6): expand CLI score fixtures to SCORE_PASS_MIN_SCORED_IMAGES=5
723fb272 fix(fx6): de-duplicate HEAD-SHA provenance guard into provenance_sha
```

Heuristics: `TEST-15`, `AUDIT-07`, `EVAL-23`, `rg-006`, `rg-015`, `sr-001`, `sr-007`.

---

## 1. Task 1 — seven CLI tests vs sample-size floor

Wave A (fx1) raised `SCORE_PASS_MIN_SCORED_IMAGES` 2→5. All seven failed identically:

```
SystemExit: score category-vacuity gate: verdict=not_ready
  (sample-size: scored=2 < min=5 (...); not adoption-eligible; ...)
```

### Classification (all seven = **(a)**)

| # | Test | Class | Reasoning |
|---|------|-------|-----------|
| 1 | `test_cmd_score_public_audience_emits_redacted_public_artifact` | **(a)** | Subject is PUBLIC redaction (local name/path/base_url withheld). 2-image corpus was incidental. |
| 2 | `test_cmd_score_default_local_emits_no_public_artifact` | **(a)** | Subject is default-audience byte-compat (no public artifact on success). |
| 3 | `test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures` | **(a)** | Subject is clean green path (pass, wrong_name_rate=0, measurable cats). Docstring mentioned n=2 only as floor clearance. |
| 4 | `test_cli_score_check_determinism_runs_cross_process_guard` | **(a)** | Subject is cross-process determinism guard wiring. |
| 5 | `test_cli_score_determinism_certifies_written_rubric_gate` | **(a)** | Subject is GATE-05: certified bytes share `rubric_gate=skip` with written artifact. |
| 6 | `test_cli_score_audience_public_check_determinism_covers_both_labels` | **(a)** | Subject is dual-label determinism under `--audience public`. |
| 7 | `test_score_freeze_certification_exits_nonzero_on_anchor_mismatch` | **(a)** | Subject is ANCHOR_MISMATCH on tampered `--expect-report`. **Critical:** first `main()` (check-determinism only) died on sample-size `not_ready` *before* the mismatch path. With n=2, the test could never exercise freeze-cert mismatch; a non-zero exit alone would be a false green. |

None were **(b)** (no test genuinely owns the small-corpus path — report tests already cover n=2 / n=4 `not_ready`). None were **(c)** (Wave A did not break production; fixtures lagged the floor).

### Fix

Shared helpers expanded (not bulk-renamed tests):

- `_clean_score_manifest_and_record` → 5 measurable single-name images (pads if floor rises).
- `_w1_audience_manifest_and_record` → 4 publishable + 1 local-only (`withheld_items=1` preserved; public `per_image` ids updated to `{10,11,12,13}`).

`SCORE_PASS_MIN_SCORED_IMAGES` **not** lowered (`sr-001`).

### RED / GREEN (verbatim)

**RED (pre-fix base, all seven):**
```
FAILED ... test_cmd_score_public_audience_emits_redacted_public_artifact
  SystemExit: score category-vacuity gate: verdict=not_ready (sample-size: scored=2 < min=5 ...)
FAILED ... test_cmd_score_default_local_emits_no_public_artifact  — same
FAILED ... test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures — same
FAILED ... test_cli_score_check_determinism_runs_cross_process_guard — same
FAILED ... test_cli_score_determinism_certifies_written_rubric_gate — same
FAILED ... test_cli_score_audience_public_check_determinism_covers_both_labels — same
FAILED ... test_score_freeze_certification_exits_nonzero_on_anchor_mismatch
  (dies on first main() with not_ready; never reaches ANCHOR_MISMATCH)
7 failed, 124 deselected in 25.98s
```

**GREEN (post-fix):**
```
.......                                                                  [100%]
7 passed, 124 deselected in 25.67s
```

### TEST-15 discrimination (expanded fixtures still load-bearing)

**Probe 1 — public redaction still fails if local name leaks:**
```
RED (expected): AssertionError — local name present in public artifact after simulated leak
  local_name='Jane Doe Private' found_in_public=True
```

**Probe 2 — freeze cert fails on ANCHOR_MISMATCH, not sample-size:**
```
  first score verdict=pass scored=5
RED (expected): SystemExit: determinism check ANCHOR_MISMATCH [score]: fresh re-score does not match --expect-report ...
  confirmed ANCHOR_MISMATCH (not sample-size not_ready)
```

**Probe 3 — n=4 still `not_ready` (floor still binds):**
```
scored=4/4 ... verdict=not_ready
RED at n-1 (expected): score category-vacuity gate: verdict=not_ready
  (sample-size: scored=4 < min=5 (...))
```

---

## 2. Task 2 — one SHA guard

### Shared module

`scripts/eval_harness/provenance_sha.py` → `normalize_head_sha(...)`.

Call sites:
- `describe_baseline.resolve_head_sha` → `empty_policy="none"`, `verify_git=True`
- `promote_atomic.validate_live_head_sha` → thin wrapper, **name+signature preserved** for fx5 generators; `empty_policy="refuse"`; always verifies (see below)

### Reconciliation decisions

| Difference | Decision | Why |
|------------|----------|-----|
| Empty / whitespace | Shared supports `empty_policy` ∈ {`none`,`refuse`}. `resolve_head_sha` → `none` (env/module unset). `validate_live_head_sha` → `refuse` (CLI flag must not silent-exit pin mode, RV2-05). Both agree empty is not a valid SHA; call-site policy differs because env-unset ≠ flag-present-empty. | Preserves both contracts without two format implementations. |
| Uppercase | Shared `strip().lower()` then hex40. Both accept upper. | Already agreed; one path now. |
| Git verify | **Always on**, with **degrade** when git missing or cwd not a work tree (fx4 shape). `verify_git` param retained on `validate_live_head_sha` for signature stability but **cannot open the guard** (`del verify_git`; always passes `True`). Hard-fail-only-when-flag (fx2) replaced by degrade. | One policy stops independent drift open (`rg-015`). Offline/non-repo still records format-valid SHAs. |

### Divergence test

`test_fx6_head_sha_entry_points_agree_on_accept_refuse_table` drives the same table through both entry points:

- Shared accept/refuse: `None`, zero-sentinel, short/non-hex, arbitrary `"a"*40` (refuse when git answers), real HEAD, uppercase real HEAD.
- Deliberate empty-policy difference asserted separately.
- Git-absent degrade: both accept format-valid fake hex.

### RED / GREEN (shared guard)

**RED:**
<!-- sha-guard:ignore-next-block -->
```
RED: HEAD_SHA is the fabricated 40-zero sentinel; ...
RED: HEAD_SHA='aaaaaaaa...' is not a resolvable commit in this repository ...
RED: HEAD_SHA must not be empty; omit the flag ...
```

**GREEN:**
```
GREEN: both accept <real HEAD>
GREEN empty: resolve→None; validate→refuse
24 passed  (test_describe_baseline_pin_provenance.py, incl. divergence test)
```

Collateral (not owned but required): `test_s4_04_non_pin_does_not_null_live_provenance` used `"b"*40`; under default-on verify that is correctly refused — switched to real worktree HEAD. Monkeypatch for degrade-without-git retargeted at `provenance_sha.subprocess`.

---

## 3. Task 3 — `_fmt_prov` empty-string branch

**Do not edit `report.py` (unowned).** Evidence only.

```python
def _fmt_prov(value, *, default="unknown"):
    if value is None: return "null"
    if isinstance(value, bool): return "true"/"false"
    if value == "": return default   # ← branch in question
    return str(value)
```

**For `provenance.head_sha` specifically — effectively dead after Wave A:**

- `resolve_head_sha` / `_head_sha` paths return `None` or a 40-hex string, never `""` (`describe_baseline` comment: `# None when unset — never "" (HARM-03)`).
- Anchor pin path: `head_sha=""` is an *input* to `build_run_record`, which does `live_head = head_sha or None` before writing provenance; pin mode then forces `record["provenance"]["head_sha"] = None`.
- Direct probe: `_fmt_prov("") == "unknown"`, `_fmt_prov(None) == "null"`.

**Not provably dead for all `_fmt_prov` call sites:** used for `base_url`, `manifest_sha256`, `started_at`, face model fields, etc. An empty string on any of those still hits the branch. Adversarial / hand-edited JSON could also present `""`.

**Follow-up (not this lane):** either keep the branch as defence-in-depth, or assert at report-build that provenance string fields are `None | non-empty` and drop the `""` arm with a unit test that fails if a producer reintroduces `""`.

---

## 4. Disagreements / counter-probes

- **fx1 n=5 derivation:** agreed. `0.5^5 = 0.03125 < 0.05`; n=2 was never justified. Did not reopen the constant.
- **Empty-string "make both agree":** fully identical empty handling would either re-open RV2-05 (CLI empty → None) or break describe unset-via-empty-env. Parameterized policy on one shared core is the honest reconciliation; divergence test documents the deliberate difference.
- **`verify_git` signature force-on:** generators still pass `verify_git=bool(args.verify_live_head_sha)` (default False). Wrapper ignores it so fx5 needs no edit this wave. Flag becomes a no-op until a follow-up removes it (`rg-006` doc sync).

---

## 5. Full suite

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
# 3 failed, 1301 passed, 4 skipped, 31 warnings in 179.66s
```

### Expected-red (fx5 owns — not fixed)

1. `test_eval_harness_face_determinism_anchor.py::test_face_generator_regenerates_byte_identical_committed_anchor`
2. `test_eval_harness_face_determinism_anchor.py::test_face_expect_report_matches_committed_freeze_green`
3. `test_eval_harness_face_determinism_anchor.py::test_cli_score_face_expect_report_end_to_end_green`

### Unexpected-red

None.

---

## 6. `git diff --stat` against `7d868a34`

```
 .../tests/test_describe_baseline_pin_provenance.py |  72 ++++-
 .../scene/tests/test_eval_harness_cli.py           | 329 ++++++++++++---------
 .../scripts/eval_harness/describe_baseline.py      |  69 +----
 .../scripts/eval_harness/promote_atomic.py         |  64 ++--
 .../scripts/eval_harness/provenance_sha.py         | 121 ++++++++
 5 files changed, 407 insertions(+), 248 deletions(-)
```

(Report file committed separately; may add one more file to the stat.)

---

## 7. What I could not verify

- Live generator CLI with `--live-head-sha` against a real promote (no network / no freeze rewrite this lane).
- That fx5's face-anchor freezes are the sole cause of the 3 reds (assumed per brief; did not bisect scoring vs freeze).
- Whether any non-head_sha provenance field still emits `""` in production paths (would need a full producer audit).

---

## 8. Cross-lane requests

| To | Ask |
|----|-----|
| **fx5** | Own the 3 face-determinism-anchor failures. After regenerating freezes, consider dropping `--verify-live-head-sha` (now a no-op) or documenting always-on verify. |
| **coord / docs** | README exit-prefix / flag docs may still describe verify as opt-in (`rg-006`). |
| **follow-up** | `_fmt_prov` `""→unknown` branch: keep as defence or delete with a producer invariant test (unowned `report.py`). |

---

## Files touched

Owned:
- `scene/tests/test_eval_harness_cli.py` (task 1)
- `scripts/eval_harness/describe_baseline.py`, `promote_atomic.py` (task 2 wrappers)
- `scripts/eval_harness/provenance_sha.py` (new)
- `.s2a/vlm6-fx6-report.md` (this)

Collateral (required by task-2 default-on verify):
- `scene/tests/test_describe_baseline_pin_provenance.py` (real HEAD fixture + degrade monkeypatch + divergence test)

Not touched: fx5 generators, face anchor freezes/seeds, `report.py`.
