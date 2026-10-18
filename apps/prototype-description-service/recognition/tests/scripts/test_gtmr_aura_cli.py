"""RED behavioral contract for the Aura operator labels in the tenant CLIs (GTMR K lane).

Scope: scripts/manage_api_keys.py and scripts/manage_portal_invitations.py only. Both CLIs are driven
in-process through their run() entry point with injected or spied sessions, so no database, network,
GPU or secret is touched. Helpers are mirrored from the sibling CLI test modules (_import_cli,
_set_database_dsn, the stack-session pattern and _UntouchedSession) rather than imported from them.

Contract (GTMSMOKE-1 operator directive; target names are proposed configuration, not observed resources):

* dev-auraface, staging-auraface and prod-auraface are accepted by --env only when ACX_ENV, the execution
  context COMPOSE_PROJECT_NAME=acx-<label>, the DSN role and the DSN database all name that dedicated
  target. ACX_ENV label equality alone is insufficient.
* Generic, sibling, wrong-context, unset and mismatched identities refuse with the existing runtime-refusal
  convention (exit 1, "refusing to run"), invoke no operation, open no session and touch no injected
  session. A tenant bootstrap in a generic store is refused as well.
* prod-auraface refuses loopback or *.local DSN hosts even when its identity matches.
* Existing dev/prod/local/staging/dev-fir behavior is a control group that must stay green.

Expected status on unchanged production, to be recorded by the parent before any implementation:
* static literal choices ........ RED: Aura labels are absent from --env choices
* existing-behavior controls .... GREEN: current runtime refusals and acceptances hold
* Aura acceptance .............. RED: --env is rejected by argparse (exit 2)
* Aura refusal contract ........ RED: exit 2 instead of the runtime refusal (exit 1)
* Aura refusal safety .......... GREEN by rejection: argparse refuses before any operation. It must stay
                                 green, and it turns RED if an implementation admits a listed wrong context.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace

import pytest

from db.settings import DEFAULT_DB_NAME, DEFAULT_PGUSER

_APP_ROOT = pathlib.Path(__file__).resolve().parents[3]
_API_CLI_PATH = _APP_ROOT / "scripts" / "manage_api_keys.py"
_PORTAL_CLI_PATH = _APP_ROOT / "scripts" / "manage_portal_invitations.py"

# Operator-frozen Aura targets. Database and role are alt_context_<label> and acx_<label> with hyphens
# replaced by underscores. "stack" names the generic stack whose project (acx-dev, acx-staging, acx-prod)
# must never satisfy an Aura label.
AURA_TARGETS: dict[str, dict[str, str]] = {
    "dev-auraface": {"database": "alt_context_dev_auraface", "role": "acx_dev_auraface", "stack": "dev"},
    "staging-auraface": {
        "database": "alt_context_staging_auraface",
        "role": "acx_staging_auraface",
        "stack": "staging",
    },
    "prod-auraface": {"database": "alt_context_prod_auraface", "role": "acx_prod_auraface", "stack": "prod"},
}
AURA_LABELS = tuple(AURA_TARGETS)
_SIBLING = {
    "dev-auraface": "staging-auraface",
    "staging-auraface": "prod-auraface",
    "prod-auraface": "dev-auraface",
}
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]", "host.local")
_REFUSED = "refusing to run"
_EXPIRES_AT = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

_API_TENANT = str(uuid.UUID(int=1))
_API_COMMANDS: dict[str, tuple[list[str], str]] = {
    "create": (["create", "--tenant", _API_TENANT], "_cmd_create"),
    "list": (["list", "--tenant", _API_TENANT], "_cmd_list"),
    "revoke": (["revoke", "--key-id", str(uuid.UUID(int=2))], "_cmd_revoke"),
    "tenant-create": (
        ["tenant", "create", "--tenant", _API_TENANT, "--site-url", "http://aura.test"],
        "_cmd_tenant_create",
    ),
    "tenant-list": (["tenant", "list"], "_cmd_tenant_list"),
}
_API_LIFECYCLE = frozenset(name for _, name in _API_COMMANDS.values())
_PORTAL_COMMANDS: dict[str, tuple[list[str], str]] = {
    "create": (["create", "--email", "operator@example.test"], "_create"),
    "list": (["list"], "_list"),
    "revoke": (["revoke", "--invitation-id", str(uuid.UUID(int=3))], "_revoke"),
}
_PORTAL_LIFECYCLE = frozenset(name for _, name in _PORTAL_COMMANDS.values())


@dataclass(frozen=True)
class _Runtime:
    """What a CLI invocation can observe: ACX_ENV, COMPOSE_PROJECT_NAME and the DSN."""

    acx_env: str | None
    compose_project: str | None
    dsn: str


@dataclass(frozen=True)
class _Outcome:
    code: int
    out: str
    err: str


def _dsn(role: str, database: str, host: str = "postgres") -> str:
    # Placeholder credential only; no real secret is referenced.
    return f"postgresql+asyncpg://{role}:fixture@{host}:5432/{database}"


def _dedicated(label: str, host: str = "postgres") -> _Runtime:
    target = AURA_TARGETS[label]
    return _Runtime(label, f"acx-{label}", _dsn(target["role"], target["database"], host))


def _refusals(label: str) -> dict[str, _Runtime]:
    target = AURA_TARGETS[label]
    sibling = AURA_TARGETS[_SIBLING[label]]
    exact = _dedicated(label).dsn
    return {
        "label-equality-generic-store": _Runtime(label, f"acx-{label}", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME)),
        "generic-role-dedicated-db": _Runtime(label, f"acx-{label}", _dsn(DEFAULT_PGUSER, target["database"])),
        "dedicated-role-generic-db": _Runtime(label, f"acx-{label}", _dsn(target["role"], DEFAULT_DB_NAME)),
        "sibling-store": _Runtime(label, f"acx-{label}", _dsn(sibling["role"], sibling["database"])),
        "wrong-execution-context": _Runtime(label, f"acx-{target['stack']}", exact),
        "unset-execution-context": _Runtime(label, None, exact),
        "unset-acx-env": _Runtime(None, f"acx-{label}", exact),
        "acx-env-sibling-label": _Runtime(_SIBLING[label], f"acx-{label}", exact),
        "acx-env-generic-stack": _Runtime(target["stack"], f"acx-{label}", exact),
    }


_REFUSAL_CASES = [pytest.param(label, case, id=f"{label}-{case}") for label in AURA_LABELS for case in _refusals(label)]
_LOOPBACK_CASES = [pytest.param(host, id=f"prod-auraface-host-{host}") for host in _LOOPBACK_HOSTS]

_API_CONTROLS = [
    pytest.param(
        "dev",
        _Runtime("dev", "acx-dev", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "postgres")),
        "accepted",
        id="dev-matched-compose-postgres-accepted",
    ),
    pytest.param(
        "prod",
        _Runtime("prod", "acx-prod", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "postgres")),
        "accepted",
        id="prod-matched-nonlocal-host-accepted",
    ),
    pytest.param(
        "prod",
        _Runtime("prod", "acx-prod", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "localhost")),
        "refused",
        id="prod-matched-loopback-refused",
    ),
    pytest.param(
        "prod",
        _Runtime("dev", "acx-prod", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "postgres")),
        "refused",
        id="prod-acx-env-dev-refused",
    ),
    pytest.param(
        "dev",
        _Runtime(None, None, _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "postgres")),
        "refused",
        id="dev-unset-acx-env-compose-host-refused",
    ),
    pytest.param(
        "dev",
        _Runtime("dev", "acx-dev", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "remote.test")),
        "refused",
        id="dev-matched-remote-host-refused",
    ),
    pytest.param(
        "prod",
        _Runtime("prod-auraface", "acx-prod", _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "postgres")),
        "refused",
        id="prod-flag-with-aura-acx-env-refused",
    ),
]
_PORTAL_CONTROLS = [
    pytest.param(
        "dev",
        _Runtime("dev", None, _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "localhost")),
        "accepted",
        id="dev-matched-local-accepted",
    ),
    pytest.param(
        "prod",
        _Runtime(None, None, _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "localhost")),
        "refused",
        id="prod-unset-loopback-refused",
    ),
    pytest.param(
        "dev",
        _Runtime("prod", None, _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "localhost")),
        "refused",
        id="dev-acx-env-prod-refused",
    ),
    pytest.param(
        "dev",
        _Runtime(None, None, _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "db.example.test")),
        "refused",
        id="dev-unset-remote-refused",
    ),
    pytest.param(
        "prod",
        _Runtime("prod-auraface", None, _dsn(DEFAULT_PGUSER, DEFAULT_DB_NAME, "localhost")),
        "refused",
        id="prod-flag-with-aura-acx-env-refused",
    ),
]


def _load_cli(path: pathlib.Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_runtime(monkeypatch, runtime: _Runtime) -> None:
    from db import settings as db_settings

    if runtime.acx_env is None:
        monkeypatch.delenv("ACX_ENV", raising=False)
    else:
        monkeypatch.setenv("ACX_ENV", runtime.acx_env)
    if runtime.compose_project is None:
        monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    else:
        monkeypatch.setenv("COMPOSE_PROJECT_NAME", runtime.compose_project)
    monkeypatch.setattr(db_settings, "get_database_settings", lambda: SimpleNamespace(postgres_dsn=runtime.dsn))


class _Ops:
    """Ordered record of every operation that reaches a spy or the session factory."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def lifecycle(self, names: frozenset[str]) -> list[str]:
        return [name for name in self.names if name in names]


