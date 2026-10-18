# WBUX-4. Bulk-Describe Integration Loop (WBUX-3 follow-ups)

> **Task:** `WBUX-4` · branch `feature/wbux-4` · worktree `context-alt-text-monorepo-wbux-4`
> **Epic:** `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (WBUX series)
> **Grounding:** WBUX-3 deferred findings `INT-01` (medium), `INT-02` (medium), `INT-03` (low) — read live via `review_findings(operation="list", task_ref="WBUX-3", status="deferred")`. Not duplicated here.
> **Date:** 2026-07-08

## Goal

Close the three integration gaps left open when WBUX-3 shipped honest bulk-describe progress: the generated drafts must reach the operator, a mid-run backend restart must not strand a run forever, and the unconsumed SSE surface (with its latent contract drift) must go.

## Decisions (operator-confirmed 2026-07-08)

- **INT-01 write-back = guarded smart default.** Drafts for images with **no existing alt** apply via one primary bulk action (low friction). Images that **already have alt** are bucketed and require **explicit per-item overwrite** — never clobbered by default. Mirrors the single-image `write_alt` opt-in (`class-describe-controller.php:124`) and the CLI `$existing_alt` guard (`class-description-command.php:212`). Rationale: refactoring-ui action-hierarchy — destructive actions are never the default.
- **INT-03 = cull describe SSE.** Delete backend `stream_describe_run`, PHP describe stream proxy, and `scene-describe-progress.schema.json`. Polling already delivers honest progress; SSE is unconsumed, pins a PHP-FPM worker, and is not a sovereignty mechanism. The **recognition scan SSE** (`useJobProgressStream.ts` → PHP `stream_job_progress`) stays as the reusable pattern if describe ever wants push.
- **INT-02 = startup reclaim.** Wire `reclaim_interrupted_runs` on FastAPI lifespan startup so non-terminal runs resume/terminate instead of hanging.

## Grounding (verified)

- Per-item results already persisted: `DescribeRunItem` (`db/models/scene.py:128`) carries `alt_text_draft`, `caption`, `provenance`, `status`, `media_id`. Repo `list_run_items` (`describe_run_repository.py:117`) already exists — the backend read is exposure only.
- `reclaim_interrupted_runs` (`describe_run_repository.py:169`) defined but never called (removed as dead code in WBUX-3 BE-05).
- WP single-image write path to mirror: `class-describe-media-service.php` (`ALT_TEXT_META_KEY`, `PROVENANCE_META_KEY`, `should_write_alt_text`).
- `existing_alt` is a WP concern (`get_post_meta(_wp_attachment_image_alt)`), resolved in the WP layer — the backend items endpoint stays WP-agnostic.

## Slices (vertical, one behavior path each)

1. **INT-01a — backend items endpoint.** `GET /scene/describe/run/{run_id}/items` → `[{media_id, status, alt_text_draft, caption, provenance}]` via `list_run_items`. New response schema + route + tenant guard. Test: run with mixed item outcomes returns the drafts. Evidence: `scene/interface_adapters/http/routers/describe_run.py`, `schemas/responses.py`.
2. **INT-01b — WP proxy read + existing_alt bucketing.** WP GET proxy `/recognition/describe/run/{id}/items` → backend; each item annotated `existing_alt: bool` via `get_post_meta`. Test (PHPUnit): proxy returns items with correct `existing_alt`. Evidence: `apps/prototype-wp-alt-context/src/api/class-describe-controller.php`.
3. **INT-01c — WP guarded apply.** Bulk apply writes `_wp_attachment_image_alt` + `_acx_description_provenance` for items **without** existing alt by default; overwrite requires explicit per-item `write_alt`. Reuse single-image write service. Test: default apply skips existing-alt items; explicit overwrite writes them. Evidence: `class-describe-controller.php`, `services/class-describe-media-service.php`.
4. **INT-01d — History UI surface.** Description History run view: primary "Apply all N (no existing alt)" + per-item overwrite for the existing-alt bucket; empty/zero states. Test: RTL unit + Playwright operator-evidence run. Evidence: `apps/prototype-wp-alt-context/js/`, `docs/scopes/e15-6-playwright-operator-evidence-harness.md`.
5. **INT-02 — startup reclaim.** Call `reclaim_interrupted_runs` in FastAPI lifespan startup. Test: a RUNNING run left over a simulated restart is reclaimed to terminal/resumed. Evidence: service `main.py` lifespan, `describe_run_repository.py:169`.
6. **INT-03 — cull describe SSE.** Delete backend stream route + `_progress_payload`, PHP describe stream proxy, `scene-describe-progress.schema.json`; assert no dangling references. Test: route removed, contract set has a single `completed` semantic. Evidence: `describe_run.py`, `class-describe-controller.php`, `contracts/`.

## Acceptance

- Operator can view a completed run's per-item drafts and apply them, with existing alt never overwritten without an explicit action.
- A backend restart mid-run does not leave a run polling forever.
- No unconsumed describe SSE surface remains; `completed` has one meaning across published describe contracts.
- Each slice: failing test first, passing evidence recorded, `handoff_close_check` green before merge.

## Deferred / out of scope

- GPU-procurement toast + self-hosted GPU offload (WBUX-3 deferred; unchanged).
- Re-introducing describe SSE as a true end-to-end push transport (only if a future task greenlights direct JS→FastAPI SSE, bypassing the WP proxy).

## Open threads (not WBUX-4 work)

- `stash@{0}` (`wbux3-worktree-unrelated-bleed`) parks two pre-existing worktree files — `docs/tasks/20.0/E20-11-hosted-provider-decision-memo.md` edit (→ E20-11) and `docs/scopes/workbench-batch-progress.md` (WBUX-3 scope intake leftover, untracked). Per operator: `git stash pop` under each owning task when that task is active. Left parked; not resolved here.
