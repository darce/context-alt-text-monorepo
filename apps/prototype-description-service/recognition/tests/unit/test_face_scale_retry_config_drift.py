"""FIR scale-retry config drift: the retry knob is part of the frozen active config.

Companion to test_face_scale_retry_provenance.py. Uses the verified AuraFace pair
through that module's helpers, because only a verified pair freezes a
FrozenFaceRuntimeConfig; the modelless composition has frozen_config None.

The knob must be frozen as the ninth FrozenFaceRuntimeConfig field, so a setting
mutation after load is reported as effective_config_changed by the same drift
check that guards every other cache input. The knob is never a cache-only key.
Unchanged-config, default-OFF and explicit-zero controls pass on base. Causal RED
tests must fail on assertions, never on setup errors.

Heuristics: [TEST-15]
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from recognition.tests.unit.test_face_scale_retry_contract import (
    RETRY_MAX_SIDE,
    _small_visible_only_at_640,
)
from recognition.tests.unit.test_face_scale_retry_provenance import _adapter, _verified_runtime

KNOB_FIELD = "retry_max_side"


def _no_faces(_pad_h: int, _pad_w: int) -> list:
    return []


def _drift_reason(monkeypatch: pytest.MonkeyPatch, runtime, expected_config) -> str | None:
    return _adapter(monkeypatch, runtime, {})._drift_reason(expected_config, None)


# ---------------------------------------------------------------------------
# Controls: must pass on base (no knob mutation, knob off).
# ---------------------------------------------------------------------------


def test_unchanged_default_off_active_config_has_no_drift_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, _no_faces, knob=None)

    assert _drift_reason(monkeypatch, runtime, runtime.frozen_config) is None


def test_explicit_zero_knob_freezes_same_config_as_unset_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    unset = _verified_runtime(monkeypatch, tmp_path, _no_faces, knob=None)
    explicit = _verified_runtime(monkeypatch, tmp_path, _no_faces, knob=0)

    assert explicit.frozen_config == unset.frozen_config
    assert _drift_reason(monkeypatch, explicit, unset.frozen_config) is None


# ---------------------------------------------------------------------------
# Causal RED: the knob is frozen into the active config and drift-checked.
# ---------------------------------------------------------------------------


def test_frozen_config_freezes_retry_knob_as_ninth_field_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, _no_faces, knob=None)
    names = {field.name for field in fields(type(runtime.frozen_config))}

    assert KNOB_FIELD in names, "CAUSAL_RED: FrozenFaceRuntimeConfig must freeze the retry knob"
    assert len(names) == 9


@pytest.mark.parametrize(("knob", "frozen"), [(None, 0), (0, 0), (RETRY_MAX_SIDE, RETRY_MAX_SIDE)])
def test_active_config_records_knob_value_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, knob: int | None, frozen: int
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(0.5, 0.5), knob=knob)

    recorded = getattr(runtime.frozen_config, KNOB_FIELD, None)
    assert recorded == frozen, f"CAUSAL_RED: active config must freeze retry knob {frozen!r}, got {recorded!r}"


@pytest.mark.parametrize(
    ("expected_knob", "active_knob"),
    [(0, RETRY_MAX_SIDE), (RETRY_MAX_SIDE, 0)],
    ids=["enabled-in-active-runtime", "disabled-in-active-runtime"],
)
def test_knob_mutation_is_effective_config_drift_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, expected_knob: int, active_knob: int
) -> None:
    visible = _small_visible_only_at_640(0.5, 0.5)
    expected = _verified_runtime(monkeypatch, tmp_path, visible, knob=expected_knob).frozen_config
    # Loaded last so its recorded artifact identity matches the files on disk.
    active = _verified_runtime(monkeypatch, tmp_path, visible, knob=active_knob)

    reason = _drift_reason(monkeypatch, active, expected)

    assert reason == "effective_config_changed", (
        f"CAUSAL_RED: knob-only mutation expected={expected_knob!r} active={active_knob!r} not detected (reason={reason!r})"
    )


@pytest.mark.parametrize("raw", ["1000", "-1", "abc"])
def test_unsupported_knob_value_fails_closed_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: str
) -> None:
    # The raw string is passed through verbatim as the environment value.
    with pytest.raises(ValueError):
        _verified_runtime(monkeypatch, tmp_path, _no_faces, knob=raw)  # type: ignore[arg-type]
