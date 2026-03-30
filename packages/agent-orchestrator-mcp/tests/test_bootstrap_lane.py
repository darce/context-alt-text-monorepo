"""Tests for bootstrap_lane.py."""

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
if str(ORCHESTRATION_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATION_DIR))

import bootstrap_lane


@pytest.fixture
def mock_lane_cfg() -> dict:
    return {
        "lane_id": "test-lane",
        "owned_paths": ["apps/my-app", "packages/my-lib"],
    }


def test_bootstrap_empty_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch("bootstrap_lane.get_lane_config", return_value=None):
        result = bootstrap_lane._bootstrap(
            orchestrator_root=tmp_path,
            task_ref="1.0",
            lane_id="test-lane",
            worktree_path=tmp_path / "wt",
        )
    assert result == 1
    captured = capsys.readouterr()
    assert "No lane config found" in captured.out


def test_bootstrap_missing_owned_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with mock.patch("bootstrap_lane.get_lane_config", return_value={"lane_id": "test"}):
        result = bootstrap_lane._bootstrap(
            orchestrator_root=tmp_path,
            task_ref="1.0",
            lane_id="test-lane",
            worktree_path=tmp_path / "wt",
        )
    assert result == 0
    captured = capsys.readouterr()
    assert "Warning: 'owned_paths' not found" in captured.out


def test_bootstrap_copy_php_deps(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    orch_app = orch_root / app_path_rel
    wt_app = wt_path / app_path_rel

    orch_app.mkdir(parents=True)
    (orch_app / "vendor").mkdir()

    wt_app.mkdir(parents=True)
    (wt_app / "composer.json").touch()

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 0
    mock_run.assert_not_called()
    assert (wt_app / "vendor").is_dir()
    assert not (wt_app / "vendor").is_symlink()


def test_bootstrap_install_php_deps(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    # Root vendor missing => run composer install
    orch_app = orch_root / app_path_rel
    orch_app.mkdir(parents=True)

    wt_app = wt_path / app_path_rel
    wt_app.mkdir(parents=True)
    (wt_app / "composer.json").touch()

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 0
    mock_run.assert_called_once_with(
        ["composer", "install", "--no-interaction", "--no-progress"],
        cwd=wt_app,
    )


def test_bootstrap_install_php_deps_failure_propagates(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    wt_app = wt_path / app_path_rel
    wt_app.mkdir(parents=True)
    (wt_app / "composer.json").touch()

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=127)
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 127


def test_bootstrap_copy_js_deps(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    orch_app = orch_root / app_path_rel
    wt_app = wt_path / app_path_rel

    orch_app.mkdir(parents=True)
    (orch_app / "node_modules").mkdir()

    wt_app.mkdir(parents=True)
    (wt_app / "package.json").touch()

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 0
    mock_run.assert_not_called()
    assert (wt_app / "node_modules").is_dir()
    assert not (wt_app / "node_modules").is_symlink()


def test_bootstrap_install_js_deps(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    wt_app = wt_path / app_path_rel
    wt_app.mkdir(parents=True)
    (wt_app / "package.json").touch()

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0)
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 0
    mock_run.assert_called_once_with(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=wt_app,
    )


def test_bootstrap_replaces_shared_js_symlink(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    orch_app = orch_root / app_path_rel
    wt_app = wt_path / app_path_rel

    (orch_app / "node_modules").mkdir(parents=True)
    wt_app.mkdir(parents=True)
    (wt_app / "package.json").touch()
    (wt_app / "node_modules").symlink_to(orch_app / "node_modules", target_is_directory=True)

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 0
    mock_run.assert_not_called()
    assert (wt_app / "node_modules").is_dir()
    assert not (wt_app / "node_modules").is_symlink()


def test_bootstrap_install_js_deps_failure_propagates(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = "apps/my-app"

    wt_app = wt_path / app_path_rel
    wt_app.mkdir(parents=True)
    (wt_app / "package.json").touch()

    with mock.patch("bootstrap_lane.get_lane_config", return_value={"owned_paths": [app_path_rel]}):
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=127)
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "l", wt_path)

    assert result == 127


def test_bootstrap_resolves_app_root_from_globbed_owned_paths(tmp_path: Path) -> None:
    orch_root = tmp_path / "root"
    wt_path = tmp_path / "wt"
    app_path_rel = Path("apps/prototype-wp-alt-context")

    orch_app = orch_root / app_path_rel
    wt_app = wt_path / app_path_rel

    (orch_app / "vendor").mkdir(parents=True)
    (orch_app / "node_modules").mkdir()

    (wt_app / "src").mkdir(parents=True)
    (wt_app / "tests" / "Unit").mkdir(parents=True)
    (wt_app / "composer.json").touch()
    (wt_app / "package.json").touch()

    lane_cfg = {
        "owned_paths": [
            "apps/prototype-wp-alt-context/src/**",
            "apps/prototype-wp-alt-context/tests/Unit/**",
        ],
        "tooling_paths": ["apps/prototype-wp-alt-context/composer.json"],
    }

    with mock.patch("bootstrap_lane.get_lane_config", return_value=lane_cfg):
        with mock.patch("subprocess.run") as mock_run:
            result = bootstrap_lane._bootstrap(orch_root, "1.0", "wp-proxy", wt_path)

    assert result == 0
    mock_run.assert_not_called()
    assert (wt_app / "vendor").is_dir()
    assert not (wt_app / "vendor").is_symlink()
    assert (wt_app / "node_modules").is_dir()
    assert not (wt_app / "node_modules").is_symlink()
