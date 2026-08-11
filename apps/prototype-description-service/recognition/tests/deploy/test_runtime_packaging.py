"""E15-33 Slice 2: a missing runtime package fails a test, not a prod boot.

`api/main.py` imports first-party top-level packages unconditionally at import
time (e.g. `scene`). If such a package is absent from the Dockerfile runtime
`COPY` list *or* the `pyproject.toml` `[tool.setuptools.packages.find].include`
list, the image builds but uvicorn dies with `ModuleNotFoundError` at boot
(the `scene/` incident, MAINT-SCENE-DEPLOY-PKG). This guard cross-checks the two
packaging manifests against the actual imports so the omission fails CI instead.

Dockerfile COPY/CMD/ENV claims use the *effective* runtime body
(ORCH-LAUNCH-01 wave-2 inheritance): shared layers live in `runtime-base` and
are inherited by `runtime` / `runtime-vlm`. Own-body-only scans false-negative
when a property is inherited.

Loaders are path-parameterized so the negative tests can prove the guard bites
against synthetic manifests, not just assert the current tree is green.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

from recognition.tests.dockerfile_stages import (
    DEFAULT_RUNTIME_STAGE,
    RUNTIME_BASE_STAGE,
    RUNTIME_VLM_STAGE,
    dockerfile_stages,
    effective_stage_body,
    has_vlm_extra,
    join_continued_lines,
    stage_resolves_vlm_extra,
)

# recognition/tests/deploy/<this> → parents[3] = the service root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
API_MAIN = SERVICE_ROOT / "api" / "main.py"
DOCKERFILE = SERVICE_ROOT / "Dockerfile"
PYPROJECT = SERVICE_ROOT / "pyproject.toml"
ENTRYPOINT_SCRIPT = SERVICE_ROOT / "scripts" / "docker-entrypoint.sh"
ENTRYPOINT_REL = "apps/prototype-description-service/scripts/docker-entrypoint.sh"

_COPY_RE = re.compile(r"^\s*COPY\s+([A-Za-z_]\w*)/\s+\1/\s*$")
_CMD_RE = re.compile(r"^\s*CMD\s+(.+)\s*$")
# Clean form forced by wave-2: decorative argv must not appease substring gates.
_CLEAN_RUNTIME_CMD = 'CMD ["/app/scripts/docker-entrypoint.sh"]'


def _first_party_top_level_imports(main_path: Path = API_MAIN, root: Path = SERVICE_ROOT) -> set[str]:
    """Top-level package names imported by main_path that are first-party dirs."""
    tree = ast.parse(Path(main_path).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return {name for name in names if (Path(root) / name).is_dir()}


def _dockerfile_copied_packages(
    dockerfile: Path = DOCKERFILE,
    *,
    stage: str = DEFAULT_RUNTIME_STAGE,
) -> set[str]:
    """Top-level dirs the named stage's *built image* COPYs (effective body).

    Stage-scoped (RC-02) + inheritance-aware (wave-2): packages COPYd in a
    parent stage (e.g. ``runtime-base``) count for children that ``FROM`` it.
    A package present only in a non-default sibling stage still must not
    satisfy the production runtime packaging contract.
    """
    body = effective_stage_body(dockerfile, stage)
    return {m.group(1) for line in body.splitlines() if (m := _COPY_RE.match(line))}


def _pyproject_included_packages(pyproject: Path = PYPROJECT) -> set[str]:
    """Top-level packages covered by find.include.

    Only a `pkg*` (or bare `pkg`) entry covers the top-level package; a `pkg.*`
    entry packages subpackages *only* and leaves `pkg/__init__.py` out — the
    exact ModuleNotFoundError this guard exists to catch — so it is excluded.
    """
    data = tomllib.loads(Path(pyproject).read_text())
    include = data["tool"]["setuptools"]["packages"]["find"]["include"]
    top: set[str] = set()
    for entry in include:
        if entry.endswith(".*"):
            continue
        top.add(entry[:-1] if entry.endswith("*") else entry)
    return top


def _missing(
    main_path: Path,
    root: Path,
    dockerfile: Path,
    pyproject: Path,
    *,
    stage: str = DEFAULT_RUNTIME_STAGE,
) -> tuple[set[str], set[str]]:
    imported = _first_party_top_level_imports(main_path, root)
    return (
        imported - _dockerfile_copied_packages(dockerfile, stage=stage),
        imported - _pyproject_included_packages(pyproject),
    )


def _cmd_lines(stage_text: str) -> list[str]:
    return [line for line in stage_text.splitlines() if _CMD_RE.match(line)]


def _entrypoint_script_text(path: Path = ENTRYPOINT_SCRIPT) -> str:
    assert path.is_file(), f"missing entrypoint script at {path}"
    return path.read_text(encoding="utf-8")


def _non_comment_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


# ---- positive: the real tree is green -----------------------------------


def test_every_api_main_import_is_packaged() -> None:
    imported = _first_party_top_level_imports()
    assert imported, "expected api/main.py to import first-party packages"
    missing_from_copy, missing_from_include = _missing(API_MAIN, SERVICE_ROOT, DOCKERFILE, PYPROJECT)
    assert not missing_from_copy, f"missing from Dockerfile runtime COPY: {sorted(missing_from_copy)}"
    assert not missing_from_include, f"missing from pyproject include: {sorted(missing_from_include)}"


def test_dockerfile_copied_packages_exist() -> None:
    missing = {
        pkg for pkg in _dockerfile_copied_packages() if not (SERVICE_ROOT / pkg).is_dir()
    }
    assert not missing, f"runtime stage COPYs nonexistent top-level dirs: {sorted(missing)}"


# ---- negative: the guard actually bites on an omission ------------------


def _make_fixture(
    tmp_path: Path,
    *,
    copy_scene: bool,
    include_scene: str | None,
    scene_stage: str = DEFAULT_RUNTIME_STAGE,
    inherit_runtime_from_base: bool = False,
) -> dict[str, Path]:
    (tmp_path / "api").mkdir()
    (tmp_path / "scene").mkdir()
    main = tmp_path / "api" / "main.py"
    main.write_text("import api\nfrom scene.interface_adapters.http.router import router\n")

    runtime_copies = ["COPY api/ api/"]
    vlm_copies = ["COPY api/ api/"]
    base_copies = ["COPY api/ api/"]
    if copy_scene and scene_stage == DEFAULT_RUNTIME_STAGE:
        runtime_copies.append("COPY scene/ scene/")
    if copy_scene and scene_stage == RUNTIME_BASE_STAGE:
        base_copies.append("COPY scene/ scene/")
    if copy_scene and scene_stage == "runtime-vlm":
        vlm_copies.append("COPY scene/ scene/")
    elif copy_scene and scene_stage not in (DEFAULT_RUNTIME_STAGE, RUNTIME_BASE_STAGE):
        vlm_copies.append("COPY scene/ scene/")

    dockerfile = tmp_path / "Dockerfile"
    if inherit_runtime_from_base:
        dockerfile.write_text(
            "FROM x AS builder\n"
            "RUN true\n"
            "\n"
            "FROM x AS runtime-base\n"
            + "\n".join(base_copies)
            + "\n"
            "\n"
            "FROM x AS runtime-vlm\n"
            + "\n".join(vlm_copies)
            + "\n"
            "\n"
            "FROM runtime-base AS runtime\n"
            + "\n".join(
                c for c in runtime_copies if c != "COPY api/ api/" or "COPY api/ api/" not in base_copies
            )
            + "\n"
        )
    else:
        dockerfile.write_text(
            "FROM x AS builder\n"
            "RUN true\n"
            "\n"
            "FROM x AS runtime-vlm\n"
            + "\n".join(vlm_copies)
            + "\n"
            "\n"
            "FROM x AS runtime\n"
            + "\n".join(runtime_copies)
            + "\n"
        )
    include = ['"api*"'] + ([f'"{include_scene}"'] if include_scene else [])
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.setuptools.packages.find]\ninclude = [" + ", ".join(include) + "]\n"
    )
    return {"main": main, "dockerfile": dockerfile, "pyproject": pyproject}


def test_guard_bites_when_scene_missing_from_dockerfile_copy(tmp_path: Path) -> None:
    f = _make_fixture(tmp_path, copy_scene=False, include_scene="scene*")
    missing_copy, missing_include = _missing(f["main"], tmp_path, f["dockerfile"], f["pyproject"])
    assert "scene" in missing_copy
    assert "scene" not in missing_include


def test_guard_bites_when_scene_missing_from_pyproject_include(tmp_path: Path) -> None:
    f = _make_fixture(tmp_path, copy_scene=True, include_scene=None)
    missing_copy, missing_include = _missing(f["main"], tmp_path, f["dockerfile"], f["pyproject"])
    assert "scene" in missing_include
    assert "scene" not in missing_copy


def test_subpackage_only_include_does_not_cover_top_level_package(tmp_path: Path) -> None:
    # BR-09: `scene.*` packages subpackages only — scene/__init__.py is omitted.
    f = _make_fixture(tmp_path, copy_scene=True, include_scene="scene.*")
    _, missing_include = _missing(f["main"], tmp_path, f["dockerfile"], f["pyproject"])
    assert "scene" in missing_include


def test_guard_bites_when_package_copy_only_in_non_default_stage(tmp_path: Path) -> None:
    """RC-02: a COPY only in runtime-vlm must not satisfy the runtime contract.

    Whole-file unions of COPY lines stay green under this mutation — the defect
    that let a second runtime stage ship past these gates.
    """
    f = _make_fixture(
        tmp_path,
        copy_scene=True,
        include_scene="scene*",
        scene_stage="runtime-vlm",
    )
    # Whole-file union (the old behaviour) still sees scene.
    whole_file = {
        m.group(1)
        for line in f["dockerfile"].read_text().splitlines()
        if (m := _COPY_RE.match(line))
    }
    assert "scene" in whole_file, "control: whole-file parser would stay green"

    missing_copy, _ = _missing(f["main"], tmp_path, f["dockerfile"], f["pyproject"])
    assert "scene" in missing_copy, (
        "stage-scoped runtime COPY must reject packages only present in runtime-vlm"
    )


def test_effective_body_sees_copy_inherited_from_runtime_base(tmp_path: Path) -> None:
    """Wave-2: COPY only in runtime-base must satisfy the runtime packaging contract.

    Own-body-only scans miss inherited packages and false-negative on the
    restructured Dockerfile (runtime FROM runtime-base).
    """
    f = _make_fixture(
        tmp_path,
        copy_scene=True,
        include_scene="scene*",
        scene_stage=RUNTIME_BASE_STAGE,
        inherit_runtime_from_base=True,
    )
    own = dockerfile_stages(f["dockerfile"])[DEFAULT_RUNTIME_STAGE]
    assert "COPY scene/ scene/" not in own, "control: scene is not in runtime own body"
    missing_copy, _ = _missing(f["main"], tmp_path, f["dockerfile"], f["pyproject"])
    assert "scene" not in missing_copy, (
        "effective runtime body must count packages COPYd in runtime-base"
    )


def test_entrypoint_cmd_chain_modules_are_copied() -> None:
    """Boot chain lives in docker-entrypoint.sh; CMD must not carry decorative argv.

    Wave-2 / RLSE-02: grepping inert CMD argv tokens is a gate appeased, not met.
    Parse the ordered chain from the real entrypoint script, require a clean CMD
    on the effective runtime body, and keep package/file presence checks.
    """
    script = _entrypoint_script_text()
    lines = _non_comment_lines(script)

    # Ordered boot chain (load-bearing): alembic upgrade → sync → verify → uvicorn.
    alembic_idx = next(
        i for i, ln in enumerate(lines) if ln.startswith("alembic") and "upgrade head" in ln
    )
    sync_idx = next(
        i for i, ln in enumerate(lines) if "python -m scripts.sync_identity_schema" in ln
    )
    verify_idx = next(
        i for i, ln in enumerate(lines) if "python -m scripts.verify_identity_schema" in ln
    )
    uvicorn_idx = next(
        i
        for i, ln in enumerate(lines)
        if ln.startswith("exec uvicorn api.main:app") or ln.startswith("uvicorn api.main:app")
    )
    assert alembic_idx < sync_idx < verify_idx < uvicorn_idx, (
        "entrypoint boot order must be alembic upgrade head → "
        "sync_identity_schema → verify_identity_schema → exec uvicorn; "
        f"got indices {(alembic_idx, sync_idx, verify_idx, uvicorn_idx)} in {lines}"
    )
    assert lines[uvicorn_idx].startswith("exec uvicorn"), (
        "uvicorn must be exec'd so it becomes PID 1"
    )

    # VLM cache verify must be gated on ACX_IMAGE_VARIANT = "vlm" specifically
    # (recognition image must not grow a VLM boot dependency). M7 inversion to
    # = "recognition" must go red — mere presence of any ACX_IMAGE_VARIANT if
    # is not enough (wave-3 / RLSE-02).
    vlm_line_idx = next(
        (i for i, ln in enumerate(lines) if "python -m scripts.verify_vlm_cache" in ln),
        None,
    )
    assert vlm_line_idx is not None, "entrypoint must invoke scripts.verify_vlm_cache for VLM"
    gate_line: str | None = None
    for ln in lines[:vlm_line_idx][::-1]:
        if "ACX_IMAGE_VARIANT" in ln and ("if " in ln or ln.startswith("if")):
            gate_line = ln
            break
        if ln in {"fi", "else", "elif"}:
            break
    assert gate_line is not None, (
        "python -m scripts.verify_vlm_cache must sit inside an "
        "ACX_IMAGE_VARIANT conditional, not run unconditionally"
    )
    # Comparison RHS only: `${VAR:-recognition}` default must not confuse the gate.
    # Good:  [ "${ACX_IMAGE_VARIANT:-recognition}" = "vlm" ]
    # M7:    [ "${ACX_IMAGE_VARIANT:-recognition}" = "recognition" ]
    assert re.search(r"""=\s*["']vlm["']""", gate_line), (
        "verify_vlm_cache gate must compare ACX_IMAGE_VARIANT equal to \"vlm\" "
        f"(got {gate_line!r}); inverted = \"recognition\" ships a VLM boot "
        "dependency on the recognition image (M7)"
    )
    assert not re.search(r"""=\s*["']recognition["']""", gate_line), (
        "verify_vlm_cache must not compare equal to \"recognition\" "
        f"(inverted polarity; got {gate_line!r})"
    )

    # Every python -m scripts.<mod> module package must be COPYd + present on disk.
    copied = _dockerfile_copied_packages()
    for mod in re.findall(r"python -m ([\w.]+)", script):
        pkg, _, leaf = mod.partition(".")
        assert pkg in copied, (
            f"{pkg} not COPYd in effective runtime image but entrypoint runs python -m {mod}"
        )
        assert (SERVICE_ROOT / pkg / f"{leaf}.py").is_file(), f"missing module file for {mod}"

    # Entrypoint must be tracked executable (mode 100755) — non-exec is a boot fail.
    tracked = subprocess.check_output(
        ["git", "ls-files", "-s", "--", ENTRYPOINT_REL],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    assert tracked, f"entrypoint not tracked at {ENTRYPOINT_REL}"
    mode = tracked.split()[0]
    assert mode == "100755", (
        f"entrypoint must be mode 100755 (executable); git ls-files -s reported {mode!r}: {tracked}"
    )

    # Effective runtime CMD must be exactly the entrypoint — no decorative argv.
    # (ol01-img removes gate-appeasement argv in a parallel pass; this assertion
    # is what forces that cleanup — see work item 2 / RLSE-02.)
    runtime_eff = effective_stage_body(DOCKERFILE, DEFAULT_RUNTIME_STAGE)
    cmds = _cmd_lines(runtime_eff)
    assert cmds, "effective runtime body must declare a CMD (inherited or own)"
    assert cmds[-1].strip() == _CLEAN_RUNTIME_CMD, (
        "runtime CMD must be exactly "
        f"{_CLEAN_RUNTIME_CMD!r} with no decorative argv "
        f"(got {cmds[-1]!r}). Boot chain is owned by docker-entrypoint.sh."
    )


# ---- RC-04: stage-scoped assertions that discriminate the current change set -


def test_rc04_runtime_does_not_resolve_vlm_extra_runtime_vlm_does() -> None:
    """runtime must not pull the vlm extra; runtime-vlm must (via builder-vlm).

    Uses COPY --from provenance (RC3): runtime's venv arrives from builder, not
    FROM inheritance, so an effective-body-only scan cannot see builder torch.
    """
    runtime_eff = effective_stage_body(DOCKERFILE, DEFAULT_RUNTIME_STAGE)
    runtime_vlm_eff = effective_stage_body(DOCKERFILE, RUNTIME_VLM_STAGE)
    builder_vlm_eff = effective_stage_body(DOCKERFILE, "builder-vlm")

    assert not stage_resolves_vlm_extra(DOCKERFILE, DEFAULT_RUNTIME_STAGE), (
        "default runtime image must not resolve the vlm extra via own body, "
        "FROM parents, or COPY --from venv edges (torch belongs to VLM path only)"
    )
    assert not has_vlm_extra(runtime_eff), (
        "effective runtime body must not itself declare the vlm extra"
    )
    assert "COPY --from=builder-vlm" not in runtime_eff, (
        "runtime must not COPY the vlm builder venv"
    )
    assert has_vlm_extra(builder_vlm_eff), (
        "builder-vlm effective body must resolve --extra vlm"
    )
    assert stage_resolves_vlm_extra(DOCKERFILE, RUNTIME_VLM_STAGE), (
        "runtime-vlm must resolve the vlm extra via builder-vlm COPY --from"
    )
    assert "COPY --from=builder-vlm" in runtime_vlm_eff, (
        "runtime-vlm must COPY the vlm builder venv (vlm extra resolution path)"
    )


def _uv_sync_commands(stage_text: str) -> list[str]:
    """Logical RUN/command lines that invoke ``uv sync`` (comments ignored)."""
    cmds: list[str] = []
    for ln in join_continued_lines(stage_text):
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.search(r"\buv\s+sync\b", stripped):
            cmds.append(stripped)
    return cmds


def test_rc04_uv_sync_uses_locked_not_frozen() -> None:
    """RB-07: every uv sync must use --locked (not --frozen)."""
    stages = dockerfile_stages(DOCKERFILE)
    for name in ("builder", "builder-vlm"):
        cmds = _uv_sync_commands(stages[name])
        assert cmds, f"{name} must invoke uv sync"
        for cmd in cmds:
            assert "--locked" in cmd, (
                f"{name} uv sync must use --locked (RB-07); got: {cmd}"
            )
            assert "--frozen" not in cmd, (
                f"{name} must not use --frozen; --locked is required so "
                f"lock/pyproject skew fails the build (RB-07). Got: {cmd}"
            )


def test_rc04_user_acx_only_on_runtime_vlm() -> None:
    """RB-03 as shipped: runtime-vlm drops to USER acx; runtime does not."""
    runtime_eff = effective_stage_body(DOCKERFILE, DEFAULT_RUNTIME_STAGE)
    runtime_vlm_eff = effective_stage_body(DOCKERFILE, RUNTIME_VLM_STAGE)
    assert re.search(r"^\s*USER\s+acx\s*$", runtime_vlm_eff, re.MULTILINE), (
        "runtime-vlm effective body must declare USER acx"
    )
    assert not re.search(r"^\s*USER\s+acx\s*$", runtime_eff, re.MULTILINE), (
        "runtime must not declare USER acx (RB-03 privilege drop deferred)"
    )


def test_rc04_no_volume_instruction_anywhere() -> None:
    """RA-10: no VOLUME instruction anywhere in the Dockerfile."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    # Match instruction lines only — comments mentioning VOLUME are fine.
    hits = [
        ln
        for ln in text.splitlines()
        if re.match(r"^\s*VOLUME\b", ln, re.IGNORECASE)
    ]
    assert not hits, f"Dockerfile must not declare VOLUME (RA-10); found: {hits}"


def test_rc04_no_transformers_cache_env_anywhere() -> None:
    """BR-04: TRANSFORMERS_CACHE must not appear (deprecated; use HF_HOME)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    # Instruction / assignment forms — prose in comments is allowed only if the
    # token is not an active ENV. Flag any non-comment occurrence.
    active = [
        ln
        for ln in text.splitlines()
        if "TRANSFORMERS_CACHE" in ln and not ln.lstrip().startswith("#")
    ]
    assert not active, (
        "TRANSFORMERS_CACHE must not be set (BR-04); use HF_HOME/HF_HUB_CACHE. "
        f"Found: {active}"
    )


def _chown_mentions_path(stage_text: str, path: str) -> bool:
    """True when a chown *instruction* (possibly continued) targets ``path``.

    Comments that mention a hypothetical ``chown ... /app`` (the deliberate
    RB-03 deviation note) must not trip the gate.
    """
    for ln in join_continued_lines(stage_text):
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not re.search(r"\bchown\b", stripped):
            continue
        # Paths are not \w-bounded (`\b/app` fails); match as a shell token.
        if re.search(rf"(?<![\w.-]){re.escape(path)}(?![\w.-])", stripped):
            return True
    return False


def test_rc04_runtime_base_acx_user_and_cache_chown_only() -> None:
    """runtime-base creates uid 10001 acx, chowns /data/cache, not /app or /opt/venv."""
    own = dockerfile_stages(DOCKERFILE)[RUNTIME_BASE_STAGE]
    joined = "\n".join(join_continued_lines(own))
    assert re.search(r"useradd\b[^\n]*-u\s+10001\b[^\n]*\bacx\b", joined) or re.search(
        r"useradd\b[^\n]*\bacx\b[^\n]*-u\s+10001\b", joined
    ), "runtime-base must create user acx with uid 10001"
    assert _chown_mentions_path(own, "/data/cache"), (
        "runtime-base must chown /data/cache for the unprivileged cache writes"
    )
    # Deliberate RB-03 deviation: do NOT chown /app or /opt/venv to acx.
    for path in ("/app", "/opt/venv"):
        assert not _chown_mentions_path(own, path), (
            f"runtime-base must NOT chown {path} (deliberate RB-03 deviation; "
            "a helpful chown -R would hand code/venv write access to acx)"
        )


# ---- RC-04 / inheritance negative mutations (TEST-15) --------------------


def test_guard_bites_when_runtime_inherits_vlm_extra(tmp_path: Path) -> None:
    """Mutation: runtime FROM a stage that uv-syncs --extra vlm must go red."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS builder\n"
        "RUN uv sync --locked --extra vlm\n"
        "\n"
        "FROM builder AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
        encoding="utf-8",
    )
    assert has_vlm_extra(effective_stage_body(df, DEFAULT_RUNTIME_STAGE))
    assert stage_resolves_vlm_extra(df, DEFAULT_RUNTIME_STAGE)


def test_guard_bites_when_runtime_copies_venv_from_vlm_builder(tmp_path: Path) -> None:
    """Wave-3 RC3: COPY --from a vlm-resolving stage contaminates runtime."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS builder\n"
        "RUN uv sync --locked --extra=vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY --from=builder /opt/venv /opt/venv\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
        encoding="utf-8",
    )
    # Effective body alone is blind to COPY --from contamination.
    assert not has_vlm_extra(effective_stage_body(df, DEFAULT_RUNTIME_STAGE))
    assert stage_resolves_vlm_extra(df, DEFAULT_RUNTIME_STAGE)


