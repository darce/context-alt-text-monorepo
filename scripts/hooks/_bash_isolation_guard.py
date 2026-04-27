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

from _branch_isolation_guard import resolve_path_branch
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


# Formatter / linter-fix command families (FU-01). These rewrite files in place
# across one or more code roots without naming individual targets in the shell
# command, so the per-token scanners above miss them. When detected on main
# without a MAINT-* task, the guard synthesises the configured code_roots as
# blocked paths so the caller surfaces the contract-backed violation. The
# registry is deliberately conservative: we match on the first "real" verb
# (after sudo/env stripping via _verb_of) and a discriminating second token so
# unrelated invocations (e.g. `make test-handoff`, `ruff check` without --fix)
# do not trigger false positives.
_FORMATTER_SUBCOMMAND_RULES: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    # Makefile-driven formatter / lint-fix targets.
    ("make", ("format-all", "format-handoff", "format-orchestrator", "format-mcp",
              "fix-lint-handoff", "fix-lint-orchestrator", "fix-lint-mcp",
              "fix-php-style")),
    # ruff format <paths...>  /  ruff check --fix
    ("ruff", ("format",)),
    # black <paths...>  — any invocation rewrites in place.
    ("black", None),
    # prettier --write / -w
    ("prettier", None),
    # npm / pnpm / yarn scripts typically aliased to formatters.
    ("npm", ("format", "fmt", "lint:fix", "fix")),
    ("pnpm", ("format", "fmt", "lint:fix", "fix")),
    ("yarn", ("format", "fmt", "lint:fix", "fix")),
    # Composer aliases used in the PHP plugin workspace.
    ("composer", ("format", "fix-style", "run-format", "run-fix-style")),
)

# Secondary fix-flag scan: commands whose baseline behaviour is read-only but
# which write to disk when a specific flag is present.
_FORMATTER_FIX_FLAG_RULES: tuple[tuple[str, frozenset[str]], ...] = (
    ("ruff", frozenset({"--fix", "--fix-only", "--unsafe-fixes"})),
    ("eslint", frozenset({"--fix"})),
    ("prettier", frozenset({"--write", "-w"})),
    ("stylelint", frozenset({"--fix"})),
)


def _detect_formatter(verb: str, args: list[str]) -> bool:
    """Return True when the verb+args look like an in-place formatter run."""
    if not verb:
        return False
    for rule_verb, subcommands in _FORMATTER_SUBCOMMAND_RULES:
        if verb != rule_verb:
            continue
        if subcommands is None:
            # verb alone is sufficient (e.g. `black`, `prettier --write`).
            return True
        # npm/yarn/pnpm often require a literal "run" token before the script.
        candidate_tokens = []
        for token in args:
            if token in {"run", "run-script", "exec", "--"}:
                continue
            if token.startswith("-"):
                continue
            candidate_tokens.append(token)
            break  # Only the first positional matters for script selection.
        if not candidate_tokens:
            continue
        if candidate_tokens[0] in subcommands:
            return True
    for rule_verb, fix_flags in _FORMATTER_FIX_FLAG_RULES:
        if verb != rule_verb:
            continue
        if any(token in fix_flags for token in args):
            return True
    return False


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


def extract_raw_write_targets(command: str) -> list[str]:
    """Return the raw (unresolved) write-target tokens parsed out of `command`.

    Mirrors the per-stage scanners used by scan_bash_command but skips the
    repo-root filter applied by `_to_repo_relative`, so absolute paths that
    resolve *outside* the current workspace are preserved. The caller (worktree
    drift guard) needs these so cross-worktree writes — e.g. `sed -i` against
    an absolute path pointing into the primary worktree from a linked feature
    worktree — can still be compared against the active task's target_worktree.
    """
    if not command or not command.strip():
        return []
    targets: list[str] = []
    for tokens in _iter_words(command):
        targets.extend(_scan_redirects(tokens))
        verb, args = _verb_of(tokens)
        if not verb:
            continue
        if verb == "sed":
            targets.extend(_scan_sed_in_place(args))
        targets.extend(_scan_verb_targets(verb, args))
        targets.extend(_scan_git_writeback(verb, args))
    targets.extend(_scan_python_inline(command))
    return targets


def scan_bash_command(
    command: str,
    repo_root: Path,
    policy: BranchIsolationPolicy,
) -> list[str]:
    if not command or not command.strip():
        return []

    candidate_paths: list[str] = []
    formatter_detected = False

    for tokens in _iter_words(command):
        candidate_paths.extend(_scan_redirects(tokens))
        verb, args = _verb_of(tokens)
        if not verb:
            continue
        if verb == "sed":
            candidate_paths.extend(_scan_sed_in_place(args))
        candidate_paths.extend(_scan_verb_targets(verb, args))
        candidate_paths.extend(_scan_git_writeback(verb, args))
        if not formatter_detected and _detect_formatter(verb, args):
            formatter_detected = True

    candidate_paths.extend(_scan_python_inline(command))

    protected_branches = frozenset({"main", "master"})

    blocked: list[str] = []
    seen: set[str] = set()
    for raw in candidate_paths:
        relative = _to_repo_relative(raw, repo_root)
        if not relative or relative in seen:
            continue
        seen.add(relative)
        if not is_branch_isolation_protected_path(relative, policy):
            continue
        per_path_branch = resolve_path_branch(raw)
        if per_path_branch is None or per_path_branch in protected_branches:
            blocked.append(relative)

    # FU-01: a formatter invocation implicitly writes across every code_root in
    # the contract. Emit the configured roots directly (with a `<root> (formatter)`
    # label) so the caller surfaces a clear, contract-backed violation without
    # fabricating file paths.
    if formatter_detected:
        for root in policy.code_roots:
            normalized = root.strip("/")
            if not normalized:
                continue
            label = f"{normalized}/ (formatter)"
            if label not in seen:
                seen.add(label)
                blocked.append(label)
        for root_file in policy.root_protected_files:
            label = f"{root_file} (formatter)"
            if label not in seen:
                seen.add(label)
                blocked.append(label)
    return blocked
