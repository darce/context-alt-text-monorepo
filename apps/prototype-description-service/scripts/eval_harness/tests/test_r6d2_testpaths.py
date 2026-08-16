"""S2R5-01: eval-harness tests must sit on the default pytest gate.

``norecursedirs`` includes ``scripts``, so collection only reaches this
tree when ``testpaths`` names ``scripts/eval_harness/tests`` explicitly.
A green app suite that never executes this directory is the same class
of gate-greenwash as the prior remote-gate incident (TEST-15 / AUDIT-08).
"""

from __future__ import annotations

import tomllib
from pathlib import Path


def _pytest_ini() -> dict:
    # tests/ -> eval_harness/ -> scripts/ -> prototype-description-service/
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["tool"]["pytest"]["ini_options"]


def test_eval_harness_tests_are_on_default_testpaths() -> None:
    """The default gate must name this directory; parent ``scripts`` is not enough."""
    paths = _pytest_ini()["testpaths"]
    assert "scripts/eval_harness/tests" in paths
    # Repo-root checkout uses the prefixed form (same pattern as recognition/tests).
    assert "apps/prototype-description-service/scripts/eval_harness/tests" in paths
    # Must not widen the gate to every scripts/ tree.
    assert "scripts" not in paths


def test_scripts_norecursedirs_still_blocks_unrelated_script_trees() -> None:
    """Do not drop the ``scripts`` norecursedirs shield to reach this suite."""
    norecurse = _pytest_ini()["norecursedirs"]
    assert "scripts" in norecurse
