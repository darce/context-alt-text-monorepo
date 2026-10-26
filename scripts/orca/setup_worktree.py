#!/usr/bin/env python3
"""Orca setup hook: claim the WorkBay task for the worktree Orca just created.

orca.yaml runs this as scripts.setup with ORCA_ROOT_PATH (the primary checkout)
and ORCA_WORKTREE_PATH (the new linked worktree). WorkBay is the only
provisioner, so this adapter copies nothing: it checks the handoff, derives the
task ref from the branch, and runs `make task-start MODE=claim` from the
primary, whose worktree bootstrap provisions the worktree.

Exit codes: 0 claimed and bootstrapped; 1 the branch is not a WorkBay task
branch; 2 a precondition failed; 3 task-start or its worktree bootstrap failed.
Diagnostics go to stderr; stdout stays empty.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

PROG = "setup_worktree"
SCRUBBED_MAKE_ENV: tuple[str, ...] = ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")
TASK_START_TIMEOUT_SECONDS = 900
STDOUT_TAIL_LINES = 40
BRANCH_FIX = (
    "WorkBay task branches are feature/<task-ref>; in Orca Settings set the branch prefix to "
    'Custom "feature" and turn auto-rename off, then recreate the worktree from Orca'
)


class RefusalError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _validate_objective(objective: str | None) -> None:
    if objective is None:
        return
    # OBJECTIVE is expanded into overlay make recipes this adapter does not control;
    # a single quote can end their shell quoting and a control character can split
    # the recipe line. An empty value would clobber the task's existing objective.
    if not objective.strip():
        raise RefusalError(2, "--objective is empty; omit it to keep the task's existing objective")
    if "'" in objective:
        raise RefusalError(2, "--objective must not contain a single quote; reword it without '")
    bad = sorted({f"U+{ord(ch):04X}" for ch in objective if unicodedata.category(ch) == "Cc"})
    if bad:
        raise RefusalError(
            2,
            f"--objective must be one line without control characters (found {', '.join(bad)}); "
            "pass plain single-line text",
        )


def _env_directory(name: str) -> Path:
    raw = os.environ.get(name, "")
    if not raw:
        raise RefusalError(
            2,
            f"{name} is not set; run this as the Orca setup hook (orca.yaml scripts.setup) "
            f"or export {name}=<absolute path>",
        )
    path = Path(raw)
    if not path.is_absolute():
        raise RefusalError(2, f"{name}={raw} is not an absolute path; pass an absolute path")
    if not path.is_dir():
        raise RefusalError(2, f"{name}={raw} is not a directory; point it at an existing checkout")
    return path.resolve()


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _require_linked_worktree_of(root: Path, worktree: Path) -> None:
    if worktree == root:
        raise RefusalError(
            2,
            f"ORCA_WORKTREE_PATH resolves to the primary checkout {root}; refusing to claim a task "
            "there. Create a new worktree from Orca instead",
        )
    proc = _git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common_dir = proc.stdout.strip()
    if proc.returncode != 0 or not common_dir:
        detail = (proc.stderr or proc.stdout or "no output").strip()
        raise RefusalError(
            2,
            f"git rev-parse --git-common-dir failed in {worktree} (exit {proc.returncode}): {detail}; "
            "ORCA_WORKTREE_PATH must be a git worktree of ORCA_ROOT_PATH",
        )
    owner = Path(common_dir).resolve().parent
    if owner != root:
        raise RefusalError(
            2,
            f"worktree {worktree} belongs to the repository at {owner}, not ORCA_ROOT_PATH {root}; "
            "run the hook from the repository that owns the worktree",
        )


def _load_task_ref_re() -> Any:
    # The branch grammar is owned by WorkBay; a local copy would drift from task-start.
    try:
        from workbay_protocol.branch_naming import TASK_REF_RE
    except ImportError as exc:
        raise RefusalError(
            2,
            f"cannot import TASK_REF_RE from workbay_protocol.branch_naming ({exc}); install the "
            f"WorkBay runtime packages into {sys.executable} (orca.yaml runs $ORCA_ROOT_PATH/.venv/bin/python; "
            "`workbay doctor --target <primary>` prints the consumer venv install command)",
        ) from exc
    return TASK_REF_RE


def _task_branch(worktree: Path, task_ref_re: Any) -> tuple[str, str]:
    grammar = f"feature/<task-ref> (TASK_REF_RE {task_ref_re.pattern})"
    proc = _git(worktree, "symbolic-ref", "--short", "HEAD")
    branch = proc.stdout.strip()
    if proc.returncode != 0 or not branch:
        raise RefusalError(
            1,
            f"HEAD is detached in {worktree}, so there is no task branch matching {grammar}. {BRANCH_FIX}",
        )
    match = task_ref_re.fullmatch(branch)
    if match is None:
        raise RefusalError(
            1, f"branch {branch!r} does not match the WorkBay task branch grammar {grammar}. {BRANCH_FIX}"
        )
    return branch, match.group("task_ref")


def _receipt(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _stdout_tail(stdout: str) -> str:
    lines = stdout.splitlines()[-STDOUT_TAIL_LINES:]
    if not lines:
        return "task-start stdout was empty"
    return "task-start stdout (tail):\n" + "\n".join(f"  {line}" for line in lines)


def _task_start(make: str, root: Path, worktree: Path, task: str, objective: str | None) -> None:
    command = [
        make,
        "--no-print-directory",
        "-C",
        str(root),
        "task-start",
        f"TASK={task}",
        "MODE=claim",
        "LIFECYCLE_ARGS=--json",
    ]
    if objective is not None:
        command.append(f"OBJECTIVE={objective}")
    shown = " ".join(command[3:])
    # Inherited MAKEFLAGS (Orca launched from a make recipe) would leak a jobserver
    # and -n/-k flags into the nested task-start.
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED_MAKE_ENV}
    retry = (
        f"fix the cause above, then bootstrap the worktree from the primary with "
        f"`{root}/.venv/bin/python {root}/scripts/workstate/bootstrap_worktree.py --worktree {worktree}` "
        "or remove the worktree and recreate it from Orca"
    )
    try:
        proc = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            text=True,
            timeout=TASK_START_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise RefusalError(3, f"`{shown}` timed out after {TASK_START_TIMEOUT_SECONDS}s; {retry}") from None
    except OSError as exc:
        raise RefusalError(3, f"cannot run `{make}` for `{shown}`: {exc}; install make or pass --make PATH") from exc
    stdout = proc.stdout or ""
    if proc.returncode != 0:
        raise RefusalError(3, f"`{shown}` exited {proc.returncode}; {retry}\n{_stdout_tail(stdout)}")
    receipt = _receipt(stdout)
    if receipt is None:
        raise RefusalError(3, f"no JSON receipt on `{shown}` stdout; {retry}\n{_stdout_tail(stdout)}")
    if receipt.get("ok") is not True:
        raise RefusalError(3, f'`{shown}` receipt has "ok": {json.dumps(receipt.get("ok"))}; {retry}')
    bootstrap = receipt.get("worktree_bootstrap")
    if not isinstance(bootstrap, dict) or bootstrap.get("ok") is not True:
        # task-start reports ok:true even when the bootstrap was skipped or failed
        # (darce/workbay#3), so only the bootstrap's own ok proves provisioning.
        raise RefusalError(
            3,
            f"`{shown}` receipt worktree_bootstrap is {json.dumps(bootstrap)}; the WorkBay worktree "
            f"bootstrap did not succeed (an empty LIFECYCLE_WORKTREE_BOOTSTRAP skips it); {retry}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--objective", default=None, help="task objective passed to task-start as OBJECTIVE")
    parser.add_argument("--make", default="make", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        _validate_objective(args.objective)
        root = _env_directory("ORCA_ROOT_PATH")
        worktree = _env_directory("ORCA_WORKTREE_PATH")
        _require_linked_worktree_of(root, worktree)
        task_ref_re = _load_task_ref_re()
        branch, task_ref = _task_branch(worktree, task_ref_re)
        _task_start(args.make, root, worktree, task_ref.upper(), args.objective)
    except RefusalError as exc:
        print(f"{PROG}: {exc}", file=sys.stderr)
        return exc.code
    print(f"{PROG}: claimed task {task_ref} on branch {branch} for worktree {worktree}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
