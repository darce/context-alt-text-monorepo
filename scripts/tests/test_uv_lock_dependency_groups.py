from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_uv_lock_dev_dependency_groups_match_pyproject() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    root_name = pyproject["project"]["name"]
    roots = [package for package in lock.get("package", []) if package.get("name") == root_name]
    assert roots, f"uv.lock has no package named {root_name}"
    assert len(roots) == 1, f"uv.lock has {len(roots)} packages named {root_name}"
    lock_groups = set((roots[0].get("dev-dependencies") or {}).keys())
    py_groups = set((pyproject.get("dependency-groups") or {}).keys())
    assert lock_groups == py_groups, (
        f"uv.lock [package.dev-dependencies] groups {sorted(lock_groups)} "
        f"!= pyproject [dependency-groups] {sorted(py_groups)}"
    )
