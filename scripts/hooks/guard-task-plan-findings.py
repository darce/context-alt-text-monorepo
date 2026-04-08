#!/usr/bin/env python3
"""Guard hook: block pasted review-finding lists in task plan markdown files.

Review findings live in the agent-handoff-mcp database. They are recorded with
``review_findings(review={"operation":"record"|"batch_record", ...})`` and read
back with ``review_findings(review={"operation":"list"|"get"})``. Pasting them
inline into a task plan duplicates the source of truth, escapes the
pre-merge gate, and silently rots when findings change status.

This hook detects pasted finding lists and rejects the write. The detection
heuristic flags any block of **three or more consecutive bulleted lines**
where each bullet starts with a finding-like identifier such as:

  - ``- AOMCP-3-BR-04: ...``
  - ``- **H-1**: ...``
  - ``- AHMCP-14-PLAN-02 — ...``
  - ``- [M-2] ...``

Single mentions and cross-references are unaffected — only structured lists
of three or more in a row trip the heuristic, which is the shape an agent
produces when copy-pasting a ``review_findings(operation="list")`` result.

Operating modes
---------------

1. **Claude Code hook** (default): reads the PreToolUse JSON payload from
   stdin and inspects ``tool_input.content`` (Write) or ``tool_input.new_string``
   (Edit). Exits 2 with an actionable reason on stderr to block the tool call.

2. ``--scan-staged``: enumerates ``git diff --cached --name-only`` filtered to
   the task-plan directories and scans each staged file blob. Suitable for a
   git ``pre-commit`` hook.

3. ``--scan-paths <path> [...]``: scans the on-disk content of each path
   (file or directory). Useful for ad-hoc sweeps of a known subtree.

4. ``--scan-repo``: enumerates ``git ls-files '*.md'`` from the repo root and
   filters by the same path scope used by the Claude Code hook mode. This is
   the mode wired into ``make lint-task-plans`` so CI sees every file the
   hook would block, not just a hard-coded subset of directories.

Path filter
-----------

Only files whose repo-relative path contains ``/docs/tasks/``, ``/docs/epics/``,
or matches ``*task-plan*.md`` are scanned. Other markdown documents are
exempt because they are allowed to discuss findings narratively.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Bullet line opens with `- ` or `* `, optional bold/bracket wrapping, then a
# finding-like identifier. Two flavors are accepted:
#   - severity shorthand: H-1, M-2, L-3
#   - task-prefixed:      AOMCP-3-BR-04, AHMCP-14-PLAN-02, E15-7-BR-01
# The full bullet does not need to be matched — we just need to recognize
# the *opening* of a finding-style entry.
_FINDING_BULLET_RE = re.compile(
    r"""
    ^\s*[-*]\s+               # bullet marker
    [*\[\(`]{0,2}             # optional opening markup (**, [, (, `)
    (?P<id>
        (?:[A-Z]{1,5}\d*-\d+(?:-[A-Z]+)?-\d+)   # task-prefixed: AOMCP-3-BR-04, E15-7-BR-01
        |
        (?:[HML]-\d+)                            # severity shorthand: H-1, M-2, L-3
    )
    [*\]\)`]{0,2}             # optional closing markup
    \s*[:\u2014\-]             # separator: ':', em-dash, or '-'
    """,
    re.VERBOSE,
)

_CONSECUTIVE_THRESHOLD = 3

_PATH_FILTER_SUBSTRINGS = ("/docs/tasks/", "/docs/epics/")
_PATH_FILTER_FILENAME_GLOBS = ("*task-plan*.md", "*-plan.md")


def _path_should_be_scanned(rel_path: str) -> bool:
    """Return True if the given repo-relative path is in scope."""
    if not rel_path.endswith(".md"):
        return False
    normalized = "/" + rel_path.lstrip("/")
    if any(needle in normalized for needle in _PATH_FILTER_SUBSTRINGS):
        return True
    name = Path(rel_path).name
    return any(_glob_match(name, pattern) for pattern in _PATH_FILTER_FILENAME_GLOBS)


def _glob_match(name: str, pattern: str) -> bool:
    # Tiny shim so we don't pull in fnmatch for one call.
    from fnmatch import fnmatchcase

    return fnmatchcase(name, pattern)


def _detect_finding_runs(text: str) -> list[tuple[int, list[str]]]:
    """Return list of (start_line_number, finding_ids) for runs >= threshold.

    Walks lines and counts consecutive bullet lines whose opener matches the
    finding pattern. A blank line, a non-bullet line, or a bullet line that
    does NOT match the finding pattern resets the run. Continuation lines
    (indented under a bullet) do not break the run, because pasted findings
    routinely include a continuation line for description.
    """
    runs: list[tuple[int, list[str]]] = []
    current_run: list[tuple[int, str]] = []
    in_bullet_continuation = False

    for idx, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.lstrip()
        is_blank = stripped == ""
        is_bullet_open = stripped.startswith(("- ", "* "))

        if is_blank:
            # Blank line ends any run.
            if len(current_run) >= _CONSECUTIVE_THRESHOLD:
                runs.append((current_run[0][0], [item[1] for item in current_run]))
            current_run = []
            in_bullet_continuation = False
            continue

        if is_bullet_open:
            match = _FINDING_BULLET_RE.match(raw_line)
            if match:
                current_run.append((idx, match.group("id")))
                in_bullet_continuation = True
                continue
            # A non-finding bullet ends the run.
            if len(current_run) >= _CONSECUTIVE_THRESHOLD:
                runs.append((current_run[0][0], [item[1] for item in current_run]))
            current_run = []
            in_bullet_continuation = False
            continue

        # Non-bullet, non-blank line: treat as continuation if we are inside
        # a bullet run, otherwise as a hard reset.
        if in_bullet_continuation and (raw_line.startswith(" ") or raw_line.startswith("\t")):
            continue
        if len(current_run) >= _CONSECUTIVE_THRESHOLD:
            runs.append((current_run[0][0], [item[1] for item in current_run]))
        current_run = []
        in_bullet_continuation = False

    if len(current_run) >= _CONSECUTIVE_THRESHOLD:
        runs.append((current_run[0][0], [item[1] for item in current_run]))

    return runs


def _format_block_reason(rel_path: str, runs: list[tuple[int, list[str]]]) -> str:
    lines = [
        "BLOCKED: Pasted review-finding list detected in a task plan.",
        "",
        f"  File: {rel_path}",
    ]
    for start_line, ids in runs:
        preview = ", ".join(ids[:6]) + (", ..." if len(ids) > 6 else "")
        lines.append(f"    line {start_line}: {len(ids)} consecutive finding bullets ({preview})")
    lines.extend(
        [
            "",
            "Review findings live in agent-handoff-mcp, not in task plans.",
            "Record them with the MCP tools so they are gated by handoff_close_check:",
            "",
            '  review_findings(review={"operation":"record",       ...})  # single finding',
            '  review_findings(review={"operation":"batch_record", ...})  # 3+ findings',
            "",
            "List existing findings with:",
            '  review_findings(review={"operation":"list", "task_ref": "<task>", "status":"open"})',
            "",
            "If you need to reference findings in the task plan, link to them by ID",
            "(e.g. 'see AOMCP-3-BR-04 in handoff') instead of duplicating their bodies.",
            "",
            "See: docs/agentic/rules/branch-review-guide.md § Review Findings Placement",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude Code hook mode
# ---------------------------------------------------------------------------


def _extract_claude_payload(stdin_data: dict) -> tuple[str, str] | None:
    """Pull (file_path, content_to_scan) from a Claude Code PreToolUse payload.

    For Write tools, scan the full ``content`` being written.

    For Edit tools, simulate the replacement against the current file content
    and scan the result. The hook must catch incremental edits whose
    ``new_string`` alone contains fewer than three finding bullets but whose
    post-edit document does — for example, an Edit that adds the third bullet
    to a file that already had two. Scanning ``new_string`` in isolation
    misses that case (AHMCP-14-BR-04).

    If the target file does not exist or cannot be read, fall back to scanning
    ``new_string`` so an obviously bad payload still trips the guard.

    Returns None when the tool input is not a markdown write/edit we care
    about.
    """
    tool_input = stdin_data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None

    file_path = tool_input.get("file_path") or ""
    if not isinstance(file_path, str) or not file_path:
        return None

    # Write tool: scan the full content being written.
    if "content" in tool_input and isinstance(tool_input["content"], str):
        return file_path, tool_input["content"]

    # Edit tool: simulate the replacement so the scan sees the post-edit
    # document, not just the inserted fragment.
    new_string = tool_input.get("new_string")
    if not isinstance(new_string, str):
        return None

    raw_old = tool_input.get("old_string")
    old_string = raw_old if isinstance(raw_old, str) else ""
    replace_all = bool(tool_input.get("replace_all", False))

    try:
        existing = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        # File missing or unreadable — Edit would fail anyway. Fall back to
        # scanning new_string alone so a self-contained bad payload still
        # blocks.
        return file_path, new_string

    if old_string and old_string in existing:
        simulated = (
            existing.replace(old_string, new_string)
            if replace_all
            else existing.replace(old_string, new_string, 1)
        )
    else:
        # old_string not found — the actual Edit will fail. Scan new_string
        # alone so a payload that pastes a finding list still trips the guard.
        simulated = new_string

    return file_path, simulated


def _to_repo_relative(path: str, repo_root: str) -> str:
    if not repo_root:
        return path
    if path.startswith(repo_root + "/"):
        return path[len(repo_root) + 1 :]
    return path


def _git_repo_root() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _run_claude_hook() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0

    extracted = _extract_claude_payload(data)
    if extracted is None:
        return 0
    file_path, content = extracted

    repo_root = _git_repo_root()
    rel_path = _to_repo_relative(file_path, repo_root)
    if not _path_should_be_scanned(rel_path):
        return 0

    runs = _detect_finding_runs(content)
    if not runs:
        return 0

    sys.stderr.write(_format_block_reason(rel_path, runs) + "\n")
    return 2


# ---------------------------------------------------------------------------
# --scan-staged mode (git pre-commit)
# ---------------------------------------------------------------------------


def _staged_markdown_paths() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        candidate = line.strip()
        if candidate and _path_should_be_scanned(candidate):
            out.append(candidate)
    return out


def _staged_blob(rel_path: str) -> str | None:
    proc = subprocess.run(
        ["git", "show", f":{rel_path}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _run_scan_staged() -> int:
    paths = _staged_markdown_paths()
    failures: list[str] = []
    for rel_path in paths:
        blob = _staged_blob(rel_path)
        if blob is None:
            continue
        runs = _detect_finding_runs(blob)
        if runs:
            failures.append(_format_block_reason(rel_path, runs))
    if failures:
        sys.stderr.write("\n\n".join(failures) + "\n")
        return 1
    return 0


# ---------------------------------------------------------------------------
# --scan-paths mode (make lint-task-plans)
# ---------------------------------------------------------------------------


def _iter_scan_targets(targets: Iterable[str]) -> Iterable[Path]:
    for raw in targets:
        path = Path(raw)
        if not path.exists():
            continue
        if path.is_file():
            yield path
            continue
        for child in path.rglob("*.md"):
            yield child


def _run_scan_paths(targets: list[str]) -> int:
    repo_root = _git_repo_root() or "."
    failures: list[str] = []
    for path in _iter_scan_targets(targets):
        try:
            rel_path = str(path.resolve().relative_to(Path(repo_root).resolve()))
        except ValueError:
            rel_path = str(path)
        if not _path_should_be_scanned(rel_path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        runs = _detect_finding_runs(text)
        if runs:
            failures.append(_format_block_reason(rel_path, runs))
    if failures:
        sys.stderr.write("\n\n".join(failures) + "\n")
        return 1
    return 0


# ---------------------------------------------------------------------------
# --scan-repo mode (make lint-task-plans)
# ---------------------------------------------------------------------------


def _run_scan_repo() -> int:
    """Sweep every tracked .md file in the repo through the path filter.

    The Claude Code hook mode treats any path containing ``/docs/tasks/`` or
    ``/docs/epics/``, plus any filename matching ``*task-plan*.md`` or
    ``*-plan.md``, as in scope. CI must mirror that scope or a bypassed local
    hook can land forbidden finding lists in files outside the hard-coded
    subtree (AHMCP-14-BR-03). Using ``git ls-files`` keeps the discovery
    grounded in tracked files and lets the same ``_path_should_be_scanned``
    helper that gates the hook also gate the sweep.
    """
    repo_root = _git_repo_root()
    if not repo_root:
        sys.stderr.write("guard-task-plan-findings: not inside a git repo\n")
        return 1
    proc = subprocess.run(
        ["git", "-C", repo_root, "ls-files", "-z", "*.md"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            "guard-task-plan-findings: git ls-files failed: " + proc.stderr
        )
        return 1
    failures: list[str] = []
    repo_root_path = Path(repo_root)
    for entry in proc.stdout.split("\0"):
        rel_path = entry.strip()
        if not rel_path or not _path_should_be_scanned(rel_path):
            continue
        try:
            text = (repo_root_path / rel_path).read_text(encoding="utf-8")
        except OSError:
            continue
        runs = _detect_finding_runs(text)
        if runs:
            failures.append(_format_block_reason(rel_path, runs))
    if failures:
        sys.stderr.write("\n\n".join(failures) + "\n")
        return 1
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scan-staged",
        action="store_true",
        help="Scan files currently staged for commit (git pre-commit mode).",
    )
    parser.add_argument(
        "--scan-paths",
        nargs="+",
        metavar="PATH",
        help="Scan the given files or directories on disk.",
    )
    parser.add_argument(
        "--scan-repo",
        action="store_true",
        help="Sweep every tracked .md file in the repo through the path filter.",
    )
    args = parser.parse_args(argv)

    selected = sum(bool(x) for x in (args.scan_staged, args.scan_paths, args.scan_repo))
    if selected > 1:
        parser.error(
            "--scan-staged, --scan-paths, and --scan-repo are mutually exclusive"
        )

    if args.scan_staged:
        return _run_scan_staged()
    if args.scan_paths:
        return _run_scan_paths(args.scan_paths)
    if args.scan_repo:
        return _run_scan_repo()
    return _run_claude_hook()


if __name__ == "__main__":
    sys.exit(main())
