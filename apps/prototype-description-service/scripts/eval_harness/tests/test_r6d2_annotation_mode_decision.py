"""S2R4-20: the S2R3-10 document-level decision is a published contract.

Closing the unreachability finding by comment alone left no record
outside GoldenEntry/report.py remarks. The named invariant constant is
the record: tests import it, the loader raises it, and GoldenEntry still
has no field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness import manifest as man
from scripts.eval_harness.manifest import (
    ANNOTATION_MODE_DOCUMENT_LEVEL_INVARIANT,
    GoldenEntry,
    ManifestError,
    load_manifest,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROVENANCED = FIXTURES / "provenanced_min.json"


def test_document_level_decision_is_a_published_invariant() -> None:
    """The decision is importable, not a comment."""
    assert ANNOTATION_MODE_DOCUMENT_LEVEL_INVARIANT == "annotation_mode_is_document_level"
    assert man._reject_per_entry_annotation_mode.__doc__ is not None
    assert "S2R4-20" in man._reject_per_entry_annotation_mode.__doc__
    assert "annotation_mode" not in GoldenEntry.model_fields


def test_loader_raises_the_published_invariant(tmp_path: Path) -> None:
    """load_manifest uses the published token, not a respelt string."""
    doc = json.loads(PROVENANCED.read_text(encoding="utf-8"))
    doc["entries"][0]["annotation_mode"] = "roster_only"
    path = tmp_path / "stamped.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ManifestError) as exc_info:
        load_manifest(str(path))
    assert exc_info.value.invariant == ANNOTATION_MODE_DOCUMENT_LEVEL_INVARIANT
