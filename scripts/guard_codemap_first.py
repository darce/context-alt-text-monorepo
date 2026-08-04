#!/usr/bin/env python3
"""PreToolUse guard: route code-symbol searches to the codemap index, not grep.

The codemap (``codebase-memory-mcp``) holds a symbol graph for this repo's code
roots. A ripgrep sweep for a symbol name is slower, noisier, and blind to call
edges, so this guard blocks *that* narrow case and names the codemap call to run
instead. Everything the index does not cover -- docs, scripts, config, free-text
regex, piped grep, single-file reads -- is left alone.

Blocking is deliberately conservative. A false block costs the agent a turn and
teaches it to route around the guard; the guard therefore fails open on every
ambiguity (see ``_decide``) and on any internal error.

Escapes, in order of preference:
  * ``CODEMAP_OK=1 rg <pattern> apps/`` -- declare that raw text search is what
    you actually need (regex sweeps, string literals, comment archaeology).
  * ``CODEMAP_FIRST_DISABLE=1`` in the environment -- repo-wide kill switch.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Code roots covered by the codemap index for this repo. Verified against
# `query_graph "MATCH (f:File) RETURN f.file_path"`: apps/ and packages/ carry
# the Python/PHP/TS symbol graph. docs/, scripts/, benchmarks/, Makefile.d/ and
# config/ are NOT indexed -- searches there must stay on grep.
INDEXED_ROOTS = ("apps", "packages")

SEARCH_COMMANDS = {"rg", "grep", "egrep", "fgrep", "ag", "ack", "ripgrep"}

# Extensions the symbol graph actually parses. A glob/type filter outside this
# set means the agent is after prose or config, which the index cannot answer.
CODE_SUFFIXES = {".py", ".php", ".ts", ".tsx", ".js", ".jsx"}
CODE_RG_TYPES = {"py", "python", "php", "ts", "tsx", "js", "jsx", "typescript", "javascript"}

# A bare identifier: what `search_graph`/`get_code_snippet` answer directly.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{2,}$")
# `def foo` / `class Bar` / `function baz` / `interface Qux` -- definition-site
# hunts, which is exactly `search_graph --name-pattern`.
_DEFINITION = re.compile(
    r"^(?:def|class|function|interface|type|const|async\s+def)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)$"
)
ADVICE = """\
Codemap is the default for code searches in this repo (per-repo policy).

Use instead:
  codebase-memory-mcp cli search_graph --project {project} --name-pattern '{ident}'
  codebase-memory-mcp cli get_code_snippet --project {project} --qualified-name '<qn>'
  codebase-memory-mcp cli trace_path --project {project} --function-name '{ident}' --mode calls
  codebase-memory-mcp cli search_code --project {project} --pattern '{pattern}'

Not indexed, so grep is correct there: docs/, scripts/, benchmarks/, Makefile.d/, config/.

If you genuinely need raw text search over {scope} (regex sweep, string literal,
comment archaeology), re-run it through Bash with the escape prefix:
  CODEMAP_OK=1 rg '{pattern}' {scope}
"""


def _repo_root(start: Path) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return start


def _project_name(root: Path) -> str:
    """Codemap derives a project slug from the absolute root path.

    A linked worktree is almost never indexed on its own, so name the canonical
    root's project instead -- that is the graph the agent can actually query.
    """
    return str(_canonical_root(root)).lstrip("/").replace("/", "-")


def _canonical_root(root: Path) -> Path:
    """The main worktree's root, given any worktree's root."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).parent
    except (OSError, subprocess.SubprocessError):
        pass
    return root


