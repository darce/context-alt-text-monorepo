"""Invalid async limits must fail at configuration, before capacity admission.

TEST-15 — Prove the green can go red (heuristics-canon v0.25.6,
The Pragmatic Programmer, ch. 9): run these against the unchanged router;
malformed values must name their setting and nonpositive limits must raise
instead of constructing a gate that reports ordinary capacity exhaustion.
No database, HTTP client, worker, or model is needed by these tests.
"""

from __future__ import annotations

import pytest


SETTINGS = ("ACX_ASYNC_MAX_PENDING_JOBS", "ACX_ASYNC_MAX_RETAINED_IMAGE_BYTES")


@pytest.fixture
def gate_factory(monkeypatch):
    # Isolate both variables, including the module's first startup construction.
    for setting in SETTINGS:
        monkeypatch.delenv(setting, raising=False)
    from scene.interface_adapters.http.routers.describe import _async_admission_gate

    return _async_admission_gate


@pytest.mark.parametrize("setting", SETTINGS)
@pytest.mark.parametrize("raw", ["not-an-integer", "1.5", ""])
def test_malformed_async_limit_names_setting(gate_factory, monkeypatch, setting, raw):
    monkeypatch.setenv(setting, raw)
    with pytest.raises(ValueError, match=setting):
        gate_factory()


@pytest.mark.parametrize("setting", SETTINGS)
@pytest.mark.parametrize("raw", ["0", "-1"])
def test_nonpositive_async_limit_fails_before_admission(gate_factory, monkeypatch, setting, raw):
    monkeypatch.setenv(setting, raw)
    # A configuration ValueError naming the setting is required here. Returning
    # a gate whose first reservation reports queue/budget exhaustion is a bug.
    with pytest.raises(ValueError, match=setting):
        gate_factory()


def test_unset_async_limits_accept_and_release(gate_factory):
    gate = gate_factory()
    assert gate.try_acquire(1) is None
    gate.release(1)
    assert gate.try_acquire(1) is None
    gate.release(1)


@pytest.mark.parametrize("jobs, image_bytes", [("1", "1"), ("2", "5")])
def test_positive_async_limits_preserve_capacity_and_release(
    gate_factory, monkeypatch, jobs, image_bytes
):
    monkeypatch.setenv(SETTINGS[0], jobs)
    monkeypatch.setenv(SETTINGS[1], image_bytes)
    gate = gate_factory()
    limit = int(image_bytes)
    assert gate.try_acquire(limit) is None  # byte boundary is inclusive
    expected = (
        "describe job queue is full"
        if jobs == "1"
        else "describe job store image byte budget exceeded"
    )
    assert gate.try_acquire(1) == expected
    gate.release(limit)
    assert gate.try_acquire(limit) is None
    gate.release(limit)
