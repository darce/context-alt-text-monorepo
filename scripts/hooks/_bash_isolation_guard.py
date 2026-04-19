#!/usr/bin/env python3
"""Shell-command scanner for Bash tool main-branch edit enforcement (BR-17).

Problem: the Edit/Write PreToolUse hook only gates the editor tool surface.
Commands like `sed -i`, `tee`, `echo > file`, `python -c "open('x','w')..."` go
through Bash, which was excluded from every hook matcher, creating a silent
bypass of the branch-isolation policy.

Scope (conservative): identify shell commands that WRITE to or DELETE protected
paths. Inspection is best-effort; when ambiguous we bias toward blocking so the
user uses the Edit/Write tool (which has proper path semantics and already goes
through the main-branch guard).

Public API:
    scan_bash_command(command, repo_root, policy) -> list[str]
        Return a list of repo-relative protected paths the command appears to
        write to (or delete). Empty list means the command is safe.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from _harness_protocol import BranchIsolationPolicy, is_branch_isolation_protected_path


_WRITE_REDIRECTS = {">", ">>", "|&>", "&>", "&>>"}

_DESTRUCTIVE_VERBS = {
    "rm": "all_nonflag",
    "unlink": "all_nonflag",
    "truncate": "all_nonflag",
    "shred": "all_nonflag",
    "tee": "all_nonflag",
    "cp": "last_nonflag",
    "mv": "last_nonflag",
    "install": "last_nonflag",
    "rsync": "last_nonflag",
    "dd": "after_flag:of=",
}

_PYTHON_WRITE_OPEN_RE = re.compile(
    r"""open\s*\(\s*['"]([^'"]+)['"]\s*,\s*['"][waxt+]+['"]""",
)
_PYTHON_PATH_WRITE_RE = re.compile(
    r"""Path\s*\(\s*['"]([^'"]+)['"]\s*\)\s*\.\s*(write_text|write_bytes|unlink|touch|replace|rename)""",
)
_PYTHON_OS_WRITE_RE = re.compile(
    r"""(?:os\.(?:remove|unlink|rename)|shutil\.(?:rmtree|move|copy|copyfile|copy2|copytree))\s*\(\s*['"]([^'"]+)['"]""",
)

_SED_IN_PLACE_FLAGS = {"-i", "--in-place"}


def _is_flag(token: str) -> bool:
    return token.startswith("-") and token != "-"


def _iter_words(command: str) -> list[list[str]]:
    pattern = re.compile(r"(\|\||&&|\||;|&(?!>))")
    stages: list[list[str]] = []
    for raw_stage in pattern.split(command):
        stage = raw_stage.strip()
        if not stage or stage in {"||", "&&", "|", ";", "&"}:
            continue
        try:
            tokens = shlex.split(stage, comments=False, posix=True)
        except ValueError:
            tokens = stage.split()
        if tokens:
            stages.append(tokens)
    return stages


def _scan_redirects(tokens: list[str]) -> list[str]:
    targets: list[str] = []
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        matched = False
        for op in sorted(_WRITE_REDIRECTS, key=len, reverse=True):
            if tok == op and idx + 1 < len(tokens):
                targets.append(tokens[idx + 1])
                idx += 2
                matched = True
                break
            if tok.startswith(op) and len(tok) > len(op):
                targets.append(tok[len(op):])
                idx += 1
                matched = True
                break
        if not matched:
            for op in sorted(_WRITE_REDIRECTS, key=len, reverse=True):
                if op in tok and not tok.startswith("-"):
                    before, _, after = tok.partition(op)
                    if before and after:
                        targets.append(after)
                        break
            idx += 1
    return targets


def _strip_command_prefix(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
        name, _, _ = tokens[i].partition("=")
        if name and name.isidentifier():
            i += 1
        else:
            break
    return tokens[i:] if i < len(tokens) else tokens


def _verb_of(tokens: list[str]) -> tuple[str, list[str]]:
    rest = _strip_command_prefix(tokens)
    if not rest:
        return "", []
    skip = {"sudo", "env", "exec", "time", "nice", "command", "builtin"}
    while rest and rest[0] in skip:
        rest = rest[1:]
    if not rest:
        return "", []
    verb = Path(rest[0]).name if "/" in rest[0] else rest[0]
    return verb, rest[1:]


def _scan_verb_targets(verb: str, args: list[str]) -> list[str]:
    if verb not in _DESTRUCTIVE_VERBS:
        return []
    rule = _DESTRUCTIVE_VERBS[verb]
    positional = [a for a in args if not _is_flag(a) and not a.startswith("+")]
    if rule == "all_nonflag":
        return positional
    if rule == "last_nonflag":
        return positional[-1:] if positional else []
    if rule.startswith("after_flag:"):
        needle = rule.split(":", 1)[1]
        matched: list[str] = []
        for token in args:
            if token.startswith(needle):
                matched.append(token[len(needle):])
        return matched
    return []


def _scan_sed_in_place(args: list[str]) -> list[str]:
    has_in_place = any(a in _SED_IN_PLACE_FLAGS or a.startswith("-i") for a in args)
    if not has_in_place:
        return []
    return [a for a in args if not _is_flag(a) and not a.startswith("+")]


def _scan_python_inline(command: str) -> list[str]:
    matches: list[str] = []
    for match in _PYTHON_WRITE_OPEN_RE.finditer(command):
        matches.append(match.group(1))
    for match in _PYTHON_PATH_WRITE_RE.finditer(command):
        matches.append(match.group(1))
    for match in _PYTHON_OS_WRITE_RE.finditer(command):
        matches.append(match.group(1))
    return matches


def _scan_git_writeback(verb: str, args: list[str]) -> list[str]:
    if verb != "git" or not args:
        return []
    subcmd = args[0] if args else ""
    rest = args[1:]
    targets: list[str] = []
    if subcmd == "checkout":
        if "--" in rest:
            dash_idx = rest.index("--")
            targets = [a for a in rest[dash_idx + 1:] if not _is_flag(a)]
        else:
            targets = [a for a in rest if not _is_flag(a)]
    elif subcmd == "restore":
        targets = [a for a in rest if not _is_flag(a) and a != "--"]
    elif subcmd == "reset":
        if "--" in rest:
            dash_idx = rest.index("--")
            targets = [a for a in rest[dash_idx + 1:] if not _is_flag(a)]
    elif subcmd == "clean":
        targets = [a for a in rest if not _is_flag(a)]
    return targets


def _to_repo_relative(path: str, repo_root: Path) -> str:
    stripped = path.strip().strip("'\"")
    if not stripped:
        return ""
    try:
        root_abs = repo_root.expanduser().resolve(strict=False)
    except OSError:
        root_abs = repo_root
    candidate = Path(stripped).expanduser()
    if not candidate.is_absolute():
        try:
            candidate = (root_abs / candidate).resolve(strict=False)
        except OSError:
            return stripped.replace("\\", "/").lstrip("/")
    else:
        try:
            candidate = candidate.resolve(strict=False)
        except OSError:
            pass
    try:
        return candidate.relative_to(root_abs).as_posix()
    except ValueError:
        return ""


def scan_bash_command(
    command: str,
    repo_root: Path,
    policy: BranchIsolationPolicy,
) -> list[str]:
    if not command or not command.strip():
        return []

    candidate_paths: list[str] = []

    for tokens in _iter_words(command):
        candidate_paths.extend(_scan_redirects(tokens))
        verb, args = _verb_of(tokens)
        if not verb:
            continue
        if verb == "sed":
            candidate_paths.extend(_scan_sed_in_place(args))
        candidate_paths.extend(_scan_verb_targets(verb, args))
        candidate_paths.extend(_scan_git_writeback(verb, args))

    candidate_paths.extend(_scan_python_inline(command))

    blocked: list[str] = []
    seen: set[str] = set()
    for raw in candidate_paths:
        relative = _to_repo_relative(raw, repo_root)
        if not relative or relative in seen:
            continue
        seen.add(relative)
        if is_branch_isolation_protected_path(relative, policy):
            blocked.append(relative)
    return blocked
