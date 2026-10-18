"""Supplemental RED contract for the Aura operator labels in the tenant CLIs (GTMR K lane, extra cases).

Companion to the frozen test_gtmr_aura_cli.py (375 tests, immutable). This module adds narrow cases the frozen contract
omits. It is not a cartesian product: each case is one distinct vector (a guard path, an effective-DSN override, a
malformed identity, or a maintained generic store), crossed only with the labels it concerns.

Both CLIs are driven in-process through run() with fake settings (get_database_settings), fake sessions (_GuardedSession)
and dispatch spies (_Ops). No database, network, secret or runtime is touched.

Contract under test (ad-aura-cli-scope supplemental K contract, F3/F4/F7):

* portal --env prod with a matching ACX_ENV must still apply the DSN loopback guard. The portal guard returns early on a
  matching ACX_ENV, so a loopback DSN is accepted today (F3). Nonlocal Compose postgres must stay accepted.
* matched portal dev keeps its no-settings-read fast path (test_manage_portal_invitations.py asserts the same).
* legal nonlocal Compose postgres acceptance stays green for maintained generic stacks (prod, staging, dev-fir), so the
  Aura guard cannot leak into generic or FIR flows.
* effective DSN overrides cannot bypass the exact Aura identity. Query user, database, host and options overrides, and
  missing or malformed identity or host, are refused without echoing the credential.
* maintained generic stores and mixed role/database pairs refuse every Aura label. Census: config/env/manifest.d/
  10-service-shared.toml POSTGRES_USER / POSTGRES_DB. Generic prod is acx_app, not acx_prod.

Expected status on unchanged production (to be recorded by the parent before any implementation):
* controls ........................ GREEN: current accept paths hold
* portal matched prod loopback .... RED: the portal guard accepts (exit 0 instead of the runtime refusal, exit 1)
* Aura refusals ................... RED: argparse rejects the label (exit 2 instead of the runtime refusal, exit 1)
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest

_APP_ROOT = pathlib.Path(__file__).resolve().parents[3]
_API_CLI_PATH = _APP_ROOT / "scripts" / "manage_api_keys.py"
_PORTAL_CLI_PATH = _APP_ROOT / "scripts" / "manage_portal_invitations.py"

_REFUSED = "refusing to run"
# Placeholder canary. It is asserted absent from refusal output and is never a real credential.
_CANARY = "gtmr-extra-canary-credential"
_EXPIRES_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_API_TENANT = str(uuid.UUID(int=1))

# Operator-frozen Aura targets. Names are proposed configuration, not observed resources. generic_role and
# generic_database name the maintained same-stack generic store used for the mixed-identity overrides below.
AURA_TARGETS: dict[str, dict[str, str]] = {
    "dev-auraface": {
        "role": "acx_dev_auraface",
        "database": "alt_context_dev_auraface",
        "generic_role": "acx_dev",
        "generic_database": "alt_context_dev",
    },
    "staging-auraface": {
        "role": "acx_staging_auraface",
        "database": "alt_context_staging_auraface",
        "generic_role": "acx_staging",
        "generic_database": "alt_context_staging",
    },
    "prod-auraface": {
        "role": "acx_prod_auraface",
        "database": "alt_context_prod_auraface",
        "generic_role": "acx_app",
        "generic_database": "alt_context_service",
    },
}
AURA_LABELS = tuple(AURA_TARGETS)

# Maintained generic stores from config/env/manifest.d/10-service-shared.toml (POSTGRES_USER, POSTGRES_DB), keyed by the
# ACX_ENV selector. The Compose project for each is acx-<selector>. Generic prod is acx_app, not acx_prod.
MAINTAINED_STORES: dict[str, tuple[str, str]] = {
    "dev": ("acx_dev", "alt_context_dev"),
    "staging": ("acx_staging", "alt_context_staging"),
    "prod": ("acx_app", "alt_context_service"),
    "dev-fir": ("acx_dev_fir", "alt_context_dev_fir"),
}
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]", "host.local")

_API_ARGV: dict[str, list[str]] = {
    "list": ["list", "--tenant", _API_TENANT],
    "tenant-create": ["tenant", "create", "--tenant", _API_TENANT, "--site-url", "http://aura.test"],
}
_API_LIFECYCLE = frozenset({"_cmd_create", "_cmd_list", "_cmd_revoke", "_cmd_tenant_create", "_cmd_tenant_list"})
_PORTAL_ARGV: dict[str, list[str]] = {
    "list": ["list"],
    "create": ["create", "--email", "operator@example.test"],
}
_PORTAL_LIFECYCLE = frozenset({"_create", "_list", "_revoke"})


@dataclass(frozen=True)
class _Runtime:
    """What a CLI invocation can observe: ACX_ENV, COMPOSE_PROJECT_NAME and the DSN returned by fake settings."""

    acx_env: str | None
    compose_project: str | None
    dsn: str


@dataclass(frozen=True)
class _Outcome:
    code: int
    out: str
    err: str


def _raw_dsn(
    *,
    user: str | None,
    database: str | None,
    host: str | None = "postgres",
    port: str = "5432",
    query: str = "",
) -> str:
    """Placeholder asyncpg DSN. The canary is the only credential; host=None yields a netloc without a host."""
    netloc = f"{user or ''}:{_CANARY}@{host}:{port}" if host is not None else f"{user or ''}:{_CANARY}@"
    return f"postgresql+asyncpg://{netloc}/{database or ''}{query}"


def _dedicated_dsn(label: str, *, query: str = "") -> str:
    target = AURA_TARGETS[label]
    return _raw_dsn(user=target["role"], database=target["database"], query=query)


def _runtime(label: str, dsn: str) -> _Runtime:
    return _Runtime(label, f"acx-{label}", dsn)


def _load_cli(path: pathlib.Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_runtime(monkeypatch, runtime: _Runtime, reads: list[str] | None = None) -> None:
    """Set ACX_ENV and COMPOSE_PROJECT_NAME and replace the settings getter with a fake that records each read."""
    from db import settings as db_settings

    if runtime.acx_env is None:
        monkeypatch.delenv("ACX_ENV", raising=False)
    else:
        monkeypatch.setenv("ACX_ENV", runtime.acx_env)
    if runtime.compose_project is None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    else:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", runtime.compose_project)

    def fake_settings() -> SimpleNamespace:
        if reads is not None:
            reads.append(runtime.dsn)
        return SimpleNamespace(postgres_dsn=runtime.dsn)

    monkeypatch.setattr(db_settings, "get_database_settings", fake_settings)


class _Ops:
    """Ordered record of every operation that reaches a spy or the session factory."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def lifecycle(self, names: frozenset[str]) -> list[str]:
        return [name for name in self.names if name in names]


