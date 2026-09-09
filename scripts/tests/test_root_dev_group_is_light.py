from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_dev_group_does_not_install_service_runtime() -> None:
    payload = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = payload["dependency-groups"]["dev"]
    joined = " ".join(dev)
    assert "prototype-description-service" not in joined
    assert "prototype-description-service[dev]" in " ".join(payload["dependency-groups"]["service-dev"])
