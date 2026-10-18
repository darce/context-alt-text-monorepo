"""Schema parity guards for the standalone GPU snapshot deployment checker."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from infra.oci.gpu_lifecycle.state_snapshot import GpuLifecycleState

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts/deploy/check-gpu-snapshots.sh"


def test_checker_gpu_state_literal_matches_canonical_producer_enum() -> None:
    """The standalone checker mirror must drift loudly from its source of truth."""
    source = CHECKER.read_text(encoding="utf-8")
    match = re.search(r"valid_gpu_states = (\([^\n]+\))", source)

    assert match is not None, "checker must expose its standalone GPU state mirror"
    checker_states = ast.literal_eval(match.group(1))

    assert set(checker_states) == {state.value for state in GpuLifecycleState}
