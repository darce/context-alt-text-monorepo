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
import os
import tomllib
from pathlib import Path

import pytest

# Measured on the 6792-item `make test` collection: durations cliff from 20.74s
# straight to the hangs, which do not terminate on their own. Nothing occupies
# the band between. A per-test bound anywhere in that band separates the two
# populations, so the ceiling is derived from the slowest healthy test -- not
# from a whole-suite total, which was never the right unit for a per-test
# bound. The 20.74s test is
# scene/tests/test_eval_harness_cli.py::test_score_rounding_cannot_hide_one_wrong_name_scaled
# -- named because an earlier comment credited it to the scene hermeticity
# test, which runs in 10.27s, and re-deriving the constant from that one would
# halve the intended headroom (AR-06).
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


def test_timeout_method_is_pinned() -> None:
    """Pinned so the choice is deliberate, not so ``thread`` is forbidden.

    The original docstring here asserted ``thread`` "os._exits the worker and
    takes its results with it". That is false (AR-02): xdist streams each
    report as it completes, so a thread-method abort loses only the in-flight
    test and still names it. ``signal`` is preferred because it aborts as an
    ordinary failure report, but it cannot fire inside a C call -- so if a
    C-level wedge ever holds the gate, flipping this to ``thread`` is the fix
    and this test is the thing to update, not a reason to widen the bound.
    """
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

    This covers the plugin-registration channel only. The override channels
    are covered by the next test; ``getini`` alone does not see them.
    """
    ini = _pytest_ini()
    assert pytestconfig.pluginmanager.hasplugin("timeout")
    # getini returns the ini value as a string for these keys.
    assert int(pytestconfig.getini("timeout")) == ini["timeout"]
    assert pytestconfig.getini("timeout_method") == ini["timeout_method"]


def test_no_override_channel_disarms_the_bound(pytestconfig: pytest.Config) -> None:
    """``getini`` reports the file, not the bound that will actually fire.

    pytest-timeout resolves ``--timeout`` > ``$PYTEST_TIMEOUT`` > ini, and the
    guards above read only the last of those. Measured (AR-01): both
    ``--timeout=0`` and ``PYTEST_TIMEOUT=0`` leave every other test in this
    file green with the bound fully disabled.

    ``PYTEST_TIMEOUT`` is the realistic vector rather than a contrived one:
    the remote gate injects environment wholesale via
    ``WORKBAY_REMOTE_GATE_ENV``, so a single future env line would restore the
    57-minute wedge with five green guards above it. Re-derive the effective
    value along the documented precedence and assert *that*.
    """
    ini_timeout = _pytest_ini()["timeout"]
    cli = pytestconfig.getoption("timeout", default=None)
    env = os.environ.get("PYTEST_TIMEOUT")

    if cli is not None:
        effective, source = float(cli), "--timeout"
    elif env not in (None, ""):
        effective, source = float(env), "$PYTEST_TIMEOUT"
    else:
        effective, source = float(ini_timeout), "ini"

    # 0 means "disabled" to pytest-timeout, so this rejects it as out of range
    # rather than needing a special case.
    assert 4 * SLOWEST_HEALTHY_TEST_SECONDS <= effective <= 600, (
        f"effective per-test timeout is {effective}s (from {source}); "
        f"the ini declares {ini_timeout}s"
    )