def test_guard_bites_when_entrypoint_variant_gate_is_inverted(tmp_path: Path) -> None:
    """Wave-3 M7: ACX_IMAGE_VARIANT = \"recognition\" must fail the polarity check."""
    script = (
        "#!/bin/sh\n"
        "set -eu\n"
        "alembic -c db/alembic.ini upgrade head\n"
        "python -m scripts.sync_identity_schema\n"
        "python -m scripts.verify_identity_schema\n"
        'if [ "${ACX_IMAGE_VARIANT:-recognition}" = "recognition" ]; then\n'
        "  python -m scripts.verify_vlm_cache\n"
        "fi\n"
        "exec uvicorn api.main:app --host 0.0.0.0 --port 8000\n"
    )
    lines = _non_comment_lines(script)
    vlm_line_idx = next(
        i for i, ln in enumerate(lines) if "python -m scripts.verify_vlm_cache" in ln
    )
    gate_line = next(
        ln
        for ln in lines[:vlm_line_idx][::-1]
        if "ACX_IMAGE_VARIANT" in ln and ("if " in ln or ln.startswith("if"))
    )
    # Inverted polarity: comparison RHS is recognition — production gate must reject.
    assert re.search(r'=\s*["\']recognition["\']', gate_line)
    assert not re.search(r'=\s*["\']vlm["\']', gate_line)


