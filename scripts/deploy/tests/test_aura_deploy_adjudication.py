"""D4 causal regressions for findings 19142–19145, with the real joined helper.

All effects stay in scratch. The independently supplied probes are also run
unchanged from /tmp (only their fixed ROOT is relocated).
"""

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/deploy/tests"))
sys.path.insert(1, str(ROOT / "scripts"))
import test_aura_edge_fence as edge_tests  # noqa: E402
import test_gtmr_aura_deploy as deploy_tests  # noqa: E402
from env.manifest import load_manifest  # noqa: E402
from env.materialize import run as materialize  # noqa: E402
from env.render_env import render_target  # noqa: E402


@pytest.fixture
def edge(tmp_path):
    yield from edge_tests.edge.__wrapped__(tmp_path)


def test_deploy_admission_refuses_cross_store_dsns_even_when_manifest_matches(tmp_path):
    fx = deploy_tests.Fixture(tmp_path)
    deploy_tests._seed_preflight(fx, "dev-auraface", deploy_tests._aura_bundle())
    manifest_root = ROOT / "config/env"
    manifest = load_manifest(manifest_root)
    bad = (
        "postgresql+asyncpg://acx_dev_auraface:fixture@postgres/"
        "alt_context_dev_auraface?user=acx_dev_fir&database=alt_context_dev_fir"
    )
    host = {
        name: [name + "=" + value]
        for name, value in {
            "POSTGRES_PASSWORD": "fixture",
            "POSTGRES_DSN": bad,
            "POSTGRES_SYNC_DSN": "postgresql+psycopg://acx_dev_fir:fixture@postgres/alt_context_dev_fir",
        }.items()
    }
    missing = set()
    text = render_target(manifest, "svc-auraface", "dev-auraface", host_lines=host, missing_host_keys=missing)
    env_file = fx.root / "opt/acx-backend/dev-auraface/.env"
    env_file.write_text(text)
    env_file.chmod(0o600)
    out, err = io.StringIO(), io.StringIO()
    assert not missing
    assert (
        materialize(
            manifest_root,
            env="dev-auraface",
            target="svc-auraface",
            into="/opt/acx-backend/dev-auraface/.env",
            check=True,
            fs_root=fx.root,
            backup_root=tmp_path / "backups",
            out=out,
            err=err,
        )
        == 0
    ), (out.getvalue(), err.getvalue())
    from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
    from sqlalchemy.engine import make_url

    _, arguments = PGDialect_asyncpg().create_connect_args(make_url(bad))
    assert (arguments["user"], arguments["database"]) == ("acx_dev_fir", "alt_context_dev_fir")
    result = deploy_tests._driver(fx, "preflight_remote_face_pipeline_models dev-auraface\n")
    assert result.returncode != 0, "cross-store DSNs reached successful model/deploy admission: " + result.stdout


def _failed_converge(edge, kill_holder):
    env_file = edge[1] / "dev/.env"
    env_file.parent.mkdir()
    env_file.write_text("ACX_IMAGE_REPO=example/old\n")
    fault = 'kill -KILL "$(cat "$ACX_EDGE_HANDLE/holder.pid")"' if kill_holder else ":"
    result = edge_tests.run(
        edge,
        """ACX_IMAGE_REPO=example/new
IMAGE_BASE=example/new
do_boot_smoke() { :; }
converge_runtime() {
"""
        + fault
        + """
 return 1
}
promote_gate dev example/new@sha256:"""
        + "a" * 64
        + "\n",
    )
    assert result.returncode != 0
    state = json.loads(env_file.read_text().split("# ACX_IMAGE_REPO_OWNER=", 1)[1])
    return result, state


def test_lost_holder_stops_sticky_repository_compensation(edge):
    result, state = _failed_converge(edge, True)
    assert "edge ownership lost" in result.stderr
    assert (edge[1] / "app/activation.journal").is_file()
    assert state["phase"] == "shipped", "continued .env rollback after holder loss: " + repr(state)


def test_live_holder_converge_failure_restores_prior_control(edge):
    result, state = _failed_converge(edge, False)
    assert "edge ownership lost" not in result.stderr
    assert state["phase"] == "restored"
    assert state["current"] == "example/old"


