from __future__ import annotations

import os
import tempfile
import socket
import stat
import subprocess
from pathlib import Path


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


def test_wrapper_filters_known_php85_wp_cli_noise(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    php_bin = bin_dir / "php"
    wp_stable = bin_dir / "wp"
    _write_executable(
        php_bin,
        "#!/bin/sh\n"
        "echo 'PHP Deprecated:  Case statements followed by a semicolon (;) are deprecated, use a colon (:) instead in phar:///tmp/vendor/react/promise/src/functions.php on line 369' 1>&2\n"
        "echo 'Deprecated: Case statements followed by a semicolon (;) are deprecated, use a colon (:) instead in phar:///tmp/vendor/react/promise/src/functions.php on line 369'\n"
        "echo 'PHP Deprecated:  Using null as an array offset is deprecated, use an empty string instead in phar:///tmp/vendor/wp-cli/php-cli-tools/lib/cli/Colors.php on line 95' 1>&2\n"
        "echo 'Deprecated: Using null as an array offset is deprecated, use an empty string instead in phar:///tmp/vendor/wp-cli/php-cli-tools/lib/cli/Colors.php on line 95'\n"
        "echo 'http://localhost:10010'\n",
    )
    _write_executable(wp_stable, "#!/bin/sh\nexit 0\n")

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "option", "get", "siteurl"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": _test_path(bin_dir),
            "LOCALWP_PHP_BIN": str(php_bin),
            "LOCALWP_WP_BIN": str(wp_stable),
            "LOCALWP_WP_DISABLE_PHP84": "1",
            "LOCALWP_WP_FILTER_KNOWN_NOISE": "1",
            "HOME": str(tmp_path),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Case statements followed by a semicolon" not in result.stdout
    assert "Case statements followed by a semicolon" not in result.stderr
    assert "http://localhost:10010" in result.stdout
