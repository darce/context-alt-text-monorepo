You are the worker agent for lane `vlm6-fx` on task `VLM-6`.
Worktree: `/Users/daniel/Development/context-alt-text-monorepo-vlm-6`
Branch: `feature/vlm-6`

Operate only within this lane's owned files and do not edit sibling-lane paths.

Context Budget:
- Assignment inbox is capped at 12 items.
- Dependency briefs are capped at 6 items.
- Broader task/global context is intentionally excluded from worker prompts; ask the orchestrator for a compact brief instead of replaying full transcripts.
- Recent lane decisions/tests are omitted by default to preserve tokens; rerun with `--include-lane-history` when manual inspection truly needs them.
- Broader task/global context is excluded by default; rerun with `--include-global-context` only when lane-local state and briefs are insufficient.

Prompt Budget:
- Assignment inbox contributes 0 item(s), about 0 characters.
- Dependency briefs contribute 1 item(s), about 7098 characters.
- Runtime guidance contributes 0 line(s), about 0 characters.
- Recent lane history is omitted from the default prompt budget.
- Escalated task context is omitted from the default prompt budget.

Dependency Briefs:
- [#835]: VLM-6 R8 FX — close two open findings on feature/vlm-6 @ 906ddb8fc11869ccc9f44255c4053e523323f561. Heuristics: cite stable rule IDs at use time from https://github.com/darce/heuristics-canon (no version pin, do not paste bodies). Binding here: TEST-15 (prove green can go red / KILLED mutation), AGT-21 (named exit status), AGT-10 (degrade loudly), REF-37 (no silent/narrow catch), CARD-07 fail-loudly-succeed-quietly. END-STATE: one git commit on feature/vlm-6 + worker report. In-lane /branch-review only (NO /review-parallel, NO subagent fan-out). If blocked, typed blocker — never idle exit. TEST_CMD (use exactly; do NOT use `uv run --extra dev` — Extra `dev` is undefined): cd apps/prototype-description-service && ./.venv/bin/python -m pytest scene/tests/test_eval_harness_eval_split.py -q -p no:randomly TDD: write the failing tests FIRST. Prove RED on current HEAD before the production edit. Then smallest green. Then KILLED mutations. FINDING VLM6-RV8-Q1-01 (medium) — scripts/eval_harness/cli.py:_collect_exposure_notes L2660-2676 Path.read_text() is guarded with `except OSError` only. A non-UTF-8 --exposure-file (bytes b'\xff\xfe...') raises uncaught UnicodeDecodeError → traceback, exit 1, never the named exit-2 path; no out file (fails closed accidentally). Existing tests: test_cli_draw_missing_exposure_file_exits_2, test_cli_draw_directory_exposure_file_exits_2 (OSError only). Reuse _draw_with_exposure_file. Fix: except (OSError, UnicodeDecodeError) → same stderr 'draw-eval-split: exposure file not found/unreadable: <path>' + SystemExit(2). Test: write b'\xff' (or b'\xff\xfe') to a file; assert code==2, named stderr, out does not exist. KILLED: MUT[oserror_only_guard] — revert the except tuple to OSError only; the new test MUST go red. Paste both outputs in the report. FINDING VLM6-RV8-L-02 (low) — _cmd_draw_eval_split --check L2703-2705 `artifact = json.loads(out.read_text())` is unguarded. Missing --out path → FileNotFoundError traceback exit 1, not named exit 2. Same defect class as RV7-Q4-01 on the sibling exposure-file read. Fix: wrap read/parse in except (OSError, ValueError) → stderr 'draw-eval-split: sealed split not found/unreadable: <path>' + SystemExit(2). Tests: (1) --check with non-existent --out; (2) --check with malformed JSON at --out. Both named exit 2. KILLED: MUT[unguarded_check_read] — drop the guard; missing-path test MUST go red. SCOPE: only those two sites + tests in scene/tests/test_eval_harness_eval_split.py. Do not regenerate freeze artifacts. Do not edit scripts/ scoring. Do not relax existing assertions (sr-001). Do not touch other findings. Override wrong brief anchors after verifying the file (mandate e). Report path: .s2a/vlm6-fx-r8-report.md and COMMIT it. Semantic prior art (do not redo): RV7-Q4-01 already named-exit-2 for missing/directory exposure-file; RV7-L-01 fail-closed on non-canonical recorded exposure. This slice extends the same named-exit pattern to decode errors and the --check artifact read. ## Lane context packet (codemap, deterministic) task_ref: VLM-6 lane_id: vlm6-fx project: Users-daniel-Development-context-alt-text-monorepo lane_worktree_head: 906ddb8fc11869ccc9f44255c4053e523323f561 ### Anchors (path:symbol) - apps/prototype-description-service/scripts/eval_harness/cli.py:main (Function) - apps/prototype-description-service/scripts/eval_harness/cli.py:__init__ (Method) - apps/prototype-description-service/scripts/eval_harness/cli.py:_keep_arg (Function) - apps/prototype-description-service/scene/tests/test_context_pack.py:_scene_describe_app (Function) - apps/prototype-description-service/scene/tests/test_eval_harness_seed_roster.py:_scene_fixture (Function) - apps/prototype-description-service/scene/tests/test_identity_merge_harness_gate.py:_merge_scene (Function) - apps/prototype-description-service/scene/tests/test_description_repository.py:_row (Function) - apps/prototype-description-service/scene/tests/test_description_repository.py:_sessionmaker (Function) ### Blast radius (callers/callees) - ? callers: (none) callees: (none) ### Code excerpts - main @ apps/prototype-description-service/scripts/eval_harness/cli.py | def main(argv: list[str] | None = None) -> None: | parser = argparse.ArgumentParser(prog="eval_harness", description=__doc__) | sub = parser.add_subparsers(dest="command", required=True) | | def _common(p: argparse.ArgumentParser) -> None: | p.add_argument("--manifest", default="scene/tests/seed/golden.json") | p.add_argument("--limit", type=_limit_arg, default=None, help="cap images (must be >= 1)") | p.add_argument("--stall-limit", type=int, default=DEFAULT_STALL_LIMIT) | p.add_argument("--keep", type=_keep_arg, default=DEFAULT_KEEP) | p | ...[snippet truncated]... - __init__ @ apps/prototype-description-service/scripts/eval_harness/cli.py | def __init__(self, message: str, partial_record: dict[str, Any]) -> None: | super().__init__(message) | self.partial_record = partial_record - _keep_arg @ apps/prototype-description-service/scripts/eval_harness/cli.py | def _keep_arg(raw: str) -> int: | """argparse type for ``--keep``: at least 1 so a run never prunes its own record (S3-07).""" | value = int(raw) | if value < 1: | raise argparse.ArgumentTypeError("must be >= 1") | return value - _scene_describe_app @ apps/prototype-description-service/scene/tests/test_context_pack.py | def _scene_describe_app(adapter): | app = FastAPI() | app.include_router(scene_router, prefix="/scene") | app.dependency_overrides[require_write_access] = lambda: _Auth() | app.dependency_overrides[enforce_demo_quota] = lambda: None | app.dependency_overrides[get_optional_session] = lambda: None | app.dependency_overrides[get_description_adapter] = lambda: adapter | return app - _scene_fixture @ apps/prototype-description-service/scene/tests/test_eval_harness_seed_roster.py | def _scene_fixture(tmp_path): | import hashlib | import json | | images = tmp_path / "images" / "mock_images" | images.mkdir(parents=True) | entries = [] | for media_id, name in [(1, "alice-pool.jpg"), (2, "bob-beach.jpg")]: | body = name.encode() | (images / name).write_bytes(body) | entries.append( | { | "path": f"mock_images/{name}", | "sha256": hashlib.sha256(body).hexdigest(), | "media_id": media_id, | "face_count": 1, | "present_identities": ["Alice Example"], | | ...[snippet truncated]... - _merge_scene @ apps/prototype-description-service/scene/tests/test_identity_merge_harness_gate.py | def _merge_scene(scene, entry, *, confirm_strangers=False): | """Fixture-conform run: only resolved identities exist as confirmed faces | (strangers have no DB identity). With ``confirm_strangers`` the stranger | is adversarially confirmed under an Easy-Wrong name — whatever the | geometry (no box, or shared box → ambiguity), that name must never land. | """ | caption = entry["base_caption"] | faces = [] | for idx, containment in enumerate(scene["expected_containment"]): | identity = containment["resolved_identity"] | if identity is not None: | | ...[snippet truncated]... Index freshness: fresh (index root is at 442d99f931030f94157239b1262deef1ce485a53).

Relevant concepts:
- relevant concepts: (skipped: offload_semantic_disabled)

Reporting Contract:
- Inspect the referenced files and implement the highest-priority open work in this lane.
- Run the lane-local tests before handoff.
- When merge-ready, run `make lane-handoff`.
- If you need clarification or are blocked, submit a blocked worker report so the orchestrator sees it in `make handoff-inbox`.

When you finish, do not run `make lane-handoff` or `make lane-report` yourself.
Return a single JSON object that matches the provided output schema.

Set `handoff_action` to:
- `merge_ready` only if you produced lane-owned code changes that are ready for orchestrator review
- `needs_guidance` if you were blocked, verification was blocked, permissions/sandbox prevented progress, or the assigned issue already appears resolved and now needs orchestrator review instead of new lane code


IMPORTANT: Your final output must be a single JSON object matching this schema:
{
  "type": "object",
  "additionalProperties": false,
  "required": [
    "handoff_action",
    "summary",
    "details",
    "tests_run",
    "blockers"
  ],
  "properties": {
    "handoff_action": {
      "type": "string",
      "enum": [
        "merge_ready",
        "needs_guidance"
      ],
      "description": "Use merge_ready only when lane-owned code changes were made and are ready for orchestrator review. Use needs_guidance for sandbox failures, verification blockers, already-resolved findings needing orchestrator review, or any case with no merge-ready commit."
    },
    "summary": {
      "type": "string",
      "minLength": 1,
      "description": "One short sentence the orchestrator can scan quickly."
    },
    "details": {
      "type": "string",
      "minLength": 1,
      "description": "Concise explanation of what changed or what was verified, plus why the lane is ready or blocked."
    },
    "tests_run": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Only the commands actually run in this session."
    },
    "blockers": {
      "type": "array",
      "items": {
        "type": "string"
      },
      "description": "Concrete blockers or asks for the orchestrator. Use an empty array when none."
    }
  }
}

IMPORTANT: When recording WorkBay handoff state, set the write actor to 'grok-4.5' (your pinned model identity), not the orchestrator.
