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


def test_preflight_accepts_interpolation_markers_inside_single_quoted_value(tmp_path: Path) -> None:
    from test_preflight_gpu_env import run_preflight, valid_demo_env, valid_env

    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_API_KEY"] = "'p$ss #x'"

    result = run_preflight(tmp_path, producer=producer, demo=valid_demo_env())

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("value", ["p$ss", '"p$ss"'])
def test_preflight_still_rejects_interpolation_in_contract_values(tmp_path: Path, value: str) -> None:
    from test_preflight_gpu_env import run_preflight, valid_demo_env, valid_env

    producer = valid_env()
    producer["ACX_GPU_ENDPOINT_API_KEY"] = value

    result = run_preflight(tmp_path, producer=producer, demo=valid_demo_env())

    assert result.returncode != 0
    assert "ERROR [7]" in result.stderr
    assert "interpolation" in result.stderr
