# VLM-6 la3 — describe_baseline: no silent clobber, no unguarded tenant write

**Lane:** `vlm6-la3-describe-baseline`  
**Task:** `VLM-6`  
**Findings:** VLM6-RH-01 (high), VLM6-RH-02 (high)  
**Branch:** `feature/vlm-6-la3`  

## Verdict

**merge_ready.** Both findings fixed in lane-owned files only. Gate green.

## Owned paths touched

| Path | Action |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/describe_baseline.py` | Fail-closed corpus, `--uploads`/`BASELINE_UPLOADS`, atomic no-clobber report writes, reuse `face_pass.assert_scratch_tenant` |
| `apps/prototype-description-service/scene/tests/test_eval_harness_describe_baseline.py` | New (create) — RH-01/RH-02 + resolve/clobber/force coverage |
| `.s2a/vlm6-la3-describe-baseline-report.md` | This report |

## Diff summary

`describe_baseline.py` (+152 / −15 conceptual):

1. **Removed** module-level hardcoded `UPLOADS = Path("/Volumes/Butter/...")`.
2. **Added** `resolve_uploads_root()` — `--uploads` flag or `BASELINE_UPLOADS` env; SystemExit names both when unset/missing (OBS-04). No laptop default.
3. **Added** `reanchor_attachment_path()` — maps TSV absolute paths onto the configured uploads root via `/wp-content/uploads/` (or `/uploads/`) marker.
4. **Fail closed on zero corpus** — if 0 of N attachment paths exist under the resolved root, print remedy + path and `return 1` **before** client construction and **before** any report write.
5. **Never empty-clobber** — `_write_report` refuses empty JSONL when a non-empty report exists; also refuses writing a brand-new empty report. Writes via temp + `os.replace`.
6. **Tenant guard (RH-02)** — on the RemoteSceneClient write path, call `assert_scratch_tenant(client)` from `face_pass` (not a second guard). Exit 2 on `SeededTenantError`. `--force` skips (parity with face_pass). Bakeoff path skips guard (analyze is a no-op stub; no MediaIdentity persist).
7. **Finally block** only rewrites reports when `work_started` is true (no zero-work overwrite).

## RED-before (unfixed code + new tests)

Command: `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -q -k describe_baseline`

```
10 failed, 2 passed, 1125 deselected in 16.15s
```

Key failures (actual output):

```
test_main_zero_corpus_exits_nonzero_and_names_remedy
E       assert 0 != 0
----------------------------- Captured stdout call -----------------------------
baseline: 1 attachments, 0 already done, 0 to describe (chunk=12)
done.

test_no_hardcoded_operator_uploads_constant
E           AssertionError: assert '/Volumes/Butter' not in '/Volumes/Bu...tent/uploads'
E               /Volumes/Butter/WP/vlm/app/public/wp-content/uploads

test_main_calls_assert_scratch_tenant_before_analyze
E       assert 0 != 0
----------------------------- Captured stdout call -----------------------------
baseline: 1 attachments, 0 already done, 0 to describe (chunk=12)
done.

test_resolve_uploads_requires_flag_or_env
E           AttributeError: ... has no attribute 'resolve_uploads_root'

test_main_happy_path_with_scratch_tenant
E       SystemExit: 2
pytest: error: unrecognized arguments: --uploads ...
```

The two cost tests in `test_describe_baseline.py` still passed (untouched surface).

## GREEN-after

Same command after fix:

```
............                                                             [100%]
12 passed, 1125 deselected in 5.46s
```

Zero-corpus stderr (OBS-04), observed with `-s`:

```
no corpus images found under uploads root /tmp/pytest-of-gate/.../uploads (0 of 1 attachment paths exist on disk). Pass --uploads DIR or set BASELINE_UPLOADS to the WordPress wp-content/uploads directory that holds this corpus.
```

## DBG-11 — tenant guard causation

Temporarily set `needs_tenant_guard = False` (guard path short-circuited; code otherwise unchanged):

```
test_main_calls_assert_scratch_tenant_before_analyze
E   assert 0 != 0
baseline: 1 attachments, 1 on disk, 0 already done, 1 to describe ...
  chunk 1: +1 items (1/1)
done.
1 failed
```

Restored `needs_tenant_guard = True`:

```
1 passed in 1.10s
```

Absence of the guard ⇒ seeded tenant proceeds to analyze/write; restoring guard returns non-zero and blocks analyze.

## Did NOT do (and why)

- **Did not edit** `face_pass.py`, `report.py`, `cli.py`, `caption_metrics.py`, `placement_metrics.py`, `manifest.py`, `golden.json` — exclusive ownership / out of scope.
- **Did not regenerate or modify** committed bakeoff-results under `docs/tasks/vlm/bakeoff-results/` — protecting those artifacts is the point of RH-01.
- **Did not move** `assert_scratch_tenant` to a shared module — brief says call it from `face_pass.py`; do not relocate.
- **Did not add a bakeoff-path tenant guard** — `BakeoffClient.analyze` is an inert no-op; no MediaIdentity persist. Guard applies to the RemoteSceneClient write path only.
- **Did not close findings in handoff MCP** — sandbox `make context` unavailable (`No rule to make target 'context'`); orchestrator owns finding status updates after review.
- **Did not run** full monorepo suite — lane gate is `-k describe_baseline` only.

## Honest notes

- Pre-fix zero-corpus RED proved `rc == 0` with `0 to describe` + `done.` (silent success). Report clobber is additionally blocked by `_write_report` empty-clobber refusal (tested separately).
- TSV still records operator absolute paths; runtime re-anchors under `--uploads`/`BASELINE_UPLOADS`. Editing the TSV was out of scope (not owned).
- Existing `scene/tests/test_describe_baseline.py` cost tests remain and stay green; new coverage lives in the owned create path `test_eval_harness_describe_baseline.py`.
