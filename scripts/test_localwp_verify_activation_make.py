from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "apps" / "prototype-wp-alt-context"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_make(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["make", *args],
        cwd=PLUGIN_DIR,
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )


def _make_fake_wp_runner(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php_bin = bin_dir / "php"
    wp_bin = bin_dir / "wp"

    _write_executable(
        php_bin,
        "#!/bin/sh\n"
        "exec \"$@\"\n",
    )
    _write_executable(
        wp_bin,
        "#!/bin/sh\n"
        "cmd=\"$*\"\n"
        "case \"$cmd\" in\n"
        "  *\"option get siteurl\"*)\n"
        "    echo \"${FAKE_WP_SITE_URL:-http://localhost:10010}\"\n"
        "    exit 0\n"
        "    ;;\n"
        "  *\"plugin deactivate alt-context\"*)\n"
        "    if [ -n \"${FAKE_WP_DEACTIVATE_OUTPUT:-}\" ]; then\n"
        "      echo \"${FAKE_WP_DEACTIVATE_OUTPUT}\"\n"
        "    fi\n"
        "    exit \"${FAKE_WP_DEACTIVATE_EXIT_CODE:-0}\"\n"
        "    ;;\n"
        "  *\"plugin activate alt-context\"*)\n"
        "    python3 -c 'import os, time; time.sleep(float(os.environ.get(\"FAKE_WP_ACTIVATE_SLEEP_SECONDS\", \"0\")))'\n"
        "    if [ -n \"${FAKE_WP_ACTIVATE_OUTPUT:-}\" ]; then\n"
        "      echo \"${FAKE_WP_ACTIVATE_OUTPUT}\"\n"
        "    fi\n"
        "    exit \"${FAKE_WP_ACTIVATE_EXIT_CODE:-0}\"\n"
        "    ;;\n"
        "  *\"plugin is-active alt-context\"*)\n"
        "    exit \"${FAKE_WP_IS_ACTIVE_EXIT_CODE:-0}\"\n"
        "    ;;\n"
        "esac\n"
        "echo \"unexpected wp args: $cmd\" >&2\n"
        "exit 99\n",
    )

    return {
        "HOME": str(tmp_path),
        "LOCALWP_PHP_BIN": str(php_bin),
        "LOCALWP_WP_BIN": str(wp_bin),
        "LOCALWP_WP_DISABLE_PHP84": "1",
    }


def test_localwp_verify_activation_requires_wp_path() -> None:
    result = _run_make(["localwp-verify-activation"])

    assert result.returncode != 0
    combined_output = result.stdout + result.stderr
    assert "WP_PATH is required" in combined_output
    assert "make localwp-verify-activation" in combined_output


def test_localwp_verify_activation_rejects_missing_wp_load(tmp_path: Path) -> None:
    invalid_wp_path = tmp_path / "not-a-wordpress-site"
    invalid_wp_path.mkdir()

    result = _run_make(
        [
            "localwp-verify-activation",
            f"WP_PATH={invalid_wp_path}",
        ]
    )

    assert result.returncode != 0
    combined_output = result.stdout + result.stderr
    assert f"Invalid WP_PATH: {invalid_wp_path} (missing wp-load.php)" in combined_output


def test_make_help_documents_activation_cycle_side_effects() -> None:
    result = _run_make(["help"])

    assert result.returncode == 0, result.stderr
    assert "make localwp-verify-activation - Re-run plugin activation cycle" in result.stdout
    assert "not a dry run" in result.stdout


def test_localwp_verify_activation_uses_subsecond_budget_gate(tmp_path: Path) -> None:
    wp_path = tmp_path / "wp"
    wp_path.mkdir()
    (wp_path / "wp-load.php").write_text("<?php\n")

    env = {
        **_make_fake_wp_runner(tmp_path),
        "FAKE_WP_ACTIVATE_SLEEP_SECONDS": "1.5",
    }

    passing_result = _run_make(
        [
            "localwp-verify-activation",
            f"WP_PATH={wp_path}",
            "ACTIVATION_BUDGET_SECONDS=2.2",
        ],
        env=env,
    )
    failing_result = _run_make(
        [
            "localwp-verify-activation",
            f"WP_PATH={wp_path}",
            "ACTIVATION_BUDGET_SECONDS=1.4",
        ],
        env=env,
    )

    assert passing_result.returncode == 0, passing_result.stdout + passing_result.stderr
    assert "Activation budget: 2.2s" in passing_result.stdout
    assert re.search(r"Plugin activation verified for http://localhost:10010 in \d+\.\d{3}s", passing_result.stdout)
    assert failing_result.returncode != 0
    assert "Plugin activation exceeded budget" in failing_result.stdout + failing_result.stderr


def test_localwp_verify_activation_reports_deactivate_output_on_activate_failure(tmp_path: Path) -> None:
    wp_path = tmp_path / "wp"
    wp_path.mkdir()
    (wp_path / "wp-load.php").write_text("<?php\n")

    env = {
        **_make_fake_wp_runner(tmp_path),
        "FAKE_WP_DEACTIVATE_OUTPUT": "deactivate warning",
        "FAKE_WP_ACTIVATE_OUTPUT": "activate failed",
        "FAKE_WP_ACTIVATE_EXIT_CODE": "7",
    }

    result = _run_make(
        [
            "localwp-verify-activation",
            f"WP_PATH={wp_path}",
        ],
        env=env,
    )

    assert result.returncode != 0
    combined_output = result.stdout + result.stderr
    assert "Plugin activation failed" in combined_output
    assert "activate failed" in combined_output
    assert "Deactivate output" in combined_output
    assert "deactivate warning" in combined_output