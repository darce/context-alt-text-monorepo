#!/usr/bin/env python3
"""Self-review runner: build a review prompt, execute Codex, validate findings, optionally record to MCP."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from backend_registry import get_backend_choices
from backend_registry import get_backend_spec
from backend_registry import resolve_bridge
from backend_registry import validate_backend
from _env import WORKER_REASONING_EFFORT_CHOICES
from _env import apply_codex_runtime_hints

REPO_ROOT = SCRIPT_DIR.parents[1]
RULES_DIR = REPO_ROOT / "docs" / "agentic" / "rules"

BACKEND_CHOICES = get_backend_choices()

# Stack guide selection by file extension
STACK_GUIDES: dict[str, str] = {
    ".py": "branch-review-python.md",
    ".ts": "branch-review-typescript.md",
    ".tsx": "branch-review-typescript.md",
    ".js": "branch-review-typescript.md",
    ".jsx": "branch-review-typescript.md",
    ".php": "branch-review-php.md",
}

REVIEW_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "summary"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "category", "file_path", "description"],
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "category": {
                        "type": "string",
                        "enum": ["ANTIPATTERN", "DEAD_CODE", "COMPLEXITY", "GAP"],
                    },
                    "file_path": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "description": {"type": "string", "minLength": 1},
                    "fix": {"type": "string"},
                },
            },
        },
        "summary": {"type": "string", "minLength": 1},
    },
}


def findings_converged(findings: list[dict[str, Any]]) -> bool:
    """Return True when findings meet convergence criteria: 0 HIGH, 0 MEDIUM, at most 1 LOW."""
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")
    return high == 0 and medium == 0 and low <= 1


# ---------------------------------------------------------------------------
# Changed-file discovery
# ---------------------------------------------------------------------------


def _changed_files(worktree_path: Path) -> list[str]:
    """Return workspace-relative paths of changed files in the lane worktree."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    staged = subprocess.run(
        ["git", "diff", "--name-only", "--cached"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    files: set[str] = set()
    for proc in (result, staged, untracked):
        if proc.returncode == 0:
            files.update(line.strip() for line in proc.stdout.splitlines() if line.strip())
    return sorted(files)


def _diff_stat(worktree_path: Path) -> str:
    """Return a compact diff stat for the lane worktree (unstaged + staged)."""
    parts: list[str] = []
    for cmd in (
        ["git", "diff", "--stat", "HEAD"],
        ["git", "diff", "--stat", "--cached"],
    ):
        result = subprocess.run(
            cmd,
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts.append(result.stdout.strip())
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Stack guide auto-detection
# ---------------------------------------------------------------------------


def _detect_stack_guides(changed_files: list[str]) -> list[str]:
    """Return deduplicated list of stack guide filenames relevant to the changed files."""
    guides: dict[str, str] = {}
    for file_path in changed_files:
        ext = Path(file_path).suffix.lower()
        guide = STACK_GUIDES.get(ext)
        if guide and guide not in guides:
            guides[guide] = guide
    return list(guides.values())


def _read_guide(filename: str) -> str:
    """Read a review guide file from the rules directory."""
    guide_path = RULES_DIR / filename
    if not guide_path.is_file():
        return ""
    return guide_path.read_text()


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------


def _build_review_prompt(
    *,
    changed_files: list[str],
    diff_stat: str,
    stack_guides: list[str],
    lane_id: str | None = None,
) -> str:
    """Assemble the full review prompt from guide content, stack guides, and diff context."""
    sections: list[str] = []

    sections.append("You are a code reviewer. Review the following lane changes using the checklist below.")
    sections.append("Return ONLY a JSON object matching the required output schema. Do not include markdown fences or commentary.")

    if lane_id:
        sections.append(f"\nLane: {lane_id}")

    # Main review guide
    main_guide = _read_guide("branch-review-guide.md")
    if main_guide:
        sections.append("\n--- BRANCH REVIEW GUIDE ---\n")
        sections.append(main_guide)

    # Stack-specific guides
    for guide_name in stack_guides:
        guide_content = _read_guide(guide_name)
        if guide_content:
            sections.append(f"\n--- {guide_name.upper()} ---\n")
            sections.append(guide_content)

    # Changed files
    sections.append("\n--- CHANGED FILES ---\n")
    if changed_files:
        for f in changed_files:
            sections.append(f"- {f}")
    else:
        sections.append("(no changed files detected)")

    # Diff stat
    if diff_stat:
        sections.append("\n--- DIFF STAT ---\n")
        sections.append(diff_stat)

    sections.append("\n--- INSTRUCTIONS ---\n")
    sections.append(
        "Walk through each checklist item for the changed files above. "
        "For each issue found, add a finding to the findings array with severity, category, "
        "file_path, description, and optionally line_start, line_end, and fix. "
        "If no issues are found, return an empty findings array with a summary noting the review was clean."
    )

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Finding ID generation
# ---------------------------------------------------------------------------


def _generate_finding_id(lane_id: str | None, index: int, finding: dict[str, Any]) -> str:
    """Generate a stable, human-readable finding ID from lane + file + index."""
    prefix = (lane_id or "review").upper().replace("-", "")[:6]
    severity_char = {"high": "H", "medium": "M", "low": "L"}.get(
        finding.get("severity", ""), "X"
    )
    return f"{prefix}-{severity_char}-{index + 1:02d}"


# ---------------------------------------------------------------------------
# Codex execution
# ---------------------------------------------------------------------------


def _codex_exec(prompt: str, worktree_path: Path) -> dict[str, Any]:
    """Execute codex with the review prompt and output schema, return parsed JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        schema_file = Path(tmpdir) / "review_schema.json"
        result_file = Path(tmpdir) / "review_result.json"
        prompt_file = Path(tmpdir) / "review_prompt.md"

        schema_file.write_text(json.dumps(REVIEW_OUTPUT_SCHEMA, indent=2))
        prompt_file.write_text(prompt)

        codex_path = _find_codex_path()
        cmd = [
            codex_path,
            "exec",
            "-C",
            str(worktree_path),
            "--output-schema",
            str(schema_file),
            "-o",
            str(result_file),
            "-",
        ]

        with prompt_file.open("r") as stdin_fh:
            completed = subprocess.run(
                cmd,
                stdin=stdin_fh,
                capture_output=True,
                text=True,
                check=False,
            )

        if completed.returncode != 0:
            raise RuntimeError(
                f"codex exec failed (exit {completed.returncode}):\n"
                f"stderr: {completed.stderr.strip()}\n"
                f"stdout: {completed.stdout.strip()}"
            )

        if not result_file.is_file():
            raise RuntimeError("codex exec did not produce a result file.")

        raw = result_file.read_text()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"codex exec produced invalid JSON: {exc}\nRaw output: {raw[:500]}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"codex exec returned non-object JSON: {type(payload).__name__}")

        return payload


def _subagent_exec(
    backend_name: str,
    prompt: str,
    worktree_path: Path,
    *,
    env: dict[str, str] | None = None,
    telemetry_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Execute the optional host-provided Codex subagent bridge for review."""
    runner = resolve_bridge(backend_name)

    runner_kwargs: dict[str, Any] = {
        "prompt": prompt,
        "schema": REVIEW_OUTPUT_SCHEMA,
        "cwd": str(worktree_path),
    }
    if env is not None:
        runner_kwargs["env"] = env
    if telemetry_callback is not None:
        runner_kwargs["telemetry_callback"] = telemetry_callback
    try:
        payload = runner(**runner_kwargs)
    except TypeError as exc:
        if "telemetry_callback" in runner_kwargs and "telemetry_callback" in str(exc):
            runner_kwargs.pop("telemetry_callback", None)
            try:
                payload = runner(**runner_kwargs)
            except TypeError as inner_exc:
                if env is None or "env" not in str(inner_exc):
                    raise
                payload = runner(prompt=prompt, schema=REVIEW_OUTPUT_SCHEMA, cwd=str(worktree_path))
        else:
            if env is None or "env" not in str(exc):
                raise
            payload = runner(prompt=prompt, schema=REVIEW_OUTPUT_SCHEMA, cwd=str(worktree_path))
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{backend_name} backend returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(
            f"{backend_name} backend returned non-object payload: {type(payload).__name__}"
        )
    return payload


def _find_codex_path() -> str:
    """Locate the codex binary via the canonical :func:`lane_exec.find_codex`."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from lane_exec import find_codex
    return find_codex()

# ---------------------------------------------------------------------------
# Result validation
# ---------------------------------------------------------------------------


def _validate_review_result(result: dict[str, Any]) -> dict[str, Any]:
    """Validate the review result against the expected schema shape. Returns the validated result."""
    if "findings" not in result:
        raise RuntimeError("Review result missing required 'findings' key.")
    if "summary" not in result:
        raise RuntimeError("Review result missing required 'summary' key.")
    if not isinstance(result["findings"], list):
        raise RuntimeError("Review result 'findings' must be an array.")
    if not isinstance(result["summary"], str) or not result["summary"].strip():
        raise RuntimeError("Review result 'summary' must be a non-empty string.")

    valid_severities = {"high", "medium", "low"}
    valid_categories = {"ANTIPATTERN", "DEAD_CODE", "COMPLEXITY", "GAP"}

    for i, finding in enumerate(result["findings"]):
        if not isinstance(finding, dict):
            raise RuntimeError(f"Finding [{i}] is not an object.")
        for required in ("severity", "category", "file_path", "description"):
            if required not in finding:
                raise RuntimeError(f"Finding [{i}] missing required field '{required}'.")
        if finding["severity"] not in valid_severities:
            raise RuntimeError(
                f"Finding [{i}] has invalid severity '{finding['severity']}'. "
                f"Valid: {sorted(valid_severities)}"
            )
        if finding["category"] not in valid_categories:
            raise RuntimeError(
                f"Finding [{i}] has invalid category '{finding['category']}'. "
                f"Valid: {sorted(valid_categories)}"
            )
        if not isinstance(finding["description"], str) or not finding["description"].strip():
            raise RuntimeError(f"Finding [{i}] has empty description.")

    return result


# ---------------------------------------------------------------------------
# MCP recording
# ---------------------------------------------------------------------------


def _record_findings(
    findings: list[dict[str, Any]],
    *,
    task_ref: str,
    session: str,
    lane_id: str | None = None,
    orchestrator_root: Path,
) -> list[str]:
    """Record each finding into MCP. Returns list of finding IDs that were recorded."""
    from agent_handoff_mcp import RuntimeConfig, configure_runtime, record_review_finding

    runtime = RuntimeConfig.for_workspace(
        orchestrator_root,
        state_dir=orchestrator_root / ".task-state",
        current_task_path=orchestrator_root / "CURRENT_TASK.md",
        exports_dir=orchestrator_root / ".task-state" / "exports",
    )
    configure_runtime(runtime)

    recorded_ids: list[str] = []
    for i, finding in enumerate(findings):
        finding_id = _generate_finding_id(lane_id, i, finding)

        details: dict[str, Any] = {}
        if "line_start" in finding and isinstance(finding["line_start"], int):
            details["line_start"] = finding["line_start"]
        if "line_end" in finding and isinstance(finding["line_end"], int):
            details["line_end"] = finding["line_end"]
        if "fix" in finding and isinstance(finding["fix"], str):
            details["fix"] = finding["fix"]

        actor: dict[str, Any] = {}
        if lane_id:
            actor["lane_id"] = lane_id

        record_review_finding(
            session=session,
            finding_id=finding_id,
            severity=finding["severity"],
            file_path=finding["file_path"],
            description=f"[{finding['category']}] {finding['description']}",
            details=details if details else None,
            actor=actor if actor else None,
            task_ref=task_ref,
        )
        recorded_ids.append(finding_id)

    return recorded_ids


# ---------------------------------------------------------------------------
# Public API for daemon callers
# ---------------------------------------------------------------------------


def run_review(
    *,
    worktree_path: Path,
    lane_id: str | None = None,
    task_ref: str | None = None,
    session: str | None = None,
    orchestrator_root: Path | None = None,
    backend: str = "codex-cli",
    reasoning_effort: str | None = None,
    record_findings: bool = False,
    dry_run: bool = False,
    progress_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Run a full review cycle: discover changes, build prompt, execute Codex, validate, optionally record."""
    backend_name = validate_backend(backend)
    env = None
    if orchestrator_root is not None:
        from _env import pythonpath_env

        env = pythonpath_env(orchestrator_root, task_ref=task_ref, lane_id=lane_id)
    elif reasoning_effort:
        env = {}
    if env is not None:
        apply_codex_runtime_hints(env, reasoning_effort=reasoning_effort)
    changed = _changed_files(worktree_path)
    stat = _diff_stat(worktree_path)
    guides = _detect_stack_guides(changed)
    prompt = _build_review_prompt(
        changed_files=changed,
        diff_stat=stat,
        stack_guides=guides,
        lane_id=lane_id,
    )

    if dry_run:
        return {
            "dry_run": True,
            "backend": backend_name,
            "prompt": prompt,
            "findings": [],
            "summary": "Dry-run mode: no review executed.",
            "converged": True,
            "changed_files": changed,
            "stack_guides": guides,
        }

    if get_backend_spec(backend_name).kind == "bridge":
        telemetry_callback = None
        if progress_callback is not None:
            def telemetry_callback(telemetry: dict[str, Any]) -> None:
                progress_callback(
                    "subagent_turn_complete",
                    backend=backend_name,
                    phase="review",
                    **telemetry,
                )
        raw_result = _subagent_exec(
            backend_name,
            prompt,
            worktree_path,
            env=env,
            telemetry_callback=telemetry_callback,
        )
    else:
        raw_result = _codex_exec(prompt, worktree_path)
    validated = _validate_review_result(raw_result)

    output: dict[str, Any] = {
        "findings": validated["findings"],
        "summary": validated["summary"],
        "converged": findings_converged(validated["findings"]),
        "changed_files": changed,
        "stack_guides": guides,
    }

    if record_findings:
        if not task_ref:
            raise RuntimeError("--task-ref is required when --record-findings is set.")
        if not session:
            raise RuntimeError("--session is required when --record-findings is set.")
        if not orchestrator_root:
            raise RuntimeError("--orchestrator-root is required when --record-findings is set.")
        recorded_ids = _record_findings(
            validated["findings"],
            task_ref=task_ref,
            session=session,
            lane_id=lane_id,
            orchestrator_root=orchestrator_root,
        )
        output["recorded_finding_ids"] = recorded_ids

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Self-review runner: execute structured code review via Codex."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("schema", help="Print the review output JSON schema.")

    run_parser = subparsers.add_parser("run", help="Execute a review against a lane worktree.")
    run_parser.add_argument("--worktree-path", required=True, help="Path to the lane worktree.")
    run_parser.add_argument("--lane-id", help="Lane identifier for finding ID generation.")
    run_parser.add_argument("--task-ref", help="Task reference (required with --record-findings).")
    run_parser.add_argument("--session", help="Session identifier (required with --record-findings).")
    run_parser.add_argument("--orchestrator-root", help="Orchestrator root path (required with --record-findings).")
    run_parser.add_argument(
        "--backend",
        default="codex-cli",
        choices=BACKEND_CHOICES,
        help="Execution backend to use (default: codex-cli).",
    )
    run_parser.add_argument(
        "--reasoning-effort",
        choices=WORKER_REASONING_EFFORT_CHOICES,
        help="Optional reasoning effort hint for codex-subagent review turns.",
    )
    run_parser.add_argument(
        "--record-findings",
        action="store_true",
        help="Record findings into MCP before returning.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the assembled prompt and skip Codex/MCP side effects.",
    )

    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.command == "schema":
        print(json.dumps(REVIEW_OUTPUT_SCHEMA, indent=2))
        return 0

    worktree_path = Path(args.worktree_path).expanduser().resolve()
    orchestrator_root = (
        Path(args.orchestrator_root).expanduser().resolve()
        if args.orchestrator_root
        else None
    )

    result = run_review(
        worktree_path=worktree_path,
        lane_id=args.lane_id,
        task_ref=args.task_ref,
        session=args.session,
        orchestrator_root=orchestrator_root,
        backend=args.backend,
        reasoning_effort=args.reasoning_effort,
        record_findings=args.record_findings,
        dry_run=args.dry_run,
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
