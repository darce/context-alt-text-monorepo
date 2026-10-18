from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-compose.sh"


def _fake_remote_tools(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Install fake ssh/scp/rsync that log argv and succeed (no real VM)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "tool_argv.log"
    for name in ("ssh", "scp", "rsync"):
        path = bindir / name
        path.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "{name} $*" >> "{log}"\n'
            "if [ -p /dev/stdin ] || [ ! -t 0 ]; then cat >/dev/null; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
        "ENV": "dev-fir",
        "OCI_HOST": "fake-oci-host.example",
        "OCI_USER": "ubuntu",
    }
    env.pop("CONFIRM", None)
    return log, env


def test_g3_04_sync_compose_dev_fir_remote_dir_is_env_basename(
    tmp_path: Path,
) -> None:
    """G3-04: ENV=dev-fir must use remote dir /opt/acx-backend/dev-fir
    (systemd WorkingDirectory templating requires basename == env).
    """
    log, env = _fake_remote_tools(tmp_path)
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + "\n" + (
        log.read_text(encoding="utf-8") if log.is_file() else ""
    )
    assert "/opt/acx-backend/dev-fir" in combined, (
        "sync-compose for ENV=dev-fir must target /opt/acx-backend/dev-fir "
        f"(basename == env); got stdout={result.stdout!r} "
        f"log={log.read_text(encoding='utf-8') if log.is_file() else ''!r}"
    )
    # Guard against collapsing onto the bare dev path.
    assert "/opt/acx-backend/dev/" not in combined.replace(
        "/opt/acx-backend/dev-fir", ""
    ), combined
