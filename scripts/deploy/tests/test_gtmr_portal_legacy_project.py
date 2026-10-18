"""Fix-forward must keep the native Compose project through verification.

Only Compose config reaches the real CLI. Runtime operations and SSH are denied
or doubled, with hashes derived from the selected model's actual bind source.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from test_app_portal_deploy import _rollback_tree_state, _write_executable
from test_gtmr_portal_recovery_generation import _fix_forward_commands, _native_recovery

DOCKER = r"""#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
from pathlib import Path

a = sys.argv[1:]
failure = os.environ.get("FAIL_STAGE", "")
if a[:2] == ["network", "ls"]:
    if failure == "inventory":
        print("inventory unavailable", file=sys.stderr)
        sys.exit(17)
    print(os.environ["INVENTORY"])
    sys.exit(0)
if not a or a[0] != "compose":
    sys.exit("unexpected Docker operation: " + repr(a))
if "config" in a:
    if failure == "config":
        print("invalid compose input", file=sys.stderr)
        sys.exit(18)
    r = subprocess.run([os.environ["REAL_DOCKER"], *a], capture_output=True, timeout=10)
    sys.stdout.buffer.write(r.stdout)
    sys.stderr.buffer.write(r.stderr)
    sys.exit(r.returncode)
files = [value for i, value in enumerate(a) if i and a[i-1] == "-f"]
args = [value for path in files for value in ("-f", path)]
r = subprocess.run([os.environ["REAL_DOCKER"], "compose", *args, "config", "--format", "json"],
                   capture_output=True, text=True, timeout=10)
if r.returncode:
    print(r.stderr, file=sys.stderr)
    sys.exit(r.returncode)
model = json.loads(r.stdout)
if "up" in a:
    stage = "up"
elif "wget" in a:
    stage = "readiness"
elif "reload" in a:
    stage = "reload"
elif "sha256sum" in a:
    stage = "container-hash"
else:
    sys.exit("unexpected Compose operation: " + repr(a))
event = {"stage": stage, "argv": a, "files": files, "model": model,
         "generations": [Path(path).read_text() for path in files]}
with open(os.environ["MODEL_RECORD"], "a") as stream:
    stream.write(json.dumps(event) + "\n")
if model["name"] != os.environ["EXPECTED_PROJECT"]:
    print("wrong project: " + model["name"], file=sys.stderr)
    sys.exit(44)
required = {model["networks"][key]["name"] for key in model["services"]["caddy"]["networks"]}
if required - set(os.environ["INVENTORY"].splitlines()):
    sys.exit(42)
if failure == stage:
    sys.exit({"up": 31, "readiness": 32, "reload": 33, "container-hash": 34}[stage])
if stage == "container-hash":
    if a[-2:] != ["sha256sum", "/etc/caddy/Caddyfile"]:
        sys.exit("unexpected container hash target: " + repr(a))
    source = next(v["source"] for v in model["services"]["caddy"]["volumes"]
                  if v["target"] == "/etc/caddy/Caddyfile")
    print(hashlib.sha256(Path(source).read_bytes()).hexdigest() + "  /etc/caddy/Caddyfile")
"""

HASH = r"""#!/usr/bin/env python3
import json, os, subprocess, sys

if sys.argv[1:] == [os.environ["HOST_CADDY"]]:
    with open(os.environ["MODEL_RECORD"], "a") as stream:
        stream.write(json.dumps({"stage": "host-hash"}) + "\n")
    if os.environ.get("FAIL_STAGE") == "host-hash":
        sys.exit(35)
r = subprocess.run(["/usr/bin/sha256sum", *sys.argv[1:]], timeout=5)
sys.exit(r.returncode)
"""

HEALTH = r"""#!/usr/bin/env python3
import json, os, sys

with open(os.environ["MODEL_RECORD"], "a") as stream:
    stream.write(json.dumps({"stage": "health"}) + "\n")
