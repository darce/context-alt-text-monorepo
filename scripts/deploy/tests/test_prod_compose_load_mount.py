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

# Compose template token the checker matches literally, not an operator input.
_LITERAL_ONLY_CHECKER_TOKENS = frozenset({"ACX_ENV"})


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


def _checker_input_keys(checker: str) -> set[str]:
    """Environment variables ``check-gpu-snapshots.sh`` actually reads.

    Only assignment-form dereferences (``var=${ACX_FOO:-...}``) are operator
    inputs. A bare ``${ACX_ENV}`` is a single-quoted compose template token the
    checker compares against, never a value it reads from the environment.
    """
    assigned = set(re.findall(r"^\s*\w+=\$\{(ACX_[A-Z0-9_]+)", checker, re.MULTILINE))
    dereferenced = set(re.findall(r"\$\{(ACX_[A-Z0-9_]+)[:}]", checker))
    unexplained = dereferenced - assigned - _LITERAL_ONLY_CHECKER_TOKENS
    assert not unexplained, f"checker reads undocumented inputs: {sorted(unexplained)}"
    return assigned


def test_readme_snapshot_check_command_tracks_checker_environment() -> None:
    command = _snapshot_check_command()
    checker = CHECK_SCRIPT.read_text(encoding="utf-8")

    assert "/run/acx/describe-load.json" not in command
    # The units aggregate the /run/acx-write parent; a per-environment value
    # here fails the checker's lifecycle-agreement assertion.
    assert re.search(r"^\s*ACX_DESCRIBE_LOAD_DIR=/run/acx-write(?=\s)", command, re.MULTILINE)
    assert re.search(r"^\s*ACX_GPU_UNIT_LOAD_DIR=/run/acx-write(?=\s)", command, re.MULTILINE)
    assert (
        "ACX_GPU_COMPOSE_FILE=apps/prototype-description-service/docker-compose.env.yml"
        in command
    )

    documented_keys = set(re.findall(r"^\s*(ACX_[A-Z0-9_]+)=", command, re.MULTILINE))
    assert documented_keys == _checker_input_keys(checker)
