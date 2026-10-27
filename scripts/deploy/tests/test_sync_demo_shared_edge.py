"""Shared edge is a read-only prerequisite, never a demo deploy mutation."""
import os
import subprocess
from pathlib import Path

import pytest

from test_sync_demo_preflight import REPO_ROOT, SCRIPT

CONVERGE = "OCI_HOST='test-host.invalid' OCI_USER='test-user' ACX_EDGE_APPLY=1 bash scripts/deploy/recognition-service.sh sync-runtime prod"


def run_deploy(tmp_path, failure=""):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    body = tmp_path / "probe"
    ssh = bin_dir / "ssh"
    ssh.write_text("""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$CALLS"
if [[ "$*" == *'sudo -n timeout -k 5'* ]]; then
  cat > "$BODY"
  case "$FAILURE" in
    sudo) echo 'sudo: a password is required' >&2; exit 1 ;;
    lock_busy) echo 'ERROR: shared edge drift: lock_busy' >&2; exit 75 ;;
    '') exit 0 ;;
    *) echo "ERROR: shared edge drift: $FAILURE" >&2; exit 1 ;;
  esac
fi
if [[ "$*" == *bash* ]]; then cat >> "$CALLS"; fi
""")
    scp = bin_dir / "scp"
    scp.write_text('#!/usr/bin/env bash\nprintf "scp %s\\n" "$*" >> "$CALLS"\n')
    ssh.chmod(0o755)
    scp.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               CALLS=str(log), BODY=str(body), FAILURE=failure, PLUGIN_ZIP="",
               OCI_HOST="test-host.invalid", OCI_USER="test-user",
               ACX_DEMO_GPU_PREFLIGHT="0", LC_ALL="C")
    result = subprocess.run(["bash", str(SCRIPT)], cwd=REPO_ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    return result, log.read_text(), body.read_text() if body.exists() else ""


def test_converged_edge_proceeds_without_edge_writes(tmp_path):
    result, calls, body = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "docker-compose.demo.yml up -d" in calls
    assert "systemctl daemon-reload" in calls
    assert "Caddyfile.new" not in calls
    assert "docker-compose.caddy.yml.new" not in calls
    assert "docker compose -f docker-compose.caddy.yml up" not in calls
    assert "sudo -n timeout -k 5 120 bash -s --" in calls
    assert "Frozen interface (lane impl-portal-shared-helper)" in body
    assert "edge_effective_caddyfile" in body
    assert 'edge_required_networks docker-compose.caddy.yml "$overlay"' in body
    assert "edge_lock_acquire /opt/acx-backend/app/activation.journal.lock 0" in body
    assert 'edge_lock_release "$handle"' in body


@pytest.mark.parametrize("failure", ["caddyfile", "compose", "network:acx-demo-net", "lock_busy", "sudo"])
def test_probe_refuses_before_demo_mutation(tmp_path, failure):
    result, calls, body = run_deploy(tmp_path, failure)
    assert result.returncode != 0
    assert failure in result.stderr
    assert CONVERGE in result.stderr
    assert "chown" not in result.stderr
    for marker in ("scp ", "docker-compose.demo.yml", "bootstrap-wp.sh", "systemctl", "sudo mkdir"):
        assert marker not in calls
    assert body


def test_no_raw_edge_writer():
    source = SCRIPT.read_text()
    for forbidden in ("> Caddyfile", "mv docker-compose.caddy.yml",
                      "docker compose -f docker-compose.caddy.yml up"):
        assert forbidden not in source


@pytest.mark.parametrize("drift", ["", "caddyfile", "compose", "network:portal-net", "network:acx-demo-net", "lock_busy"])
def test_streamed_probe_checks_state_and_releases_lock(tmp_path, drift):
    # Exercise the streamed program itself, keeping the frozen helper mocked at
    # its ABI so this test cannot touch the machine's shared edge.
    import base64
    result, _, body = run_deploy(tmp_path)
    assert result.returncode == 0
    assert "EDGE_PROBE" not in body  # heredoc delimiters are local only
    program = body[body.rindex("\nset -euo pipefail"):]
    live = tmp_path / "live"
    live.mkdir()
    (live / "Caddyfile").write_text("wrong" if drift == "caddyfile" else "base")
    (live / "docker-compose.caddy.yml").write_text("wrong" if drift == "compose" else "compose")
    program = program.replace("/opt/acx-backend", str(live))
    released = tmp_path / "released"
    overrides = """
edge_lock_acquire() {
  [[ "$DRIFT" != lock_busy ]] || return 75
  printf 'handle'
}
edge_lock_release() { printf '%s' "$1" > "$RELEASED"; }
edge_compose_cleanup() { :; }
edge_effective_caddyfile() { cat "$1"; }
edge_compose_args() { EDGE_COMPOSE_ARGV=(-f "$1"); }
edge_required_networks() { printf 'portal-net\\n'; }
docker() {
  if [[ "$1" == compose ]]; then printf 'abcdef123456'; return; fi
  case "$DRIFT" in
    network:portal-net) printf '{"acx-demo-net":{}}' ;;
    network:acx-demo-net) printf '{"portal-net":{}}' ;;
    *) printf '{"portal-net":{},"acx-demo-net":{}}' ;;
  esac
}
"""
    env = dict(os.environ, DRIFT=drift, RELEASED=str(released), LC_ALL="C")
    encoded = [base64.b64encode(value).decode() for value in (b"base", b"compose")]
    checked = subprocess.run(["bash", "-s", "--", *encoded], input=overrides + program,
                             env=env, capture_output=True, text=True, timeout=10)
    assert checked.returncode == (75 if drift == "lock_busy" else 1 if drift else 0), checked.stderr
    if drift:
        assert drift in checked.stderr
    if drift == "lock_busy":
        assert not released.exists()
    else:
        assert released.read_text() == "handle"
