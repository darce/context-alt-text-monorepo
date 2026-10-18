"""FIR-11-S2R3-14 — VLM-2A must name the identification/caption rebaseline.

A detection-refusal wave republished true_rejections 6→10 and
must_right_defined_images 0→37 / must_right_failed_images 0→34.
Those deltas are honest (current golden already carried 37 rubric rows)
but they are an identification and caption rebaseline. A later notes
restore dropped that account. The artifact itself must still say so.
"""

from __future__ import annotations

import json
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]
_JSON = _REPO_ROOT / "docs/tasks/vlm/VLM-2A-baseline-20260706-report.json"
_MD = _REPO_ROOT / "docs/tasks/vlm/VLM-2A-baseline-20260706-report.md"


def _json_notes() -> str:
    payload = json.loads(_JSON.read_text(encoding="utf-8"))
    notes = payload.get("notes") or []
    if isinstance(notes, list):
        return "\n".join(str(n) for n in notes)
    return str(notes)


def _md_notes() -> str:
    return "\n".join(
        line[len("- notes:") :].strip()
        for line in _MD.read_text(encoding="utf-8").splitlines()
        if line.startswith("- notes:")
    )


def test_vlm2a_notes_name_identification_and_caption_rebaseline() -> None:
    for blob, label in ((_json_notes(), "json"), (_md_notes(), "md")):
        assert blob, f"{label} has no notes"
        low = blob.lower()
        assert "true_rejections" in low or "true rejections" in low, (
            f"{label} missing true_rejections rebaseline"
        )
        assert "6" in blob and "10" in blob, f"{label} missing true_rejections 6→10"
        assert "must_right_defined_images" in low or "must-right" in low or "must_right" in low, (
            f"{label} missing must_right_defined_images"
        )
        assert "37" in blob, f"{label} missing must_right_defined_images 37"
        assert "34" in blob, f"{label} missing must_right_failed_images 34"
        assert "0" in blob, f"{label} missing the pre-rebaseline 0"
        # published caption numbers must still be the honest rebaseline, not hand-edited
        payload = json.loads(_JSON.read_text(encoding="utf-8"))
        assert payload["caption"]["must_right_defined_images"] == 37
        assert payload["caption"]["must_right_failed_images"] == 34
