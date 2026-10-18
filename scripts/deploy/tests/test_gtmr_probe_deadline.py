"""Behavioral RED for connected topology reads, without a live SSH host.

RES-02 — Timeout on every blocking call; Release It!, ch. 5
(SOURCES.md#src-release-it). TEST-15 — Prove the green can go red;
The Pragmatic Programmer, ch. 9 (SOURCES.md#src-pragmatic-programmer).
This tests existing topology semantics; dedicated FIR topology design is separate.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

import pytest
from conftest import _write_executable

SCRIPT = Path(__file__).resolve().parents[1] / "recognition-service.sh"
DEADLINE = 1
# The production wrapper allows one second for termination. Leave one further
# second for scheduling, but remain well below the fake read's six-second stall.
DEADLINE_WITH_GRACE = DEADLINE + 2
PROBES = ("runtime-compose", "check-compose", "check-unit", "check-membership")


def _probe(tmp_path: Path, probe: str, mode: str):
    """Source real gates and deadline wrapper; replace only transport/rendering.

    The finite stall is a safety ceiling, not a deadline implementation: the
    assertion must fail if production waits for that ceiling. No test watchdog
    is used to turn a hung gate into an apparent successful rejection.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    topology = tmp_path / "topology"
    topology.mkdir()
    for name in ("docker-compose.env.yml", "Caddyfile", "docker-compose.caddy.yml"):
        (topology / name).write_text(f"healthy {name}\n")
    (topology / "unit").write_text("healthy unit\n")
    before = {p.name: p.read_bytes() for p in topology.iterdir()}
    events = tmp_path / "ssh.log"
    mutations = tmp_path / "mutations.log"
    connected = tmp_path / "connected"
    _write_executable(
        fake_bin / "ssh",
        r'''#!/usr/bin/env bash
set -euo pipefail
remote=${!#}
case "$remote" in
  "cat '/srv/probe/docker-compose.env.yml'"*) kind=compose; file=docker-compose.env.yml ;;
  "cat '/etc/systemd/system/probe.service'"*) kind=unit; file=unit ;;
  "cat '/opt/acx-backend/Caddyfile'"*) kind=edge; file=Caddyfile ;;
  "cat '/opt/acx-backend/docker-compose.caddy.yml'"*) kind=edge; file=docker-compose.caddy.yml ;;
  "cd '/opt/acx-backend' && cid="*)
    [[ "$remote" == *"docker inspect"* && "$remote" == *"echo MEMBER"* ]] || exit 98
    kind=membership; file= ;;
  *) printf 'unexpected SSH: %s\n' "$remote" >>"$PROBE_MUTATIONS"; exit 97 ;;
esac
printf '%s\n' "$kind" >>"$PROBE_EVENTS"
if [[ "$kind" == "$PROBE_TARGET" && "$PROBE_MODE" != healthy ]]; then
  case "$PROBE_MODE" in
    stall)
      # Reached the remote read after connection/authentication, with partial
      # output. ConnectTimeout alone cannot bound this established session.
      date +%s.%N >"$PROBE_CONNECTED"
      printf 'partial remote read\n'
      sleep 6
      exit 255 ;;
    transport) exit 255 ;;
    drift)
      if [[ "$kind" == membership ]]; then printf 'MISSING\n'; else printf 'changed topology\n'; fi
      exit 0 ;;
    missing) exit 1 ;;
    *) exit 98 ;;
  esac
fi
if [[ "$kind" == membership ]]; then printf 'MEMBER\n'; else cat "$PROBE_TOPOLOGY/$file"; fi
''',
    )
    # Any attempted side effect is recorded and refused, including commands
    # mistakenly moved outside SSH by a future gate change.
    for tool in ("sudo", "docker", "systemctl", "scp", "rsync", "curl"):
        _write_executable(
            fake_bin / tool,
            '#!/bin/sh\nprintf "%s %s\\n" "$0" "$*" >>"$PROBE_MUTATIONS"\nexit 97\n',
        )
    gate = "runtime_in_sync" if probe.startswith("runtime") else "converge_check"
    target = probe.split("-", 1)[1]
    driver = tmp_path / "driver.sh"
    driver.write_text(
        f"source {shlex.quote(str(SCRIPT))}\n"
        "OCI_USER=test\nOCI_HOST=invalid.test\nSSH_TARGET=invalid.test\n"
        "GREEN=; YELLOW=; RED=; RESET=\n"
        f"SERVICE_DIR={shlex.quote(str(topology))}\n"
        f"ACX_REMOTE_COMMAND_TIMEOUT={DEADLINE}\nACX_REMOTE_INSPECT_TIMEOUT={DEADLINE}\n"
        "env_to_remote_dir() { printf '/srv/probe'; }\n"
        "env_to_unit() { printf 'probe'; }\n"
        # Rendering normally consults the secret backend. This fixture supplies
        # a known expected unit, avoiding unrelated SSH and credential reads.
        'render_unit() { cat "$PROBE_TOPOLOGY/unit"; }\n'
        f"{gate} dev\n"
    )
    # A small allowlist avoids inherited deployment or credential configuration.
    env = {
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "LC_ALL": "C",
        "PROBE_TARGET": target,
        "PROBE_MODE": mode,
        "PROBE_EVENTS": str(events),
        "PROBE_MUTATIONS": str(mutations),
        "PROBE_CONNECTED": str(connected),
        "PROBE_TOPOLOGY": str(topology),
    }
    started = time.time()
    result = subprocess.run(
        ["bash", str(driver)], env=env, cwd=SCRIPT.parents[2],
        text=True, capture_output=True, check=False, timeout=15,
    )
    finished = time.time()
    elapsed = finished - (float(connected.read_text()) if connected.exists() else started)
    output = result.stdout + result.stderr
    transcript = (
        f"probe={probe} mode={mode} advertised_deadline={DEADLINE}s "
        f"elapsed={elapsed:.3f}s rc={result.returncode}\n"
        f"ssh_reads:\n{events.read_text() if events.exists() else ''}"
        f"output:\n{output}\n"
        f"mutations:\n{mutations.read_text() if mutations.exists() else ''}"
    )
    (tmp_path / "transcript.log").write_text(transcript)
    print(transcript)
    assert events.exists(), "gate never reached fake SSH"
    assert target in events.read_text().splitlines(), "target read was not exercised"
    assert not mutations.exists(), transcript
    assert {p.name: p.read_bytes() for p in topology.iterdir()} == before, transcript
    return result, elapsed, output, connected


