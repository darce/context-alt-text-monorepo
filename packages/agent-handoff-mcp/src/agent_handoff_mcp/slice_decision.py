from __future__ import annotations

import re

LEGACY_SLICE_COMPLETE_RE = re.compile(r"^slice_complete_\w+$")
PREFIXED_SLICE_COMPLETE_RE = re.compile(
    r"^[a-z]{2,4}_slice_complete_[A-Za-z0-9_-]+_\w+$"
)

# Full canonical grammar: <author_tag>_<decision_kind>_<work_ref>_<slug>
# - author_tag:    [a-z]{2,4}
# - decision_kind: one or more underscore-delimited lowercase words, e.g. slice_complete
# - work_ref:      task/epic reference, e.g. E12-1, ADPH-4, or any alphanumeric+hyphen token
# - slug:          [a-z0-9][a-z0-9_]* (at least one char, starts with alphanumeric)
CANONICAL_DECISION_RE = re.compile(
    r"^[a-z]{2,4}_[a-z][a-z0-9_]*_[A-Za-z0-9][A-Za-z0-9_-]*_[a-z0-9][a-z0-9_]*$"
)


def is_legacy_slice_complete_decision(decision: str) -> bool:
    return bool(LEGACY_SLICE_COMPLETE_RE.match(decision))


def is_prefixed_slice_complete_decision(decision: str) -> bool:
    return bool(PREFIXED_SLICE_COMPLETE_RE.match(decision))


def is_slice_complete_decision(decision: str) -> bool:
    """Return True if the decision is a slice-complete id in either supported format."""
    return is_legacy_slice_complete_decision(decision) or is_prefixed_slice_complete_decision(decision)


def is_canonical_decision(decision: str) -> bool:
    """Return True if the decision id conforms to the full canonical grammar.

    Canonical form: ``<author_tag>_<decision_kind>_<work_ref>_<slug>``

    This accepts any decision kind, not just ``slice_complete``.
    """
    return bool(CANONICAL_DECISION_RE.match(decision))


def classify_decision_id(decision: str) -> str:
    """Classify a decision id string into one of four categories.

    Returns:
        ``"canonical"``       – matches the full canonical grammar.
        ``"legacy_slice"``    – matches the legacy ``slice_complete_*`` form (grandfathered).
        ``"malformed_slice"`` – contains ``slice_complete`` but violates the grammar.
        ``"freeform"``        – does not use slice_complete at all and is not canonical.
    """
    if is_canonical_decision(decision):
        return "canonical"
    if is_legacy_slice_complete_decision(decision):
        return "legacy_slice"
    if "slice_complete" in decision:
        return "malformed_slice"
    return "freeform"


def extract_slice_label(decision: str) -> str:
    """Extract the label payload from a slice-complete decision id."""
    if is_legacy_slice_complete_decision(decision):
        return decision[len("slice_complete_"):]
    parts = decision.split("_slice_complete_", 1)
    if len(parts) == 2:
        return parts[1]
    return decision