class _GuardedSession:
    """Injected session. commit/rollback/close are recorded; any other use is a failure."""

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
    captured = capsys.readouterr()
    return _Outcome(code=code, out=captured.out, err=captured.err)


def _env_choices(parser) -> tuple[str, ...]:
    (action,) = [candidate for candidate in parser._actions if candidate.dest == "env"]
    return tuple(action.choices)


# ---------------------------------------------------------------------------
# Static literal config contract (RED: labels absent from --env choices)
# ---------------------------------------------------------------------------


def test_api_env_choices_declare_three_aura_labels_and_keep_existing_stacks() -> None:
    choices = _env_choices(_load_cli(_API_CLI_PATH, "gtmr_aura_api_choices")._build_parser())
    assert set(AURA_LABELS) <= set(choices)
    assert {"prod", "dev", "local", "staging", "dev-fir"} <= set(choices)


def test_portal_env_choices_declare_three_aura_labels_and_keep_existing_stacks() -> None:
    choices = _env_choices(_load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_choices")._build_parser())
    assert set(AURA_LABELS) <= set(choices)
    assert {"prod", "dev", "local"} <= set(choices)


# ---------------------------------------------------------------------------
# Existing dev/prod behavior controls (GREEN on unchanged production; must stay green)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("flag", "runtime", "expected"), _API_CONTROLS)
async def test_api_existing_stack_behavior_is_preserved(flag, runtime, expected, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_control")
    _apply_runtime(monkeypatch, runtime)
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", flag, "list", "--tenant", _API_TENANT], session, capsys)

    if expected == "accepted":
        assert outcome.code == 0, outcome.err
        assert ops.lifecycle(_API_LIFECYCLE) == ["_cmd_list"]
    else:
        assert outcome.code == 1, outcome.err
        assert _REFUSED in outcome.err
        assert ops.names == []
    assert session.touched == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("flag", "runtime", "expected"), _PORTAL_CONTROLS)
async def test_portal_existing_stack_behavior_is_preserved(flag, runtime, expected, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_control")
    _apply_runtime(monkeypatch, runtime)
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()

    outcome = await _invoke(cli, ["--env", flag, "list"], session, capsys)

    if expected == "accepted":
        assert outcome.code == 0, outcome.err
        assert ops.lifecycle(_PORTAL_LIFECYCLE) == ["_list"]
        assert session.commits == 1
    else:
        assert outcome.code == 1, outcome.err
        assert _REFUSED in outcome.err
        assert ops.names == []
        assert session.commits == 0
    assert session.touched == []


# ---------------------------------------------------------------------------
# Aura acceptance in the exact dedicated execution/store (RED on unchanged production)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("injected", [True, False], ids=["injected-session", "session-factory"])
@pytest.mark.parametrize("command", list(_API_COMMANDS))
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_api_aura_label_accepted_in_dedicated_store(label, command, injected, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_accept")
    argv_tail, lifecycle = _API_COMMANDS[command]
    _apply_runtime(monkeypatch, _dedicated(label))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *argv_tail], session if injected else None, capsys)

    assert outcome.code == 0, outcome.err
    assert ops.lifecycle(_API_LIFECYCLE) == [lifecycle]
    assert session.touched == []
    assert ops.names.count("async_session_factory") == (0 if injected else 1)
    assert session.closed is (not injected)


@pytest.mark.asyncio
@pytest.mark.parametrize("injected", [True, False], ids=["injected-session", "session-factory"])
@pytest.mark.parametrize("command", list(_PORTAL_COMMANDS))
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_portal_aura_label_accepted_in_dedicated_store(label, command, injected, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_accept")
    argv_tail, lifecycle = _PORTAL_COMMANDS[command]
    _apply_runtime(monkeypatch, _dedicated(label))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *argv_tail], session if injected else None, capsys)

    assert outcome.code == 0, outcome.err
    assert ops.lifecycle(_PORTAL_LIFECYCLE) == [lifecycle]
    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.touched == []
    assert ops.names.count("async_session_factory") == (0 if injected else 1)
    assert session.closed is (not injected)


