"""FIR-11-S2R3-10: persisted annotation_mode is document-level only.

GoldenEntry forbids a per-entry stamp (extra=forbid, no field). Shipping
the mixed-stamp / cannot-widen lattice as if it were a persisted contract
is worse than either making the field real or refusing at the document
level. This suite pins the second option: an on-disk entry stamp is a
named loader refusal, not a pydantic extra=forbid accident.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.manifest import (
    GoldenEntry,
    ManifestError,
    load_manifest,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROVENANCED = FIXTURES / "provenanced_min.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc: dict, name: str = "manifest.json") -> Path:
    out = tmp_path / name
    out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return out


def test_on_disk_per_entry_stamp_is_named_document_level_refusal(tmp_path: Path) -> None:
    """A real JSON file carrying a per-entry stamp must fail by named invariant."""
    doc = _load_json(PROVENANCED)
    doc["entries"][0]["annotation_mode"] = "roster_only"
    path = _write(tmp_path, doc, "stamped.json")
    with pytest.raises(ManifestError) as exc_info:
        load_manifest(str(path))
    err = exc_info.value
    assert err.invariant == "annotation_mode_is_document_level"
    assert err.entry_index == 0
    assert err.entry_path == "fixtures/ada_example_101.jpg"
    assert "document-level" in str(err)
    # Must not collapse to a generic extra=forbid schema wrap.
    assert "Extra inputs are not permitted" not in str(err)


def test_on_disk_exhaustive_per_entry_stamp_also_refused(tmp_path: Path) -> None:
    """Agreeing-with-document is not a loophole; the field is not persisted."""
    doc = _load_json(PROVENANCED)
    doc["annotation_mode"] = "roster_only"
    doc["entries"][1]["annotation_mode"] = "exhaustive"
    path = _write(tmp_path, doc, "mixed.json")
    with pytest.raises(ManifestError) as exc_info:
        load_manifest(str(path))
    err = exc_info.value
    assert err.invariant == "annotation_mode_is_document_level"
    assert err.entry_index == 1
    assert err.entry_path == "fixtures/quiet_example_102.jpg"


def test_golden_entry_still_has_no_annotation_mode_field() -> None:
    """We refused the 'add the field' option; the lattice stays raw-mapping-only."""
    assert "annotation_mode" not in GoldenEntry.model_fields
