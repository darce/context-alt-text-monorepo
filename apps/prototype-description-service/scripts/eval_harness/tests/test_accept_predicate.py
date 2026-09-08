"""FIR-12 BR-63/69/71: accept_predicate is the single authority for tie-at-tau.

The boundary case (``score == tau``) is not a coincidence to be hand-waved:
``select_threshold`` draws candidate thresholds from the observed finite
score set, so a calibrated ``tau`` always lands exactly on a data point and
this tie is reached by construction on every real run, not by luck.
"""

from __future__ import annotations

import pytest

from scripts.eval_harness.accept_predicate import accepts, is_fnir_miss, is_fpi

TAU = 0.50
JUST_BELOW = TAU - 1e-9
JUST_ABOVE = TAU + 1e-9


class TestIsFpiBoundary:
    """JANUS 2.3.4 non-mated predicate: strictly > tau."""

    def test_at_tau_is_not_fpi(self):
        assert is_fpi(TAU, TAU) is False

    def test_just_below_tau_is_not_fpi(self):
        assert is_fpi(JUST_BELOW, TAU) is False

    def test_just_above_tau_is_fpi(self):
        assert is_fpi(JUST_ABOVE, TAU) is True


class TestIsFnirMissBoundary:
    """JANUS 2.3.4 mated predicate: strictly < tau."""

    def test_at_tau_is_not_a_miss(self):
        assert is_fnir_miss(TAU, TAU) is False

    def test_just_below_tau_is_a_miss(self):
        assert is_fnir_miss(JUST_BELOW, TAU) is True

    def test_just_above_tau_is_not_a_miss(self):
        assert is_fnir_miss(JUST_ABOVE, TAU) is False


class TestAcceptsBoundary:
    """Operational apply-path predicate: >= tau (tie accepts)."""

    def test_at_tau_accepts(self):
        assert accepts(TAU, TAU) is True

    def test_just_below_tau_rejects(self):
        assert accepts(JUST_BELOW, TAU) is False

    def test_just_above_tau_accepts(self):
        assert accepts(JUST_ABOVE, TAU) is True


def test_fpi_and_fnir_miss_never_both_true_at_a_tie():
    """JANUS scores a tie in the system's favour on both sides at once."""
    assert is_fpi(TAU, TAU) is False
    assert is_fnir_miss(TAU, TAU) is False


@pytest.mark.parametrize("tau", [0.0, 0.20, 0.50, 0.6180339887, 0.90, 1.0])
def test_selection_and_apply_predicates_agree_off_the_exact_tie(tau):
    """BR-71 structural lockstep.

    Away from the exact tie, the calibrator's selection predicate (``is_fpi``,
    used by ``fmr_at`` and the OOF sweep) and the apply path's decision rule
    (``accepts``, used by ``face_assignment`` and ``synthetic_occlusion``)
    must agree — both are answering "does the system act on this score",
    and the only place they may legitimately diverge is a score exactly at
    tau. This sweep deliberately excludes ``score == tau`` rather than
    papering over it: that divergence is real, documented in
    ``accepts.__doc__`` and in LANE_REPORT.md, and is a separate
    behaviour-hat fix (making calibrated tau never land on an observed
    score), not something this structural test should hide.
    """
    sweep = (
        tau - 0.3,
        tau - 0.05,
        tau - 1e-9,
        tau + 1e-9,
        tau + 0.05,
        tau + 0.3,
    )
    for score in sweep:
        assert is_fpi(score, tau) == accepts(score, tau), (score, tau)

    # Documented, not hidden: the two predicates diverge exactly at the tie.
    assert is_fpi(tau, tau) is False
    assert accepts(tau, tau) is True
