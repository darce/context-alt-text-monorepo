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

    for candidate in artifact["candidates"]:
        assert candidate["a10_24gb_fit"] in {"yes", "tight", "headroom_only"}
        command = candidate["command"]
        assert "-m scripts.eval_harness.bakeoff --endpoint" in command
        assert f"--model-id {candidate['model_id']}" in command
        if candidate["reasoning_tuned"]:
            assert "--no-think" in command


def test_gpu_bakeoff_report_placeholders_are_marked_pending_live_gpu() -> None:
    index = json.loads((VLM_DOCS / "VLM-3-gpu-bakeoff-candidates-2026-07-08.json").read_text())
    for candidate in index["candidates"]:
        report_path = VLM_DOCS / candidate["report_artifact"]
        report = json.loads(report_path.read_text())
        assert report["schema"] == "acx-eval/v1"
        assert report["task_ref"] == "VLM-3"
        assert report["model_id"] == candidate["model_id"]
        assert report["status"] == "pending_live_gpu_bakeoff"
