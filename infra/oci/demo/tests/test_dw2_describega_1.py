import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
GATE_SCRIPT = REPO_ROOT / "infra/oci/demo/lib/describe-gate.sh"


def classify(profile: str, readiness: str) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; classify_describe_gate "$2" 100 0 UNKNOWN "$3"',
            "test",
            str(GATE_SCRIPT),
            profile,
            readiness,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def extract_profile(payload: dict[str, object]) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; extract_probed_description_adapter 200 "$2"',
            "test",
            str(GATE_SCRIPT),
            json.dumps({"status": "ok", "description_adapter": payload}),
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_local_cpu_pending_readiness_blocks_gate() -> None:
    readiness = "florence_small|local_cpu|false|false|null|false|false|endpoint_resolution_pending"

    assert classify("florence_small", readiness) == "BLOCK"


@pytest.mark.parametrize("identity_key", ["model_id", "model_version"])
def test_trusted_profile_rejects_whitespace_model_identity(identity_key: str) -> None:
    payload: dict[str, object] = {
        "profile": "gpu_qwen30b",
        "kind": "gpu",
        "endpoint_configured": True,
        "endpoint_allowlisted": True,
        "endpoint_private": True,
        "checked_at": 1789603200.0,
        "fresh": True,
        "usable": True,
        "reason": None,
        "model_id": "model",
        "model_version": "version",
    }
    payload[identity_key] = " \t\n "

    assert extract_profile(payload) == ""
