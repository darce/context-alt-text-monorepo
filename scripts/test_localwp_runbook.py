from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = REPO_ROOT / "apps" / "prototype-wp-alt-context" / "docs" / "localwp-development-runbook.md"


def test_runbook_covers_localwp_gate_secret_flow() -> None:
    text = RUNBOOK.read_text()

    assert "wp-config.local.php" in text
    assert "ACX_RECOGNITION_URL" in text
    assert "ACX_RECOGNITION_API_KEY" in text
    assert "python -m scripts.manage_api_keys create --tenant" in text
    assert "python -m scripts.manage_api_keys revoke --key-id" in text
    assert "bash scripts/localwp-wp.sh" in text
    assert "fingerprint" in text.lower()
