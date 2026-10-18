"""P6 causal controls: byte-preserving CRLF and daemon-free manual recovery."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from test_app_portal_deploy import REPO_ROOT, RUNBOOK, _rollback_tree_state, _run
from test_portal_manual_backout_journal import _manual_commands, _manual_state

LIB = REPO_ROOT / "scripts/deploy/lib/shared-edge.sh"
BASE = REPO_ROOT / "apps/prototype-description-service/docker-compose.caddy.yml"


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
@pytest.mark.parametrize("tail", [b"", b"\n", b"\r\n", b"\r\n# unmanaged suffix\r\n"])
def test_managed_line_endings_and_eof_are_preserved(tmp_path: Path, newline: bytes, tail: bytes) -> None:
    block = newline.join(
        [b"# BEGIN APP_PORTAL_VHOST", b"portal.example.com {", b" respond ok", b"}", b"# END APP_PORTAL_VHOST"]
    )
    block += tail if tail in (b"", b"\n", b"\r\n") else b"\r\n"
    base, live = tmp_path / "base", tmp_path / "live"
    base.write_bytes(b"api.example.com {\n respond healthy\n}\n")
    live.write_bytes(b"# leading comment\r\r\n" + block + (b"# unmanaged suffix\r\n" if b"suffix" in tail else b""))
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; edge_effective_caddyfile "$2" "$3"', "_", str(LIB), str(base), str(live)],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == base.read_bytes() + b"\n" + block


@pytest.mark.parametrize("address", [b"portal.example.com", b"https://auraface.dev.altcontext.com:443"])
def test_crlf_does_not_admit_standalone_cr_or_protected_hosts(tmp_path: Path, address: bytes) -> None:
    base, live = tmp_path / "base", tmp_path / "live"
    base.write_bytes(b"api.example.com {\n respond healthy\n}\n")
    cases = [address, b"portal.ex\rample.com", b"portal.example.com\r"]
    for host in cases:
        live.write_bytes(b"# BEGIN APP_PORTAL_VHOST\r\n" + host + b" {\r\n respond ok\r\n}\r\n# END APP_PORTAL_VHOST")
        result = subprocess.run(
            ["bash", "-c", 'source "$1"; edge_effective_caddyfile "$2" "$3"', "_", str(LIB), str(base), str(live)],
            capture_output=True,
            timeout=10,
        )
        if host == b"portal.example.com":
            assert result.returncode == 0, result.stderr
        else:
            assert result.returncode != 0, result.stdout
            assert result.stdout == b""


def _fix_forward_commands() -> str:
    section = RUNBOOK.read_text().split("If the hashes differ", 1)[1]
    return section.split("```bash\n", 1)[1].split("```", 1)[0]


def _native_recovery(tmp_path: Path, *, optional_present: bool, overlay_present: bool = True):
    real_docker = shutil.which("docker")
    assert real_docker, "daemon-free Docker Compose config CLI is required"
    backend = _manual_state(tmp_path, "prepared")
    (backend / "app/activation.journal").unlink()
    (backend / "docker-compose.caddy.yml").write_bytes(BASE.read_bytes())
    overlay = "services:\n  caddy:\n    volumes:\n      - " + str(backend / "app/www") + ":/srv/app-portal:ro\n"
    (backend / "app/docker-compose.app.yml").write_text(overlay)
    for stamp in ("10", "20"):
        target = backend / f"app/rollback/docker-compose.app.yml.{stamp}"
        if overlay_present:
            target.write_text(overlay)
        else:
            target.unlink()
            (backend / f"app/rollback/absent-overlay.{stamp}").write_text("app-portal-absent-overlay-v1\n")
    networks = [
        "acx-prod-net",
        "acx-staging-net",
        "acx-dev-net",
        "acx-dev-fir-net",
        "acx-demo-net",
        "acx-dev-auraface-net",
    ]
    if optional_present:
        networks += ["acx-staging-auraface-net", "acx-prod-auraface-net"]
    binary = tmp_path / "bin"
    binary.mkdir()
    stub = binary / "docker"
    stub.write_text("""#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
a=sys.argv[1:]
if a[:2]==["network","ls"]:
    print(os.environ["INVENTORY"]);sys.exit(0)
if a[0]!="compose":sys.exit(97)
if "config" in a:
    r=subprocess.run([os.environ["REAL_DOCKER"],*a],capture_output=True,timeout=10)
    sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr);sys.exit(r.returncode)
if "up" in a or "exec" in a:
    files=[]
    for i,v in enumerate(a):
        if v=="-f":files += [v,a[i+1]]
    r=subprocess.run([os.environ["REAL_DOCKER"],"compose",*files,"config","--format","json"],capture_output=True,text=True,timeout=10)
    if r.returncode:print(r.stderr,file=sys.stderr);sys.exit(r.returncode)
    model=json.loads(r.stdout)
    required={model["networks"][k]["name"] for k in model["services"]["caddy"]["networks"]}
    if required-set(os.environ["INVENTORY"].splitlines()):sys.exit(42)
    with open(os.environ["MODEL_RECORD"],"a") as f:
        f.write(json.dumps({"argv":a,"files":files,"model":model})+"\\n")
    sys.exit(0)
