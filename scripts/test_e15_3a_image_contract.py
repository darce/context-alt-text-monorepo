"""Image-contract guard for E15-3a-BR-07.

The deployed acx-backend image must include `scripts/` so operators can
run `python -m scripts.manage_api_keys` inside the api container per
the BR-02 task plan and `.env.prod.example`. Originally discovered in
prod when `docker compose exec api python -m scripts.manage_api_keys`
failed with `ModuleNotFoundError: No module named 'scripts'`.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "apps" / "prototype-description-service" / "Dockerfile"
SCRIPTS_DIR = REPO_ROOT / "apps" / "prototype-description-service" / "scripts"

COPY_SCRIPTS = re.compile(r"^COPY\s+scripts/\s+scripts/\s*$", re.MULTILINE)


def test_dockerfile_copies_scripts_into_runtime() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert COPY_SCRIPTS.search(text), (
        "Dockerfile must contain `COPY scripts/ scripts/` so the operator CLI "
        "(scripts/manage_api_keys.py) is reachable in the deployed image. "
        "Without it, `python -m scripts.manage_api_keys` fails with ModuleNotFoundError "
        "in production (E15-3a-BR-07)."
    )


def test_manage_api_keys_module_exists_at_expected_path() -> None:
    cli = SCRIPTS_DIR / "manage_api_keys.py"
    assert cli.is_file(), f"expected {cli} to exist"
