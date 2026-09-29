from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "scripts/deploy/lib/gpu-env-contract.sh"


def decode_env_value(value: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; acx_env_literal_value "$2"',
            "env-contract-test",
            str(CONTRACT),
            value,
        ],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(("envelope", "expected"), [("'p$ss'", "p$ss"), (r"'a\b'", r"a\b")])
def test_single_quoted_dollar_and_backslash_are_literal(envelope: str, expected: str) -> None:
    result = decode_env_value(envelope)

    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


@pytest.mark.parametrize(
    "value",
    [
        "p$ss",
        r"a\b",
        '"p$ss"',
        r'"a\b"',
        "'line\nbreak'",
        "'embedded\rcarriage'",
        "'embedded'quote'",
    ],
)
def test_invalid_env_literal_values_fail(value: str) -> None:
    result = decode_env_value(value)

    assert result.returncode != 0
    assert "ERROR:" in result.stderr
    assert value not in result.stdout + result.stderr
