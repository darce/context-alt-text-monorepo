"""Native Compose admission and real v2 recovery of the executable back-out.

Only Docker runtime actions and injected filesystem failures are doubled. Config
and project selection use the installed Compose CLI; recovery runs app-portal.sh.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from test_app_portal_deploy import OVERLAY, SCRIPT, SNIPPET, _rollback_tree_state
from test_gtmr_portal_recovery_generation import _native_recovery
from test_portal_manual_backout_journal import _manual_commands, _recovery_commands


def _fixture(tmp_path: Path, *, marked: bool, overlay: bool):
    backend, binary, record, env, _ = _native_recovery(
        tmp_path, optional_present=True, overlay_present=overlay
    )
    base = backend / "docker-compose.caddy.yml"
    if not marked:
        base.write_text(base.read_text().replace("# shared-edge: optional-auraface-networks", "# legacy base"))
    # Different actual project names catch selecting today's live overlay rather
    # than the rollback candidate, and dropping name: during runtime operations.
    live_overlay = backend / "app/docker-compose.app.yml"
    live_overlay.write_text("name: live-project\n" + live_overlay.read_text())
    if overlay:
        for stamp in ("10", "20"):
            p = backend / f"app/rollback/docker-compose.app.yml.{stamp}"
            p.write_text("name: rollback-project\n" + p.read_text())
    else:
        shutil.rmtree(backend / "app/rollback/www.20")
        (backend / "app/rollback/absent-www.20").write_text("app-portal-absent-www-v1\n")
    env.update(BACKEND=str(backend), FAULT="", APP_APPROVED_ROOTS=str(backend),
               PREFLIGHT_RECORD=str(tmp_path / "preflight.jsonl"))
    env.pop("AURA_EDGE_TEST_HELPER", None)
    docker = binary / "docker"
    code = docker.read_text().replace(
        'if a[0]!="compose":sys.exit(97)',
        'if a==["compose","version"]:sys.exit(0)\nif a[0]!="compose":sys.exit(97)',
    ).replace(
        'print(os.environ["INVENTORY"]);sys.exit(0)',
        'if os.environ.get("FAULT")=="inventory":sys.exit(17)\n    print(os.environ["INVENTORY"]);sys.exit(0)',
    ).replace(
        'if "config" in a:\n',
        'if "config" in a:\n'
        '    with open(os.environ["PREFLIGHT_RECORD"],"a") as f:f.write(json.dumps(a)+"\\n")\n'
        '    if os.environ.get("FAULT")=="config":sys.exit(18)\n',
    ).replace(
        '    sys.exit(0)\nsys.exit(97)',
        '    fault=os.environ.get("FAULT", "")\n'
        '    if (fault=="up" and "up" in a) or (fault=="readiness" and "wget" in a) or (fault=="reload" and "reload" in a):sys.exit(19)\n'
        '    sys.exit(0)\nsys.exit(97)',
    )
    docker.write_text(code)
    for name in ("cp", "rm", "mv"):
        real = shutil.which(name)
        assert real
        wrapper = binary / name
        wrapper.write_text('''#!/usr/bin/env python3
import os,subprocess,sys
from pathlib import Path
args=sys.argv[1:]
fault=os.environ.get("FAULT", "")
b=Path(os.environ["BACKEND"])
dest=args[-1]
name=Path(sys.argv[0]).name
if name=="cp" and fault=="overlay-copy" and dest.startswith(str(b/"app/activation.journal.new.overlay.")):
    Path(dest).write_text("services: [broken YAML")
    print("injected partial overlay copy",file=sys.stderr);sys.exit(23)
r=subprocess.run([REAL,*args],timeout=10)
if r.returncode:sys.exit(r.returncode)
hit=(
 (name=="cp" and fault=="snapshot" and dest.startswith(str(b/"app/rollback/Caddyfile."))) or
 (name=="cp" and fault=="caddy" and dest==str(b/"Caddyfile")) or
 (name=="rm" and fault=="www-remove" and dest==str(b/"app/www")) or
 (name=="cp" and fault=="www-copy" and dest==str(b/"app/www")) or
 (fault=="overlay" and dest==str(b/"app/docker-compose.app.yml")) or
 (name=="rm" and fault=="cleanup" and dest.startswith(str(b/"app/rollback/Caddyfile.")))
)
if hit:print("injected after "+fault,file=sys.stderr);sys.exit(23)
sys.exit(0)
'''.replace("REAL", repr(real)))
        wrapper.chmod(0o755)
    # Readiness retries are still counted in the native-model runtime record.
    (binary / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (binary / "sleep").chmod(0o755)
    (binary / "ssh").write_text("#!/bin/sh\necho 'unexpected SSH' >&2\nexit 97\n")
    (binary / "ssh").chmod(0o755)
    return backend, binary, record, env


def _backout(backend: Path, env: dict[str, str]):
    return subprocess.run(
        ["bash", "-c", _manual_commands().replace("/opt/acx-backend", str(backend))],
        env=env, capture_output=True, text=True, timeout=30,
    )


def _recover(tmp_path: Path, backend: Path, binary: Path, env: dict[str, str]):
    # Run the exact documented standalone invocation with all four transitive
    # inputs, not an extracted imitation of the recovery functions.
    copies = {
        "/tmp/app-portal-recovery.sh": SCRIPT,
        "/tmp/app-portal-recovery.shared-edge.sh": backend / "app/shared-edge.sh",
        "/tmp/app-portal-recovery.Caddyfile.app": SNIPPET,
        "/tmp/app-portal-recovery.overlay.yml": OVERLAY,
    }
    command = _recovery_commands()
    for original, source in sorted(copies.items(), key=lambda item: -len(item[0])):
        copy = tmp_path / Path(original).name
        copy.write_bytes(source.read_bytes())
        command = command.replace(original, str(copy))
    command = command.replace("/opt/acx-backend", str(backend)).replace(
        "/usr/local/bin/app-portal-health-check", str(binary / "health-check")
    )
    return subprocess.run(
        ["bash", "-c", command], env={**env, "FAULT": "", "FRONTEND_DIST": "/inherited/build"},
        capture_output=True, text=True, timeout=30,
    )


def _assert_target(backend: Path, overlay: bool):
    assert (backend / "Caddyfile").read_bytes() == b"caddy 20\n"
    if overlay:
        assert (backend / "app/www/index.html").read_bytes() == b"frontend 20\n"
        assert (backend / "app/docker-compose.app.yml").read_bytes() == (
            backend / "app/rollback/docker-compose.app.yml.20"
        ).read_bytes()
    else:
        assert not (backend / "app/www").exists()
        assert not (backend / "app/docker-compose.app.yml").exists()


@pytest.mark.parametrize("marked,fault", [(False, "config"), (True, "config"), (True, "inventory")])
@pytest.mark.parametrize("overlay", [False, True])
def test_candidate_refusal_writes_nothing(tmp_path: Path, marked: bool, overlay: bool, fault: str):
    backend, binary, record, env = _fixture(tmp_path, marked=marked, overlay=overlay)
    before = _rollback_tree_state(backend)
    result = _backout(backend, {**env, "FAULT": fault})
    assert result.returncode != 0, result.stdout + result.stderr
    assert _rollback_tree_state(backend) == before
    assert not record.exists()
    assert not (backend / "app/activation.journal").exists()
    assert not list(backend.glob("app/activation.journal.new.*"))


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("overlay", [False, True])
def test_selected_candidate_survives_live_restoration(tmp_path: Path, marked: bool, overlay: bool):
    backend, binary, record, env = _fixture(tmp_path, marked=marked, overlay=overlay)
    snapshots = _rollback_tree_state(backend / "app/rollback")
    live_inode = (backend / "Caddyfile").stat().st_ino
    lock = _rollback_tree_state(backend / "app/activation.journal.lock")
    result = _backout(backend, env)
    assert result.returncode == 0, result.stdout + result.stderr
    _assert_target(backend, overlay)
    models = [json.loads(line) for line in record.read_text().splitlines()]
    assert len({tuple(m["files"]) for m in models}) == 1
    assert len({json.dumps(m["model"], sort_keys=True) for m in models}) == 1
    assert models[0]["model"]["name"] == ("rollback-project" if overlay else "acx-backend")
    assert "up" in models[0]["argv"]
    assert "wget" in models[1]["argv"]
    assert "reload" in models[-1]["argv"]
    preflight = [json.loads(line) for line in Path(env["PREFLIGHT_RECORD"]).read_text().splitlines()]
    assert any(str(backend / "app/rollback/docker-compose.app.yml.20") in a for a in preflight) == overlay
    assert (backend / "Caddyfile").stat().st_ino == live_inode
    assert _rollback_tree_state(backend / "app/activation.journal.lock") == lock
    assert _rollback_tree_state(backend / "app/rollback") == snapshots
    assert not (backend / "app/activation.journal").exists()


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize(
    "overlay,fault",
    [(overlay, fault) for overlay in (False, True)
     for fault in ("snapshot", "caddy", "www-remove", "www-copy", "overlay-copy", "overlay", "up", "readiness", "reload", "cleanup")
     if overlay or fault not in ("www-copy", "overlay-copy")],
)
def test_partial_backout_resumes_with_native_recovery(tmp_path: Path, marked: bool, overlay: bool, fault: str):
    backend, binary, record, env = _fixture(tmp_path, marked=marked, overlay=overlay)
    snapshots = _rollback_tree_state(backend / "app/rollback")
    live_before = (backend / "Caddyfile").read_bytes()
    live_inode = (backend / "Caddyfile").stat().st_ino
    lock = _rollback_tree_state(backend / "app/activation.journal.lock")
    result = _backout(backend, {**env, "FAULT": fault})
    assert result.returncode != 0, result.stdout + result.stderr
    journal = backend / "app/activation.journal"
    assert journal.is_file(), "partial back-out has no native recovery record"
    fields = dict(line.split("=", 1) for line in journal.read_text().splitlines())
    assert fields["version"] == "2"
    assert fields["rollback_caddy"] != str(backend / "app/rollback/Caddyfile.20")
    assert fields["phase"] == ("snapshotting" if fault == "snapshot" else "restored" if fault == "cleanup" else {
        "caddy": "prepared", "www-remove": "caddy_promoted", "www-copy": "caddy_promoted", "overlay": "www_promoted", "overlay-copy": "www_promoted"
    }.get(fault, "overlay_promoted"))
    for path, state in snapshots.items():
        assert _rollback_tree_state(backend / "app/rollback")[path] == state
    if fault == "overlay-copy":
        assert "injected partial overlay copy" in result.stderr
        assert (backend / "app/docker-compose.app.yml").read_text().startswith("name: live-project\n")
    if fault == "readiness":
        models = [json.loads(line) for line in record.read_text().splitlines()]
        assert sum("wget" in m["argv"] for m in models) == 10
        assert not any("reload" in m["argv"] for m in models)
    # Manual retry refuses rather than overwriting recovery evidence.
    before_retry = _rollback_tree_state(backend)
    refused = _backout(backend, env)
    assert refused.returncode != 0 and "activation journal present" in refused.stderr
    assert _rollback_tree_state(backend) == before_retry
    recovered = _recover(tmp_path, backend, binary, env)
    assert recovered.returncode == 2, recovered.stdout + recovered.stderr
    assert "recovering interrupted activation" in recovered.stdout
    assert recovered.stderr.strip() == "ERROR: FRONTEND_DIST is required for --apply"
    assert not journal.exists() and not journal.is_symlink()
    assert _rollback_tree_state(backend / "app/rollback") == snapshots
    if fault == "snapshot":
        assert (backend / "Caddyfile").read_bytes() == live_before
    else:
        _assert_target(backend, overlay)
    assert (backend / "Caddyfile").stat().st_ino == live_inode
    assert _rollback_tree_state(backend / "app/activation.journal.lock") == lock
    # A second native invocation performs no replay; a manual retry remains valid.
    replay_before = _rollback_tree_state(backend)
    records_before = record.read_bytes() if record.exists() else b""
    again = _recover(tmp_path, backend, binary, env)
    assert again.returncode == 2 and "recovering interrupted" not in again.stdout
    assert _rollback_tree_state(backend) == replay_before
    assert (record.read_bytes() if record.exists() else b"") == records_before
    retried = _backout(backend, env)
    assert retried.returncode == 0, retried.stdout + retried.stderr
    _assert_target(backend, overlay)
    assert _rollback_tree_state(backend / "app/rollback") == snapshots


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("overlay", [False, True])
def test_native_candidate_config_refusal_preserves_state(tmp_path: Path, marked: bool, overlay: bool):
    backend, binary, record, env = _fixture(tmp_path, marked=marked, overlay=overlay)
    candidate = backend / ("app/rollback/docker-compose.app.yml.20" if overlay else "docker-compose.caddy.yml")
    candidate.write_text(candidate.read_text() + "\nservices: [unterminated\n")
    before = _rollback_tree_state(backend)
    result = _backout(backend, env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "yaml" in result.stderr.lower(), result.stderr
    assert _rollback_tree_state(backend) == before
    assert not record.exists()
    assert not (backend / "app/activation.journal").exists()


@pytest.mark.parametrize("marked", [False, True])
@pytest.mark.parametrize("overlay", [False, True])
def test_candidate_cannot_redirect_caddy_bind(tmp_path: Path, marked: bool, overlay: bool):
    backend, binary, record, env = _fixture(tmp_path, marked=marked, overlay=overlay)
    wrong = tmp_path / "other-Caddyfile"
    wrong.write_text("untouched\n")
    if overlay:
        candidate = backend / "app/rollback/docker-compose.app.yml.20"
        candidate.write_text(candidate.read_text() + f"      - {wrong}:/etc/caddy/Caddyfile:ro\n")
    else:
        candidate = backend / "docker-compose.caddy.yml"
        candidate.write_text(candidate.read_text().replace("./Caddyfile:/etc/caddy/Caddyfile:ro", f"{wrong}:/etc/caddy/Caddyfile:ro"))
    before = _rollback_tree_state(backend)
    result = _backout(backend, env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "candidate Caddyfile bind source" in result.stderr
    assert _rollback_tree_state(backend) == before
    assert wrong.read_bytes() == b"untouched\n"
    assert not record.exists()
