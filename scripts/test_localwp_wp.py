from __future__ import annotations

import os
import shutil
import tempfile
import socket
import stat
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "localwp-wp.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run_plan(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(env)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), "--print-plan"],
        capture_output=True,
        text=True,
        env=merged_env,
        check=False,
    )


def _test_path(bin_dir: Path) -> str:
    return f"{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin"


def test_print_plan_prefers_wp_nightly(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php_bin = bin_dir / "php"
    wp_nightly = bin_dir / "wp-nightly"
    wp_stable = bin_dir / "wp"
    _write_executable(php_bin, "#!/bin/sh\nexit 0\n")
    _write_executable(wp_nightly, "#!/bin/sh\nexit 0\n")
    _write_executable(wp_stable, "#!/bin/sh\nexit 0\n")

    result = _run_plan(
        {
            "PATH": _test_path(bin_dir),
            "LOCALWP_PHP_BIN": str(php_bin),
            "LOCALWP_WP_NIGHTLY_BIN": str(wp_nightly),
            "HOME": str(tmp_path),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "mode=nightly" in result.stdout
    assert f"php_bin={php_bin}" in result.stdout
    assert f"wp_bin={wp_nightly}" in result.stdout


def test_print_plan_prefers_php84_for_stable_wp(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php_bin = bin_dir / "php"
    php84_bin = bin_dir / "php84"
    wp_stable = bin_dir / "wp"
    _write_executable(php_bin, "#!/bin/sh\nexit 0\n")
    _write_executable(php84_bin, "#!/bin/sh\nexit 0\n")
    _write_executable(wp_stable, "#!/bin/sh\nexit 0\n")

    result = _run_plan(
        {
            "PATH": _test_path(bin_dir),
            "LOCALWP_PHP_BIN": str(php_bin),
            "LOCALWP_WP_PHP84_BIN": str(php84_bin),
            # Force stable/php84 selection regardless of a machine-installed wp-nightly.
            "LOCALWP_WP_DISABLE_NIGHTLY": "1",
            "HOME": str(tmp_path),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "mode=php84-stable" in result.stdout
    assert f"php_bin={php84_bin}" in result.stdout
    assert f"wp_bin={wp_stable}" in result.stdout


def test_print_plan_falls_back_to_default_wp(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php_bin = bin_dir / "php"
    wp_stable = bin_dir / "wp"
    _write_executable(php_bin, "#!/bin/sh\nexit 0\n")
    _write_executable(wp_stable, "#!/bin/sh\nexit 0\n")

    result = _run_plan(
        {
            "PATH": _test_path(bin_dir),
            "LOCALWP_PHP_BIN": str(php_bin),
            "LOCALWP_WP_DISABLE_PHP84": "1",
            # Force default selection regardless of a machine-installed wp-nightly.
            "LOCALWP_WP_DISABLE_NIGHTLY": "1",
            "HOME": str(tmp_path),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "mode=default" in result.stdout
    assert f"php_bin={php_bin}" in result.stdout
    assert f"wp_bin={wp_stable}" in result.stdout


def test_print_plan_reports_socket_when_available(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php_bin = bin_dir / "php"
    wp_stable = bin_dir / "wp"
    _write_executable(php_bin, "#!/bin/sh\nexit 0\n")
    _write_executable(wp_stable, "#!/bin/sh\nexit 0\n")

    fd, socket_name = tempfile.mkstemp(prefix="acx-sock-", dir="/tmp")
    os.close(fd)
    os.unlink(socket_name)
    socket_path = Path(socket_name)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(socket_path))
    try:
        result = _run_plan(
            {
                "PATH": _test_path(bin_dir),
                "LOCALWP_PHP_BIN": str(php_bin),
                "LOCALWP_SOCKET": str(socket_path),
                "HOME": str(tmp_path),
            }
        )
    finally:
        sock.close()
        if socket_path.exists():
            socket_path.unlink()

    assert result.returncode == 0, result.stderr
    assert f"socket={socket_path}" in result.stdout


def _require_php() -> str:
    php = shutil.which("php")
    if php is None:
        pytest.skip("no system php available to exercise error_reporting")
    return php


def _php_version_id(php: str) -> int:
    out = subprocess.run([php, "-r", "echo PHP_VERSION_ID;"], capture_output=True, text=True, check=False)
    return int((out.stdout or "0").strip() or "0")


def _run_fake_wp(
    fake_wp: Path,
    php: str,
    tmp_path: Path,
    extra_env: dict[str, str],
    *,
    socket_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the wrapper against a PHP-based fake wp under a hermetic env.

    Ambient LOCALWP_* is stripped so a developer's shell overrides cannot skew
    the run, and nightly/php@8.4 resolution is disabled so the runner is
    deterministically the `default` path (real php + the fake wp) regardless of
    what is installed on the machine."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("LOCALWP_")}
    env.update(
        {
            "LOCALWP_PHP_BIN": php,
            "LOCALWP_WP_BIN": str(fake_wp),
            "LOCALWP_WP_DISABLE_PHP84": "1",
            "LOCALWP_WP_DISABLE_NIGHTLY": "1",
            "HOME": str(tmp_path),
        }
    )
    if socket_path is not None:
        env["LOCALWP_SOCKET"] = str(socket_path)
    env.update(extra_env)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), "option", "get", "siteurl"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_wrapper_suppresses_user_deprecations_at_source(tmp_path: Path) -> None:
    """A userland deprecation the old exact-match sed net never knew is muted at
    the source; an E_ALL control proves suppression (not absence) silences it."""
    php = _require_php()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_wp = bin_dir / "wp"
    _write_executable(
        fake_wp,
        "<?php\n"
        "trigger_error('FAKE_UNLISTED_DEPRECATION_NOISE', E_USER_DEPRECATED);\n"
        "fwrite(STDOUT, \"http://localhost:10010\\n\");\n",
    )

    suppressed = _run_fake_wp(fake_wp, php, tmp_path, {})
    assert suppressed.returncode == 0, suppressed.stderr
    combined = suppressed.stdout + suppressed.stderr
    assert "FAKE_UNLISTED_DEPRECATION_NOISE" not in combined, combined
    assert "http://localhost:10010" in suppressed.stdout

    visible = _run_fake_wp(fake_wp, php, tmp_path, {"LOCALWP_WP_ERROR_REPORTING": "E_ALL"})
    assert "FAKE_UNLISTED_DEPRECATION_NOISE" in (visible.stdout + visible.stderr)


def test_wrapper_mutes_engine_deprecation(tmp_path: Path) -> None:
    """The reported noise is engine E_DEPRECATED (from WP-CLI's phars), which
    trigger_error cannot raise. strlen(null) emits a real engine deprecation on
    PHP >= 8.1; it must be muted by default and surface under E_ALL — this guards
    the ~E_DEPRECATED half of the mask, not just ~E_USER_DEPRECATED."""
    php = _require_php()
    if _php_version_id(php) < 80100:
        pytest.skip("engine null-to-param deprecation requires PHP >= 8.1")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_wp = bin_dir / "wp"
    _write_executable(
        fake_wp,
        "<?php\n"
        "strlen(null);\n"  # engine E_DEPRECATED: "Passing null to parameter ..."
        "fwrite(STDOUT, \"http://localhost:10010\\n\");\n",
    )

    suppressed = _run_fake_wp(fake_wp, php, tmp_path, {})
    assert suppressed.returncode == 0, suppressed.stderr
    combined = suppressed.stdout + suppressed.stderr
    assert "Passing null to parameter" not in combined, combined
    assert "http://localhost:10010" in suppressed.stdout

    visible = _run_fake_wp(fake_wp, php, tmp_path, {"LOCALWP_WP_ERROR_REPORTING": "E_ALL"})
    assert "Passing null to parameter" in (visible.stdout + visible.stderr)


def test_wrapper_suppresses_deprecations_on_socket_branch(tmp_path: Path) -> None:
    """The socket branch of run_wp_inner (used against a live LocalWP mysqld.sock)
    carries its own error_reporting flag; exercise it with a bound socket so a
    regression there cannot pass unnoticed."""
    php = _require_php()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_wp = bin_dir / "wp"
    _write_executable(
        fake_wp,
        "<?php\n"
        "trigger_error('SOCKET_BRANCH_DEPRECATION', E_USER_DEPRECATED);\n"
        "fwrite(STDOUT, \"http://localhost:10010\\n\");\n",
    )

    fd, socket_name = tempfile.mkstemp(prefix="acx-sock-", dir="/tmp")
    os.close(fd)
    os.unlink(socket_name)
    socket_path = Path(socket_name)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(socket_path))
    try:
        result = _run_fake_wp(fake_wp, php, tmp_path, {}, socket_path=socket_path)
    finally:
        sock.close()
        if socket_path.exists():
            socket_path.unlink()

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "SOCKET_BRANCH_DEPRECATION" not in combined, combined
    assert "http://localhost:10010" in result.stdout


def test_wrapper_keeps_real_warnings_visible(tmp_path: Path) -> None:
    """Muting deprecations must not mute warnings/notices/errors."""
    php = _require_php()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_wp = bin_dir / "wp"
    _write_executable(
        fake_wp,
        "<?php\n"
        "trigger_error('A_DEPRECATION_TO_MUTE', E_USER_DEPRECATED);\n"
        "trigger_error('A_REAL_WARNING_TO_KEEP', E_USER_WARNING);\n"
        "fwrite(STDOUT, \"http://localhost:10010\\n\");\n",
    )

    result = _run_fake_wp(fake_wp, php, tmp_path, {})
    combined = result.stdout + result.stderr
    assert "A_DEPRECATION_TO_MUTE" not in combined, combined
    assert "A_REAL_WARNING_TO_KEEP" in combined, combined
    assert "http://localhost:10010" in result.stdout
