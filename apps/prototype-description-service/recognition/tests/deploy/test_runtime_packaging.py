"""E15-33 Slice 2: a missing runtime package fails a test, not a prod boot.

`api/main.py` imports first-party top-level packages unconditionally at import
time (e.g. `scene`). If such a package is absent from the Dockerfile runtime
`COPY` list *or* the `pyproject.toml` `[tool.setuptools.packages.find].include`
list, the image builds but uvicorn dies with `ModuleNotFoundError` at boot
(the `scene/` incident, MAINT-SCENE-DEPLOY-PKG). This guard cross-checks the two
packaging manifests against the actual imports so the omission fails CI instead.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

# recognition/tests/deploy/<this> → parents[3] = the service root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
API_MAIN = SERVICE_ROOT / "api" / "main.py"
DOCKERFILE = SERVICE_ROOT / "Dockerfile"
PYPROJECT = SERVICE_ROOT / "pyproject.toml"


def _first_party_top_level_imports() -> set[str]:
    """Top-level package names imported by api/main.py that are first-party dirs."""
    tree = ast.parse(API_MAIN.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return {name for name in names if (SERVICE_ROOT / name).is_dir()}


def _dockerfile_copied_packages() -> set[str]:
    """Top-level dirs the runtime stage COPYs, e.g. `COPY api/ api/` → {'api'}."""
    pattern = re.compile(r"^\s*COPY\s+([A-Za-z_]\w*)/\s+\1/\s*$")
    return {m.group(1) for line in DOCKERFILE.read_text().splitlines() if (m := pattern.match(line))}


def _pyproject_included_packages() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text())
    include = data["tool"]["setuptools"]["packages"]["find"]["include"]
    return {entry.rstrip("*").rstrip(".") for entry in include}


def test_every_api_main_import_is_packaged() -> None:
    imported = _first_party_top_level_imports()
    assert imported, "expected api/main.py to import first-party packages"

    copied = _dockerfile_copied_packages()
    included = _pyproject_included_packages()

    missing_from_copy = imported - copied
    missing_from_include = imported - included
    assert not missing_from_copy, (
        f"packages imported by api/main.py but missing from the Dockerfile "
        f"runtime COPY list: {sorted(missing_from_copy)}"
    )
    assert not missing_from_include, (
        f"packages imported by api/main.py but missing from pyproject "
        f"[tool.setuptools.packages.find].include: {sorted(missing_from_include)}"
    )


def test_dockerfile_copied_packages_exist() -> None:
    """Reverse guard: a COPY'd package name must be a real top-level dir (typos)."""
    missing = {pkg for pkg in _dockerfile_copied_packages() if not (SERVICE_ROOT / pkg).is_dir()}
    assert not missing, f"Dockerfile COPYs nonexistent top-level dirs: {sorted(missing)}"
