"""Unit tests for the api.main startup banner commit-SHA resolution.

E15-3a-BR-20: the startup banner was logging ``Git: unknown (unknown)`` in
the Docker image because ``_log_startup_info`` shells out to ``git rev-parse``
which has no ``.git`` directory inside the container. ``/version`` already
reads the build-arg ``APP_GIT_COMMIT_SHA``; the banner must follow the same
resolution so operator logs carry the real deployed SHA.
"""

from __future__ import annotations

import logging

import pytest

import api.main as main_module


def test_startup_banner_prefers_app_git_commit_sha(monkeypatch, caplog) -> None:
    """When APP_GIT_COMMIT_SHA is set, the banner must report it (not 'unknown')."""
    monkeypatch.setenv("APP_GIT_COMMIT_SHA", "c13e28fc0000000000000000000000000000dead")
    # Simulate the Docker container: git rev-parse fails/returns unknown.
    monkeypatch.setattr(main_module, "_get_git_info", lambda: ("unknown", "unknown"))

    with caplog.at_level(logging.INFO, logger="db.startup"):
        main_module._log_startup_info()

    banner_lines = [rec.getMessage() for rec in caplog.records]
    git_line = next((line for line in banner_lines if line.startswith("Git: ")), None)
    assert git_line is not None, f"no Git banner line found in: {banner_lines}"
    assert "c13e28fc" in git_line, f"expected APP_GIT_COMMIT_SHA in banner, got: {git_line}"
    assert "unknown" not in git_line.split(" (")[0], (
        f"banner commit field must not be 'unknown' when APP_GIT_COMMIT_SHA is set: {git_line}"
    )


def test_startup_banner_falls_back_to_git_rev_parse_when_no_env(monkeypatch, caplog) -> None:
    """Dev path: APP_GIT_COMMIT_SHA unset -> use _get_git_info()."""
    monkeypatch.delenv("APP_GIT_COMMIT_SHA", raising=False)
    monkeypatch.setattr(main_module, "_get_git_info", lambda: ("abc1234", "feature/x"))

    with caplog.at_level(logging.INFO, logger="db.startup"):
        main_module._log_startup_info()

    banner_lines = [rec.getMessage() for rec in caplog.records]
    git_line = next((line for line in banner_lines if line.startswith("Git: ")), None)
    assert git_line is not None
    assert "abc1234" in git_line
    assert "feature/x" in git_line