def _is_indexed_path(raw: str, root: Path) -> bool | None:
    """True if the operand lands in an indexed code root.

    Returns None for "cannot tell" (glob operand, path outside the repo), which
    the caller treats as allow.
    """
    if any(ch in raw for ch in "*?["):
        return None
    candidate = (root / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    try:
        rel = candidate.relative_to(root.resolve())
    except ValueError:
        return None
    # A single concrete file is a read, not a sweep.
    if candidate.is_file():
        return False
    head = rel.parts[0] if rel.parts else ""
    return head in INDEXED_ROOTS


def _pattern_is_symbolic(pattern: str) -> str | None:
    """Return the identifier the codemap could answer, or None."""
    stripped = pattern.strip()
    for anchor in ("\\b", "^", "$"):
        stripped = stripped.replace(anchor, "")
    stripped = stripped.strip()
    if not stripped:
        return None
    definition = _DEFINITION.match(stripped)
    if definition:
        return definition.group(1)
    # Anything with regex metacharacters or whitespace fails _IDENTIFIER and is
    # therefore left to grep -- the graph cannot answer it.
    if _IDENTIFIER.match(stripped):
        return stripped
    return None


def _filter_excludes_code(tool_input: dict) -> bool:
    """True when a glob/type filter aims the search away from indexed code."""
    glob = tool_input.get("glob") or ""
    if glob:
        suffixes = {Path(part).suffix for part in re.split(r"[,\s{}]+", glob) if part}
        suffixes.discard("")
        if suffixes and not (suffixes & CODE_SUFFIXES):
            return True
    file_type = (tool_input.get("type") or "").strip()
    if file_type and file_type not in CODE_RG_TYPES:
        return True
    return False


def _decide_grep(tool_input: dict, root: Path) -> tuple[str, str] | None:
    pattern = tool_input.get("pattern")
    if not isinstance(pattern, str):
        return None
    ident = _pattern_is_symbolic(pattern)
    if ident is None:
        return None
    if _filter_excludes_code(tool_input):
        return None
    path = tool_input.get("path")
    if path:
        indexed = _is_indexed_path(str(path), root)
        if indexed is not True:
            return None
        scope = str(path)
    else:
        # Repo-wide sweep: it covers the indexed roots by definition.
        scope = "."
    return ident, scope


def _split_segments(command: str) -> list[tuple[bool, str]]:
    """Split a shell line into (is_piped_into, segment) pairs."""
    segments: list[tuple[bool, str]] = []
    buf: list[str] = []
    piped = False
    next_piped = False
    i = 0
    quote: str | None = None
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            i += 1
            continue
        two = command[i : i + 2]
        if two in ("&&", "||"):
            segments.append((piped, "".join(buf)))
            buf, piped, next_piped = [], False, False
            i += 2
            continue
        if ch in "|;\n":
            segments.append((piped, "".join(buf)))
            next_piped = ch == "|"
            buf, piped = [], next_piped
            i += 1
            continue
        buf.append(ch)
        i += 1
    segments.append((piped, "".join(buf)))
    return [(p, s.strip()) for p, s in segments if s.strip()]


def _decide_bash(tool_input: dict, root: Path) -> tuple[str, str] | None:
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    if "CODEMAP_OK=1" in command:
        return None
    for piped, segment in _split_segments(command):
        if piped:
            # Filtering another command's output is not a codebase search.
            continue
        try:
            argv = shlex.split(segment)
        except ValueError:
            continue
        # Drop leading `FOO=bar` env assignments so `env rg ...` still matches.
        while argv and re.match(r"^\w+=", argv[0]):
            argv.pop(0)
        if argv and Path(argv[0]).name == "env":
            argv.pop(0)
            while argv and re.match(r"^\w+=", argv[0]):
                argv.pop(0)
        if not argv:
            continue
        name = Path(argv[0]).name
        if name not in SEARCH_COMMANDS:
            continue
        args = argv[1:]
        if any(f in ("-l", "--files-with-matches", "--files") for f in args):
            # Filename inventory, not symbol lookup.
            continue
        explicit_pattern = _flag_value(args, ("-e", "--regexp"))
        operands = _operands(args)
        if explicit_pattern is not None:
            pattern, paths = explicit_pattern, operands
        elif operands:
            pattern, paths = operands[0], operands[1:]
        else:
            continue
        ident = _pattern_is_symbolic(pattern)
        if ident is None:
            continue
        type_flag = _flag_value(args, ("-t", "--type"))
        if type_flag and type_flag not in CODE_RG_TYPES:
            continue
        glob_flag = _flag_value(args, ("-g", "--glob", "--include"))
        if glob_flag and _filter_excludes_code({"glob": glob_flag}):
            continue
        if not paths:
            if name in ("rg", "ripgrep", "ag", "ack"):
                # Recursive from cwd by default.
                return ident, "."
            continue  # bare `grep pattern` reads stdin
        for raw in paths:
            if _is_indexed_path(raw, root) is True:
                return ident, raw
    return None


_VALUE_FLAGS = {"-e", "--regexp", "-t", "--type", "-g", "--glob", "--include",
                "--exclude", "-m", "--max-count", "-A", "-B", "-C", "--context",
                "-f", "--file", "--type-not", "-T"}


def _operands(args: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == "--":
            continue
        if arg.startswith("-") and len(arg) > 1:
            if arg in _VALUE_FLAGS:
                skip = True
            continue
        out.append(arg)
    return out


def _flag_value(args: list[str], names: tuple[str, ...]) -> str | None:
    for i, arg in enumerate(args):
        if arg in names and i + 1 < len(args):
            return args[i + 1]
        for n in names:
            if arg.startswith(f"{n}="):
                return arg.split("=", 1)[1]
    return None


def decide(payload: dict, root: Path) -> str | None:
    """Return a block reason, or None to allow."""
    if os.environ.get("CODEMAP_FIRST_DISABLE") == "1":
        return None
    if not shutil.which("codebase-memory-mcp"):
        return None
    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Grep":
        hit = _decide_grep(tool_input, root)
        pattern = str(tool_input.get("pattern", ""))
    elif tool_name == "Bash":
        hit = _decide_bash(tool_input, root)
        pattern = ""
    else:
        return None
    if hit is None:
        return None
    ident, scope = hit
    return ADVICE.format(
        project=_project_name(root),
        ident=ident,
        pattern=pattern or ident,
        scope=scope,
    )


def main() -> int:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 - never break the harness on a read error
        return 0
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    try:
        cwd = Path(payload.get("cwd") or os.getcwd())
        reason = decide(payload, _repo_root(cwd))
    except Exception as exc:  # noqa: BLE001 - fail open, but say so
        print(f"guard-codemap-first: internal error, allowing ({exc})", file=sys.stderr)
        return 0
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