sys.exit(97)
""")
    stub.chmod(0o755)
    health = binary / "health-check"
    health.write_text("#!/bin/sh\nexit 0\n")
    health.chmod(0o755)
    record = tmp_path / "models.jsonl"
    env = dict(
        os.environ,
        PATH=f"{binary}:{os.environ['PATH']}",
        REAL_DOCKER=real_docker,
        INVENTORY="\n".join(networks),
        MODEL_RECORD=str(record),
        BASH_ENV="",
        TMPDIR=str(tmp_path),
    )
    env.pop("APP_SHARED_EDGE_LIB", None)
    return backend, binary, record, env, networks


@pytest.mark.parametrize("optional_present", [False, True])
@pytest.mark.parametrize(
    "route", ["backout", "backout-no-overlay", "backout-standalone", "fix-forward", "fix-forward-no-overlay"]
)
def test_manual_routes_share_one_native_effective_generation(
    tmp_path: Path, optional_present: bool, route: str
) -> None:
    backend, binary, record, env, networks = _native_recovery(
        tmp_path,
        optional_present=optional_present,
        overlay_present=route not in ("backout-no-overlay", "fix-forward-no-overlay"),
    )
    if route == "fix-forward-no-overlay":
        (backend / "app/docker-compose.app.yml").unlink()
        if optional_present:
            # Also exercise an unmarked legacy base with only its selected
            # base file. No nonexistent overlay may enter the recreate argv.
            base = backend / "docker-compose.caddy.yml"
            base.write_text(base.read_text().replace("# shared-edge: optional-auraface-networks", "# legacy base"))
    if route == "backout-standalone":
        # The same fourth artifact transported with the standalone recovery
        # script; no installed helper or VM checkout is available here.
        artifact = tmp_path / "app-portal-recovery.shared-edge.sh"
        artifact.write_bytes((backend / "app/shared-edge.sh").read_bytes())
        (backend / "app/shared-edge.sh").unlink()
        env["APP_SHARED_EDGE_LIB"] = str(artifact)
    live = backend / "Caddyfile"
    inode = live.stat().st_ino
    lock = backend / "app/activation.journal.lock"
    lock_before = (lock.stat().st_ino, lock.read_bytes())
    commands = _fix_forward_commands() if route.startswith("fix-forward") else _manual_commands()
    commands = commands.replace("/opt/acx-backend", str(backend)).replace(
        "/usr/local/bin/app-portal-health-check", str(binary / "health-check")
    )
    result = subprocess.run(["bash", "-c", commands], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    models = [json.loads(line) for line in record.read_text().splitlines()]
    assert len(models) >= 3
    assert len({tuple(item["files"]) for item in models}) == 1
    assert len({json.dumps(item["model"], sort_keys=True) for item in models}) == 1
    assert models[0]["argv"][-5:] == ["up", "-d", "--force-recreate", "--no-deps", "caddy"]
    assert any("wget" in item["argv"] for item in models)
    assert any("reload" in item["argv"] for item in models)
    model = models[0]["model"]
    assert {n["name"] for n in model["networks"].values()} == set(networks)
    assert any(v["target"] == "/srv/app-portal" for v in model["services"]["caddy"]["volumes"]) == (
        route not in ("backout-no-overlay", "fix-forward-no-overlay")
    )
    assert live.stat().st_ino == inode
    assert (lock.stat().st_ino, lock.read_bytes()) == lock_before
    assert not (backend / "app/activation.journal").exists()
    assert not list(tmp_path.glob("shared-edge-compose.*.json"))
    if route.startswith("backout"):
        assert live.read_text() == "caddy 20\n"
        assert (backend / "app/www/index.html").read_text() == "frontend 20\n"


@pytest.mark.parametrize("route", ["backout", "fix-forward"])
@pytest.mark.parametrize("reason", ["journal", "missing-helper", "symlink-helper", "inventory-failure"])
def test_manual_route_admission_preserves_protected_state(tmp_path: Path, route: str, reason: str) -> None:
    backend, binary, record, env, _ = _native_recovery(tmp_path, optional_present=False)
    helper = backend / "app/shared-edge.sh"
    if reason == "journal":
        (backend / "app/activation.journal").write_text("phase=prepared\n")
    elif reason == "missing-helper":
        helper.unlink()
    elif reason == "symlink-helper":
        helper.unlink()
        helper.symlink_to(LIB)
    else:
        (binary / "docker").write_text("#!/bin/sh\nexit 1\n")
    before = _rollback_tree_state(backend)
    commands = _fix_forward_commands() if route.startswith("fix-forward") else _manual_commands()
    commands = commands.replace("/opt/acx-backend", str(backend))
    result = subprocess.run(["bash", "-c", commands], env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, result.stdout + result.stderr
    assert not record.exists()
    # Inventory failure can occur after manual file restore; journal/helper
    # admission must always precede every protected-state mutation.
    if reason != "inventory-failure" or route == "fix-forward":
        assert _rollback_tree_state(backend) == before


def test_successful_apply_packages_the_reviewed_helper(tmp_path: Path) -> None:
    result = _run(tmp_path, args=["--apply"], extra_env={"BASH_ENV": ""})
    assert result.returncode == 0, result.stdout + result.stderr
    installed = tmp_path / "opt/acx-backend/app/shared-edge.sh"
    assert installed.read_bytes() == LIB.read_bytes()
    assert not installed.is_symlink()
