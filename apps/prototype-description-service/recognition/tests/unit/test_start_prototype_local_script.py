from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
APP_ROOT = REPO_ROOT / "apps" / "prototype-description-service"


def _copy_start_script(tmp_path: Path) -> Path:
    project_root = tmp_path / "prototype-description-service"
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir(parents=True)
    script_path = scripts_dir / "start_prototype_local.sh"
    shutil.copy2(APP_ROOT / "scripts" / "start_prototype_local.sh", script_path)
    return script_path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_start_prototype_local_uses_project_python_when_offline(tmp_path: Path) -> None:
    script_path = _copy_start_script(tmp_path)
    project_root = script_path.parents[1]
    stub_log = tmp_path / "python-stub.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    project_python = project_root / ".venv" / "bin" / "python"
    project_python.parent.mkdir(parents=True)
    _write_executable(
        project_python,
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${PYTHON_STUB_LOG:?}"
exit 0
""",
    )
    _write_executable(
        fake_bin / "lsof",
        """#!/usr/bin/env bash
exit 1
""",
    )

    env = {
        **os.environ,
        "ASSUME_OFFLINE": "1",
        "CACHE_BASE": str(tmp_path / "cache"),
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "PYTHON_STUB_LOG": str(stub_log),
        "SKIP_DB_CHECK": "1",
        "START_SCAN_WORKER": "0",
    }
    env.pop("PYTHON_BIN", None)

    result = subprocess.run(
        ["bash", str(script_path), "start"],
        cwd=project_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "-m uvicorn api.main:app" in stub_log.read_text()


def test_make_serve_preserves_skip_install_fast_path() -> None:
    makefile = (APP_ROOT / "Makefile").read_text()
    serve_block_match = re.search(r"^serve: dev-ready\n(?P<body>(?:\t.*\n)+)", makefile, re.MULTILINE)

    assert serve_block_match is not None
    assert "SKIP_INSTALL=1" in serve_block_match.group("body")
