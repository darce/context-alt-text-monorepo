"""Pytest session bootstrap for ``agent-orchestrator-mcp``.

Three responsibilities:

1. Put this package's ``src/`` and the sibling ``agent-handoff-mcp``
   ``src/`` on ``sys.path`` so direct ``pytest`` invocations from the
   package directory work without an editable install AND so the
   handoff-mcp import resolves to *this* worktree's source rather than
   to whatever the editable install points at.
2. Hard-fail the session if either ``agent_handoff_mcp`` or
   ``agent_orchestrator_mcp`` resolves to a path outside this worktree.
   The orchestrator package depends on ``agent_handoff_mcp`` (via the
   editable install), so if pytest is invoked from a linked worktree
   but the editable install points at the root checkout,
   ``import agent_handoff_mcp`` resolves to the root's source code and
   the linked worktree's refactor never gets exercised. AHMCP-10
   regressed 65 orchestrator tests because of exactly this bug; the
   guard catches that class of false-positive verification at session
   start.
3. Mark the session so the agent-handoff-mcp commit-SHA validator
   accepts synthetic test SHAs without resolving them through git.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATOR_SRC = REPO_ROOT / "packages" / "agent-orchestrator-mcp" / "src"
HANDOFF_SRC = REPO_ROOT / "packages" / "agent-handoff-mcp" / "src"
EXPECTED_HANDOFF_PACKAGE_DIR = HANDOFF_SRC / "agent_handoff_mcp"
EXPECTED_ORCHESTRATOR_PACKAGE_DIR = ORCHESTRATOR_SRC / "agent_orchestrator_mcp"

# Prepend both src/ paths so this worktree's source wins over any
# environment-wide editable install pointing at a different checkout.
for _path in (HANDOFF_SRC, ORCHESTRATOR_SRC):
    _path_str = str(_path)
    if _path_str in sys.path:
        sys.path.remove(_path_str)
    sys.path.insert(0, _path_str)

# Tell the agent-handoff-mcp commit-SHA validator to accept synthetic
# test SHAs without resolving them through git.
os.environ.setdefault("AGENT_HANDOFF_SKIP_SHA_VALIDATION", "1")


def pytest_sessionstart(session) -> None:  # type: ignore[no-untyped-def]
    """Verify both packages resolve to *this* worktree's source.

    Imports both packages once, compares ``__file__`` against the
    expected paths, and raises ``pytest.UsageError`` if either differs.
    See module docstring for why this matters.
    """
    import pytest

    import agent_handoff_mcp  # noqa: PLC0415 - intentional late import for the guard.
    import agent_orchestrator_mcp  # noqa: PLC0415 - intentional late import for the guard.

    handoff_actual = Path(agent_handoff_mcp.__file__).resolve().parent
    orchestrator_actual = Path(agent_orchestrator_mcp.__file__).resolve().parent

    mismatches = []
    if handoff_actual != EXPECTED_HANDOFF_PACKAGE_DIR:
        mismatches.append(("agent_handoff_mcp", handoff_actual, EXPECTED_HANDOFF_PACKAGE_DIR))
    if orchestrator_actual != EXPECTED_ORCHESTRATOR_PACKAGE_DIR:
        mismatches.append(
            (
                "agent_orchestrator_mcp",
                orchestrator_actual,
                EXPECTED_ORCHESTRATOR_PACKAGE_DIR,
            )
        )
    if not mismatches:
        return

    lines = [
        "One or more in-monorepo packages resolved to the wrong source tree.",
        "",
    ]
    for name, actual, expected in mismatches:
        lines.extend(
            [
                f"  {name}",
                f"    imported from : {actual}",
                f"    expected      : {expected}",
                "",
            ]
        )
    lines.extend(
        [
            "This usually means pytest was invoked directly while a package's",
            "editable install points at a different worktree (typically the",
            "root checkout). Tests will pass against the wrong source code and",
            "produce false-positive verifications.",
            "",
            "Always run package tests via the Makefile target, which sets",
            "PYTHONPATH to the current worktree's src/ directory:",
            "",
            "  cd packages/agent-orchestrator-mcp && make test-orchestrator",
            "",
            "Or, if you must invoke pytest directly, set PYTHONPATH explicitly",
            "so it precedes the editable install:",
            "",
            f"  PYTHONPATH={HANDOFF_SRC}:{ORCHESTRATOR_SRC} pytest tests -q",
        ]
    )
    raise pytest.UsageError("\n".join(lines))