class _GuardedSession:
    """Injected session. commit/rollback/close are recorded; any other attribute use is a failure."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.touched: list[str] = []

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True

    def __getattr__(self, name: str):
        self.touched.append(name)
        raise AssertionError(f"session.{name} was used; a refused or unproven identity must not touch the session")


def _spy(ops: _Ops, name: str, result=None):
    async def spy(*_args, **_kwargs):
        ops.names.append(name)
        return result() if callable(result) else result

    return spy


def _install_session_factory(monkeypatch, ops: _Ops, session: _GuardedSession) -> None:
    from db import session as db_session_module

    def factory():
        ops.names.append("async_session_factory")
        return session

    monkeypatch.setattr(db_session_module, "async_session_factory", factory)


def _install_api_spies(monkeypatch, cli: ModuleType, ops: _Ops) -> None:
    for lifecycle in _API_LIFECYCLE:
        monkeypatch.setattr(cli, lifecycle, _spy(ops, lifecycle, result=0))


def _portal_create_result():
    invitation = SimpleNamespace(
        id=uuid.UUID(int=4),
        invited_email="operator@example.test",
        expires_at=_EXPIRES_AT,
    )
    return invitation, "fixture-invitation-token"


def _portal_revoke_result():
    return SimpleNamespace(id=uuid.UUID(int=3), expires_at=_EXPIRES_AT)


def _install_portal_spies(monkeypatch, cli: ModuleType, ops: _Ops) -> None:
    monkeypatch.setattr(cli, "enable_rls_bypass", _spy(ops, "enable_rls_bypass"))
    monkeypatch.setattr(cli, "disable_rls_bypass", _spy(ops, "disable_rls_bypass"))
    monkeypatch.setattr(cli, "_create", _spy(ops, "_create", _portal_create_result))
    monkeypatch.setattr(cli, "_list", _spy(ops, "_list"))
    monkeypatch.setattr(cli, "_revoke", _spy(ops, "_revoke", _portal_revoke_result))


async def _invoke(cli: ModuleType, argv: list[str], session, capsys) -> _Outcome:
    try:
        code = await cli.run(argv=argv, session=session)
    except SystemExit as exc:  # argparse usage errors leave run() through SystemExit
        code = exc.code if isinstance(exc.code, int) else 1
    except AssertionError:
        raise  # a session touch or a spy failure must fail the test with its own message
    except Exception as exc:  # a crash is a failed refusal; report only its type so a DSN cannot leak via a message
        code = -1
        sys.stderr.write(f"unhandled {type(exc).__name__}\n")
    captured = capsys.readouterr()
    return _Outcome(code=code, out=captured.out, err=captured.err)


def _assert_refused(outcome: _Outcome, ops: _Ops, session: _GuardedSession) -> None:
    """Refusal contract: runtime-refusal exit 1, the existing message, no output, no operation, no session use."""
    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert outcome.out == ""
    assert _CANARY not in outcome.out + outcome.err
    assert ops.names == []
    assert session.touched == []
    assert session.commits == 0
    assert session.rollbacks == 0


# ---------------------------------------------------------------------------
# F3: matched generic portal prod must still apply the DSN loopback guard (RED: portal returns early on match)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_PORTAL_ARGV))
@pytest.mark.parametrize("host", _LOOPBACK_HOSTS)
async def test_portal_matched_generic_prod_refuses_loopback_dsn(host, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_prod_loopback")
    user, database = MAINTAINED_STORES["prod"]
    _apply_runtime(monkeypatch, _Runtime("prod", "acx-prod", _raw_dsn(user=user, database=database, host=host)))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", "prod", *_PORTAL_ARGV[command]], session, capsys)

    _assert_refused(outcome, ops, session)


# ---------------------------------------------------------------------------
# Existing-behavior controls (GREEN on unchanged production; must stay green after the K fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portal_matched_generic_prod_accepts_nonlocal_compose_postgres(monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_prod_postgres")
    user, database = MAINTAINED_STORES["prod"]
    _apply_runtime(monkeypatch, _Runtime("prod", "acx-prod", _raw_dsn(user=user, database=database)))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", "prod", *_PORTAL_ARGV["list"]], session, capsys)

    assert outcome.code == 0, outcome.err
    assert ops.lifecycle(_PORTAL_LIFECYCLE) == ["_list"]
    assert session.commits == 1
    assert session.touched == []


@pytest.mark.asyncio
async def test_portal_matched_dev_never_reads_settings(monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_dev_no_read")
    user, database = MAINTAINED_STORES["dev"]
    reads: list[str] = []
    _apply_runtime(monkeypatch, _Runtime("dev", None, _raw_dsn(user=user, database=database, host="localhost")), reads)
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", "dev", *_PORTAL_ARGV["list"]], session, capsys)

    assert outcome.code == 0, outcome.err
    assert reads == []
    assert ops.lifecycle(_PORTAL_LIFECYCLE) == ["_list"]
    assert session.commits == 1
    assert session.touched == []


_GENERIC_STACK_CONTROLS = [
    pytest.param("staging", "acx-staging", "staging", id="staging-maintained-compose-postgres"),
    pytest.param("dev-fir", "acx-dev-fir", "dev-fir", id="dev-fir-maintained-compose-postgres"),
    pytest.param("prod", "acx-prod", "prod", id="prod-maintained-compose-postgres"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("env", "compose", "store"), _GENERIC_STACK_CONTROLS)
async def test_api_maintained_generic_stack_accepts_nonlocal_compose_postgres(
    env, compose, store, monkeypatch, capsys
) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_extra_api_generic_control")
    user, database = MAINTAINED_STORES[store]
    _apply_runtime(monkeypatch, _Runtime(env, compose, _raw_dsn(user=user, database=database)))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", env, *_API_ARGV["list"]], session, capsys)

    assert outcome.code == 0, outcome.err
    assert ops.lifecycle(_API_LIFECYCLE) == ["_cmd_list"]
    assert session.touched == []


# ---------------------------------------------------------------------------
# Effective DSN overrides cannot bypass exact Aura identity (RED: argparse rejects the label today)
# The netloc names the exact identity; a query parameter contradicts it. asyncpg dialect create_connect_args merges
# every query key into the effective connect arguments, so the effective values are what must be checked.
# ---------------------------------------------------------------------------


def _override_cases() -> list:
    cases = []
    for label in AURA_LABELS:
        target = AURA_TARGETS[label]
        user, database = target["generic_role"], target["generic_database"]
        # prod: loopback effective host (netloc still names the Compose service). dev/staging: effective host outside
        # the local and Compose-postgres set. Loopback is legal for dev, so it is not asserted for dev/staging.
        host_query = "?host=127.0.0.1" if label == "prod-auraface" else "?host=remote.example.test"
        queries = {
            "query-user": f"?user={user}",
            "query-database": f"?database={database}",
            "query-options-role": f"?options=-c%20role%3D{user}",
            "query-host": host_query,
        }
        if label == "prod-auraface":
            queries["query-user-and-database"] = f"?user={user}&database={database}"
        for kind, query in queries.items():
            cases.append(pytest.param(label, _dedicated_dsn(label, query=query), id=f"{label}-{kind}"))
    return cases


_OVERRIDE_CASES = _override_cases()


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "dsn"), _OVERRIDE_CASES)
async def test_api_aura_effective_dsn_override_refused(label, dsn, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_extra_api_override")
    _apply_runtime(monkeypatch, _runtime(label, dsn))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_API_ARGV["list"]], session, capsys)

    _assert_refused(outcome, ops, session)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "dsn"), _OVERRIDE_CASES)
async def test_portal_aura_effective_dsn_override_refused(label, dsn, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_override")
    _apply_runtime(monkeypatch, _runtime(label, dsn))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_PORTAL_ARGV["list"]], session, capsys)

    _assert_refused(outcome, ops, session)


# ---------------------------------------------------------------------------
# Missing or malformed Aura identity or host is refused without echoing the credential (RED)
# ---------------------------------------------------------------------------

_MALFORMED_KINDS = ("missing-host", "missing-database", "missing-role", "malformed-port")


def _malformed_dsn(label: str, kind: str) -> str:
    target = AURA_TARGETS[label]
    if kind == "missing-host":
        return _raw_dsn(user=target["role"], database=target["database"], host=None)
    if kind == "missing-database":
        return _raw_dsn(user=target["role"], database=None)
    if kind == "missing-role":
        return _raw_dsn(user=None, database=target["database"])
    return _raw_dsn(user=target["role"], database=target["database"], port="not-a-port")


_MALFORMED_CASES = [
    pytest.param(label, kind, id=f"{label}-{kind}") for label in AURA_LABELS for kind in _MALFORMED_KINDS
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "kind"), _MALFORMED_CASES)
async def test_api_aura_malformed_identity_refused_without_credential(label, kind, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_extra_api_malformed")
    _apply_runtime(monkeypatch, _runtime(label, _malformed_dsn(label, kind)))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_API_ARGV["list"]], session, capsys)

    _assert_refused(outcome, ops, session)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "kind"), _MALFORMED_CASES)
async def test_portal_aura_malformed_identity_refused_without_credential(label, kind, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_malformed")
    _apply_runtime(monkeypatch, _runtime(label, _malformed_dsn(label, kind)))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_PORTAL_ARGV["list"]], session, capsys)

    _assert_refused(outcome, ops, session)


# ---------------------------------------------------------------------------
# Maintained generic stores and mixed role/database pairs refuse every Aura label (RED).
# Write commands are used: tenant bootstrap (API) and invitation creation (portal) are the state-changing risks.
# ---------------------------------------------------------------------------

_GENERIC_STORE_CASES = [
    pytest.param(label, store, id=f"{label}-maintained-{store}") for label in AURA_LABELS for store in MAINTAINED_STORES
]


def _mixed_dsn(label: str, shape: str) -> str:
    target = AURA_TARGETS[label]
    if shape == "generic-role-dedicated-db":
        return _raw_dsn(user=target["generic_role"], database=target["database"])
    return _raw_dsn(user=target["role"], database=target["generic_database"])


_MIXED_CASES = [
    pytest.param(label, shape, id=f"{label}-{shape}")
    for label in AURA_LABELS
    for shape in ("generic-role-dedicated-db", "dedicated-role-generic-db")
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "store"), _GENERIC_STORE_CASES)
async def test_api_aura_label_refuses_maintained_generic_store(label, store, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_extra_api_generic_store")
    user, database = MAINTAINED_STORES[store]
    _apply_runtime(monkeypatch, _runtime(label, _raw_dsn(user=user, database=database)))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_API_ARGV["tenant-create"]], session, capsys)

    _assert_refused(outcome, ops, session)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "store"), _GENERIC_STORE_CASES)
async def test_portal_aura_label_refuses_maintained_generic_store(label, store, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_generic_store")
    user, database = MAINTAINED_STORES[store]
    _apply_runtime(monkeypatch, _runtime(label, _raw_dsn(user=user, database=database)))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_PORTAL_ARGV["create"]], session, capsys)

    _assert_refused(outcome, ops, session)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "shape"), _MIXED_CASES)
async def test_api_aura_label_refuses_mixed_role_database_pair(label, shape, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_extra_api_mixed")
    _apply_runtime(monkeypatch, _runtime(label, _mixed_dsn(label, shape)))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_API_ARGV["tenant-create"]], session, capsys)

    _assert_refused(outcome, ops, session)


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "shape"), _MIXED_CASES)
async def test_portal_aura_label_refuses_mixed_role_database_pair(label, shape, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_extra_portal_mixed")
    _apply_runtime(monkeypatch, _runtime(label, _mixed_dsn(label, shape)))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", label, *_PORTAL_ARGV["create"]], session, capsys)

    _assert_refused(outcome, ops, session)
