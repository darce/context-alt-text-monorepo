"""D5-B / D4-C1 (19142): admission must match native driver database identity.

The D4 boundary probe is retained in the immutable D5-context, including its old
scratch paths and failure log. These owned tests use the complete native checkout,
real SQLAlchemy argument producers, and the existing bounded preflight fixture.
No engine is created and no driver connects. Model files contain fixture bytes.

Run against the D5-B candidate temporarily applied to recognition-service.sh;
the published script belongs to the later mechanical join. No helper ABI changes.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
import test_gtmr_aura_deploy as native
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.engine import make_url

DRIVERS = (
    ("POSTGRES_DSN", "asyncpg", PGDialect_asyncpg, "database"),
    ("POSTGRES_SYNC_DSN", "psycopg", PGDialect_psycopg, "dbname"),
)
PRIVATE = "PRIVATE_D5_SENTINEL"


@pytest.fixture
def fx(tmp_path):
    fixture = native.Fixture(tmp_path)
    # Match the actual producer ABI: ssh -l deploy-test -- fake-host.invalid ...
    # Keep the existing command relocation; deny any unexpected transport target.
    ssh = fixture.bin / "ssh"
    body = ssh.read_text()
    marker = 'remote=""\n'
    assert body.count(marker) == 1
    ssh.write_text(
        body.replace(
            marker,
            '[[ "${args[host_at]}" == "fake-host.invalid" ]] || {\n'
            '  echo "unexpected SSH target denied" >&2; exit 98;\n'
            "}\n" + marker,
            1,
        )
    )
    return fixture


def _set_env(fixture, label: str, **updates: str) -> None:
    path = fixture.root / f"opt/acx-backend/{label}/.env"
    lines = [line for line in path.read_text().splitlines() if line.split("=", 1)[0] not in updates]
    path.write_text("\n".join([*lines, *(f"{key}={value}" for key, value in updates.items())]) + "\n")


def _protected_state(root: Path) -> dict:
    return {
        str(path.relative_to(root)): (path.read_bytes(), path.stat().st_ino, stat.S_IMODE(path.stat().st_mode))
        for path in root.rglob("*")
        if path.is_file()
    }


def _preflight(fixture, label: str, *, admitted: bool, secrets: tuple[str, ...]):
    before = _protected_state(fixture.root)
    result = native._driver(fixture, f"preflight_remote_face_pipeline_models {label}")
    output = result.stdout + result.stderr
    transcript = output + "".join(fixture.seen(name) for name in ("ssh", "scp", "mutations", "docker", "curl"))
    for secret in secrets:
        assert secret not in transcript, "preflight disclosed a credential"
    assert _protected_state(fixture.root) == before
    assert not any(fixture.seen(name) for name in ("mutations", "docker", "scp", "curl"))
    if admitted:
        assert result.returncode == 0, output
        if label in native.AURA:
            assert "ONNX weights present and sha256-verified" in output
    else:
        assert result.returncode != 0, "admitted database differs from actual driver database argument"
        assert "Aura database identity refused" in output
        # Refusal happens after the one dotenv snapshot, before model verification.
        assert len(fixture.seen("ssh").splitlines()) == 1
        assert "ONNX weights present" not in output


def _dsn(label: str, driver: str, database: str, password: str = PRIVATE, *, user: str | None = None) -> str:
    role = user if user is not None else "acx_" + label.replace("-", "_")
    return f"postgresql+{driver}://{role}:{password}@postgres:5432/{database}"


def _driver_arguments(dsn: str, dialect_type):
    args, kwargs = dialect_type().create_connect_args(make_url(dsn))
    assert args == []
    return kwargs


@pytest.mark.parametrize("key,driver,dialect_type,dbkey", DRIVERS, ids=["asyncpg", "psycopg"])
@pytest.mark.parametrize("encoded", [False, True], ids=["exact-control", "D4-encoded"])
def test_native_d4_database_identity(fx, key, driver, dialect_type, dbkey, encoded):
    """Adapt the native D4 encoded/exact cases without changing their evidence."""
    label = "dev-auraface"
    native._seed_preflight(fx, label, native._aura_bundle())
    database = "alt_context_dev_%61uraface" if encoded else "alt_context_dev_auraface"
    dsn = _dsn(label, driver, database)
    arguments = _driver_arguments(dsn, dialect_type)
    assert arguments[dbkey] == database
    assert (arguments[dbkey] == "alt_context_dev_auraface") is not encoded
    _set_env(fx, label, **{key: dsn})
    _preflight(fx, label, admitted=not encoded, secrets=(PRIVATE, dsn))


@pytest.mark.parametrize("label", native.AURA)
@pytest.mark.parametrize("credentials", ["plain", "escaped-password", "escaped-user-and-password"])
def test_exact_database_and_encoded_credentials_match_both_drivers(fx, label, credentials):
    native._seed_preflight(fx, label, native._aura_bundle())
    role = "acx_" + label.replace("-", "_")
    database = "alt_context_" + label.replace("-", "_")
    password = PRIVATE if credentials == "plain" else PRIVATE + "%40ss%3Aword%25%2F%3F%23%5C"
    decoded = PRIVATE if credentials == "plain" else PRIVATE + "@ss:word%/?#\\"
    user = role.replace("acx", "%61cx", 1) if credentials == "escaped-user-and-password" else role
    dsns = {}
    for key, driver, dialect_type, dbkey in DRIVERS:
        dsn = _dsn(label, driver, database, password, user=user)
        arguments = _driver_arguments(dsn, dialect_type)
        assert arguments[dbkey] == database
        assert arguments["host"] == "postgres" and arguments["port"] == 5432
        assert arguments["user"] == role and arguments["password"] == decoded
        dsns[key] = dsn
    _set_env(fx, label, **dsns)
    _preflight(fx, label, admitted=True, secrets=(PRIVATE, password, decoded, *dsns.values()))


@pytest.mark.parametrize("label", native.AURA)
@pytest.mark.parametrize("key,driver,dialect_type,dbkey", DRIVERS, ids=["asyncpg", "psycopg"])
@pytest.mark.parametrize("escape", ["lower-hex", "upper-hex", "whole-name", "double-escape"])
def test_escaped_database_is_not_the_isolated_store(fx, label, key, driver, dialect_type, dbkey, escape):
    native._seed_preflight(fx, label, native._aura_bundle())
    expected = "alt_context_" + label.replace("-", "_")
    variants = {
        "lower-hex": expected.replace("_", "%5f", 1),
        "upper-hex": expected.replace("_", "%5F", 1),
        "whole-name": "".join(f"%{ord(c):02x}" for c in expected),
        "double-escape": expected.replace("auraface", "%2561uraface"),
    }
    database = variants[escape]
    password = PRIVATE + "%40ss%3Aword"
    dsn = _dsn(label, driver, database, password)
    arguments = _driver_arguments(dsn, dialect_type)
    assert arguments[dbkey] == database and arguments[dbkey] != expected
    assert arguments["password"] == PRIVATE + "@ss:word"
    _set_env(fx, label, **{key: dsn})
    _preflight(fx, label, admitted=False, secrets=(PRIVATE, password, arguments["password"], dsn))


@pytest.mark.parametrize("label", ["dev", "staging", "prod"])
def test_generic_preflight_retains_its_existing_dsn_contract(fx, label):
    native._seed_env(fx, label)
    _set_env(fx, label, POSTGRES_DSN="legacy_%61", POSTGRES_SYNC_DSN="opaque")
    _preflight(fx, label, admitted=True, secrets=(PRIVATE,))
    assert len(fx.seen("ssh").splitlines()) == 1


def test_fixture_denies_unexpected_ssh_target(fx):
    result = native._driver(fx, "ssh -l deploy-test -- unapproved.invalid true")
    assert result.returncode == 98
    assert "unexpected SSH target denied" in result.stderr
    assert not fx.seen("ssh")