def test_guard_bites_when_uv_sync_uses_frozen(tmp_path: Path) -> None:
    """Mutation: --frozen instead of --locked must be detectable as RB-07 fail."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS builder\n"
        "# comment may mention --frozen without failing the gate\n"
        "RUN uv sync --frozen --no-dev --extra bench --no-install-project\n"
        "\n"
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --frozen --no-dev --extra bench --extra vlm --no-install-project\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN true\n",
        encoding="utf-8",
    )
    cmds = _uv_sync_commands(dockerfile_stages(df)["builder"])
    assert cmds and all("--frozen" in c for c in cmds)
    assert all("--locked" not in c for c in cmds)


def test_guard_bites_when_runtime_gains_user_acx(tmp_path: Path) -> None:
    """Mutation: USER acx on runtime (effective) violates the RB-03 deferral."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime-base\n"
        "RUN useradd -u 10001 acx && mkdir -p /data/cache && chown acx:acx /data/cache\n"
        "USER acx\n"
        "\n"
        "FROM runtime-base AS runtime-vlm\n"
        "ENV ACX_IMAGE_VARIANT=vlm\n"
        "\n"
        "FROM runtime-base AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
        encoding="utf-8",
    )
    assert re.search(
        r"^\s*USER\s+acx\s*$",
        effective_stage_body(df, DEFAULT_RUNTIME_STAGE),
        re.MULTILINE,
    )


