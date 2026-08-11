"""E15-33 Slice 2: a missing runtime package fails a test, not a prod boot.

`api/main.py` imports first-party top-level packages unconditionally at import
time (e.g. `scene`). If such a package is absent from the Dockerfile runtime
`COPY` list *or* the `pyproject.toml` `[tool.setuptools.packages.find].include`
list, the image builds but uvicorn dies with `ModuleNotFoundError` at boot
(the `scene/` incident, MAINT-SCENE-DEPLOY-PKG). This guard cross-checks the two
packaging manifests against the actual imports so the omission fails CI instead.

Dockerfile COPY claims are scoped to the default `runtime` stage
(ORCH-LAUNCH-01-S1-RC-02): whole-file unions of COPY lines stay green when a
second stage (e.g. `runtime-vlm`) duplicates the list, which is exactly how the
torch-bearing default-target flip shipped past these gates.

Loaders are path-parameterized so the negative tests can prove the guard bites
against synthetic manifests, not just assert the current tree is green.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from recognition.tests.dockerfile_stages import (
    DEFAULT_RUNTIME_STAGE,
    dockerfile_stages,
)

# recognition/tests/deploy/<this> → parents[3] = the service root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
API_MAIN = SERVICE_ROOT / "api" / "main.py"
DOCKERFILE = SERVICE_ROOT / "Dockerfile"
PYPROJECT = SERVICE_ROOT / "pyproject.toml"

_COPY_RE = re.compile(r"^\s*COPY\s+([A-Za-z_]\w*)/\s+\1/\s*$")


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
    """Top-level dirs the named stage COPYs, e.g. `COPY api/ api/` → {'api'}.

    Stage-scoped (RC-02): a package present only in a non-default stage must not
    satisfy the production runtime packaging contract.
    """
    stages = dockerfile_stages(dockerfile)
    body = stages.get(stage, "")
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
) -> dict[str, Path]:
    (tmp_path / "api").mkdir()
    (tmp_path / "scene").mkdir()
    main = tmp_path / "api" / "main.py"
    main.write_text("import api\nfrom scene.interface_adapters.http.router import router\n")

    runtime_copies = ["COPY api/ api/"]
    vlm_copies = ["COPY api/ api/"]
    if copy_scene and scene_stage == DEFAULT_RUNTIME_STAGE:
        runtime_copies.append("COPY scene/ scene/")
    if copy_scene and scene_stage == "runtime-vlm":
        vlm_copies.append("COPY scene/ scene/")
    elif copy_scene and scene_stage != DEFAULT_RUNTIME_STAGE:
        # Non-default stage that is not runtime-vlm: still put scene there only.
        vlm_copies.append("COPY scene/ scene/")

    dockerfile = tmp_path / "Dockerfile"
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


def test_entrypoint_cmd_chain_modules_are_copied() -> None:
    # BR2-05: the CMD chain (alembic → sync → verify → uvicorn) and every
    # `python -m scripts.<mod>` it invokes must be runnable from the image:
    # ordered chain present, and each -m module's package COPYd + file present.
    runtime = dockerfile_stages(DOCKERFILE)[DEFAULT_RUNTIME_STAGE]
    cmd = next(line for line in runtime.splitlines() if line.startswith("CMD"))
    chain = [
        "alembic",
        "scripts.sync_identity_schema",
        "scripts.verify_identity_schema",
        "uvicorn api.main:app",
    ]
    for a, b in zip(chain, chain[1:], strict=False):
        assert cmd.index(a) < cmd.index(b), cmd

    copied = _dockerfile_copied_packages()
    for mod in re.findall(r"python -m ([\w.]+)", cmd):
        pkg, _, leaf = mod.partition(".")
        assert pkg in copied, f"{pkg} not COPYd in runtime but CMD runs python -m {mod}"
        assert (SERVICE_ROOT / pkg / f"{leaf}.py").is_file(), f"missing module file for {mod}"
