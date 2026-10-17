"""D recognition edge consumers tested with P's real frozen helper in a scratch checkout.

Before the P lane joins, set AURA_EDGE_TEST_HELPER to the supplied frozen helper.
No helper files are copied into the authored source tree.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import _write_executable

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/recognition-service.sh"


@pytest.fixture
def edge(tmp_path):
    deploy = tmp_path / "checkout/scripts/deploy"
    (deploy / "lib").mkdir(parents=True)
    shutil.copy(SCRIPT, deploy / SCRIPT.name)
    for name in ("bounded-remote-build.sh", "ocir-auth.sh"):
        shutil.copy(SCRIPT.parent / "lib" / name, deploy / "lib" / name)
    helper = Path(os.environ.get("AURA_EDGE_TEST_HELPER", SCRIPT.parent / "lib/shared-edge.sh"))
    assert helper.is_file(), "join P helper or supply AURA_EDGE_TEST_HELPER for isolated D ABI verification"
    shutil.copy(helper, deploy / "lib/shared-edge.sh")
    remote = tmp_path / "remote"
    app = remote / "app"
    app.mkdir(parents=True)
    (remote / "Caddyfile").write_text(
        "dev.example.com {\n reverse_proxy dev-api:8000\n}\n\n# BEGIN APP_PORTAL_VHOST\nportal.example.com {\n root * /www\n file_server\n}\n# END APP_PORTAL_VHOST"
    )
    (remote / "docker-compose.caddy.yml").write_text("services: {}\n")
    (app / "docker-compose.app.yml").write_text("services: {}\n")
    binary = tmp_path / "bin"
    binary.mkdir()
    _write_executable(binary / "sudo", '#!/bin/sh\nexec "$@"\n')
    _write_executable(
        binary / "ssh",
        '#!/bin/bash\nremote="${@: -1}"\nremote=${remote//\\/opt\\/acx-backend/$REMOTE_ROOT}\nremote=${remote//\\/etc\\/systemd\\/system/$SYSTEMD_ROOT}\nif [[ "$remote" == "bash -s" ]]; then sed "s|/opt/acx-backend|$REMOTE_ROOT|g" | bash -s; else exec bash -c "$remote"; fi\n',
    )
    _write_executable(
        binary / "docker",
        r"""#!/usr/bin/env python3
import json,os,sys,time
from pathlib import Path
args=sys.argv[1:]
with open(os.environ["DOCKER_RECORD"],"a") as f: f.write(" ".join(args)+"\n")
if "config" in args:
    if os.environ.get("FAIL_CONFIG"): sys.exit(1)
    if os.environ.get("STALL_CONFIG"): time.sleep(6)
    model=json.loads(os.environ.get("COMPOSE_MODEL",'{"services":{"caddy":{"networks":{"legacy":null}}},"networks":{"legacy":{"name":"legacy-real"}}}'))
    if "-f" in args:
        text=Path(args[args.index("-f")+1]).read_text()
        if text.startswith("{"): model=json.loads(text)
    print(json.dumps(model))
elif "ps" in args: print("aaaaaaaaaaaa")
elif "inspect" in args: print(os.environ.get("INSPECT_NETWORKS",'{"legacy-real":{}}'))
elif args[:2] == ["network","ls"]: print("legacy-real\nacx-dev-fir-net")
elif "reload" in args:
    if os.environ.get("KILL_HOLDER_ON_RELOAD"):
        fields=dict(line.split("=",1) for line in (Path(os.environ["APP_ROOT"])/"activation.journal").read_text().splitlines())
        holder=int((Path(fields["handle"])/"holder.pid").read_text())
        os.kill(holder,9)
        sys.exit(5)
    if os.environ.get("FAIL_RELOAD"): sys.exit(5)
elif "validate" in args and os.environ.get("STALL_VALIDATE"):
    Path(os.environ["STALLED_RECORD"]).write_text("connected")
    time.sleep(6)