# ---------------------------------------------------------------------------
# Aura refusal contract: existing runtime-refusal convention (RED on unchanged production:
# the label is rejected by argparse with exit 2 instead of the identity guard's exit 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "case"), _REFUSAL_CASES)
async def test_api_aura_identity_refusal_uses_runtime_guard(label, case, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_refusal")
    _apply_runtime(monkeypatch, _refusals(label)[case])
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    _install_session_factory(monkeypatch, ops, _GuardedSession())

    outcome = await _invoke(cli, ["--env", label, "list", "--tenant", _API_TENANT], None, capsys)

    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert outcome.out == ""
    assert ops.names == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("label", "case"), _REFUSAL_CASES)
async def test_portal_aura_identity_refusal_uses_runtime_guard(label, case, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_refusal")
    _apply_runtime(monkeypatch, _refusals(label)[case])
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    _install_session_factory(monkeypatch, ops, _GuardedSession())

    outcome = await _invoke(cli, ["--env", label, "list"], None, capsys)

    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert outcome.out == ""
    assert ops.names == []


@pytest.mark.asyncio
@pytest.mark.parametrize("host", _LOOPBACK_CASES)
async def test_api_prod_aura_refuses_loopback_even_when_identity_matches(host, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_loopback")
    _apply_runtime(monkeypatch, _dedicated("prod-auraface", host=host))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    _install_session_factory(monkeypatch, ops, _GuardedSession())

    outcome = await _invoke(cli, ["--env", "prod-auraface", "list", "--tenant", _API_TENANT], None, capsys)

    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert ops.names == []


@pytest.mark.asyncio
@pytest.mark.parametrize("host", _LOOPBACK_CASES)
async def test_portal_prod_aura_refuses_loopback_even_when_identity_matches(host, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_loopback")
    _apply_runtime(monkeypatch, _dedicated("prod-auraface", host=host))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    _install_session_factory(monkeypatch, ops, _GuardedSession())

    outcome = await _invoke(cli, ["--env", "prod-auraface", "list"], None, capsys)

    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert ops.names == []


@pytest.mark.asyncio
@pytest.mark.parametrize("label", AURA_LABELS)
async def test_api_tenant_bootstrap_never_creates_aura_tenant_in_generic_store(label, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_bootstrap")
    _apply_runtime(monkeypatch, _refusals(label)["label-equality-generic-store"])
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    argv_tail, _ = _API_COMMANDS["tenant-create"]

    outcome = await _invoke(cli, ["--env", label, *argv_tail], session, capsys)

    assert outcome.code == 1, outcome.err
    assert _REFUSED in outcome.err
    assert ops.names == []
    assert session.touched == []
    assert session.commits == 0


# ---------------------------------------------------------------------------
# Aura refusal safety invariant (GREEN on unchanged production only by argparse rejection; must stay
# green, and must turn RED if an implementation admits any listed wrong identity or context)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_API_COMMANDS))
@pytest.mark.parametrize(("label", "case"), _REFUSAL_CASES)
async def test_api_aura_identity_refusal_invokes_no_operation(label, case, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_safety")
    argv_tail, _ = _API_COMMANDS[command]
    _apply_runtime(monkeypatch, _refusals(label)[case])
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *argv_tail], session, capsys)

    assert outcome.code != 0, outcome.err
    assert outcome.out == ""
    assert ops.names == []
    assert session.touched == []
    assert session.commits == 0
    assert session.rollbacks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_PORTAL_COMMANDS))
@pytest.mark.parametrize(("label", "case"), _REFUSAL_CASES)
async def test_portal_aura_identity_refusal_invokes_no_operation(label, case, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_safety")
    argv_tail, _ = _PORTAL_COMMANDS[command]
    _apply_runtime(monkeypatch, _refusals(label)[case])
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", label, *argv_tail], session, capsys)

    assert outcome.code != 0, outcome.err
    assert outcome.out == ""
    assert ops.names == []
    assert session.touched == []
    assert session.commits == 0
    assert session.rollbacks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_API_COMMANDS))
