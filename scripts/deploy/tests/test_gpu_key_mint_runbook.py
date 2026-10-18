from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "gpu-key-mint.md"
MAKEFILE = REPO_ROOT / "Makefile"


def test_gpu_key_mint_runbook_documents_the_local_writer_contract() -> None:
    runbook = RUNBOOK.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")
    combined = runbook + makefile

    for obsolete in (
        "--ssh-target",
        "approved-vm",
        "approved VM",
        "instance-principal writer",
    ):
        assert obsolete not in combined

    assert 'make gpu-key-mint GPU_KEY_MINT_ARGS="--approve-mint"' in runbook
    assert 'GPU_KEY_MINT_ARGS="--approve-mint --rotate"' in runbook
    assert "bash scripts/deploy/gpu-key-mint.sh --approve-mint" in runbook
    assert "ACX_OCI_PYTHON" in runbook
    assert "gtimeout" in runbook
