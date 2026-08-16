from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "db-reset-remote.sh"


def _run_db_reset_remote(
    env_overrides: dict[str, str],
    *,
    tmp_path: Path | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run db-reset-remote.sh hermetically with a fake ssh on PATH."""
    env = {**os.environ}
    for key in ("ENV", "CONFIRM", "DRY_RUN", "OCI_HOST", "OCI_USER"):
        env.pop(key, None)
    env.update(env_overrides)

    if tmp_path is not None:
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        ssh = bindir / "ssh"
        ssh.write_text(
            "#!/bin/sh\n"
            "echo \"ssh $*\" >&2\n"
            "exit 99\n",
            encoding="utf-8",
        )
        ssh.chmod(0o755)
        env["PATH"] = f"{bindir}:{env.get('PATH', '')}"

    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *(extra_args or [])],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
        timeout=30,
    )


def test_g3_03_db_reset_remote_dev_fir_dry_run_plan(tmp_path: Path) -> None:
    """G3-03: ENV=dev-fir CONFIRM=RESET DRY_RUN=1 prints the fir identity plan."""
    result = _run_db_reset_remote(
        {"ENV": "dev-fir", "CONFIRM": "RESET", "DRY_RUN": "1"},
        tmp_path=tmp_path,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    out = result.stdout
    assert "acx-dev-fir-postgres-1" in out, out
    assert "acx_dev_fir" in out, out
    assert "alt_context_dev_fir" in out, out
    assert "https://fir.dev.api.altcontext.com/health" in out, out


def test_g3_03_db_reset_remote_dev_fir_refuses_without_confirm(
    tmp_path: Path,
) -> None:
    """G3-03: ENV=dev-fir with wrong/missing CONFIRM must refuse non-zero."""
    missing = _run_db_reset_remote({"ENV": "dev-fir"}, tmp_path=tmp_path)
    assert missing.returncode != 0, missing.stdout
    wrong = _run_db_reset_remote(
        {"ENV": "dev-fir", "CONFIRM": "yes"},
        tmp_path=tmp_path,
    )
    assert wrong.returncode != 0, wrong.stdout


def test_g3_03_db_reset_remote_prod_refused(tmp_path: Path) -> None:
    """G3-03: ENV=prod is refused (SEC-04 — no prod schema-reset path)."""
    result = _run_db_reset_remote(
        {"ENV": "prod", "CONFIRM": "RESET"},
        tmp_path=tmp_path,
    )
    assert result.returncode != 0, result.stdout