def test_unknown_handle_cannot_write_topology_snapshot(edge):
    (edge[1] / "dev").mkdir()
    result = edge_tests.run(
        edge, "ACX_EDGE_HANDLE=/tmp/unknown-ownership-handle\nprepare_runtime_topology_backups dev 0\n"
    )
    assert result.returncode != 0, "unknown owner created topology snapshot and latest pointer"
    assert not (edge[1] / "backups").exists()


@pytest.mark.parametrize("space", ["", "\v", "\f", "\x85", "prefix-CR"])
def test_restore_preserves_newer_portal_block_with_supported_whitespace(edge, space):
    _, remote, _ = edge
    caddy = remote / "Caddyfile"
    unmanaged = "dev.example.com {\n reverse_proxy dev-api:8000\n}\n\n"
    if space == "prefix-CR":
        unmanaged = "# safe comment " + "\r" * 12 + "\n" + unmanaged
        space = ""
    block = (
        "# BEGIN APP_PORTAL_VHOST\nportal.example.com {\n"
        + space * 12
        + "\n respond VERSION\n}\n# END APP_PORTAL_VHOST"
    )
    original = unmanaged + block.replace("VERSION", "old")
    current = unmanaged + block.replace("VERSION", "new")
    caddy.write_bytes(original.encode())
    saved = edge_tests.run(
        edge,
        """ACX_DEPLOY_TRANSACTION_ID=old-snapshot
recognition_edge_begin dev || exit $?
recognition_edge_remote snapshot dev || exit $?
recognition_edge_finish
""",
    )
    assert saved.returncode == 0, saved.stdout + saved.stderr
    # A completed portal publication between the two recognition transactions.
    caddy.write_bytes(current.encode())
    result = edge_tests.run(
        edge,
        """ACX_DEPLOY_TRANSACTION_ID=new-restore
recognition_edge_begin dev || exit $?
restore_edge_backups dev || exit $?
recognition_edge_finish
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected_block = block.replace("VERSION", "new").encode()
    actual_block = caddy.read_bytes().split(b"# BEGIN APP_PORTAL_VHOST", 1)[1]
    assert actual_block == expected_block.split(b"# BEGIN APP_PORTAL_VHOST", 1)[1], caddy.read_bytes()


def test_restore_does_not_erase_a_later_unrelated_edge_generation(edge):
    _, remote, _ = edge
    caddy = remote / "Caddyfile"
    original = caddy.read_bytes()
    saved = edge_tests.run(
        edge,
        """ACX_DEPLOY_TRANSACTION_ID=old-global-snapshot
recognition_edge_begin dev || exit $?
recognition_edge_remote snapshot dev || exit $?
recognition_edge_finish
""",
    )
    assert saved.returncode == 0, saved.stdout + saved.stderr
    # Later completed publication by another edge owner, with identical portal bytes.
    current = b"new-other-owner.example.com {\n respond healthy\n}\n\n" + original
    caddy.write_bytes(current)
    result = edge_tests.run(
        edge,
        """ACX_DEPLOY_TRANSACTION_ID=restore-old-dev-snapshot
recognition_edge_begin dev || exit $?
restore_edge_backups dev || exit $?
recognition_edge_finish
""",
    )
    # Refusal or a scoped merge are both acceptable; wholesale loss is not.
    assert b"new-other-owner.example.com" in caddy.read_bytes(), (
        result.returncode,
        result.stdout,
        result.stderr,
        caddy.read_bytes(),
    )


@pytest.mark.parametrize("key", ["POSTGRES_DSN", "POSTGRES_SYNC_DSN"])
@pytest.mark.parametrize(
    "fault",
    [
        "query-role",
        "query-database",
        "query-host",
        "duplicate-query",
        "hostaddr",
        "service",
        "options",
        "unknown-query",
        "role",
        "database",
        "host",
        "port",
        "missing-port",
        "missing-host",
        "missing-role",
        "missing-database",
        "wrong-driver",
        "fragment",
        "multihost",
        "duplicate-env",
        "uppercase-scheme",
    ],
)
def test_each_dsn_identity_or_ambiguity_refused_before_target_mutation(tmp_path, key, fault):
    fx = deploy_tests.Fixture(tmp_path)
    label = "dev-auraface"
    deploy_tests._seed_preflight(fx, label, deploy_tests._aura_bundle())
    driver = "asyncpg" if key == "POSTGRES_DSN" else "psycopg"
    good = f"postgresql+{driver}://acx_dev_auraface:PRIVATE_SENTINEL@postgres:5432/alt_context_dev_auraface"
    faults = {
        "query-role": good + "?user=acx_dev_fir",
        "query-database": good
        + ("?database=alt_context_dev_fir" if driver == "asyncpg" else "?dbname=alt_context_dev_fir"),
        "query-host": good + "?host=other-store",
        "duplicate-query": good + "?host=postgres&host=other-store",
        "hostaddr": good + "?hostaddr=127.0.0.2",
        "service": good + "?service=fir",
        "options": good + "?options=-csearch_path=fir",
        "unknown-query": good + "?unreviewed=1",
        "role": good.replace("acx_dev_auraface:", "acx_dev_fir:"),
        "database": good.replace("/alt_context_dev_auraface", "/alt_context_dev_fir"),
        "host": good.replace("@postgres:", "@other-store:"),
        "port": good.replace(":5432/", ":5433/"),
        "missing-port": good.replace("postgres:5432", "postgres"),
        "missing-host": good.replace("postgres:5432", ""),
        "missing-role": good.replace("acx_dev_auraface:", ":"),
        "missing-database": good.replace("/alt_context_dev_auraface", "/"),
        "wrong-driver": good.replace("+" + driver, "+psycopg2"),
        "fragment": good + "#ignored",
        "multihost": good.replace("@postgres:5432", "@postgres:5432,other-store:5432"),
        "duplicate-env": good,
        "uppercase-scheme": good.replace("postgresql", "POSTGRESQL"),
    }
    env_file = fx.root / "opt/acx-backend/dev-auraface/.env"
    text = env_file.read_text()
    lines = [line for line in text.splitlines() if not line.startswith(key + "=")]
    lines.append(key + "=" + faults[fault])
    if fault == "duplicate-env":
        lines.append(key + "=" + good)
    env_file.write_text("\n".join(lines) + "\n")
    before = env_file.read_bytes(), env_file.stat().st_ino
    result = deploy_tests._driver(fx, "preflight_remote_face_pipeline_models dev-auraface")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert (env_file.read_bytes(), env_file.stat().st_ino) == before
    assert not fx.seen("mutations") and not fx.seen("scp") and not fx.seen("docker")


@pytest.mark.parametrize("label", deploy_tests.AURA)
@pytest.mark.parametrize("port", [":5432"])
def test_admitted_dsn_subset_matches_actual_async_and_sync_driver_arguments(tmp_path, label, port):
    from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
    from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
    from sqlalchemy.engine import make_url

    fx = deploy_tests.Fixture(tmp_path)
    deploy_tests._seed_preflight(fx, label, deploy_tests._aura_bundle())
    role = "acx_" + label.replace("-", "_")
    database = "alt_context_" + label.replace("-", "_")
    env_file = fx.root / f"opt/acx-backend/{label}/.env"
    text = env_file.read_text()
    for key, driver, dialect, dbkey in [
        ("POSTGRES_DSN", "asyncpg", PGDialect_asyncpg(), "database"),
        ("POSTGRES_SYNC_DSN", "psycopg", PGDialect_psycopg(), "dbname"),
    ]:
        # Percent escapes in the credentials/path have driver semantics, never
        # dotenv evaluation or shell interpolation. No driver connects here.
        dsn = f"postgresql+{driver}://{role}:p%40ss%3Aword@postgres{port}/{database}"
        _, arguments = dialect.create_connect_args(make_url(dsn))
        assert arguments["host"] == "postgres"
        assert int(arguments.get("port", 5432)) == 5432
        assert arguments["user"] == role and arguments[dbkey] == database
        assert arguments["password"] == "p@ss:word"
        text = (
            "\n".join(line for line in text.splitlines() if not line.startswith(key + "="))
            + "\n"
            + key
            + "="
            + dsn
            + "\n"
        )
    env_file.write_text(text)
    result = deploy_tests._driver(fx, f"preflight_remote_face_pipeline_models {label}")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not fx.seen("mutations") and not fx.seen("scp") and not fx.seen("docker")


@pytest.mark.parametrize(
    "operation",
    [
        'image_repo_resource claim "$REMOTE_ROOT/dev" "" ""',
        "restore_prior_image_repo_env",
        "restore_topology_backups dev",
        "install_rendered_unit dev",
        "repair_blob_volume_ownership dev",
        "recreate_cutover_candidate dev",
        "abort_cutover_candidate dev",
        "enable_cutover_candidate dev",
        "commit_cutover_state dev",
        "do_restart dev",
        "restore_runtime_and_edge dev",
        "staged_rollback_runtime dev",
        "write_deployed_release_receipt dev " + "a" * 40 + " example/image@sha256:" + "b" * 64,
    ],
)
@pytest.mark.parametrize("ownership", ["missing", "unknown", "dead", "expired"])
def test_every_runtime_mutation_entry_refuses_unowned_compensation(edge, operation, ownership):
    remote = edge[1]
    (remote / "dev").mkdir()
    (remote / "dev/.env").write_text("ACX_IMAGE_REPO=example/old\n")
    protected = [
        remote / "Caddyfile",
        remote / "docker-compose.caddy.yml",
        remote / "app/docker-compose.app.yml",
        remote / "dev/.env",
    ]
    before = [(p.read_bytes(), p.stat().st_ino) for p in protected]
    faults = {
        "missing": ":",
        "unknown": "ACX_EDGE_HANDLE=/tmp/unknown-handle",
        "dead": 'recognition_edge_begin dev || exit $?\nkill -KILL "$(cat "$ACX_EDGE_HANDLE/holder.pid")"',
        "expired": 'recognition_edge_begin dev || exit $?\nprintf "1\\n" >"$ACX_EDGE_HANDLE/expires"',
    }
    result = edge_tests.run(edge, faults[ownership] + "\nACX_PRIOR_IMAGE_REPO_ENV=dev\n" + operation)
    assert result.returncode != 0, result.stdout + result.stderr
    assert [(p.read_bytes(), p.stat().st_ino) for p in protected] == before
    assert not (remote / "backups").exists()
    assert not Path(edge[2]["DOCKER_RECORD"]).exists()
    if ownership in ("dead", "expired"):
        assert (remote / "app/activation.journal").is_file()


def test_stale_compose_generation_refuses_before_any_restore_write(edge):
    remote = edge[1]
    saved = edge_tests.run(
        edge, "recognition_edge_begin dev && recognition_edge_remote snapshot dev && recognition_edge_finish"
    )
    assert saved.returncode == 0, saved.stdout + saved.stderr
    compose = remote / "docker-compose.caddy.yml"
    compose.write_text("services: {caddy: {image: newer-owner}}\n")
    protected = [remote / "Caddyfile", compose, remote / "app/docker-compose.app.yml"]
    before = [(p.read_bytes(), p.stat().st_ino) for p in protected]
    snapshots = {p: p.read_bytes() for p in (remote / "backups").rglob("*") if p.is_file()}
    result = edge_tests.run(edge, "ACX_DEPLOY_TRANSACTION_ID=fresh-restore\nrestore_edge_backups dev")
    assert result.returncode != 0, result.stdout + result.stderr
    assert "generation" in result.stderr
    assert [(p.read_bytes(), p.stat().st_ino) for p in protected] == before
    assert {p: p.read_bytes() for p in snapshots} == snapshots
    assert not (remote / "backups/dev/fresh-restore").exists()
    assert (remote / "app/activation.journal").is_file()
    assert not Path(edge[2]["DOCKER_RECORD"]).exists()


def test_holder_death_between_snapshot_commands_stops_all_later_writes(edge):
    remote = edge[1]
    directory = remote / "dev"
    directory.mkdir()
    compose = directory / "docker-compose.env.yml"
    compose.write_text("prior compose\n")
    sudo = Path(edge[2]["PATH"].split(":")[0]) / "sudo"
    # The first real copy finishes, then its holder dies before the next
    # command. No compatibility backup or latest/ready publication may follow.
    sudo.write_text("""#!/bin/bash
"$@"
rc=$?
if [[ "$1" == cp && "$*" == *"docker-compose.env.yml"* ]]; then
  handle=$(sed -n "s/^handle=//p" "$APP_ROOT/activation.journal")
  kill -KILL "$(cat "$handle/holder.pid")"
fi
exit "$rc"
""")
    sudo.chmod(0o755)
    result = edge_tests.run(edge, "ACX_DEPLOY_TRANSACTION_ID=mid-snapshot\nprepare_runtime_topology_backups dev 0")
    assert result.returncode != 0, result.stdout + result.stderr
    snapshot = remote / "backups/dev/mid-snapshot"
    assert (snapshot / "docker-compose.env.yml").read_text() == "prior compose\n"
    assert compose.read_text() == "prior compose\n"
    assert not (directory / "docker-compose.env.yml.bak").exists()
    assert not (snapshot / "topology.ready").exists()
    assert not (remote / "backups/dev/latest").exists()
    assert (remote / "app/activation.journal").is_file()


def test_owned_unit_install_and_receipt_complete_with_real_helper(edge):
    remote = edge[1]
    directory = remote / "dev"
    directory.mkdir()
    result = edge_tests.run(
        edge,
        """recognition_edge_begin dev || exit $?
recognition_edge_install /etc/systemd/system/acx-dev.service "fixture unit" || exit $?
write_deployed_release_receipt dev """
        + "a" * 40
        + " example/image@sha256:"
        + "b" * 64
        + "\nrecognition_edge_finish\n",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (remote / "systemd/acx-dev.service").read_text() == "fixture unit"
    receipt = json.loads((directory / "deployed-release.json").read_text())
    assert receipt["env"] == "dev" and receipt["sha"] == "a" * 40
    assert not (remote / "app/activation.journal").exists()


def test_fir_preflight_keeps_its_existing_dsn_contract(tmp_path):
    fx = deploy_tests.Fixture(tmp_path)
    deploy_tests._seed_preflight(fx, "dev-fir", deploy_tests._fir_bundle())
    env_file = fx.root / "opt/acx-backend/dev-fir/.env"
    with env_file.open("a") as stream:
        stream.write("POSTGRES_DSN=legacy\nPOSTGRES_DSN=opaque\nPOSTGRES_SYNC_DSN=legacy\n")
    result = deploy_tests._driver(fx, "preflight_remote_face_pipeline_models dev-fir")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not fx.seen("mutations") and not fx.seen("docker")


def test_stale_global_generation_cannot_enable_candidate_as_recovery_fallback(edge):
    remote = edge[1]
    saved = edge_tests.run(
        edge, "recognition_edge_begin dev && recognition_edge_remote snapshot dev && recognition_edge_finish"
    )
    assert saved.returncode == 0, saved.stdout + saved.stderr
    caddy = remote / "Caddyfile"
    caddy.write_bytes(b"later.example.com {\n respond healthy\n}\n\n" + caddy.read_bytes())
    before = caddy.read_bytes(), caddy.stat().st_ino
    result = edge_tests.run(
        edge,
        """ACX_DEPLOY_TRANSACTION_ID=stale-recovery
ACX_CUTOVER_ENV=dev
ACX_TRAFFIC_FLIPPED=1
enable_cutover_candidate() { printf enabled >"$REMOTE_ROOT/unsafe-fallback"; }
recover_interrupted_cutover
""",
    )
    assert result.returncode == 75, result.stdout + result.stderr
    assert (caddy.read_bytes(), caddy.stat().st_ino) == before
    assert not (remote / "unsafe-fallback").exists()
    assert not Path(edge[2]["DOCKER_RECORD"]).exists()
    assert (remote / "app/activation.journal").is_file()
