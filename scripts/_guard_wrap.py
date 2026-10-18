"""Guard wrapper command transform (internal).

Single source for the wrapper-prefix form shared by the renderer
(``generate_agent_workflows.py``) and the contract-content checker
(``check_harness_sync.py``). Stdlib-only by design: the checker runs in
environments without the renderer's pydantic dependency.
"""

from __future__ import annotations

import re
import shlex

_GUARD_WRAPPER_RELPATH = "scripts/hooks/_run_guard.py"
_WORKSPACE_ROOT_EXPR = "$(git rev-parse --show-toplevel)"
# Kept aligned with coherence._INTERPRETERS (REV-A-002): the resolve gate and
# the wrap transform must classify the same words as interpreter prefixes.
_WRAP_INTERPRETER_WORDS = frozenset({"python", "python3", "bash", "sh", "uv", "uvx"})
# Workspace-root env anchors ($CLAUDE_PROJECT_DIR/, ${GROK_WORKSPACE_ROOT}/, …)
_WRAP_ANCHOR_RE = re.compile(r"^\$\{?[A-Za-z_][A-Za-z0-9_]*\}?/")


def _looks_like_handler_path(token: str) -> bool:
    stripped = _WRAP_ANCHOR_RE.sub("", token)
    return "/" in stripped or stripped.endswith((".py", ".sh"))


def _quote_command_token(token: str) -> str:
    # Re-add the double quotes the contract uses around env-anchored paths so
    # the harness shell still expands the anchor variable.
    if "$" in token or " " in token:
        return f'"{token}"'
    return token


def wrap_guard_command(command: str, *, fail_mode: object = None) -> str:
    """Prefix one rendered hook command with the guard wrapper.

    The wrapper path is emitted with the SAME per-harness anchor the command
    already uses (``$CLAUDE_PROJECT_DIR`` for Claude, ``${GROK_WORKSPACE_ROOT}``
    for Grok). Unanchored relative commands discover the checkout root through
    Git, so a hook launched from a subdirectory still finds both wrapper and
    handler. The original interpreter word is dropped: the wrapper re-derives
    bash vs python3 from the handler extension. Idempotent — an already-wrapped
    command is returned unchanged. Missing handlers fail closed by default;
    pass ``fail_mode="open"`` only for hooks that intentionally allow them.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return command
    if not words:
        return command
    rest = words[1:] if words[0] in _WRAP_INTERPRETER_WORDS else list(words)
    if not rest:
        return command
    script = rest[0]
    if script.endswith("_run_guard.py"):
        return command
    if not _looks_like_handler_path(script):
        # The leading token is not a recognizable handler path (e.g. an
        # interpreter subcommand like `uv run <script>`): refuse to wrap
        # rather than mis-wrap a non-path token as the handler (REV-A-002).
        return command
    anchor_match = _WRAP_ANCHOR_RE.match(script)
    if anchor_match:
        anchor = anchor_match.group(0)
        handler = script
    else:
        anchor = f"{_WORKSPACE_ROOT_EXPR}/"
        handler = script if script.startswith("/") else f"{anchor}{script}"
    tokens = ["python3", f"{anchor}{_GUARD_WRAPPER_RELPATH}"]
    if fail_mode != "open":
        tokens.append("--fail-mode=closed")
    tokens.extend([handler, *rest[1:]])
    return " ".join(_quote_command_token(token) for token in tokens)
