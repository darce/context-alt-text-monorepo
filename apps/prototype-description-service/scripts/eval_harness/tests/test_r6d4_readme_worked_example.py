"""S2R5-23 — README worked example must be per-run, not a shared /tmp path."""

from __future__ import annotations

from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


def test_worked_offline_example_uses_mktemp_not_shared_tmp() -> None:
    """S2R5-23: a fixed /tmp/acx-eval-score collides across users on a shared VM.

    mkdir -p on a foreign-owned existing directory returns 0, then the next
    documented command fails Permission denied. WORK=$(mktemp -d) is per-run.
    """
    text = README.read_text(encoding="utf-8")
    start = text.index("### Worked offline example")
    end = text.index("## Hosted provider matrix")
    example = text[start:end]
    assert "WORK=$(mktemp -d)" in example
    assert "/tmp/acx-eval-score" not in example
    assert "$WORK/run.json" in example
    assert "mkdir -p /tmp/" not in example