@pytest.mark.parametrize("probe", PROBES)
def test_connected_topology_read_obeys_deadline(tmp_path: Path, probe: str) -> None:
    result, elapsed, output, connected = _probe(tmp_path, probe, "stall")
    assert connected.exists(), "fake SSH did not establish the stalled read"
    assert result.returncode != 0, output
    assert elapsed < DEADLINE_WITH_GRACE, (
        f"{probe}: established SSH read exceeded advertised {DEADLINE}s deadline "
        f"plus termination/scheduling grace: {elapsed:.3f}s"
    )
    if probe.startswith("check"):
        assert "transport failure" in output, output
        assert "drift:" not in output and "runtime drift detected" not in output, output


@pytest.mark.parametrize("probe", PROBES)
def test_matching_topology_is_healthy_control(tmp_path: Path, probe: str) -> None:
    result, _, output, _ = _probe(tmp_path, probe, "healthy")
    assert result.returncode == 0, output
    if probe.startswith("check"):
        assert "no runtime drift" in output, output


@pytest.mark.parametrize("probe", PROBES)
def test_transport_failure_is_not_topology_drift(tmp_path: Path, probe: str) -> None:
    result, _, output, _ = _probe(tmp_path, probe, "transport")
    assert result.returncode != 0, output
    if probe.startswith("check"):
        assert "transport failure" in output, output
        assert "drift:" not in output and "runtime drift detected" not in output, output


@pytest.mark.parametrize("probe", PROBES)
def test_completed_read_with_topology_drift_is_rejected(tmp_path: Path, probe: str) -> None:
    result, _, output, _ = _probe(tmp_path, probe, "drift")
    assert result.returncode != 0, output
    if probe.startswith("check"):
        assert "drift:" in output and "runtime drift detected" in output, output
        assert "transport failure" not in output, output


@pytest.mark.parametrize("probe", ("check-compose", "check-unit"))
def test_missing_remote_file_remains_topology_drift(tmp_path: Path, probe: str) -> None:
    result, _, output, _ = _probe(tmp_path, probe, "missing")
    assert result.returncode != 0, output
    assert "drift:" in output and "runtime drift detected" in output, output
    assert "transport failure" not in output, output
