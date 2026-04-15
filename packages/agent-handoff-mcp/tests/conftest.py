"""Pytest session bootstrap for ``agent-handoff-mcp``.

Two responsibilities:

1. Put this package's ``src/`` on ``sys.path`` so direct ``pytest``
   invocations from the package directory work without an editable install.
2. Hard-fail the session if the resolved ``agent_handoff_mcp`` import is
   not coming from this package's ``src/`` directory. That guard exists
   because Python's editable installs are environment-wide: a single
   ``pip install -e packages/agent-handoff-mcp`` from the repo root
   makes every Python interpreter in the venv resolve
   ``import agent_handoff_mcp`` to whichever path was last installed,
   regardless of which git worktree the test session is running from.
   Linked worktrees inherit that same install pointer, so a refactor
   that lives only in the linked worktree's ``src/`` will silently NOT
   be exercised by tests run inside that worktree -- pytest will run
   against the root worktree's source instead. The guard catches that
   class of false-positive verification at session start.
3. Mark the session so the agent-handoff-mcp commit-SHA validator
   accepts synthetic test SHAs (`"abc123"`, `"def456"`, etc.) without
   trying to resolve them through git. Production callers always run
   without this env var set.
4. Keep branch enforcement opt-in so ambient shell env does not change
   unrelated test behavior. Enforcement tests delete the bypass and set
   `AGENT_HANDOFF_ENFORCE_BRANCH=1` explicitly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT / "src"
EXPECTED_PACKAGE_DIR = SRC_ROOT / "agent_handoff_mcp"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Tell the commit-SHA validator to accept synthetic test SHAs without
# resolving them through git. This MUST be set before any
# ``agent_handoff_mcp`` import that walks the validation path.
os.environ.setdefault("AGENT_HANDOFF_SKIP_SHA_VALIDATION", "1")
os.environ.setdefault("AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT", "1")


def pytest_sessionstart(session) -> None:  # type: ignore[no-untyped-def]
    """Verify ``agent_handoff_mcp`` resolves to *this* worktree's source.

    See module docstring for why this matters. The check imports the
    package once, compares ``__file__`` against the expected path, and
    raises ``pytest.UsageError`` if they differ -- aborting the session
    before any test can produce a false-positive pass.
    """
    import pytest

    import agent_handoff_mcp  # noqa: PLC0415 - intentional late import for the guard.

    actual = Path(agent_handoff_mcp.__file__).resolve().parent
    if actual != EXPECTED_PACKAGE_DIR:
        raise pytest.UsageError(
            "agent_handoff_mcp resolved to the wrong source tree.\n"
            f"  imported from : {actual}\n"
            f"  expected      : {EXPECTED_PACKAGE_DIR}\n"
            "\n"
            "This usually means pytest was invoked directly while the\n"
            "package's editable install points at a different worktree\n"
            "(typically the root checkout). Tests will pass against the\n"
            "wrong source code and produce false-positive verifications.\n"
            "\n"
            "Always run package tests via the Makefile target, which\n"
            "sets PYTHONPATH to the current worktree's src/ directory:\n"
            "\n"
            "  cd packages/agent-handoff-mcp && make test-handoff\n"
            "\n"
            "Or, if you must invoke pytest directly, set PYTHONPATH\n"
            "explicitly so it precedes the editable install:\n"
            "\n"
            f"  PYTHONPATH={SRC_ROOT} pytest tests -q\n"
        )