sys.exit(36 if os.environ.get("FAIL_STAGE") == "health" else 0)
"""


def _fixture(tmp_path: Path, *, marked: bool, overlay: str = "named", optional: bool = True):
    backend, binary, record, env, networks = _native_recovery(tmp_path, optional_present=optional)
    base = backend / "docker-compose.caddy.yml"
    if not marked:
        base.write_text(base.read_text().replace("# shared-edge: optional-auraface-networks", "# legacy base"))
    installed = backend / "app/docker-compose.app.yml"
    if overlay == "absent":
        installed.unlink()
    elif overlay == "named":
        installed.write_text("name: selected-overlay-project\n" + installed.read_text())
    expected = "selected-overlay-project" if overlay == "named" else "acx-backend"
    _write_executable(binary / "docker", DOCKER)
    _write_executable(binary / "sha256sum", HASH)
    _write_executable(binary / "health-check", HEALTH)
    # Make readiness exhaustion deterministic without ten seconds of sleeps.
    _write_executable(binary / "sleep", "#!/bin/sh\nexit 0\n")
    _write_executable(binary / "ssh", "#!/bin/sh\necho 'unexpected SSH' >&2\nexit 98\n")
    for key in ("COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES", "DOCKER_CONTEXT"):
        env.pop(key, None)
    env.update(
        EXPECTED_PROJECT=expected,
        HOST_CADDY=str(backend / "Caddyfile"),
        DOCKER_HOST="unix:///nonexistent-p7-b-denied.sock",
        FAIL_STAGE="",
    )
    return backend, binary, record, env, networks


def _execute(fixture):
    backend, binary, record, env, _ = fixture
    before = _rollback_tree_state(backend)
    commands = (
        _fix_forward_commands()
        .replace("/opt/acx-backend", str(backend))
        .replace("/usr/local/bin/app-portal-health-check", str(binary / "health-check"))
    )
    result = subprocess.run(["bash", "-c", commands], env=env, capture_output=True, text=True, timeout=30)
    events = [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []
    assert _rollback_tree_state(backend) == before, "fix-forward altered protected live or rollback state"
    assert not list(backend.parents[1].glob("shared-edge-compose.*.json"))
    return result, events


@pytest.mark.parametrize("marked", [False, True], ids=["legacy", "normalized"])
@pytest.mark.parametrize("overlay", ["named", "unnamed", "absent"])
def test_fix_forward_uses_actual_selected_project_through_hash_and_health(tmp_path, marked, overlay):
    fixture = _fixture(tmp_path, marked=marked, overlay=overlay, optional=not marked)
    backend, _, _, env, networks = fixture
    result, events = _execute(fixture)
    assert result.returncode == 0, result.stdout + result.stderr
    assert [event["stage"] for event in events] == [
        "up",
        "readiness",
        "reload",
        "host-hash",
        "container-hash",
        "health",
    ]
    runtime = [event for event in events if "model" in event]
    assert {event["model"]["name"] for event in runtime} == {env["EXPECTED_PROJECT"]}
    assert len({tuple(event["files"]) for event in runtime}) == 1
    assert len({json.dumps(event["model"], sort_keys=True) for event in runtime}) == 1
    model = runtime[0]["model"]
    assert {value["name"] for value in model["networks"].values()} == set(networks)
    assert any(v["target"] == "/srv/app-portal" for v in model["services"]["caddy"]["volumes"]) == (overlay != "absent")
    if marked:
        assert len(runtime[0]["files"]) == 1
        generation = json.loads(runtime[0]["generations"][0])
        assert generation["name"] == env["EXPECTED_PROJECT"]
    else:
        assert runtime[0]["files"] == ["docker-compose.caddy.yml"] + (
            [] if overlay == "absent" else [str(backend / "app/docker-compose.app.yml")]
        )
    digest = hashlib.sha256((backend / "Caddyfile").read_bytes()).hexdigest()
    assert result.stdout.splitlines() == [f"{digest}  {backend / 'Caddyfile'}", f"{digest}  /etc/caddy/Caddyfile"]


@pytest.mark.parametrize("marked", [False, True], ids=["legacy", "normalized"])
@pytest.mark.parametrize(
    "failure,code,stages",
    [
        ("up", 31, ["up"]),
        ("readiness", 1, ["up"] + ["readiness"] * 10),
        ("reload", 33, ["up", "readiness", "reload"]),
        ("host-hash", 35, ["up", "readiness", "reload", "host-hash"]),
        ("container-hash", 34, ["up", "readiness", "reload", "host-hash", "container-hash"]),
        ("health", 36, ["up", "readiness", "reload", "host-hash", "container-hash", "health"]),
    ],
)
def test_fix_forward_failure_status_and_verification_order(tmp_path, marked, failure, code, stages):
    fixture = _fixture(tmp_path, marked=marked)
    fixture[3]["FAIL_STAGE"] = failure
    result, events = _execute(fixture)
    assert result.returncode == code, result.stdout + result.stderr
    assert [event["stage"] for event in events] == stages
    assert {event["model"]["name"] for event in events if "model" in event} == {"selected-overlay-project"}
    if failure in ("up", "readiness", "reload"):
        assert result.stdout == ""
    if failure == "readiness":
        assert "not ready after 10 attempts" in result.stderr


@pytest.mark.parametrize("reason", ["journal", "missing-helper", "symlink-helper", "inventory", "config"])
def test_fix_forward_refusal_preserves_state_before_runtime(tmp_path, reason):
    fixture = _fixture(tmp_path, marked=True, optional=False)
    backend, _, _, env, _ = fixture
    helper = backend / "app/shared-edge.sh"
    if reason == "journal":
        (backend / "app/activation.journal").write_text("phase=prepared\n")
    elif reason == "missing-helper":
        helper.unlink()
    elif reason == "symlink-helper":
        saved = tmp_path / "helper.sh"
        helper.rename(saved)
        helper.symlink_to(saved)
    else:
        env["FAIL_STAGE"] = reason
    result, events = _execute(fixture)
    assert result.returncode != 0, result.stdout + result.stderr
    assert events == []
    assert result.stdout == ""
    assert "STOP:" in result.stderr or "ERROR:" in result.stderr
