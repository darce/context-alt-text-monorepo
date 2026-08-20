"""Single authority for the "does score == tau count?" decision (FIR-12 BR-63/69/71).

Before this module, the tie-at-tau convention was a design decision repeated
as seven separate literal comparisons across ``calibrate_face_thresholds.py``,
``face_assignment.py``, ``synthetic_occlusion.py`` and
``open_set_identification.py`` (REF-19: no information leakage -- the
convention had leaked into every call site instead of being owned by one).
That let the sites drift out of lockstep with each other (REF-26: DRY is
about knowledge, not text -- the fact "how do we treat a tie at tau" needed a
multi-site edit, and one site was missed in a prior migration). This module
is that single owner: callers import the named predicate for their use case
instead of writing ``score > tau`` / ``score >= tau`` / ``score < tau``
inline.

Two published metrics and one operational decision are NOT the same
predicate -- do not collapse them:

- ``is_fpi`` and ``is_fnir_miss`` implement JANUS Sec2.3.4's published-metric
  inequality split, which is intentionally asymmetric: a tie at tau counts
  in the system's favour on *both* sides (not counted as a false positive,
  not counted as a miss).
- ``accepts`` implements the operational apply-path decision rule, which is
  a single yes/no gate and has no reason to share JANUS's asymmetry.

The calibrator's selection metric (``fmr_at`` in ``calibrate_face_thresholds.py``)
and the open-set published-metric scorer (``open_set_identification._is_fpi``)
must both call ``is_fpi`` -- not because they are the same as the apply path,
but because they are the same as *each other*: they are both instances of
the JANUS FPI definition, and a calibrated tau is only meaningful if the
metric that chose it (JANUS FPI) is the metric that gets published (JANUS
FPI). ``face_assignment`` and ``synthetic_occlusion`` apply-path sites must
call ``accepts`` because they are answering a different question ("do we
act on this score") from the published-metric sites ("does this score count
against the published rate").
"""

from __future__ import annotations


def is_fpi(score: float, tau: float) -> bool:
    """JANUS Sec2.3.4 non-mated (false-positive-identification) predicate.

    A non-mated rank-1 search counts as a false positive only when its score
    is *strictly greater than* ``tau``. A score exactly equal to ``tau`` is
    NOT a false positive -- JANUS scores that tie in the system's favour.
    """
    return score > tau


def is_fnir_miss(score: float, tau: float) -> bool:
    """JANUS Sec2.3.4 mated (false-negative-identification-rate) predicate.

    A mated search counts as a miss only when the mate's score is *strictly
    less than* ``tau``. A score exactly equal to ``tau`` is NOT a miss --
    JANUS scores that tie in the system's favour, matching ``is_fpi``'s
    treatment of the same boundary from the other side.
    """
    return score < tau


def accepts(score: float, tau: float) -> bool:
    """Operational apply-path decision rule: is ``score`` accepted at ``tau``?

    This is the DECISION rule the system acts on (face assignment, occlusion
    recovery), distinct from ``is_fpi`` and ``is_fnir_miss`` above, which are
    published-metric predicates and must not be reused for the apply path.
    A score exactly equal to ``tau`` IS accepted.

    The calibrator's selection metric (what ``select_threshold`` optimizes
    against) must use the same predicate as this apply path, or the
    calibrated operating point is not the one actually deployed: today the
    calibrator selects tau against ``is_fpi`` (JANUS FPI, strict ``>``) while
    this apply-path predicate is ``>=``, so a candidate tau equal to an
    observed impostor score is judged "not FPI" by the calibrator yet
    "accept" by this function for that same score. See LANE_REPORT.md for
    the known live instance of this gap (fixture media_id=301) and why this
    commit does not fix it.
    """
    return score >= tau