@pytest.mark.parametrize("host", _LOOPBACK_CASES)
async def test_api_prod_aura_loopback_invokes_no_operation(host, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_API_CLI_PATH, "gtmr_aura_api_loopback_safety")
    argv_tail, _ = _API_COMMANDS[command]
    _apply_runtime(monkeypatch, _dedicated("prod-auraface", host=host))
    ops = _Ops()
    _install_api_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", "prod-auraface", *argv_tail], session, capsys)

    assert outcome.code != 0, outcome.err
    assert ops.names == []
    assert session.touched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("command", list(_PORTAL_COMMANDS))
@pytest.mark.parametrize("host", _LOOPBACK_CASES)
async def test_portal_prod_aura_loopback_invokes_no_operation(host, command, monkeypatch, capsys) -> None:
    cli = _load_cli(_PORTAL_CLI_PATH, "gtmr_aura_portal_loopback_safety")
    argv_tail, _ = _PORTAL_COMMANDS[command]
    _apply_runtime(monkeypatch, _dedicated("prod-auraface", host=host))
    ops = _Ops()
    _install_portal_spies(monkeypatch, cli, ops)
    session = _GuardedSession()
    _install_session_factory(monkeypatch, ops, session)

    outcome = await _invoke(cli, ["--env", "prod-auraface", *argv_tail], session, capsys)

    assert outcome.code != 0, outcome.err
    assert ops.names == []
    assert session.touched == []