""",
    )
    env = dict(os.environ, PATH=f"{binary}:{os.environ['PATH']}", DOCKER_RECORD=str(tmp_path / "docker.log"))
    (remote / "systemd").mkdir()
    env["SYSTEMD_ROOT"] = str(remote / "systemd")
    env["REMOTE_ROOT"] = str(remote)
    _write_executable(binary / "systemctl", "#!/bin/sh\nexit 0\n")
    env["APP_ROOT"] = str(app)
    env["ACX_REMOTE_COMMAND_TIMEOUT"] = "30"
    env["EDGE_LOCK_STATE_ROOT"] = str(tmp_path)
    yield deploy / SCRIPT.name, remote, env
    # Real detached holders are always released, including assertion failures.
    for handle in tmp_path.glob("shared-edge-lock.*"):
        subprocess.run(
            ["bash", "-c", f"source {shlex.quote(str(helper))}; edge_lock_release {shlex.quote(str(handle))} 2"],
            env=env,
            text=True,
            capture_output=True,
            timeout=5,
        )


def run(edge, body, **values):
    script, remote, env = edge
    env = dict(env, **values)
    command = (
        f"source {shlex.quote(str(script))}\nACX_DEPLOY_BACKUP_ROOT={shlex.quote(str(remote / 'backups'))}\n" + body
    )
    return subprocess.run(["bash", "-c", command], env=env, text=True, capture_output=True, timeout=60)


@pytest.mark.parametrize(
    "operation", ["flip_edge_alias dev next", "restore_edge_backups dev", "prepare_runtime_topology_backups dev 1"]
)
def test_lost_handle_refuses_before_any_edge_write(edge, operation):
    _, remote, _ = edge
    caddy = remote / "Caddyfile"
    before = caddy.read_bytes()
    inode = caddy.stat().st_ino
    result = run(
        edge,
        f"ACX_EDGE_HANDLE=/tmp/unknown-ownership-handle\nACX_CANDIDATE_DIGEST_REF=example/image@sha256:{'a' * 64}\n{operation}\n",
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert caddy.read_bytes() == before
    assert caddy.stat().st_ino == inode
    assert not (remote / "backups").exists(), "lost owner wrote snapshot/journal state"


def test_flip_and_restore_preserve_portal_bytes_overlay_and_bind_inode(edge):
    _, remote, _ = edge
    caddy = remote / "Caddyfile"
    original = caddy.read_bytes()
    inode = caddy.stat().st_ino
    overlay = remote / "app/docker-compose.app.yml"
    overlay_bytes = overlay.read_bytes()
    result = run(
        edge,
        f'''ACX_CANDIDATE_DIGEST_REF=example/image@sha256:{"a" * 64}
recognition_edge_begin dev || exit $?
flip_edge_alias dev next || exit $?
grep -q 'dev-api-next:8000' "{caddy}" || exit 91
restore_edge_backups dev || exit $?
recognition_edge_finish || exit $?
''',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert caddy.read_bytes() == original
    assert caddy.stat().st_ino == inode
    assert overlay.read_bytes() == overlay_bytes
    assert not (remote / "app/activation.journal").exists()


def test_portal_pending_journal_refuses_without_live_changes(edge):
    _, remote, _ = edge
    journal = remote / "app/activation.journal"
    journal.write_text("version=2\nphase=prepared\n")
    before = (remote / "Caddyfile").read_bytes()
    result = run(edge, "recognition_edge_begin dev\n")
    assert result.returncode != 0
    assert "journal" in result.stderr
    assert (remote / "Caddyfile").read_bytes() == before
    assert journal.read_text() == "version=2\nphase=prepared\n"


def test_dead_holder_keeps_journal_and_prevents_fallback(edge):
    _, remote, _ = edge
    result = run(
        edge,
        f"""recognition_edge_begin dev || exit $?
kill -KILL "$(cat "$ACX_EDGE_HANDLE/holder.pid")"
ACX_CANDIDATE_DIGEST_REF=example/image@sha256:{"a" * 64}
flip_edge_alias dev next
""",
    )
    assert result.returncode != 0
    assert (remote / "app/activation.journal").exists()
    assert b"dev-api-next" not in (remote / "Caddyfile").read_bytes()
    assert not Path(edge[2]["DOCKER_RECORD"]).exists()


def test_dead_holder_after_reload_error_blocks_recreate_fallback(edge):
    _, remote, _ = edge
    result = run(
        edge,
        f"""recognition_edge_begin dev || exit $?
ACX_CANDIDATE_DIGEST_REF=example/image@sha256:{"a" * 64}
flip_edge_alias dev next
""",
        KILL_HOLDER_ON_RELOAD="1",
    )
    assert result.returncode != 0
    assert (remote / "app/activation.journal").exists()
    commands = Path(edge[2]["DOCKER_RECORD"]).read_text()
    assert "reload" in commands
    assert " up " not in " " + commands


def test_alive_owner_reload_failure_has_bounded_recreate_fallback(edge):
    result = run(
        edge,
        f"""recognition_edge_begin dev || exit $?
