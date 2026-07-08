from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MEMO = REPO_ROOT / "docs" / "tasks" / "vlm" / "VLM-3-gpu-detailed-tier-decision-memo.md"


def test_decision_memo_names_one_winner_and_cites_artifacts() -> None:
    text = MEMO.read_text()

    assert "Decision: Qwen3-VL-30B-A3B-Instruct" in text
    assert text.count("Decision: ") == 1
    assert "VLM-3-gpu-spike-2026-07-08.json" in text
    assert "VLM-3-gpu-bakeoff-candidates-2026-07-08.json" in text
    assert "VLM-3-bakeoff-Qwen3-VL-30B-A3B-Instruct-report.json" in text
    assert "License verdict" in text
    assert "pending live OCI bake-off" in text


def test_decision_memo_records_must_right_and_easy_wrong() -> None:
    text = MEMO.read_text()

    assert "Must-Right" in text
    assert "Easy-Wrong" in text
    assert "CPU to GPU speedup" in text
    assert "Do not promote the provisional decision to final" in text
