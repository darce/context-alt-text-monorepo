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
_GIT_TIMEOUT_SECONDS = 1

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


def _repo_context(start: Path) -> tuple[Path, Path]:
    """Resolve the current and canonical roots with one bounded Git call."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--path-format=absolute", "--git-common-dir"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        roots = [Path(line) for line in out.stdout.splitlines() if line.strip()]
        if out.returncode == 0 and len(roots) >= 2:
            root, common_dir = roots[:2]
            if not common_dir.is_absolute():
                common_dir = root / common_dir
            return root, common_dir.resolve().parent
    except (OSError, subprocess.SubprocessError):
        pass
    return start, start


def _project_name(root: Path, canonical_root: Path | None = None) -> str:
    """Codemap derives a project slug from the absolute root path.

    A linked worktree is almost never indexed on its own, so name the canonical
    root's project instead -- that is the graph the agent can actually query.
    """
    return str(canonical_root or _canonical_root(root)).lstrip("/").replace("/", "-")


def _canonical_root(root: Path) -> Path:
    """The main worktree's root, given any worktree's root."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).parent
    except (OSError, subprocess.SubprocessError):
        pass
    return root


def _is_indexed_path(raw: str, root: Path, base: Path | None = None) -> bool | None:
    """True if the operand lands in an indexed code root.

    Returns None for "cannot tell" (glob operand, path outside the repo), which
    the caller treats as allow.
    """
    if any(ch in raw for ch in "*?["):
        return None
    relative_base = (base or root).resolve()
    candidate = (relative_base / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    try:
        rel = candidate.relative_to(root.resolve())
    except ValueError:
        return None
    # A single concrete file is a read, not a sweep.
    if candidate.is_file():
        return False
    head = rel.parts[0] if rel.parts else ""
    # The repository root itself is a recursive search over every indexed root.
    return not rel.parts or head in INDEXED_ROOTS


def _strip_outer_anchors(pattern: str) -> str:
    """Remove only anchors wrapping a pattern, preserving internal regex syntax."""
    stripped = pattern.strip()
    while True:
        before = stripped
        for anchor in ("^", r"\b"):
            if stripped.startswith(anchor):
                stripped = stripped[len(anchor):].lstrip()
        for anchor in ("$", r"\b"):
            if stripped.endswith(anchor):
                stripped = stripped[:-len(anchor)].rstrip()
        if stripped == before:
            return stripped


def _pattern_is_symbolic(pattern: str) -> str | None:
    """Return the identifier the codemap could answer, or None."""
    stripped = _strip_outer_anchors(pattern)
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
        positive = [part for part in _split_glob_filters(str(glob))
                    if part and not part.startswith("!")]
        if positive:
            expanded: list[str] = []
            for part in positive:
                expanded.extend(_expand_glob_braces(part))
            # Prove that every positive alternative names a non-code suffix.
            # Unknown/dynamic patterns stay guarded because they may include
            # one of the indexed source extensions.
            if expanded and all(
                (suffix := Path(part).suffix.lower())
                and not any(ch in suffix for ch in "*?[")
                and suffix not in CODE_SUFFIXES
                for part in expanded
            ):
                return True
    file_type = (tool_input.get("type") or "").strip()
    if file_type and file_type not in CODE_RG_TYPES:
        return True
    return False


def _split_glob_filters(glob: str) -> list[str]:
    """Split independent glob filters without splitting brace alternatives."""
    filters: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in glob:
        if ch == "{":
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
        if depth == 0 and (ch == "," or ch.isspace()):
            if buf:
                filters.append("".join(buf))
                buf = []
            continue
        buf.append(ch)
    if buf:
        filters.append("".join(buf))
    return filters


def _expand_glob_braces(pattern: str) -> list[str]:
    """Expand the simple comma-brace forms accepted by ripgrep's glob flag."""
    opening = pattern.find("{")
    if opening < 0:
        return [pattern]
    closing = pattern.find("}", opening + 1)
    if closing < 0:
        return [pattern]
    options = pattern[opening + 1:closing].split(",")
    if len(options) == 1:
        return [pattern]
    expanded: list[str] = []
    for option in options:
        expanded.extend(_expand_glob_braces(
            pattern[:opening] + option + pattern[closing + 1:]
        ))
    return expanded


def _decide_grep(tool_input: dict, root: Path, current_dir: Path) -> tuple[str, str] | None:
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
        indexed = _is_indexed_path(str(path), root, current_dir)
        if indexed is not True:
            return None
        scope = str(path)
    else:
        if _is_indexed_path(".", root, current_dir) is not True:
            return None
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
        previous = command[i - 1] if i else ""
        if ch == "#" and (not previous or previous.isspace() or previous in ";|&()"):
            while i < len(command) and command[i] != "\n":
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


def _change_directory(argv: list[str], current_dir: Path | None) -> Path | None:
    """Resolve a simple shell ``cd`` for subsequent relative operands."""
    if current_dir is None:
        return None
    args = argv[1:]
    while args and args[0] in ("-L", "-P", "--"):
        args.pop(0)
    if len(args) != 1 or args[0] == "-":
        return None
    target = Path(args[0]).expanduser()
    if not target.is_absolute():
        target = current_dir / target
    target = target.resolve()
    return target if target.is_dir() else None


def _decide_bash(tool_input: dict, root: Path, working_dir: Path) -> tuple[str, str] | None:
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    current_dir: Path | None = working_dir.resolve()
    for piped, segment in _split_segments(command):
        if piped:
            # Filtering another command's output is not a codebase search.
            continue
        try:
            argv = shlex.split(segment)
        except ValueError:
            continue
        escape = False
        # Drop leading `FOO=bar` env assignments so `env rg ...` still matches.
        while argv and re.match(r"^\w+=", argv[0]):
            escape = escape or argv[0] == "CODEMAP_OK=1"
            argv.pop(0)
        if argv and Path(argv[0]).name == "env":
            argv.pop(0)
            while argv and re.match(r"^\w+=", argv[0]):
                escape = escape or argv[0] == "CODEMAP_OK=1"
                argv.pop(0)
        if not argv:
            continue
        name = Path(argv[0]).name
        if name == "cd":
            current_dir = _change_directory(argv, current_dir)
            continue
        if name not in SEARCH_COMMANDS:
            continue
        if escape:
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
        type_flags = _flag_values(args, ("-t", "--type"))
        if type_flags and all(flag not in CODE_RG_TYPES for flag in type_flags):
            continue
        glob_flags = _flag_values(args, ("-g", "--glob", "--include"))
        if glob_flags and _filter_excludes_code({"glob": ",".join(glob_flags)}):
            continue
        if not paths:
            if name in ("rg", "ripgrep", "ag", "ack"):
                # Recursive from cwd by default.
                if current_dir is not None and _is_indexed_path(".", root, current_dir) is True:
                    return ident, "."
            continue  # bare `grep pattern` reads stdin
        for raw in paths:
            if current_dir is not None and _is_indexed_path(raw, root, current_dir) is True:
                return ident, raw
    return None


_VALUE_FLAGS = {"-e", "--regexp", "-t", "--type", "-g", "--glob", "--include",
                "--exclude", "-m", "--max-count", "-A", "-B", "-C", "--context",
                "-f", "--file", "--type-not", "-T", "--replace"}


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


def _flag_values(args: list[str], names: tuple[str, ...]) -> list[str]:
    """Return every value for a repeatable flag such as ``--type`` or ``--glob``."""
    values: list[str] = []
    for i, arg in enumerate(args):
        if arg in names and i + 1 < len(args):
            values.append(args[i + 1])
            continue
        for name in names:
            if arg.startswith(f"{name}="):
                values.append(arg.split("=", 1)[1])
                break
    return values


def decide(payload: dict, root: Path, canonical_root: Path | None = None) -> str | None:
    """Return a block reason, or None to allow."""
    if os.environ.get("CODEMAP_FIRST_DISABLE") == "1":
        return None
    if not shutil.which("codebase-memory-mcp"):
        return None
    tool_name = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    cwd = payload.get("cwd")
    working_dir = Path(cwd).resolve() if isinstance(cwd, str) and cwd else root.resolve()
    if tool_name == "Grep":
        hit = _decide_grep(tool_input, root, working_dir)
        pattern = str(tool_input.get("pattern", ""))
    elif tool_name == "Bash":
        hit = _decide_bash(tool_input, root, working_dir)
        pattern = ""
    else:
        return None
    if hit is None:
        return None
    ident, scope = hit
    return ADVICE.format(
        project=_project_name(root, canonical_root),
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
        cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
        root, canonical_root = _repo_context(cwd)
        reason = decide(payload, root, canonical_root)
    except Exception as exc:  # noqa: BLE001 - fail open, but say so
        print(f"guard-codemap-first: internal error, allowing ({exc})", file=sys.stderr)
        return 0
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
