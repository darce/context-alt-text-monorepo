"""Nested DSN startup-role refusal for the Aura operator labels in the tenant CLIs (GTMR K lane, RED-first).

Finding (independent review of K): a dedicated Aura URL can carry a nested ``dsn`` query key, for example
``?dsn=postgresql://localhost/generic?role=acx_app``. The outer user, database and host stay dedicated, so they pass the
identity checks in scripts/_aura_target_guard.py. SQLAlchemy forwards ``dsn`` to asyncpg.connect as a keyword, and
asyncpg parses the nested query into ``server_settings={'role': 'acx_app'}``. The effective startup role is then not the
dedicated role.

Contract under test (companion to the frozen test_gtmr_aura_cli.py, which stays unchanged):

* For every Aura label, both CLIs and both commands of each CLI, a nested ``dsn`` query key is refused with exit 1 and
  the existing refusal text. The refusal does not depend on the nested value or on the key's letter case. It happens
  before any session is created, before RLS bypass and before dispatch.
* Controls: a dedicated Aura DSN without a nested key still reaches dispatch with exit 0 and the expected lifecycle.

Both CLIs run in-process through run() with fake settings, a recording session factory, a guarded fake session and
dispatch spies. No database, socket, DNS, secret or runtime is touched.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import urllib.parse
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
_CANARY = "gtmr-nested-dsn-canary-credential"
_EXPIRES_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
_API_TENANT = str(uuid.UUID(int=1))

# Dedicated Aura identities (proposed configuration, not observed resources): label -> (role, database).
_DEDICATED: dict[str, tuple[str, str]] = {
    "dev-auraface": ("acx_dev_auraface", "alt_context_dev_auraface"),
    "staging-auraface": ("acx_staging_auraface", "alt_context_staging_auraface"),
    "prod-auraface": ("acx_prod_auraface", "alt_context_prod_auraface"),
}
# Maintained generic startup role of the same stack (config/env/manifest.d/10-service-shared.toml, POSTGRES_USER).
# Generic prod is acx_app, not acx_prod.
_GENERIC_ROLE: dict[str, str] = {
    "dev-auraface": "acx_dev",
    "staging-auraface": "acx_staging",
    "prod-auraface": "acx_app",
}
AURA_LABELS: tuple[str, ...] = tuple(_DEDICATED)
# nested-generic-role: the reported vector (startup role set to the maintained generic role).
# nested-dedicated-role: the nested value names the dedicated identity, so refusal must not depend on the value.
# nested-uppercase-key: the same vector under an upper-case key, so refusal must not depend on key case.
_VECTORS: tuple[str, ...] = ("nested-generic-role", "nested-dedicated-role", "nested-uppercase-key")

_API_ARGV: dict[str, list[str]] = {
    "list": ["list", "--tenant", _API_TENANT],
    "tenant-create": ["tenant", "create", "--tenant", _API_TENANT, "--site-url", "http://aura.test"],
}
_API_DISPATCH: dict[str, str] = {"list": "_cmd_list", "tenant-create": "_cmd_tenant_create"}
_API_LIFECYCLE = frozenset({"_cmd_create", "_cmd_list", "_cmd_revoke", "_cmd_tenant_create", "_cmd_tenant_list"})
_PORTAL_ARGV: dict[str, list[str]] = {
    "list": ["list"],
    "create": ["create", "--email", "operator@example.test"],
}
_PORTAL_DISPATCH: dict[str, str] = {"list": "_list", "create": "_create"}
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


def _nested_dsn(label: str, vector: str) -> str:
    """The nested DSN string carried inside the outer Aura URL."""
    if vector == "nested-dedicated-role":
        role, database = _DEDICATED[label]
        return f"postgresql://localhost/{database}?role={role}"
    return f"postgresql://localhost/generic?role={_GENERIC_ROLE[label]}"


def _nested_query(label: str, vector: str) -> str:
    key = "DSN" if vector == "nested-uppercase-key" else "dsn"
    return "?" + urllib.parse.urlencode({key: _nested_dsn(label, vector)})


def _aura_dsn(label: str, *, query: str = "") -> str:
    """Placeholder asyncpg DSN with the dedicated identity in the netloc. The canary is the only credential."""
    role, database = _DEDICATED[label]
    return f"postgresql+asyncpg://{role}:{_CANARY}@postgres:5432/{database}{query}"


def _load_cli(path: pathlib.Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_runtime(monkeypatch, runtime: _Runtime) -> None:
    """Set ACX_ENV and COMPOSE_PROJECT_NAME and replace the settings getter with a fake returning the DSN."""
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
        return SimpleNamespace(postgres_dsn=runtime.dsn)

    monkeypatch.setattr(db_settings, "get_database_settings", fake_settings)


class _Ops:
    """Ordered record of every operation that reaches a spy or the session factory."""

    def __init__(self) -> None:
        self.names: list[str] = []


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
        raise AssertionError(f"session.{name} was used; a refused identity must not touch the session")


def _spy(ops: _Ops, name: str, result=None):
    async def spy(*_args, **_kwargs):
        ops.names.append(name)
        return result() if callable(result) else result

    return spy


def _install_session_factory(monkeypatch, ops: _Ops, session: _GuardedSession) -> None:
    """Record every session creation. run() calls the factory only when no session is injected."""
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


def _install_portal_spies(monkeypatch, cli: ModuleType, ops: _Ops) -> None:
    monkeypatch.setattr(cli, "enable_rls_bypass", _spy(ops, "enable_rls_bypass"))
    monkeypatch.setattr(cli, "disable_rls_bypass", _spy(ops, "disable_rls_bypass"))
    monkeypatch.setattr(cli, "_create", _spy(ops, "_create", _portal_create_result))
    monkeypatch.setattr(cli, "_list", _spy(ops, "_list"))
    monkeypatch.setattr(cli, "_revoke", _spy(ops, "_revoke", lambda: None))


async def _invoke(cli: ModuleType, argv: list[str], capsys) -> _Outcome:
    """Run the CLI without an injected session, so the session factory is on the path under test."""
    try:
        code = await cli.run(argv=argv)
    except SystemExit as exc:  # argparse usage errors leave run() through SystemExit
        code = exc.code if isinstance(exc.code, int) else 1
    except AssertionError:
        raise  # a session touch or a spy failure must fail the test with its own message
    except Exception as exc:  # a crash is reported by type only, so a DSN cannot leak through a message
        code = -1
        sys.stderr.write(f"unhandled {type(exc).__name__}\n")
    captured = capsys.readouterr()
    return _Outcome(code=code, out=captured.out, err=captured.err)


def _assert_refused(outcome: _Outcome, ops: _Ops, session: _GuardedSession, nested: str) -> None:
    """Refusal contract: exit 1 with the existing message, no output, and no session, RLS bypass or dispatch."""
    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert outcome.out == ""
    assert _CANARY not in outcome.out + outcome.err
    assert nested not in outcome.out + outcome.err
    assert ops.names == [], f"operations ran after refusal: {ops.names}"
    assert session.touched == []
    assert session.commits == 0
    assert session.rollbacks == 0
    assert session.closed is False


# ---------------------------------------------------------------------------
# Nested dsn key refused for every Aura label, command and vector, before any session, RLS bypass or dispatch (RED)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", _VECTORS)
@pytest.mark.parametrize("command", list(_API_ARGV))
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_api_nested_dsn_startup_role_refused_before_session(label, command, vector, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_nested_api")
    _apply_runtime(monkeypatch, _Runtime(label, f"acx-{label}", _aura_dsn(label, query=_nested_query(label, vector))))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *_API_ARGV[command]], capsys)

    _assert_refused(outcome, ops, session, _nested_dsn(label, vector))


@pytest.mark.asyncio
@pytest.mark.parametrize("vector", _VECTORS)
@pytest.mark.parametrize("command", list(_PORTAL_ARGV))
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_portal_nested_dsn_startup_role_refused_before_rls_bypass(
    label, command, vector, monkeypatch, capsys
) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_nested_portal")
    _apply_runtime(monkeypatch, _Runtime(label, f"acx-{label}", _aura_dsn(label, query=_nested_query(label, vector))))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *_PORTAL_ARGV[command]], capsys)

    _assert_refused(outcome, ops, session, _nested_dsn(label, vector))


# ---------------------------------------------------------------------------
# Controls: a dedicated Aura DSN without a nested key still reaches dispatch (GREEN before and after the fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_API_ARGV))
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_api_dedicated_dsn_without_nested_key_dispatches(label, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_nested_api_control")
    _apply_runtime(monkeypatch, _Runtime(label, f"acx-{label}", _aura_dsn(label)))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *_API_ARGV[command]], capsys)

    assert outcome.code == 0, outcome.err
    assert ops.names == ["async_session_factory", _API_DISPATCH[command]]
    assert session.touched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_PORTAL_ARGV))
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_portal_dedicated_dsn_without_nested_key_dispatches(label, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_nested_portal_control")
    _apply_runtime(monkeypatch, _Runtime(label, f"acx-{label}", _aura_dsn(label)))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *_PORTAL_ARGV[command]], capsys)

    assert outcome.code == 0, outcome.err
    assert ops.names == [
        "async_session_factory",
        "enable_rls_bypass",
        _PORTAL_DISPATCH[command],
        "disable_rls_bypass",
    ]
    assert session.commits == 1
    assert session.touched == []
