"""GATELIVE-1: the suite must keep a per-test liveness bound.

The remote gate serialises on a single mutex and has no liveness property
of its own -- it cannot distinguish a frozen output stream from a slow
test, so a deadlocked test holds the mutex until a human intervenes and
the run's partial results are unrecoverable. The per-test bound declared
in ``[tool.pytest.ini_options]`` is the only thing that bounds that, so
it is guarded the same way the collection scope is (S2R5-01): silently
dropping it would restore the old failure mode with nothing to notice.
"""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

# The whole suite runs in ~220s across 3 xdist workers. A single test
# allowed to outlive that is a deadlock, not a slow test.
WHOLE_SUITE_BASELINE_SECONDS = 220


def _pytest_ini() -> dict:
    # tests/ -> eval_harness/ -> scripts/ -> prototype-description-service/
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["tool"]["pytest"]["ini_options"]


def test_per_test_timeout_is_declared_and_bounded() -> None:
    """A finite ceiling must exist, and it must actually bound something."""
    ini = _pytest_ini()
    timeout = ini["timeout"]
    assert isinstance(timeout, int)
    assert 0 < timeout <= 2 * WHOLE_SUITE_BASELINE_SECONDS


def test_timeout_method_preserves_sibling_worker_results() -> None:
    """``thread`` os._exits the worker; that is the evidence loss we are fixing."""
    assert _pytest_ini()["timeout_method"] == "signal"


def test_faulthandler_dumps_stacks_before_the_abort() -> None:
    """The stack dump is worthless if it fires after the test is already dead."""
    ini = _pytest_ini()
    assert ini["faulthandler_timeout"] < ini["timeout"]


def test_timeout_plugin_is_installed() -> None:
    """The ini keys are inert without the plugin -- and pytest ignores them silently.

    Deliberately a failure, never an ``importorskip``: a skip here would be
    the exact greenwash the bound exists to prevent.
    """
    assert importlib.util.find_spec("pytest_timeout") is not None
