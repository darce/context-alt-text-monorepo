"""Pytest entry point for the GPU evidence exporter Bash contract suite."""

from __future__ import annotations

import os
import subprocess
import socket
import sys

import pytest
from pathlib import Path

SUITE = Path(__file__).with_name("test-export-gpu-evidence.sh")
REPO_ROOT = Path(__file__).resolve().parents[3]


def test_export_gpu_evidence_shell_suite() -> None:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    result = subprocess.run(
        ["bash", str(SUITE)],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        # The suite forks a real exporter per scenario and includes a SIGKILL crash case;
        # it takes ~90s on macOS. 30s was sized for the pre-hardening suite.
        timeout=300,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "all assertions passed" in result.stdout, output


@pytest.mark.parametrize("owner", ["remote", "indeterminate", "local_dead"])
def test_existing_lock_is_never_taken_over(tmp_path: Path, owner: str) -> None:
    """An age/PID observation cannot authorize replacing another writer's lock."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_bytes(b"previous evidence")
    lock = tmp_path / "bundle.lock"
    lock.mkdir()
    owner_file = lock / "owner"
    if owner != "indeterminate":
        host = "other-evidence-host" if owner == "remote" else socket.gethostname()
        owner_file.write_text(f"pid=99999999\nhost={host}\nstart_time=1\n")
    before_owner = owner_file.read_bytes() if owner_file.exists() else None
    before_inode = lock.stat().st_ino
    transaction = tmp_path / ".bundle.tmp.other-writer"
    transaction.mkdir()
    (transaction / "payload").write_bytes(b"in-progress evidence")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment["PATH"]
    environment["EVIDENCE_LOCK_MAX_TIME"] = "1"
    environment["OCI_BIN"] = "/usr/bin/false"
    result = subprocess.run(
        ["bash", str((SUITE.parent.parent / "lib/export-gpu-evidence.sh")),
         "--instance-id", "ocid1.instance.example", "--compartment-id", "ocid1.compartment.example",
         "--since", "2026-09-01T00:00:00Z", "--until", "2026-09-01T01:00:00Z", "--out", str(bundle)],
        env=environment, capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode != 0
    assert "timed out waiting for evidence bundle lock" in result.stderr
    assert lock.stat().st_ino == before_inode
    assert (owner_file.read_bytes() if owner_file.exists() else None) == before_owner
    assert (bundle / "manifest.json").read_bytes() == b"previous evidence"
    assert (transaction / "payload").read_bytes() == b"in-progress evidence"
