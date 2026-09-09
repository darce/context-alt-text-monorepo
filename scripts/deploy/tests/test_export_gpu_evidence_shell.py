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


@pytest.mark.parametrize("restore_fails", [False, True])
def test_term_during_publication_preserves_previous_bundle(tmp_path: Path, restore_fails: bool) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_bytes(b"previous evidence")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_oci = fake_bin / "oci"
    fake_oci.write_text("#!/bin/bash\ncase \" $* \" in\n*' compute instance get '*) printf '%s\\n' '{\"data\":{\"id\":\"ocid1.instance.example\",\"compartment-id\":\"ocid1.compartment.example\",\"lifecycle-state\":\"STOPPED\"}}';;\n*) printf '%s\\n' '{\"data\":[]}' ;;\nesac\n")
    fake_oci.chmod(0o755)
    fake_mv = fake_bin / "mv"
    fake_mv.write_text(r"""#!/bin/bash
set -eu
[[ "${1:-}" != -- ]] || shift
if [[ "$1" == */previous && "$RESTORE_FAILS" == 1 ]]; then
    exit 74
fi
/bin/mv "$@"
if [[ "$1" == "$SIGNAL_BUNDLE" ]]; then
    kill -TERM "$PPID"
fi
""")
    fake_mv.chmod(0o755)
    environment = os.environ.copy()
    environment.update({
        "PATH": str(fake_bin) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + environment["PATH"],
        "OCI_BIN": str(fake_oci), "SIGNAL_BUNDLE": str(bundle),
        "RESTORE_FAILS": "1" if restore_fails else "0",
    })
    args = ["bash", str(SUITE.parent.parent / "lib/export-gpu-evidence.sh"),
            "--instance-id", "ocid1.instance.example", "--compartment-id", "ocid1.compartment.example",
            "--since", "2026-09-01T00:00:00Z", "--until", "2026-09-01T01:00:00Z", "--out", str(bundle)]
    result = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode != 0, result.stdout + result.stderr
    if restore_fails:
        transactions = list(tmp_path.glob(".bundle.tmp.*"))
        assert len(transactions) == 1, result.stderr
        assert (transactions[0] / "previous/manifest.json").read_bytes() == b"previous evidence"
        assert (transactions[0] / ".publish-intent").is_file()
        # A subsequent writer restores the preserved backup before its OCI failure.
        environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
        environment["OCI_BIN"] = "/usr/bin/false"
        recovered = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=20, check=False)
        assert recovered.returncode != 0
    assert (bundle / "manifest.json").read_bytes() == b"previous evidence"
    assert not list(tmp_path.glob(".bundle.tmp.*"))


@pytest.mark.parametrize("fault", ["none", "artifact", "publish_parent"])
def test_publication_durability_barriers(tmp_path: Path, fault: str) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_bytes(b"previous evidence")
    fake_oci = tmp_path / "oci"
    fake_oci.write_text("#!/bin/bash\ncase \" $* \" in\n*' compute instance get '*) printf '%s\\n' '{\"data\":{\"id\":\"ocid1.instance.example\",\"compartment-id\":\"ocid1.compartment.example\",\"lifecycle-state\":\"STOPPED\"}}';;\n*) printf '%s\\n' '{\"data\":[]}' ;;\nesac\n")
    fake_oci.chmod(0o755)
    log = tmp_path / "barriers.log"
    # Instrument the real fsync calls without requiring a storage-crash emulator.
    (tmp_path / "sitecustomize.py").write_text(r"""
import os
from pathlib import Path
_original_open, _original_fsync = os.open, os.fsync
_paths = {}
def traced_open(path, *args, **kwargs):
    fd = _original_open(path, *args, **kwargs)
    _paths[fd] = str(path)
    return fd
def traced_fsync(fd):
    path = _paths.get(fd, "")
    bundle = Path(os.environ["DURABILITY_BUNDLE"])
    with open(os.environ["DURABILITY_LOG"], "a") as log:
        log.write(path + "\n")
    fault = os.environ["DURABILITY_FAULT"]
    if fault == "artifact" and path.endswith("/manifest.json"):
        raise OSError("injected artifact fsync failure")
    if fault == "publish_parent" and path == str(bundle.parent) and (bundle / "manifest.json").exists() and (bundle / "manifest.json").read_bytes() != b"previous evidence":
        raise OSError("injected publication parent fsync failure")
    return _original_fsync(fd)
os.open, os.fsync = traced_open, traced_fsync
""")
    environment = os.environ.copy()
    environment.update({"PATH": str(Path(sys.executable).parent) + os.pathsep + environment["PATH"],
                        "PYTHONPATH": str(tmp_path), "OCI_BIN": str(fake_oci),
                        "DURABILITY_LOG": str(log), "DURABILITY_BUNDLE": str(bundle), "DURABILITY_FAULT": fault})
    args = ["bash", str(SUITE.parent.parent / "lib/export-gpu-evidence.sh"),
            "--instance-id", "ocid1.instance.example", "--compartment-id", "ocid1.compartment.example",
            "--since", "2026-09-01T00:00:00Z", "--until", "2026-09-01T01:00:00Z", "--out", str(bundle)]
    result = subprocess.run(args, env=environment, capture_output=True, text=True, timeout=20, check=False)
    if fault == "none":
        assert result.returncode == 0, result.stderr
        synced = log.read_text().splitlines()
        intent_index = next(i for i, path in enumerate(synced) if path.endswith("/.publish-intent"))
        before_intent = synced[:intent_index]
        for artifact in bundle.iterdir():
            assert any(path.endswith("/" + artifact.name) for path in before_intent), artifact.name
        assert any(Path(path).name == "bundle" for path in before_intent), before_intent
    else:
        assert result.returncode != 0, result.stdout + result.stderr
        if fault == "artifact":
            assert (bundle / "manifest.json").read_bytes() == b"previous evidence"
        else:
            transactions = list(tmp_path.glob(".bundle.tmp.*"))
            assert len(transactions) == 1, result.stderr
            assert (transactions[0] / "previous/manifest.json").read_bytes() == b"previous evidence"
            assert (transactions[0] / ".publish-intent").is_file()
