#!/usr/bin/env python3
"""Record a review run via the Python API fallback.

Use this helper when the MCP ``review_runs`` tool is unavailable in the
current harness but the installed ``agent_handoff_mcp`` package is importable.
The script records the review run and refreshes generated handoff views so the
fallback behaves like the normal write path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from agent_handoff_mcp import RuntimeConfig, configure_runtime, record_review_run, render_handoff

REPO_ROOT = Path(__file__).resolve().parents[1]
VALID_REVIEW_MODES = ("branch", "planning", "release_audit")
VALID_SUBJECT_KINDS = ("task_plan", "epic", "branch", "adr", "roadmap", "other")
VALID_VERDICTS = ("pass", "pass_with_findings", "fail", "conditional_pass")


def _normalize_subject_path(repo_root: Path, subject_path: str) -> str:
    normalized = subject_path.strip()
    if not normalized or normalized == ".":
        return "."

    candidate = Path(normalized)
    resolved = (candidate if candidate.is_absolute() else repo_root / candidate).resolve()
    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _git_value(repo_root: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _build_actor(
    *,
    repo_root: Path,
    agent: str | None,
    model: str | None,
    model_label: str | None,
    reasoning_level: str | None,
    git_value_fn: Callable[..., str | None] = _git_value,
) -> dict[str, str]:
    actor: dict[str, str] = {}
    if agent:
        actor["agent"] = agent
    if model:
        actor["model"] = model
    if model_label:
        actor["model_label"] = model_label
    if reasoning_level:
        actor["reasoning_level"] = reasoning_level

    branch = git_value_fn(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    commit_sha = git_value_fn(repo_root, "rev-parse", "HEAD")
    if branch:
        actor["branch"] = branch
    if commit_sha:
        actor["commit_sha"] = commit_sha
    return actor


def _require_ok(name: str, payload: Any) -> None:
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise RuntimeError(f"{name} returned ok=False: {payload}")


def record_handoff_review_run(
    *,
    repo_root: Path,
    review_run_id: str,
    session: str,
    subject_path: str,
    subject_kind: str,
    review_mode: str,
    verdict: str,
    verdict_decision: str,
    task_ref: str | None = None,
    agent: str | None = None,
    model: str | None = None,
    model_label: str | None = None,
    reasoning_level: str | None = None,
    runtime_factory: Callable[[Path], RuntimeConfig] = RuntimeConfig.for_repo,
    configure_runtime_fn: Callable[[RuntimeConfig], Any] = configure_runtime,
    record_review_run_fn: Callable[..., Any] = record_review_run,
    render_handoff_fn: Callable[..., Any] = render_handoff,
    git_value_fn: Callable[..., str | None] = _git_value,
) -> dict[str, Any]:
    configure_runtime_fn(runtime_factory(repo_root))

    normalized_subject = _normalize_subject_path(repo_root, subject_path)
    actor_payload = _build_actor(
        repo_root=repo_root,
        agent=agent,
        model=model,
        model_label=model_label,
        reasoning_level=reasoning_level,
        git_value_fn=git_value_fn,
    )

    kwargs: dict[str, Any] = {
        "review_run_id": review_run_id,
        "session": session,
        "subject_path": normalized_subject,
        "subject_kind": subject_kind,
        "review_mode": review_mode,
        "verdict": verdict,
        "verdict_decision": verdict_decision,
    }
    if task_ref:
        kwargs["task_ref"] = task_ref
    if actor_payload:
        kwargs["actor"] = actor_payload

    record_result = record_review_run_fn(**kwargs)
    _require_ok("record_review_run", record_result)

    dashboard_result = render_handoff_fn(kind="dashboard")
    _require_ok("render_handoff(kind='dashboard')", dashboard_result)

    current_task_result = None
    if task_ref:
        current_task_result = render_handoff_fn(kind="current_task", task_ref=task_ref)
        _require_ok("render_handoff(kind='current_task')", current_task_result)

    return {
        "record_review_run": record_result,
        "render_dashboard": dashboard_result,
        "render_current_task": current_task_result,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Stable review run identifier.")
    parser.add_argument("--session", required=True, help="Session identifier for the review run.")
    parser.add_argument("--subject-path", required=True, help="Reviewed artifact path or '.'.")
    parser.add_argument(
        "--subject-kind",
        default="other",
        choices=VALID_SUBJECT_KINDS,
        help="Kind of reviewed artifact.",
    )
    parser.add_argument(
        "--review-mode",
        required=True,
        choices=VALID_REVIEW_MODES,
        help="Review mode to persist.",
    )
    parser.add_argument(
        "--verdict",
        required=True,
        choices=VALID_VERDICTS,
        help="Review verdict.",
    )
    parser.add_argument(
        "--verdict-decision",
        required=True,
        help="Decision identifier that explains the verdict.",
    )
    parser.add_argument("--task-ref", help="Optional task_ref override.")
    parser.add_argument("--agent", help="Optional actor.agent override.")
    parser.add_argument("--model", help="Optional actor.model override.")
    parser.add_argument("--model-label", help="Optional actor.model_label override.")
    parser.add_argument("--reasoning-level", help="Optional actor.reasoning_level override.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = record_handoff_review_run(
            repo_root=REPO_ROOT,
            review_run_id=args.run_id,
            session=args.session,
            subject_path=args.subject_path,
            subject_kind=args.subject_kind,
            review_mode=args.review_mode,
            verdict=args.verdict,
            verdict_decision=args.verdict_decision,
            task_ref=args.task_ref,
            agent=args.agent,
            model=args.model,
            model_label=args.model_label,
            reasoning_level=args.reasoning_level,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"handoff-review-run: ERROR - {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())