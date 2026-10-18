"""Causal companion regressions using real gates, selectors and unit rendering.

TEST-15 — Prove the green can go red; The Pragmatic Programmer, ch. 9
(SOURCES.md#src-pragmatic-programmer). RES-02 — Timeout on every blocking
call; Release It!, ch. 5 (SOURCES.md#src-release-it).

Only SSH is simulated. No live host, secrets, deployment or source rewrite.
Backend key absence is a supported default, distinct from SSH exit 255.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from conftest import _write_executable

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"
TEMPLATE = SCRIPT.parents[2] / "apps/prototype-description-service/systemd/acx-env.service.template"
DEADLINE = 1
# Existing deadline helper has a one-second termination grace; allow one more
# second for scheduling. The finite six-second fake stall must exceed this.
DEADLINE_WITH_GRACE = DEADLINE + 2
CASES = [
    pytest.param(gate, env, target, id=f"{gate}-{env}-{target}")
    for gate in ("runtime_in_sync", "converge_check")
    for env in ("dev", "prod")
    for target in ("backend", "unit", "admin")
    if target != "admin" or env == "prod"
]


def _probe(tmp_path: Path, gate: str, environment: str, target: str, mode: str):
    topology = tmp_path / "topology"
    (topology / "systemd").mkdir(parents=True)
    shutil.copyfile(TEMPLATE, topology / "systemd/acx-env.service.template")
    for name in (
        "docker-compose.env.yml", "docker-compose.admin.yml",
        "Caddyfile", "docker-compose.caddy.yml",
    ):
        (topology / name).write_text(f"matching fixture {name}\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    events = tmp_path / "ssh.log"
    mutations = tmp_path / "mutations.log"
    connected = tmp_path / "connected"
    _write_executable(
        fake_bin / "ssh",
        r'''#!/usr/bin/env bash
set -euo pipefail
remote=${!#}
case "$remote" in
  "grep -E '^RECOGNITION_SECRET_BACKEND=' '/opt/acx-backend/$PROBE_ENV/.env'"*)
    kind=backend; file= ;;
  "cat '/opt/acx-backend/$PROBE_ENV/docker-compose.env.yml'"*)
    kind=compose; file=docker-compose.env.yml ;;
  "cat '/opt/acx-backend/$PROBE_ENV/docker-compose.admin.yml'"*)
    kind=admin; file=docker-compose.admin.yml ;;
  "cat '/etc/systemd/system/acx-$PROBE_ENV.service'"*)
    kind=unit; file=unit ;;
  "cat '/opt/acx-backend/Caddyfile'"*) kind=edge; file=Caddyfile ;;
  "cat '/opt/acx-backend/docker-compose.caddy.yml'"*)
    kind=edge; file=docker-compose.caddy.yml ;;
  "cd '/opt/acx-backend' && cid="*)
    [[ "$remote" == *"docker inspect"* && "$remote" == *"echo MEMBER"* ]] || exit 98
    kind=membership; file= ;;
  *) printf 'unexpected SSH: %s\n' "$remote" >>"$PROBE_MUTATIONS"; exit 97 ;;
esac
printf '%s %s\n' "$kind" "$remote" >>"$PROBE_EVENTS"
if [[ "$kind" == "$PROBE_TARGET" ]]; then
  case "$PROBE_MODE" in
    stall)
      # Connection/authentication completed. The remote operation then blocks
      # and eventually succeeds with matching bytes: ConnectTimeout cannot
      # enforce the operation deadline, nor can drift reject these bytes.
      date +%s.%N >"$PROBE_CONNECTED"
      sleep 6 ;;
    transport) exit 255 ;;
    missing)
      # The real grep pipeline returns empty success for an absent backend
      # key. Missing cat targets instead return 1 and are topology drift.
      if [[ "$kind" == backend ]]; then exit 0; else exit 1; fi ;;
    healthy) : ;;
    *) exit 98 ;;
  esac
fi
case "$kind" in
  backend) printf 'dotenv\n' ;;
  membership) printf 'MEMBER\n' ;;
  *) cat "$PROBE_TOPOLOGY/$file" ;;
esac
''',
    )
    for tool in ("sudo", "docker", "systemctl", "scp", "rsync", "curl"):
        _write_executable(
            fake_bin / tool,
            '#!/bin/sh\nprintf "%s %s\\n" "$0" "$*" >>"$PROBE_MUTATIONS"\nexit 97\n',
        )
    # Avoid inheriting any host deployment or credential configuration.
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin", "LC_ALL": "C",
        "OCI_USER": "test", "OCI_HOST": "invalid.test",
        "PROBE_ENV": environment, "PROBE_TARGET": target, "PROBE_MODE": mode,
        "PROBE_TOPOLOGY": str(topology), "PROBE_EVENTS": str(events),
        "PROBE_MUTATIONS": str(mutations), "PROBE_CONNECTED": str(connected),
    }
    prelude = (
        f"source {shlex.quote(str(SCRIPT))}\n"
        f"SERVICE_DIR={shlex.quote(str(topology))}\n"
        "GREEN=; YELLOW=; RED=; RESET=\n"
        f"ACX_REMOTE_COMMAND_TIMEOUT={DEADLINE}\nACX_REMOTE_INSPECT_TIMEOUT={DEADLINE}\n"
    )
    # Use the maintained renderer and template to prepare the deployed DEFAULT
    # backend topology. Explicit backend is fixture setup only; both actual
    # gates below invoke the unmodified one-argument render_unit, including SSH.
    prepared = subprocess.run(
        ["bash", "-c", prelude + f"render_unit {environment} ''\n"],
        env=env, text=True, capture_output=True, check=True, timeout=5,
    )
    (topology / "unit").write_text(prepared.stdout)
    assert "{{ENV}}" not in prepared.stdout
    assert f"WorkingDirectory=/opt/acx-backend/{environment}" in prepared.stdout
    assert "\n# ExecStartPre=" in prepared.stdout
    if environment == "prod":
        assert "-f docker-compose.admin.yml" in prepared.stdout
    before = {str(p.relative_to(topology)): p.read_bytes() for p in topology.rglob("*") if p.is_file()}
    driver = tmp_path / "driver.sh"
    driver.write_text(prelude + f"{gate} {environment}\n")
    started = time.monotonic()
    # Safety ceiling only: TimeoutExpired is a test error, never evidence of
    # successful deadline enforcement. Finite fake reads normally exit first.
    result = subprocess.run(
        ["bash", str(driver)], cwd=SCRIPT.parents[2], env=env,
        text=True, capture_output=True, check=False, timeout=15,
    )
    elapsed = time.monotonic() - started
    output = result.stdout + result.stderr
    transcript = (
        f"gate={gate} env={environment} target={target} mode={mode} "
        f"advertised_deadline={DEADLINE}s bounded_grace=2s "
        f"elapsed={elapsed:.3f}s rc={result.returncode}\n"
        f"ssh_reads:\n{events.read_text() if events.exists() else ''}"
        f"output:\n{output}\n"
        f"mutations:\n{mutations.read_text() if mutations.exists() else ''}"
    )
    (tmp_path / "transcript.log").write_text(transcript)
    print(transcript)
    assert events.exists(), transcript
    reads = [line.split(" ", 1)[0] for line in events.read_text().splitlines()]
    assert target in reads, "target read was not exercised: " + transcript
    assert not mutations.exists(), transcript
    assert {str(p.relative_to(topology)): p.read_bytes() for p in topology.rglob("*") if p.is_file()} == before, transcript
    return result, elapsed, output, connected


@pytest.mark.parametrize("gate,environment,target", CASES)
def test_connected_companion_read_obeys_deadline(tmp_path, gate, environment, target):
    result, elapsed, output, connected = _probe(tmp_path, gate, environment, target, "stall")
    assert connected.exists(), "fake SSH never reached the connected operation"
    # Assert latency first so rejection after six seconds cannot mask the gap.
    assert elapsed < DEADLINE_WITH_GRACE, (
        f"{gate}/{environment}/{target}: {elapsed:.3f}s exceeds advertised "
        f"{DEADLINE}s deadline plus 2s termination/scheduling grace; rc={result.returncode}\n{output}"
    )
    assert result.returncode != 0, output
    if gate == "converge_check":
        assert "transport failure" in output, output
        assert "drift:" not in output and "runtime drift detected" not in output, output


@pytest.mark.parametrize("gate,environment,target", CASES)
def test_matching_default_topology_is_healthy_control(tmp_path, gate, environment, target):
    result, _, output, _ = _probe(tmp_path, gate, environment, target, "healthy")
    assert result.returncode == 0, output
    if gate == "converge_check":
        assert "no runtime drift" in output, output


@pytest.mark.parametrize("gate,environment,target", CASES)
def test_companion_transport_failure_refuses_matching_topology(tmp_path, gate, environment, target):
    result, _, output, _ = _probe(tmp_path, gate, environment, target, "transport")
    assert "drift:" not in output and "runtime drift detected" not in output, output
    assert result.returncode != 0, output
    if gate == "converge_check":
        assert "transport failure" in output, output


@pytest.mark.parametrize("gate,environment,target", CASES)
def test_missing_key_default_and_missing_file_drift_controls(tmp_path, gate, environment, target):
    result, _, output, _ = _probe(tmp_path, gate, environment, target, "missing")
    if target == "backend":
        assert result.returncode == 0, output
        if gate == "converge_check":
            assert "no runtime drift" in output, output
    else:
        assert result.returncode != 0, output
        if gate == "converge_check":
            assert "drift:" in output and "runtime drift detected" in output, output
    assert "transport failure" not in output, output
