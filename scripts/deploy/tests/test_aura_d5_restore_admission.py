"""D5-A composite recovery: native script/helper, finite hermetic transports.

Uses the published script in the complete checkout, with its real Git metadata
and transitive inputs. Author verification temporarily installs the candidate;
there is no candidate selector or production bypass. See the D5-A handoff in
the candidate restore comment and the immutable D4 boundary probe for the RED.

Author custody (actual Downer dispatch 5; Powner remains dispatch 8):
  Logical input 602acba37fb0b0996ee0d76352f471ff6bccf319,
  native base fc210637035aed5e757f3708ce7424829f0c30c0,
  input tree a327bf0feb01837fd404ce430ec57678714970f7.
  Transient published candidate SHA256:
  1242edd111b0be353cb5d0864e716169d738f14d99957c0ffb487b14d718f3b2.
  Baseline log /tmp/auraface-D5-A-red.log: exit 1, four generation-refusal
  failures, six valid dev/Aura/FIR controls passed, 15 deselected, 101.22s.
  First candidate run was interrupted (exit 130) after four pass indicators
  and five setup-failure indicators: the Docker double lacked the actual
  flip producer docker-run validation ABI. Log retained at
  /tmp/auraface-D5-A-final-setup-interrupted.log. Added that exact ABI and
  compare only post-admission runtime actions; candidate source unchanged.
  Corrected-fixture preliminary run was interrupted (exit 130) after eight
  pass indicators to cover the sibling restore_runtime_and_edge entry, which
  also needed admission when the edge pointer is entirely absent. Log:
  /tmp/auraface-D5-A-pre-final-scope-interrupted.log. Final source includes
  that guard and two independent missing-pointer cases for the two entries.
  Final scoped matrix log /tmp/auraface-D5-A-final.log; invoke this whole
  module with .venv/bin/python -m pytest -q -p no:cacheprovider, under timeout
  900s and PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
  MKL_NUM_THREADS=1. Includes ten unchanged substantive neighbor invocations.
  Only candidate, git-apply patch and this test are published by D5-A.
  The production script is restored to base before commit. To join, apply
  docs/reviews/auraface-D5/D5-A-recognition-service.patch; reverse the same
  patch to undo it before any deployment. No runtime state is touched here.
  The actual combined tree still needs independent XHIGH review; D4-C1 and
  P6-R1/R2 remain separately owned. No image/model/quality approval is implied.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from conftest import _write_executable

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/recognition-service.sh"


@pytest.fixture
def recovery(tmp_path):
    remote = tmp_path / "remote"
    (remote / "app").mkdir(parents=True)
    (remote / "systemd").mkdir()
    (remote / "Caddyfile").write_bytes(
        b"dev.example.com {\n reverse_proxy dev-api:8000\n}\n\n"
        b"# BEGIN APP_PORTAL_VHOST\r\nportal.example.com {\r\n root * /www\r\n"
        b" file_server\r\n}\r\n# END APP_PORTAL_VHOST"
    )
    for path in (remote / "docker-compose.caddy.yml", remote / "app/docker-compose.app.yml"):
        path.write_text("services: {}\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    _write_executable(binary / "sudo", '#!/bin/sh\nexec "$@"\n')
    _write_executable(binary / "ssh", '''#!/usr/bin/env python3
import os,subprocess,sys
from pathlib import Path
a=sys.argv[1:]
expected=["-o","BatchMode=yes","-o","ConnectTimeout=5","-o","ConnectionAttempts=1","-l","d5","--","d5.invalid"]
if a[:-1]!=expected or not a[-1].startswith("sudo timeout -k 5 20 bash -s -- "):
    Path(os.environ["UNEXPECTED_SSH"]).write_text(repr(a))
    sys.exit(97)
def mapped(s):
    return s.replace("/opt/acx-backend",os.environ["REMOTE_ROOT"]).replace("/etc/systemd/system",os.environ["SYSTEMD_ROOT"])
r=subprocess.run(["bash","-c",mapped(a[-1])],input=mapped(sys.stdin.read()),text=True,timeout=27)
sys.exit(r.returncode)
''')
    _write_executable(binary / "docker", '''#!/usr/bin/env python3
import json,os,signal,sys
from pathlib import Path
a=sys.argv[1:]
with open(os.environ["DOCKER_RECORD"],"a") as f: f.write(" ".join(a)+"\\n")
if "config" in a:
    if os.environ.get("FAIL_CONFIG"): sys.exit(19)
    if os.environ.get("LOSE_ON_CONFIG"):
        d=dict(s.split("=",1) for s in (Path(os.environ["APP_ROOT"])/"activation.journal").read_text().splitlines())
        handle=Path(d["handle"])
        if os.environ["LOSE_ON_CONFIG"]=="dead": os.kill(int((handle/"holder.pid").read_text()),signal.SIGKILL)
        else: (handle/"expires").write_text("1\\n")
    print(json.dumps({"services":{"caddy":{"networks":{"legacy":None}}},"networks":{"legacy":{"name":"legacy-real"}}}))
elif a[:2]==["network","ls"]: print("legacy-real")
elif "ps" in a: print("a"*12)
elif a[0]=="inspect": print('{"legacy-real":{}}')
elif a[:3]==["run","--rm","-v"] and a[4:]==["caddy:2-alpine","caddy","validate","--config","/etc/caddy/Caddyfile"]:
    if not a[3].endswith(":/etc/caddy/Caddyfile:ro") or not Path(a[3].split(":",1)[0]).is_file(): sys.exit(98)
elif a[0]=="compose" and any(x in a for x in ("exec","up","rm")): pass
else: sys.exit(98)
''')
    _write_executable(binary / "systemctl", '''#!/bin/sh
printf '%s\n' "$*" >>"$SYSTEMCTL_RECORD"
case "$1" in
  daemon-reload|stop|disable) exit 0 ;;
  is-enabled) exit 1 ;;
  *) exit 98 ;;
esac
''')
    env = dict(
        os.environ,
        PATH=f"{binary}:/usr/bin:/bin",
        TMPDIR=str(tmp_path),
        EDGE_LOCK_STATE_ROOT=str(tmp_path),
        OCI_HOST="d5.invalid",
        OCI_USER="d5",
        ACX_REMOTE_COMMAND_TIMEOUT="20",
        REMOTE_ROOT=str(remote),
        SYSTEMD_ROOT=str(remote / "systemd"),
        APP_ROOT=str(remote / "app"),
        DOCKER_RECORD=str(tmp_path / "docker.log"),
        SYSTEMCTL_RECORD=str(tmp_path / "systemctl.log"),
        UNEXPECTED_SSH=str(tmp_path / "unexpected-ssh"),
    )
    env.pop("AURA_EDGE_TEST_HELPER", None)
    yield SCRIPT, remote, env
    for handle in tmp_path.glob("shared-edge-lock.*"):
        subprocess.run(
            ["bash", "-c", 'source "$1"; edge_lock_release "$2" 2', "_",
             str(SCRIPT.parent / "lib/shared-edge.sh"), str(handle)],
            env=env, capture_output=True, timeout=5,
        )
    assert not Path(env["UNEXPECTED_SSH"]).exists(), "unexpected SSH was denied"
    assert sum(p.lstat().st_size for p in tmp_path.rglob("*") if p.is_file() and not p.is_symlink()) < 256 * 1024**2


def run(recovery, body, **extra):
    script, remote, env = recovery
    command = (
        f"source {shlex.quote(str(script))}\n"
        f"ACX_DEPLOY_BACKUP_ROOT={shlex.quote(str(remote / 'backups'))}\n" + body
    )
    return subprocess.run(["bash", "-c", command], env=dict(env, **extra),
                          text=True, capture_output=True, timeout=55)


def ok(result):
    assert result.returncode == 0, result.stdout + result.stderr


def seed(recovery, label="dev", *, finish=True, present=True):
    remote = recovery[1]
    directory = remote / label
    (directory / "db/docker-prod-init").mkdir(parents=True)
    paths = [directory / "docker-compose.env.yml", remote / f"systemd/acx-{label}.service",
             directory / "db/docker-prod-init/001-extensions.sql"]
    if present:
        for p in paths:
            p.write_text("prior:" + p.name + "\n")
    ok(run(recovery, f"ACX_DEPLOY_TRANSACTION_ID=saved\nprepare_runtime_topology_backups {label} 1 || exit $?\n"
           + ("recognition_edge_finish" if finish else ":")))
    for p in paths:
        p.write_text("current:" + p.name + "\n")
    return remote / f"backups/{label}/saved", paths


def state(remote):
    """Protect every existing live/backup file, symlink and journal inode."""
    return {
        str(p.relative_to(remote)): (p.lstat().st_ino, p.readlink() if p.is_symlink() else p.read_bytes())
        for p in remote.rglob("*") if p.is_file() or p.is_symlink()
    }


def begin(recovery, label="dev", *, current=False):
    transaction = "saved" if current else "fresh"
    if current:
        return journal_owner(recovery)
    return f"ACX_DEPLOY_TRANSACTION_ID={transaction}\nrecognition_edge_begin {label} || exit $?\n"


def journal_owner(recovery):
    fields = dict(line.split("=", 1) for line in (recovery[1] / "app/activation.journal").read_text().splitlines())
    return "\n".join(f"{name}={shlex.quote(fields[key])}" for name, key in (
        ("ACX_DEPLOY_TRANSACTION_ID", "transaction"), ("ACX_EDGE_HANDLE", "handle"), ("ACX_EDGE_ENV", "env")
    )) + "\n"


def refuse_unchanged(recovery, command, expected=None, **extra):
    before = state(recovery[1])
    commands = Path(recovery[2]["DOCKER_RECORD"])
    command_before = commands.read_text() if commands.exists() else ""
    units = Path(recovery[2]["SYSTEMCTL_RECORD"])
    units_before = units.read_text() if units.exists() else ""
    result = run(recovery, command, **extra)
    assert (result.returncode == expected if expected else result.returncode != 0), result.stdout + result.stderr
    assert state(recovery[1]) == before, result.stdout + result.stderr
    assert (recovery[1] / "app/activation.journal").is_file()
    command_after = commands.read_text() if commands.exists() else ""
    assert command_after.startswith(command_before)
    assert not any(" " + word + " " in " " + line + " "
        for line in command_after[len(command_before):].splitlines() for word in ("exec", "up", "rm"))
    assert (units.read_text() if units.exists() else "") == units_before
    return result


@pytest.mark.parametrize("generation", ["stale", "missing"])
@pytest.mark.parametrize("current", [False, True], ids=["pointer", "current-only"])
def test_d4_generation_refusal_preserves_complete_restore(recovery, generation, current):
    snapshot, _ = seed(recovery, finish=not current)
    if generation == "stale":
        live = recovery[1] / "Caddyfile"
        live.write_bytes(b"later.example.com {\n respond healthy\n}\n" + live.read_bytes())
    else:
        (snapshot / "edge/generation.json").unlink()
    owner = begin(recovery, current=current)
    ok(run(recovery, owner))
    owner = journal_owner(recovery)
    refuse_unchanged(recovery, owner + "restore_runtime_topology dev" + (" current-only" if current else ""), 75)


@pytest.mark.parametrize("fault", ["missing-last", "symlink-last", "invalid-pointer", "incomplete", "missing-bootstrap-ready"])
@pytest.mark.parametrize("edge_first", [False, True], ids=["composite", "reverse-control"])
def test_reverse_topology_admission_precedes_caddy_writes(recovery, fault, edge_first):
    snapshot, _ = seed(recovery)
    # Make a real edge rollback observable, with its generation recorded by the
    # actual producer rather than a fabricated generation.json.
    ok(run(recovery, "ACX_DEPLOY_TRANSACTION_ID=flip\nrecognition_edge_begin dev || exit $?\n"
           + "flip_edge_alias dev next example/image@sha256:" + "a" * 64 + " || exit $?\nrecognition_edge_finish"))
    # Select the original topology and the flip producer's edge snapshot.
    if fault in ("missing-last", "symlink-last"):
        sql = snapshot / "db-init/001-extensions.sql"
        sql.unlink()
        if fault == "symlink-last":
            sql.symlink_to(recovery[1] / "dev/db/docker-prod-init/001-extensions.sql")
    elif fault == "invalid-pointer":
        (recovery[1] / "backups/dev/latest").write_text(str(snapshot / "../saved") + "\n")
    elif fault == "incomplete":
        (snapshot / "topology.ready").unlink()
        (snapshot / "topology.pending").touch()
    else:
        (snapshot / "db-init.ready").unlink()
    ok(run(recovery, begin(recovery)))
    # The ordering control deliberately calls the composite through a wrapper
    # that swaps its two legacy writers. Both orders must pre-admit both halves.
    body = journal_owner(recovery)
    if edge_first:
        body += '''original=$(declare -f restore_runtime_topology)
swapped=${original//restore_topology_backups/RESTORE_SWAP}
swapped=${swapped//restore_edge_backups/restore_topology_backups}
eval "${swapped//RESTORE_SWAP/restore_edge_backups}"
'''
    refuse_unchanged(recovery, body + "restore_runtime_topology dev")


@pytest.mark.parametrize("label", ["dev", "dev-auraface", "dev-fir"])
@pytest.mark.parametrize("present", [False, True], ids=["prior-absence", "prior-files"])
def test_valid_composite_restores_dev_aura_and_fir(recovery, label, present):
    _, paths = seed(recovery, label, present=present)
    live = recovery[1] / "Caddyfile"
    before = live.read_bytes(), live.stat().st_ino
    result = run(recovery, begin(recovery, label) + f"restore_runtime_topology {label} || exit $?\nrecognition_edge_finish")
    ok(result)
    assert (live.read_bytes(), live.stat().st_ino) == before
    for p in paths:
        assert p.read_text() == "prior:" + p.name + "\n" if present else not p.exists()
    assert not (recovery[1] / "app/activation.journal").exists()


@pytest.mark.parametrize("fault", ["missing-edge-compose", "unsafe-edge-source", "bad-overlay", "config-error"])
def test_edge_admission_refuses_before_topology_writer(recovery, fault):
    snapshot, _ = seed(recovery)
    if fault == "missing-edge-compose":
        (snapshot / "edge/docker-compose.caddy.yml").unlink()
    elif fault == "unsafe-edge-source":
        source = snapshot / "edge/Caddyfile.pre-cutover"
        source.unlink()
        source.symlink_to(recovery[1] / "Caddyfile")
    elif fault == "bad-overlay":
        (recovery[1] / "app/docker-compose.app.yml").write_text("__APP_WWW__")
    ok(run(recovery, begin(recovery)))
    refuse_unchanged(recovery, journal_owner(recovery) + "restore_runtime_topology dev",
                     **({"FAIL_CONFIG": "1"} if fault == "config-error" else {}))


@pytest.mark.parametrize("entry", ["restore_runtime_topology", "restore_runtime_and_edge"])
def test_missing_edge_pointer_refuses_both_composite_entries(recovery, entry):
    seed(recovery)
    (recovery[1] / "backups/dev/edge-cutover.current").unlink()
    ok(run(recovery, begin(recovery)))
    refuse_unchanged(recovery, journal_owner(recovery) + entry + " dev")


@pytest.mark.parametrize("loss", ["dead", "expired"])
def test_admitted_plan_still_fences_ownership_at_commit(recovery, loss):
    seed(recovery)
    ok(run(recovery, begin(recovery)))
    refuse_unchanged(recovery, journal_owner(recovery) + "restore_runtime_topology dev", LOSE_ON_CONFIG=loss)


def test_current_only_without_snapshots_leaves_unknown_live_files_untouched(recovery):
    ok(run(recovery, begin(recovery)))
    before = state(recovery[1])
    ok(run(recovery, journal_owner(recovery) + "restore_runtime_topology dev current-only"))
    assert state(recovery[1]) == before


@pytest.mark.parametrize("ownership", ["missing", "unknown", "dead", "expired"])
def test_composite_never_compensates_without_ownership(recovery, ownership):
    remote = recovery[1]
    body = ""
    if ownership in ("dead", "expired"):
        ok(run(recovery, begin(recovery)))
        body = journal_owner(recovery)
        body += ('kill -KILL "$(cat "$ACX_EDGE_HANDLE/holder.pid")"\n' if ownership == "dead"
                 else 'printf "1\\n" >"$ACX_EDGE_HANDLE/expires"\n')
    elif ownership == "unknown":
        body = "ACX_EDGE_HANDLE=/tmp/unknown-D5-owner\nACX_EDGE_ENV=dev\n"
    before = state(remote)
    result = run(recovery, body + "restore_runtime_topology dev")
    assert result.returncode == 75, result.stdout + result.stderr
    assert state(remote) == before
    assert not (remote / "backups").exists()
    assert not Path(recovery[2]["DOCKER_RECORD"]).exists()
    assert not Path(recovery[2]["SYSTEMCTL_RECORD"]).exists()


@pytest.mark.parametrize("space", ["", "\v", "\f", "\x85", "prefix-CR"])
def test_neighbor_newer_portal_block_survives_restore(recovery, space):
    import test_aura_deploy_adjudication as neighbor

    neighbor.test_restore_preserves_newer_portal_block_with_supported_whitespace(recovery, space)


@pytest.mark.parametrize("name", [
    "test_unknown_handle_cannot_write_topology_snapshot",
    "test_stale_compose_generation_refuses_before_any_restore_write",
    "test_stale_global_generation_cannot_enable_candidate_as_recovery_fallback",
    "test_lost_holder_stops_sticky_repository_compensation",
    "test_live_holder_converge_failure_restores_prior_control",
])
def test_substantive_neighbor_with_native_inputs(recovery, name):
    import test_aura_deploy_adjudication as neighbor

    # Keep the neighbor assertions and real producer/helper paths. Only supply
    # this module's native-source fixture, avoiding its historical source copy.
    getattr(neighbor, name)(recovery)
