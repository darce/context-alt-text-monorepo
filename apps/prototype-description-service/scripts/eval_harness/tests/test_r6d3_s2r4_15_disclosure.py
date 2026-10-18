"""S2R4-15 — S2R3-07 rebaseline must be named in the artifacts themselves.

A later refusal/hold wave added notes that say 'caption unchanged' against
the already-rebaselined S2R3-07 numbers. That hides the original movement
(insertion 0.888→0.890, MiniCPM 9→8 / 0.667→0.800, failure-path rewrite).
A note that only says 'disclosed' or lives on JSON but not the markdown
twin is the same defect.
"""

from __future__ import annotations

import json
from pathlib import Path


_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[5]


def _notes(rel: str) -> str:
    path = _REPO_ROOT / rel
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        payload = json.loads(text)
        notes = payload.get("notes") or []
        if isinstance(notes, list):
            return "\n".join(str(n) for n in notes)
        return str(notes)
    return "\n".join(
        line[len("- notes:") :].strip()
        for line in text.splitlines()
        if line.startswith("- notes:")
    )


def _both(stem_rel_json: str, stem_rel_md: str) -> tuple[str, str]:
    return _notes(stem_rel_json), _notes(stem_rel_md)


def test_646_notes_name_s2r3_07_caption_and_failure_path_moves() -> None:
    """The exemplar S2R4-15 artifact still publishes the a90a091e numbers."""
    json_notes, md_notes = _both(
        "docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3-report.json",
        "docs/tasks/altq/bakeoff-results/run-altq-646-interleave-v3-report.md",
    )
    for blob, label in ((json_notes, "json"), (md_notes, "md")):
        assert blob, f"{label} has no notes"
        low = blob.lower()
        assert "0.888" in blob and "0.890" in blob, f"{label} missing insertion 0.888→0.890"
        assert "0.685" in blob and "0.684" in blob, f"{label} missing name_precision 0.685→0.684"
        assert "203" in blob and "204" in blob, f"{label} missing wrong_name_images 203→204"
        assert "24" in blob and "25" in blob, f"{label} missing title hallucinated 24→25"
        assert "Sable Current" in blob, f"{label} missing new hallucinated name"
        assert "19" in blob and "20" in blob, f"{label} missing true_rejections 19→20"
        assert "0.635" in blob and "0.634" in blob, f"{label} missing long name_precision"
        assert "262" in blob and "263" in blob, f"{label} missing long wrong_name_images"
        assert "2026/07/" in blob and "personal/" in blob, f"{label} missing failure-path rewrite"
        assert "s2r3-07" in low or "a90a091e" in low, f"{label} must name the producing wave"


def test_minicpm_notes_name_s2r3_07_caption_rebaseline() -> None:
    json_notes, md_notes = _both(
        "docs/tasks/vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.json",
        "docs/tasks/vlm/VLM-2B-bakeoff-MiniCPM-V-4.5-report.md",
    )
    for blob, label in ((json_notes, "json"), (md_notes, "md")):
        assert blob, f"{label} has no notes"
        assert "9" in blob and "8" in blob, f"{label} missing must_right_defined_images 9→8"
        assert "0.667" in blob and "0.800" in blob, f"{label} missing mean_gated_score 0.667→0.800"
        assert "name precision" in blob.lower() or "name_precision" in blob.lower(), (
            f"{label} missing new name-precision line"
        )


def test_caprl_and_qwen3_notes_name_s2r3_07_caption_rebaseline() -> None:
    pairs = (
        (
            "docs/tasks/vlm/VLM-2B-bakeoff-CapRL-Qwen3VL-4B-report.json",
            "docs/tasks/vlm/VLM-2B-bakeoff-CapRL-Qwen3VL-4B-report.md",
        ),
        (
            "docs/tasks/vlm/VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-report.json",
            "docs/tasks/vlm/VLM-2B-bakeoff-Qwen3-VL-4B-Instruct-report.md",
        ),
    )
    for json_rel, md_rel in pairs:
        json_notes, md_notes = _both(json_rel, md_rel)
        for blob, label in ((json_notes, json_rel), (md_notes, md_rel)):
            assert blob, f"{label} has no notes"
            assert "9" in blob and "8" in blob, f"{label} missing must_right 9→8"
            assert "0.900" in blob or "0.9" in blob, f"{label} missing old mean_gated 0.900"
            assert "0.889" in blob or "0.8889" in blob, f"{label} missing new mean_gated 0.889"
            assert "name precision" in blob.lower() or "name_precision" in blob.lower(), (
                f"{label} missing new name-precision line"
            )


def test_e20_fusion_reports_disclose_ident_withdrawal_and_manifest_swap() -> None:
    pairs = (
        (
            "docs/tasks/20.0/E20-FUSION-adhoc-report.json",
            "docs/tasks/20.0/E20-FUSION-adhoc-report.md",
        ),
        (
            "docs/tasks/20.0/E20-FUSION-staged-report.json",
            "docs/tasks/20.0/E20-FUSION-staged-report.md",
        ),
    )
    for json_rel, md_rel in pairs:
        json_notes, md_notes = _both(json_rel, md_rel)
        for blob, label in ((json_notes, json_rel), (md_notes, md_rel)):
            assert blob, f"{label} has no notes (S2R4-15: fusion twins shipped none)"
            low = blob.lower()
            assert "refused" in low, f"{label} must disclose identification refusal"
            assert "04d5712a" in low and "73cbe113" in low, (
                f"{label} must name score_manifest 04d5712a→73cbe113"
            )
            assert "matches fetch" in low or "manifest_matches_fetch" in low, (
                f"{label} must disclose matches-fetch flip"
            )
