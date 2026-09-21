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

import pytest

# Measured on the full 6791-item collection: durations cliff from 20.74s (the
# slowest healthy test, scene suite hermeticity) straight to the hangs, which
# do not terminate on their own. Nothing occupies the band between. A per-test
# bound anywhere in that band separates the two populations, so the ceiling is
# derived from the slowest healthy test -- not from a whole-suite total, which
# was never the right unit for a per-test bound.
SLOWEST_HEALTHY_TEST_SECONDS = 21


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
    # Clear of the slowest healthy test even on a host several times slower
    # than the gate, but still finite: an unbounded-in-practice ceiling on a
    # mutex-serialised gate is the failure mode this file exists to prevent.
    assert 4 * SLOWEST_HEALTHY_TEST_SECONDS <= timeout <= 600


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


def test_timeout_is_live_in_the_running_config(pytestconfig: pytest.Config) -> None:
    """The distribution being importable does not mean pytest registered the option.

    ``find_spec`` above proves the wheel is on disk. It still passes under
    ``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` or ``-p no:timeout``, where pytest
    drops ``timeout``/``timeout_method`` with only a non-fatal
    ``PytestConfigWarning`` -- the bound is gone and every guard here is green.
    Assert the resolved config, which is the thing that actually bounds a test.
    """
    ini = _pytest_ini()
    assert pytestconfig.pluginmanager.hasplugin("timeout")
    # getini returns the ini value as a string for these keys.
    assert int(pytestconfig.getini("timeout")) == ini["timeout"]
    assert pytestconfig.getini("timeout_method") == ini["timeout_method"]
