from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_dev_group_matches_the_committed_lock() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    root = next(package for package in lock["package"] if package["name"] == "context-alt-text-monorepo-root")

    assert project["dependency-groups"]["dev"] == ["prototype-description-service[dev]"]
    assert "service-dev" not in project["dependency-groups"]
    assert root["dev-dependencies"]["dev"] == [{"name": "prototype-description-service", "extra": ["dev"]}]
