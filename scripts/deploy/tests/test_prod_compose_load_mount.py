"""Production GPU snapshot mount and operator-command contract tests."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "apps/prototype-description-service/docker-compose.prod.yml"
ENV_EXAMPLE = ROOT / "apps/prototype-description-service/.env.prod.example"
README = ROOT / "infra/oci/README.md"
CHECK_SCRIPT = ROOT / "scripts/deploy/check-gpu-snapshots.sh"


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _snapshot_check_command() -> str:
    readme = README.read_text(encoding="utf-8")
    commands = re.findall(r"```bash\n(.*?)```", readme, flags=re.DOTALL)
    matches = [command for command in commands if "check-gpu-snapshots.sh" in command]
    assert len(matches) == 1, "README must contain one fenced snapshot-check command"
    return matches[0]


def test_prod_compose_splits_read_only_state_from_writable_load() -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    volumes = api["volumes"]

    assert "${ACX_GPU_SNAPSHOT_DIR}:/run/acx:ro" in volumes
    assert "${ACX_DESCRIBE_LOAD_DIR}:/run/acx-write/prod" in volumes
    assert not any(
        volume.startswith("${ACX_DESCRIBE_LOAD_DIR}:/run/acx-write/prod:")
        and volume.rsplit(":", 1)[-1] == "ro"
        for volume in volumes
    )

    environment = set(api["environment"])
    assert "ACX_DESCRIBE_LOAD_PATH=${ACX_DESCRIBE_LOAD_PATH}" in environment
    assert "ACX_GPU_STATE_STALE_SECONDS=${ACX_GPU_STATE_STALE_SECONDS:-180}" in environment
    assert (
        "ACX_DESCRIBE_LOAD_REFRESH_SECONDS=${ACX_DESCRIBE_LOAD_REFRESH_SECONDS}"
        in environment
    )


def test_prod_env_uses_namespaced_writable_load_directory() -> None:
    env = _env_example()

    assert env["ACX_ENV"] == "prod"
    assert env["ACX_GPU_SNAPSHOT_DIR"] == "/run/acx"
    assert env["ACX_DESCRIBE_LOAD_DIR"] == "/run/acx-write/prod"
    assert env["ACX_DESCRIBE_LOAD_PATH"].startswith("/run/acx-write/prod/")


def test_readme_snapshot_check_command_tracks_checker_environment() -> None:
    command = _snapshot_check_command()
    checker = CHECK_SCRIPT.read_text(encoding="utf-8")

    assert "/run/acx/describe-load.json" not in command
    assert "ACX_DESCRIBE_LOAD_DIR=/run/acx-write/prod" in command
    assert "ACX_DESCRIBE_LOAD_PATH=/run/acx-write/prod/describe-load.json" in command

    documented_keys = set(re.findall(r"^\s*(ACX_[A-Z0-9_]+)=", command, re.MULTILINE))
    checker_keys = set(re.findall(r"\bACX_[A-Z0-9_]+\b", checker))
    assert documented_keys == checker_keys
