"""Regressions for YAML block redaction in deploy diagnostics."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"


def _sanitize_source() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("sanitize_deploy_diagnostic() {")
    end = source.index("\n}\n", start)
    return source[start : end + 2]


def _sanitize(raw: str) -> str:
    result = subprocess.run(
        ["bash", "-c", _sanitize_source() + "\nsanitize_deploy_diagnostic"],
        input=raw,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("password: !!str |\n  opaque-tagged-password-123\n", "opaque-tagged-password-123"),
        (
            "password: &secret-anchor !!str |\n  opaque-anchored-password-123\n",
            "opaque-anchored-password-123",
        ),
        (
            "password: !!str &secret-anchor |\n  opaque-reordered-password-123\n",
            "opaque-reordered-password-123",
        ),
        ("Authorization: |\n  opaque-authorization-123\n", "opaque-authorization-123"),
    ],
)
def test_redacts_yaml_secret_blocks_with_node_properties(raw: str, secret: str) -> None:
    output = _sanitize(raw)
    assert secret not in output, output
    assert "[REDACTED]" in output, output


def test_keeps_nonsecret_yaml_block_contents_visible() -> None:
    output = _sanitize("description: |\n  visible-description-456\n")
    assert "visible-description-456" in output, output