def test_guard_bites_when_volume_instruction_added(tmp_path: Path) -> None:
    """Mutation: any VOLUME instruction is RA-10."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime\n"
        "VOLUME /data/cache\n",
        encoding="utf-8",
    )
    hits = [
        ln
        for ln in df.read_text().splitlines()
        if re.match(r"^\s*VOLUME\b", ln, re.IGNORECASE)
    ]
    assert hits


def test_guard_bites_when_transformers_cache_env_set(tmp_path: Path) -> None:
    """Mutation: active TRANSFORMERS_CACHE env is BR-04."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime\n"
        "ENV TRANSFORMERS_CACHE=/data/cache/transformers\n",
        encoding="utf-8",
    )
    active = [
        ln
        for ln in df.read_text().splitlines()
        if "TRANSFORMERS_CACHE" in ln and not ln.lstrip().startswith("#")
    ]
    assert active


def test_guard_bites_when_runtime_base_chowns_app(tmp_path: Path) -> None:
    """Mutation: chown /app (or /opt/venv) in runtime-base must be rejected."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime-base\n"
        "RUN groupadd -r acx && useradd -r -g acx -u 10001 acx \\\n"
        "    && mkdir -p /data/cache && chown acx:acx /data/cache \\\n"
        "    && chown -R acx:acx /app /opt/venv\n"
        "\n"
        "FROM runtime-base AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
        encoding="utf-8",
    )
    own = dockerfile_stages(df)[RUNTIME_BASE_STAGE]
    assert _chown_mentions_path(own, "/app")
    assert _chown_mentions_path(own, "/opt/venv")


def test_guard_bites_on_stage_inheritance_cycle(tmp_path: Path) -> None:
    """Cycle in FROM graph must raise rather than recurse forever."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS a\n"
        "RUN true\n"
        "\n"
        "FROM a AS b\n"
        "RUN true\n"
        "\n"
        "FROM b AS a\n"
        "RUN true\n",
        encoding="utf-8",
    )
    # Last definition of `a` wins in our setdefault? setdefault keeps first body's
    # list object but bases[name] is overwritten on each FROM — last base wins.
    # Either way resolution of a stage that points at a cycle must raise.
    import pytest

    # Rewrite with a true cycle a→b→a via distinct names without redefinition:
    df.write_text(
        "FROM python:3.12-slim AS a\n"
        "RUN echo a\n"
        "\n"
        "FROM a AS b\n"
        "RUN echo b\n",
        encoding="utf-8",
    )
    # Manually poke bases to create a cycle without invalid Dockerfile redef.
    from recognition.tests import dockerfile_stages as ds

    own = {"a": "RUN echo a", "b": "RUN echo b"}
    bases = {"a": "b", "b": "a"}
    with pytest.raises(ValueError, match="cycle"):
        ds._resolve_effective(own, bases, "a")


def test_guard_bites_when_cmd_has_decorative_argv(tmp_path: Path) -> None:
    """Mutation: decorative CMD argv (gate-appeasement tokens) must fail clean CMD."""
    df = tmp_path / "Dockerfile"
    df.write_text(
        "FROM python:3.12-slim AS runtime-base\n"
        'CMD ["/app/scripts/docker-entrypoint.sh", "alembic", "uvicorn api.main:app"]\n'
        "\n"
        "FROM runtime-base AS runtime\n"
        "ENV ACX_IMAGE_VARIANT=recognition\n",
        encoding="utf-8",
    )
    cmds = _cmd_lines(effective_stage_body(df, DEFAULT_RUNTIME_STAGE))
    assert cmds
    assert cmds[-1].strip() != _CLEAN_RUNTIME_CMD
