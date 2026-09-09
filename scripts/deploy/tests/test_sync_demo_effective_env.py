"""RED: sync-demo GPU preflight must read Compose/systemd effective prod/.env.

TEST-15 / RLSE-03: preflight the env Compose actually loads, not a sibling
secrets path. DATA-13: this suite never prints live env contents.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

EFFECTIVE_PROD_ENV = "/opt/acx-backend/prod/.env"
DEMO_ENV = "/opt/acx-backend/demo/secrets/.env"

# Post-preflight stack/edge mutations that must not run when preflight fails.
_STACK_EDGE_MARKERS = (
    "docker-compose.demo.yml",
    "docker-compose.caddy.yml",
    "Caddyfile",
    "docker compose",
    "docker network",
    "systemctl",
    "bootstrap-wp.sh",
    "acx-demo.service",
)

_SSH_SHIM = """\
import json
import sys
from pathlib import Path

log = Path({log!r})
record = {{"tool": "ssh", "argv": sys.argv[1:]}}
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")
# Never exec a real ssh. Fail closed on the GPU preflight so later deploy
# steps cannot run.
if any("--check-reaper" in arg for arg in sys.argv[1:]):
    sys.exit(17)
sys.exit(0)
"""

_SCP_SHIM = """\
import json
import sys
from pathlib import Path

log = Path({log!r})
record = {{"tool": "scp", "argv": sys.argv[1:]}}
log.parent.mkdir(parents=True, exist_ok=True)
with log.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")
# Never exec a real scp and never copy bytes off-box.
sys.exit(0)
"""


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        script = candidate / "scripts" / "deploy" / "sync-demo.sh"
        if script.is_file():
            return candidate
    raise FileNotFoundError("scripts/deploy/sync-demo.sh not found above test file")


def _install_shims(bin_dir: Path, log: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, body in (
        ("ssh", _SSH_SHIM.format(log=str(log))),
        ("scp", _SCP_SHIM.format(log=str(log))),
    ):
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)


def _load_records(log: Path) -> list[dict[str, object]]:
    if not log.is_file():
        return []
    records: list[dict[str, object]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _preflight_tokens(records: list[dict[str, object]]) -> list[str]:
    matches = [
        rec
        for rec in records
        if rec.get("tool") == "ssh"
        and any("--check-reaper" in str(arg) for arg in rec.get("argv", []))
    ]
    assert matches, "preflight ssh with --check-reaper was not invoked"
    assert len(matches) == 1, "GPU preflight must run once"
    argv = [str(arg) for arg in matches[0]["argv"]]  # type: ignore[index]
    remote = argv[-1]
    return shlex.split(remote)


def test_sync_demo_preflight_reads_effective_prod_env(tmp_path: Path) -> None:
    repo_root = _repo_root()
    script = repo_root / "scripts" / "deploy" / "sync-demo.sh"
    assert script.is_file(), f"missing source: {script}"

    bin_dir = tmp_path / "bin"
    log = tmp_path / "argv.jsonl"
    _install_shims(bin_dir, log)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["ACX_DEMO_GPU_PREFLIGHT"] = "1"
    env["OCI_HOST"] = "test-host.invalid"
    env["OCI_USER"] = "test-user"
    env["PLUGIN_ZIP"] = ""
    for key in ("GIT_SSH", "GIT_SSH_COMMAND", "SSH_AUTH_SOCK"):
        env.pop(key, None)

    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    records = _load_records(log)
    tokens = _preflight_tokens(records)
    assert "--check-reaper" in tokens
    reaper_at = tokens.index("--check-reaper")
    producer = tokens[reaper_at + 1]
    demo = tokens[reaper_at + 2]
    assert demo == DEMO_ENV, f"demo env path mismatch: {demo!r}"

    # Intended RED while sync-demo.sh still passes prod/secrets/.env.
    assert producer == EFFECTIVE_PROD_ENV, (
        "effective prod env mismatch: "
        f"expected {EFFECTIVE_PROD_ENV!r}, got {producer!r}; "
        f"exit={result.returncode}"
    )

    assert result.returncode == 4, (
        "preflight failure must abort fail-closed with exit 4; "
        f"got {result.returncode}"
    )
    assert "GPU environment preflight failed" in result.stderr

    joined = "\n".join(
        rec["tool"] + " " + " ".join(str(arg) for arg in rec.get("argv", []))  # type: ignore[operator]
        for rec in records
    )
    for marker in _STACK_EDGE_MARKERS:
        assert marker not in joined, f"post-preflight mutation observed: {marker}"