ACX_CANDIDATE_DIGEST_REF=example/image@sha256:{"a" * 64}
flip_edge_alias dev next || exit $?
flip_edge_alias dev canonical || exit $?
recognition_edge_finish
""",
        FAIL_RELOAD="1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    commands = Path(edge[2]["DOCKER_RECORD"]).read_text()
    assert "reload" in commands and "up -d --force-recreate --no-deps caddy" in commands
    assert "docker-compose.app.yml" in commands


def test_converge_uses_actual_names_and_omits_absent_other_aura_tiers(edge):
    import base64
    import json

    _, remote, _ = edge
    model = {
        "services": {
            "caddy": {"networks": {"legacy": None, "aura_dev": None, "aura_staging": None, "aura_prod": None}}
        },
        "networks": {
            "legacy": {"name": "legacy-real"},
            "aura_dev": {"name": "acx-dev-auraface-net"},
            "aura_staging": {"name": "acx-staging-auraface-net"},
            "aura_prod": {"name": "acx-prod-auraface-net"},
        },
    }
    compose = base64.b64encode(json.dumps(model).encode()).decode()
    caddy = base64.b64encode(b"aura.example.com {\n reverse_proxy dev-auraface-api:8000\n}\n").decode()
    result = run(
        edge,
        f"""recognition_edge_begin dev-auraface || exit $?
recognition_edge_remote converge dev-auraface {caddy} {compose} || exit $?
recognition_edge_finish
""",
        COMPOSE_MODEL=json.dumps(model),
        INSPECT_NETWORKS='{"legacy-real":{},"acx-dev-auraface-net":{}}',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    installed = json.loads((remote / "docker-compose.caddy.yml").read_text())
    assert set(installed["services"]["caddy"]["networks"]) == {"legacy", "aura_dev"}
    commands = Path(edge[2]["DOCKER_RECORD"]).read_text().splitlines()
    creates = [line for line in commands if line.startswith("network create")]
    assert len(creates) == 1 and creates[0].endswith(" acx-dev-auraface-net"), creates


def test_stalled_validation_is_bounded_and_retains_journal(edge):
    import time

    _, remote, _ = edge
    record = remote / "stalled"
    acquired = run(edge, "recognition_edge_begin dev")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    journal = dict(line.split("=", 1) for line in (remote / "app/activation.journal").read_text().splitlines())
    started = time.monotonic()
    # Exercise the real validation operation after prerequisite snapshot work:
    # append it after the emitted check action, keeping the production functions
    # and the frozen helper intact across a separate SSH invocation.
    result = run(
        edge,
        f"""ACX_EDGE_HANDLE={shlex.quote(journal["handle"])}
ACX_EDGE_ENV=dev
ACX_DEPLOY_TRANSACTION_ID={shlex.quote(journal["transaction"])}
ACX_REMOTE_COMMAND_TIMEOUT=2
original_program="$(recognition_edge_program)"
recognition_edge_program() {{ printf '%s\\n' "$original_program"; printf 'edge_apply reload\\n'; }}
recognition_edge_remote check dev
""",
        STALL_VALIDATE="1",
        STALLED_RECORD=str(record),
    )
    elapsed = time.monotonic() - started
    assert result.returncode != 0
    assert record.exists(), result.stdout + result.stderr
    assert elapsed < 6, elapsed
    assert (remote / "app/activation.journal").exists()
    assert b"dev-api-next" not in (remote / "Caddyfile").read_bytes()


def test_converge_installs_real_compose_bootstrap_bind_and_scoped_unit(edge):
    import json

    _, remote, _ = edge
    env_root = remote / "dev-auraface"
    env_root.mkdir()
    (env_root / ".env").write_text("RECOGNITION_SECRET_BACKEND=env\n")
    model = {
        "services": {"caddy": {"networks": {"legacy": None, "aura": None}}},
        "networks": {"legacy": {"name": "legacy-real"}, "aura": {"name": "acx-dev-auraface-net"}},
    }
    app = ROOT / "apps/prototype-description-service"
    result = run(
        edge,
        f"""SERVICE_DIR={shlex.quote(str(app))}
ACX_EDGE_APPLY=1
converge_runtime dev-auraface || exit $?
recognition_edge_finish
""",
        COMPOSE_MODEL=json.dumps(model),
        INSPECT_NETWORKS='{"legacy-real":{},"acx-dev-auraface-net":{}}',
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (env_root / "docker-compose.env.yml").read_bytes() == (app / "docker-compose.env.yml").read_bytes()
    assert (env_root / "db/docker-prod-init/001-extensions.sql").read_bytes() == (
        app / "db/docker-prod-init/001-extensions.sql"
    ).read_bytes()
    unit = (remote / "systemd/acx-dev-auraface.service").read_text()
    assert "WorkingDirectory=/opt/acx-backend/dev-auraface" in unit
    assert " stop api worker" in unit
    assert not (env_root / "docker-compose.admin.yml").exists()
