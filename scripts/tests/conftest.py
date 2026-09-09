"""Gates-harness pytest defaults.

This suite does not build ``apps/prototype-wp-alt-context/public/assets/dist``.
Live freshness fails closed unless the operator marks the bundle optional
in the intentionally optional CI job. Collection must not set that bypass.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ADMIN_SOURCE_ROOT_ENV = "ACX_ADMIN_SOURCE_ROOT"
ADMIN_DIST_ROOT_ENV = "ACX_ADMIN_DIST_ROOT"
PACKAGE_DIST_ROOT_ENV = "ACX_PACKAGE_DIST_ROOT"
DIST_ROOT = Path(__file__).resolve().parents[2] / "apps/prototype-wp-alt-context/public/assets/dist"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_admin_bundle: real-tree admin bundle and deploy-zip checks (fail-closed)",
    )


def _using_override_roots() -> bool:
    return any(
        name in os.environ
        for name in (ADMIN_SOURCE_ROOT_ENV, ADMIN_DIST_ROOT_ENV, PACKAGE_DIST_ROOT_ENV)
    )


def _admin_dist_present() -> bool:
    return DIST_ROOT.is_dir() and any(path.is_file() for path in DIST_ROOT.rglob("*"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Keep live-tree checks off the default collection when dist is absent.

    Deselect is not a skip: the fail-closed contract is exercised by the
    subprocess tests that invoke the live nodes with override roots.
    """
    del config
    if _using_override_roots() or _admin_dist_present():
        return
    items[:] = [item for item in items if item.get_closest_marker("live_admin_bundle") is None]
