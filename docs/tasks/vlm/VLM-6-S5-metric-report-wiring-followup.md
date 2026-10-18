# VLM-6 S5 follow-up: metric + report wiring (from deferred branch-review findings)

> **Status**: scope note (2026-07-15). Captures the S5-deferred findings from the VLM-6
> branch review so the ranking / decision-memo slice (S5) has the report + metric machinery
> it needs. Findings are tracked live in workbay (status=deferred):
> `review_findings(review={"operation":"list","task_ref":"VLM-6","status":"deferred"})`.
> Parent plan: `VLM-6-gpu-vlm-bakeoff-task-plan.md`.

## Why

S1 landed the harness (source-aware publishability, `face_boxes`, hallucination/placement
metrics), but three report/metric capabilities were deliberately deferred to S5 — where the
ranking actually consumes them. The audience-aware report split is currently unreachable, and
two placement-metric gaps under-detect. Each is a small, testable slice; run `/review-parallel`
per the merge-gate rule.

## Work items

### W1 — Wire the audience-aware report split (VLM6-C-01 / VLM6-F-03)

The public/local split (`report.Audience`, `_filter_for_public_audience`, the redaction block)
is verified sound but **unreachable**: no caller passes `Audience.PUBLIC` and there is no
`--audience` flag, so no redacted public artifact is ever produced.

- Add `--audience {local,public}` to `cli._cmd_score` (and `fusion_runner`) threading
  `Audience.PUBLIC` into `build_reports`; write the redacted public report to a distinct
  `<run>-report.public.{json,md}` path.
- Test: the public artifact is emitted, contains **only** publishable (celebs01) entries, and
  excludes every local path/name (extend `test_public_serialized_output_leaks_no_local_path_or_name`).
- This is the prerequisite that makes the `rd.altcontext.com` public gallery (RND-1) safe to
  build — it is the only sanctioned path from eval output to a public surface.

### W2 — BETWEEN wrong-claim detection (VLM6-D-01)

`placement_metrics._INVERT` has no `SpatialRelation.BETWEEN` case, so a caption asserting a
**wrong** between-claim scores as "no claim" (`accuracy=None`) instead of "wrong", silently
inflating placement accuracy for any image with a between-relation error.

- Add a between-specific wrong detector (swap `subject` with `reference`/`reference2`), or
  explicitly document/assert BETWEEN is correct-only so accuracy consumers know it under-detects.
- Test: a `BETWEEN` fact + a caption asserting the wrong between-claim scores as wrong.

### W3 — Free-text phrase robustness (VLM6-D-02)

`_invert_phrase` tokenizes on `split()` + exact match, so a direction token with attached
punctuation silently fails to invert (dormant today — the only phrase generator ends cleanly —
but `SpatialFact.phrases` is free-text, so future/manual authoring loses wrong-claim detection).

- Strip trailing punctuation before matching `_INVERT` (e.g. `token.strip(string.punctuation)`),
  or use a `\b` word-boundary regex substitution.
- Test: `_invert_phrase('in the foreground.')` and `_invert_phrase('to the left, near X')` invert.

## Sequencing

W1–W3 land before S5 ranking consumes the public report / placement accuracy. All three are
independent of the Golden-150 curation (which produces the corpus S5 scores *over*), so they can
proceed in parallel with the operator curation pass. Land them as one small slice (or three), gated
by `/review-parallel` + the remote gate, on `feature/vlm-6`.
