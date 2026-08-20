"""Re-derivable evidence for the mutation guard's ``expect_survived`` claims.

``M6`` is exempt from the kill requirement on the grounds that emptying the
``_synthetic_audit_targets`` token loop is verdict-equivalent for
``audit_provenance_row``. That is a load-bearing claim -- it is the whole reason
a surviving mutant does not fail the gate -- and it was previously supported
only by grid sizes quoted in a commit message and a docstring that disagreed
with each other and with the tree (FIR-7-LR-05).

These tests run the real applier from ``mutation_guard`` against a deterministic
grid and pin both halves of the claim: verdict/reason equivalence at the public
entry point, and the *absence* of path equivalence one layer down. The second
half matters as much as the first -- if it ever starts holding, the masking arm
that makes M6 safe has moved, and the exemption needs re-deriving.

Scope, measured rather than assumed. The grid varies source, derived model,
clearance token, photo clearance and generator lineage; it holds the licence tag
at ``MIT``. So it reddens for defects on the axes it sweeps -- substituting the
M3 (empty NC ids), M10 (disabled lineage branch) and M14 (package denylist
always misses) appliers for M6 each makes the equivalence assertion fail -- and
is blind to licence-tag defects such as M1 and M13, which it leaves green. Those
axes are pinned by ``test_license_policy.py``; do not read a green here as
evidence about them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve().parent


def _load(name: str, source: str) -> Any:
    """Load a license_policy variant from source text under its own name."""
    path = _HERE / f"_eq_{name}.py"
    path.write_text(source, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Registered before exec so the module's own dataclasses resolve.
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def modules() -> tuple[Any, Any]:
    sys.path.insert(0, str(_HERE))
    try:
        from mutation_guard import _m6_empty_synthetic_token_loop
    finally:
        sys.path.pop(0)

    pristine = (_HERE / "license_policy.py").read_text(encoding="utf-8")
    mutated = _m6_empty_synthetic_token_loop(pristine)
    assert mutated != pristine, "M6 applier was a no-op -- its anchor has rotted"
    return _load("_eq_base", pristine), _load("_eq_m6", mutated)


# Deliberately small: this is a per-run regression pin, not an exhaustive
# sweep. Every axis M6 can plausibly move is represented -- both synthetic
# registry heads, an expanded head, the operator-owned tag, a registered
# occluder source, a research source and an unregistered one; derived values
# covering empty / both heads / NC / allowlisted / denylisted.
_SOURCES = (
    "dcface",
    "vec2face",
    "dcface-v2",
    "self-generated",
    "operator-photo",
    "ffhq",
    "buffalo_l",
    "unknown-src",
)
_DERIVED = (
    "",
    "dcface",
    "vec2face",
    "insightface/buffalo_l",
    "yunet",
    "ultralytics",
)
_PHOTO_CLEARANCES = (None, "cleared", "pending")
_LICENSES = ("MIT",)
_LINEAGE = (None, "stylegan3-ffhq")


def _grid(module: Any) -> list[dict[str, Any]]:
    """Every (source, derived, clearance, photo, licence, lineage) combination."""
    clearances = (None, module.DCFACE_CLEARANCE_DECISION, "bogus_token_xyz")
    rows = []
    for source in _SOURCES:
        for derived in _DERIVED:
            for clearance in clearances:
                for photo in _PHOTO_CLEARANCES:
                    for licence in _LICENSES:
                        for lineage in _LINEAGE:
                            row: dict[str, Any] = {
                                "source": source,
                                "derived_from_model": derived,
                                "license": licence,
                                "model_id": "yunet",
                                "package": "numba",
                            }
                            if clearance is not None:
                                row["clearance_decision"] = clearance
                            if photo is not None:
                                row["photo_clearance"] = photo
                            if lineage is not None:
                                row["generator_lineage"] = lineage
                            rows.append(row)
    return rows


# Quoted by _m6_empty_synthetic_token_loop's docstring and by the mutation
# table's justification. Changing the grid means changing both.
EXPECTED_GRID_ROWS = 864
EXPECTED_PROBED_VERDICTS = EXPECTED_GRID_ROWS * 5


def test_m6_grid_size_is_the_number_the_docstring_quotes(modules: tuple[Any, Any]) -> None:
    base, _ = modules
    assert len(_grid(base)) == EXPECTED_GRID_ROWS


def test_m6_is_verdict_and_reason_equivalent_on_audit_provenance_row(
    modules: tuple[Any, Any],
) -> None:
    base, m6 = modules
    deltas = []
    probed = 0
    for row in _grid(base):
        for name in (c.name for c in base.PolicyCategory):
            probed += 1
            got_base = base.audit_provenance_row(
                dict(row), category=getattr(base.PolicyCategory, name)
            )
            got_m6 = m6.audit_provenance_row(
                dict(row), category=getattr(m6.PolicyCategory, name)
            )
            left = (got_base.ok, getattr(got_base.reason, "value", None))
            right = (got_m6.ok, getattr(got_m6.reason, "value", None))
            if left != right:
                deltas.append((name, row, left, right))

    assert probed == EXPECTED_PROBED_VERDICTS
    assert deltas == [], (
        f"M6 is no longer verdict-equivalent ({len(deltas)}/{probed} deltas). "
        "Its expect_survived=True exemption is void until re-derived; first "
        "delta: " + repr(deltas[0])
    )


def test_m6_is_not_path_equivalent_one_layer_down(modules: tuple[Any, Any]) -> None:
    """The masking arms are what make M6 safe -- pin that they are still doing work.

    If this ever reports zero, the downstream floor/registration arms have
    stopped compensating and M6's verdict equivalence has become accidental
    rather than structural (SECD-06).
    """
    base, m6 = modules
    deltas = 0
    probed = 0
    for row in _grid(base):
        for name in (c.name for c in base.PolicyCategory):
            probed += 1
            kwargs = {
                "source": row["source"],
                "derived": row["derived_from_model"],
                "has_generator_lineage": "generator_lineage" in row,
            }
            left = base._synthetic_audit_targets(
                category=getattr(base.PolicyCategory, name), **kwargs
            )
            right = m6._synthetic_audit_targets(
                category=getattr(m6.PolicyCategory, name), **kwargs
            )
            if left != right:
                deltas += 1

    assert deltas > 0, (
        "M6 now produces identical _synthetic_audit_targets output. It has "
        "become a genuine equivalent mutant rather than a masked one; the "
        "docstring's 'NOT path-equivalent' claim is stale."
    )
