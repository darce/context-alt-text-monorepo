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

When invoked as a script (``python3 scripts/test_acx_backend_image_contract.py``)
the checks run via ``main()`` and exit non-zero on failure. pytest discovery
still collects the ``test_*`` functions.

The parser is intentionally local (duplicated from
``recognition/tests/dockerfile_stages.py``) so this script runs from the
repo root without importing the service package.
"""

from __future__ import annotations

import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "apps" / "prototype-description-service" / "Dockerfile"
SCRIPTS_DIR = REPO_ROOT / "apps" / "prototype-description-service" / "scripts"
OCI_README = REPO_ROOT / "infra" / "oci" / "README.md"

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

_FROM_RE = re.compile(
    r"^\s*FROM\s+(?P<ref>\S+)(?:\s+AS\s+(?P<name>[\w.-]+))?\s*$",
    re.IGNORECASE,
)


def _parse_dockerfile(
    dockerfile: pathlib.Path,
) -> tuple[dict[str, str], dict[str, str]]:
    stages: dict[str, list[str]] = {}
    bases: dict[str, str] = {}
    current: list[str] | None = None
    for line in pathlib.Path(dockerfile).read_text(encoding="utf-8").splitlines():
        match = _FROM_RE.match(line)
        if match:
            name = match.group("name")
            ref = match.group("ref")
            if name is None:
                current = None
                continue
            current = stages.setdefault(name, [])
            bases[name] = ref
            continue
        if current is not None:
            current.append(line)
    return {name: "\n".join(body) for name, body in stages.items()}, bases


def dockerfile_stages(dockerfile: pathlib.Path) -> dict[str, str]:
    """Ordered ``{stage_name: own_stage_body}`` for every named ``FROM ... AS``.

    Insertion order is the file order, so ``list(stages)[-1]`` is the default
    BuildKit target. Kept local so this script runs from the repo root without
    importing the service package.
    """
    bodies, _ = _parse_dockerfile(dockerfile)
    return bodies


def _resolve_effective(
    own: dict[str, str],
    bases: dict[str, str],
    stage: str,
    stack: frozenset[str] = frozenset(),
) -> str:
    if stage not in own:
        raise KeyError(stage)
    if stage in stack:
        cycle = " -> ".join([*stack, stage])
        raise ValueError(f"Dockerfile stage inheritance cycle: {cycle}")
    own_body = own[stage]
    base = bases.get(stage, "")
    if base in own:
        parent = _resolve_effective(own, bases, base, stack | {stage})
        if parent and own_body:
            return f"{parent}\n{own_body}"
        return parent or own_body
    return own_body


def effective_stage_body(dockerfile: pathlib.Path, stage: str) -> str:
    """Built-image body for ``stage`` (own + inherited parents)."""
    own, bases = _parse_dockerfile(dockerfile)
    assert stage in own, (
        f"Dockerfile missing stage {stage!r}; have {list(own)}"
    )
    return _resolve_effective(own, bases, stage)


def assert_default_target_is_runtime(dockerfile: pathlib.Path = DOCKERFILE) -> None:
    stages = dockerfile_stages(dockerfile)
    assert stages, f"expected named build stages in {dockerfile}"
    last = list(stages)[-1]
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


if __name__ == "__main__":
    raise SystemExit(main())
