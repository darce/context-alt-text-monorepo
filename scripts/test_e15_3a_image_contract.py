"""Image-contract guard for E15-3a-BR-07 and BR-03 build-arg follow-up.

Two guards live here:

1. BR-07 guard: the deployed acx-backend image must include `scripts/`
   so operators can run `python -m scripts.manage_api_keys` inside the
   api container per the BR-02 task plan and `.env.prod.example`.
   Originally discovered in prod when
   `docker compose exec api python -m scripts.manage_api_keys` failed
   with `ModuleNotFoundError: No module named 'scripts'`.

2. BR-03 follow-up guard: the deployed image must carry its build-time
   git SHA in the `APP_GIT_COMMIT_SHA` environment variable so the
   runtime `/health` and `/version` endpoints (api/main.py) can surface
   a non-"unknown" commit_sha for the plugin-side probe and operator
   forensics. The runtime reader lives at api/main.py line ~70
   (`os.environ.get("APP_GIT_COMMIT_SHA", "")`). The producer side is
   this Dockerfile (`ARG GIT_COMMIT_SHA` + `ENV APP_GIT_COMMIT_SHA`)
   plus the operator deploy command (`docker build --build-arg
   GIT_COMMIT_SHA=$(git rev-parse HEAD) ...`) documented in
   infra/oci/README.md. Without both halves the health-payload ships
   `commit_sha: "unknown"` and BR-03's /version surface provides no
   value to the plugin backend_too_old probe.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "apps" / "prototype-description-service" / "Dockerfile"
SCRIPTS_DIR = REPO_ROOT / "apps" / "prototype-description-service" / "scripts"
OCI_README = REPO_ROOT / "infra" / "oci" / "README.md"

COPY_SCRIPTS = re.compile(r"^COPY\s+scripts/\s+scripts/\s*$", re.MULTILINE)
ARG_GIT_SHA = re.compile(r"^ARG\s+GIT_COMMIT_SHA\b", re.MULTILINE)
ENV_APP_GIT_SHA = re.compile(
    r"^ENV\s+APP_GIT_COMMIT_SHA\s*=\s*\$\{?GIT_COMMIT_SHA\}?\s*$",
    re.MULTILINE,
)
README_BUILD_ARG = re.compile(
    r"docker\s+build(?:[^\n]|\\\n)*--build-arg\s+GIT_COMMIT_SHA=",
)


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


def test_dockerfile_declares_git_commit_sha_build_arg() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert ARG_GIT_SHA.search(text), (
        "Dockerfile must declare `ARG GIT_COMMIT_SHA` so operators can pass "
        "--build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) at build time. "
        "Without it the runtime image cannot surface a real commit_sha via "
        "/health or /version and the BR-03 plugin probe is blind (E15-3a-BR-03 "
        "follow-up)."
    )


def test_dockerfile_exports_app_git_commit_sha_env() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert ENV_APP_GIT_SHA.search(text), (
        "Dockerfile runtime stage must contain "
        "`ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}` so api/main.py's "
        "os.environ.get('APP_GIT_COMMIT_SHA') reader returns the build-time "
        "SHA instead of falling back to 'unknown' (E15-3a-BR-03 follow-up)."
    )


def test_oci_readme_deploy_command_passes_git_commit_sha_build_arg() -> None:
    text = OCI_README.read_text(encoding="utf-8")
    assert README_BUILD_ARG.search(text), (
        "infra/oci/README.md deploy instructions must show `docker build "
        "--build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) ...` so operators "
        "actually populate the build-time SHA. The Dockerfile ARG is inert "
        "without a matching operator-side producer (E15-3a-BR-03 follow-up)."
    )
