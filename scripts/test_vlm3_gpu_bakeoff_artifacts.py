import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VLM_DOCS = REPO_ROOT / "docs" / "tasks" / "vlm"


def test_gpu_bakeoff_candidate_artifact_uses_existing_harness_endpoint_commands() -> None:
    artifact = json.loads((VLM_DOCS / "VLM-3-gpu-bakeoff-candidates-2026-07-08.json").read_text())

    assert artifact["schema"] == "acx-gpu-bakeoff/v1"
    assert artifact["task_ref"] == "VLM-3"
    assert artifact["hardware_target"]["shape"] == "VM.GPU.A10.1"
    assert artifact["harness"]["script"] == "apps/prototype-description-service/scripts/eval_harness/bakeoff.py"
    assert artifact["harness"]["forked"] is False
    assert len(artifact["candidates"]) >= 7

    model_ids = {candidate["model_id"] for candidate in artifact["candidates"]}
    assert "Qwen3-VL-30B-A3B-Instruct" in model_ids
    assert "Phi-4-multimodal" in model_ids

    # S2-01 / rg-006: commands run from the service cwd; --out lands under repo docs/tasks/vlm.
    assert artifact["harness"]["cwd"] == "apps/prototype-description-service"
    budget = artifact["hardware_target"]["usable_vram_budget_gb"]
    for candidate in artifact["candidates"]:
        expected_fit = _expected_fit(candidate["estimated_model_gb"], budget)
        assert candidate["a10_24gb_fit"] == expected_fit
        command = candidate["command"]
        assert "-m scripts.eval_harness.bakeoff --endpoint" in command
        assert f"--model-id {candidate['model_id']}" in command
        assert f"--out ../../../docs/tasks/vlm/VLM-3-bakeoff-{candidate['model_id']}-run-record.json" in command
        assert "ACX_EVAL_LIVE=1" in command and "GOLDEN_IMAGES_DIR=" in command
        if candidate["reasoning_tuned"]:
            assert "--no-think" in command

    # S2-06: Kimi-VL-A3B-2506 is the Thinking-2506 refresh, not non-thinking Instruct.
    kimi = next(c for c in artifact["candidates"] if c["model_id"] == "Kimi-VL-A3B-2506")
    assert kimi["reasoning_tuned"] is True
    assert "--no-think" in kimi["command"]
    notes = kimi.get("notes", "")
    assert "Thinking" in notes or "thinking" in notes


def test_gpu_bakeoff_report_placeholders_are_marked_pending_live_gpu() -> None:
    """Pending stubs must be distinguishable from scored acx-eval/v1 REPORTs (S2-02).

    Real REPORTs carry kind=report plus counts/provenance/per_image. Placeholders
    keep the schema family for discoverability but use kind=pending_report and an
    explicit pending status so consumers never treat them as measured evidence.
    """
    index = json.loads((VLM_DOCS / "VLM-3-gpu-bakeoff-candidates-2026-07-08.json").read_text())
    real_report_keys = {"counts", "provenance", "per_image", "caption", "faces", "failures"}
    for candidate in index["candidates"]:
        report_path = VLM_DOCS / candidate["report_artifact"]
        report = json.loads(report_path.read_text())
        assert report["schema"] == "acx-eval/v1"
        assert report["kind"] == "pending_report"
        assert report["kind"] != "report"
        assert report["task_ref"] == "VLM-3"
        assert report["model_id"] == candidate["model_id"]
        assert report["status"] == "pending_live_gpu_bakeoff"
        assert str(report["status"]).startswith("pending")
        assert real_report_keys.isdisjoint(report.keys())


def _expected_fit(estimated_gb: float, usable_budget_gb: float) -> str:
    ratio = estimated_gb / usable_budget_gb
    if ratio <= 0.60:
        return "headroom"
    if ratio <= 0.85:
        return "yes"
    if ratio <= 1.0:
        return "tight"
    return "headroom_only"
