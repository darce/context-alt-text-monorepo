"""Tests covering dependency helpers for the roster service."""

from __future__ import annotations

import os

from roster.config import reload_config
from roster.ports.dependencies import get_roster_service, reset_roster_service


def test_get_roster_service_returns_singleton(tmp_path) -> None:
    os.environ["ROSTER_DATA_DIR"] = str(tmp_path)
    reload_config()
    reset_roster_service()
    reload_config()

    first = get_roster_service()
    second = get_roster_service()

    assert first is second

    reset_roster_service()
    third = get_roster_service()
    assert third is not first

    reset_roster_service()
    os.environ.pop("ROSTER_DATA_DIR", None)
    reload_config()
