"""Offline diagnostic and deadline regressions using the frozen module's fake store.

All targets, tokens and credentials are fixture canaries. The shared harness
stubs session creation and settings; its virtual clock performs no real waits.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


_HARNESS_PATH = Path(__file__).with_name("test_gtmc_portal_isolated_invitation.py")
_SPEC = importlib.util.spec_from_file_location("_invitation_deadline_harness", _HARNESS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
h = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(h)
factory = h.factory

INVITATION_ID = h.TENANT_ID


def _setup(monkeypatch, factory, *, hang=()):
    cli = h._load_cli(monkeypatch)
    h._configure_env(monkeypatch, acx_env=None, dsn=h.LOCAL_DSN)
    h._fake_token(monkeypatch)
    clock = h._VirtualClock()
    session = h._SpySession(clock, hang=hang)
    factory.session = session
    return cli, clock, session


def _argv(command):
    argv = ["--env", "local", command]
    if command == "revoke":
        argv += ["--invitation-id", str(INVITATION_ID)]
    elif command == "create":
        argv += ["--email", h.INVITEE_EMAIL]
    return argv


def _revoke_result():
    return SimpleNamespace(id=INVITATION_ID, expires_at=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize("failure", [
    "exception", "timeout", "reset-exception", "none-reset-exception", "none-reset-timeout",
])
def test_revoke_precommit_failure_never_claims_not_pending(monkeypatch, capsys, factory, failure):
    cli, clock, session = _setup(monkeypatch, factory)

    async def revoke(_args, _session):
        if failure == "exception":
            raise RuntimeError(h.FAKE_CREDENTIAL)
        if failure == "timeout":
            await asyncio.get_running_loop().create_future()
        return None if failure.startswith("none-") else _revoke_result()

    async def reset(_session):
        if failure.endswith("timeout"):
            await asyncio.get_running_loop().create_future()
        raise RuntimeError(h.FAKE_CREDENTIAL)

    monkeypatch.setattr(cli, "_revoke", revoke)
    if "reset" in failure:
        monkeypatch.setattr(cli, "disable_rls_bypass", reset)
    assert h._drive(clock, cli.run(_argv("revoke"))) == 1
    captured = capsys.readouterr()
    assert "operation failed or refused" in captured.err
    assert "not found or not pending" not in captured.err
    assert "commit" not in session.log
    assert session.log == ["rollback", "close"]
    assert clock.now == (10 if "timeout" in failure else 0)
    h._assert_no_token_output(captured)


def test_revoke_none_is_the_not_pending_diagnostic(monkeypatch, capsys, factory):
    cli, clock, session = _setup(monkeypatch, factory)

    async def revoke(_args, _session):
        return None

    monkeypatch.setattr(cli, "_revoke", revoke)
    assert h._drive(clock, cli.run(_argv("revoke"))) == 1
    captured = capsys.readouterr()
    assert captured.err == "error: invitation not found or not pending\n"
    assert session.log == ["rollback", "close"]
    h._assert_no_token_output(captured)


@pytest.mark.parametrize("command", ["revoke", "list"])
@pytest.mark.parametrize("failure", ["exception", "timeout"])
def test_noncreate_commit_ambiguity_names_the_operation(monkeypatch, capsys, factory, command, failure):
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit",) if failure == "timeout" else ())

    async def revoke(_args, _session):
        return _revoke_result()

    async def fail_commit():
        raise RuntimeError(h.FAKE_CREDENTIAL)

    monkeypatch.setattr(cli, "_revoke", revoke)
    if failure == "exception":
        monkeypatch.setattr(session, "commit", fail_commit)
    assert h._drive(clock, cli.run(_argv(command))) == 1
    captured = capsys.readouterr()
    assert "commit unacknowledged" in captured.err
    assert "before reissue" not in captured.err
    assert "invitation_id=None" not in captured.err
    if command == "revoke":
        assert f"reconcile invitation_id={INVITATION_ID}" in captured.err
        assert "revoked invitation_id=" not in captured.err
        assert "not found or not pending" not in captured.err
    else:
        assert "reconcile invitation list" in captured.err
    h._assert_no_token_output(captured)


def test_create_commit_ambiguity_keeps_id_and_reissue_guidance(monkeypatch, capsys, factory):
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit",))

    async def create(_args, _session):
        return SimpleNamespace(
            id=INVITATION_ID, invited_email=h.INVITEE_EMAIL,
            expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        ), h.FAKE_TOKEN

    monkeypatch.setattr(cli, "_create", create)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    captured = capsys.readouterr()
    assert f"reconcile invitation_id={INVITATION_ID} before reissue" in captured.err
    assert session.log == ["rollback", "close"]
    h._assert_no_token_output(captured)


_OVERRIDE_KEYS = (
    "user", "username", "database", "dbname", "host", "hostaddr", "port",
    "service", "servicefile", "options", "dsn",
)


@pytest.mark.parametrize("key", _OVERRIDE_KEYS)
@pytest.mark.parametrize("form", ["upper", "mixed", "encoded", "repeated"])
def test_fir_override_keys_are_refused_after_casefold_and_decoding(monkeypatch, capsys, factory, key, form):
    rendered = key.upper() if form == "upper" else key[0].upper() + key[1:]
    if form == "encoded":
        rendered = f"%{ord(rendered[0]):02X}" + rendered[1:]
    query = f"?{rendered}=fixture"
    if form == "repeated":
        query += f"&{rendered}=fixture-again"
    _assert_fir_target(monkeypatch, capsys, factory, query=query, admitted=False)


def _assert_fir_target(monkeypatch, capsys, factory, *, admitted, driver="postgresql+asyncpg", port="5432", host="postgres", query=""):
    cli = h._load_cli(monkeypatch)
    endpoint = host if port is None else f"{host}:{port}"
    dsn = f"{driver}://acx_dev_fir:{h.FAKE_CREDENTIAL}@{endpoint}/alt_context_dev_fir{query}"
    reads = h._configure_env(monkeypatch, acx_env="dev-fir", dsn=dsn)
    clock = h._VirtualClock()
    session = h._SpySession(clock)
    factory.session = session
    assert h._drive(clock, cli.run(["--env", "dev-fir", "list"])) == (0 if admitted else 1)
    assert len(reads) == 1
    assert factory.calls == int(admitted)
    if not admitted:
        assert session.log == []
    captured = capsys.readouterr()
    assert dsn not in captured.out + captured.err
    h._assert_no_token_output(captured)


@pytest.mark.parametrize(
    ("port", "admitted"),
    [(None, True), ("1", True), ("5432", True), ("65535", True),
     ("0", False), ("-1", False), ("65536", False), ("bad", False)],
    ids=["default", "minimum", "standard", "maximum", "zero", "negative", "too-large", "malformed"],
)
def test_fir_port_allowlist(monkeypatch, capsys, factory, port, admitted):
    _assert_fir_target(monkeypatch, capsys, factory, port=port, admitted=admitted)


@pytest.mark.parametrize(
    ("driver", "admitted"),
    [("postgresql", True), ("postgresql+asyncpg", True),
     ("postgresql+psycopg", False), ("postgresql+psycopg2", False),
     ("postgres", False), ("mysql+asyncpg", False)],
    ids=["postgresql", "asyncpg", "psycopg", "psycopg2", "legacy-alias", "other-backend"],
)
def test_fir_driver_allowlist(monkeypatch, capsys, factory, driver, admitted):
    _assert_fir_target(monkeypatch, capsys, factory, driver=driver, admitted=admitted)


@pytest.mark.parametrize(
    ("host", "admitted"),
    [("postgres", True), ("localhost", True), ("127.0.0.1", True), ("[::1]", True),
     ("127.0.0.2", False), ("0.0.0.0", False), ("fixture.local", False),
     ("localhost.", False), ("postgres,localhost", False)],
    ids=["compose", "localhost", "ipv4-loopback", "ipv6-loopback", "other-loopback",
         "wildcard", "local-suffix", "trailing-dot", "multi-host"],
)
def test_fir_host_allowlist(monkeypatch, capsys, factory, host, admitted):
    _assert_fir_target(monkeypatch, capsys, factory, host=host, admitted=admitted)


def test_triple_hang_has_fourteen_second_virtual_ceiling(monkeypatch, capsys, factory):
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit", "rollback", "close"))
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert clock.now == 14
    assert session.events == [
        ("commit", "start", 0), ("commit", "cancelled", 10),
        ("rollback", "start", 10), ("rollback", "cancelled", 12),
        ("close", "start", 12), ("close", "cancelled", 14),
    ]
    h._assert_no_token_output(capsys.readouterr())


@pytest.mark.parametrize("stage", ["enable", "flush", "disable"])
def test_delayed_precommit_shares_the_original_deadline(monkeypatch, capsys, factory, stage):
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit", "rollback", "close"))

    async def delay(_session=None):
        await asyncio.sleep(8)

    if stage == "flush":
        monkeypatch.setattr(session, "flush", delay)
    else:
        monkeypatch.setattr(cli, f"{stage}_rls_bypass", delay)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert clock.now == 14
    assert session.events == [
        ("commit", "start", 8), ("commit", "cancelled", 10),
        ("rollback", "start", 10), ("rollback", "cancelled", 12),
        ("close", "start", 12), ("close", "cancelled", 14),
    ]
    h._assert_no_token_output(capsys.readouterr())


async def _resistant_hang(session, name, settle_delay):
    session.events.append((name, "start", session._clock.now))
    try:
        await asyncio.get_running_loop().create_future()
    except asyncio.CancelledError:
        session.events.append((name, "cancelled", session._clock.now))
        await asyncio.sleep(settle_delay)
        session.events.append((name, "settled", session._clock.now))
        raise


def test_rollback_cap_is_absolute_after_late_transaction_settlement(monkeypatch, capsys, factory):
    cli, clock, session = _setup(monkeypatch, factory, hang=("rollback", "close"))

    async def commit():
        await _resistant_hang(session, "commit", 1.5)

    monkeypatch.setattr(session, "commit", commit)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert clock.now == 14
    assert session.events == [
        ("commit", "start", 0), ("commit", "cancelled", 10), ("commit", "settled", 11.5),
        ("rollback", "start", 11.5), ("rollback", "cancelled", 12),
        ("close", "start", 12), ("close", "cancelled", 14),
    ]
    h._assert_no_token_output(capsys.readouterr())


def test_close_cap_is_absolute_after_late_rollback_settlement(monkeypatch, capsys, factory):
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit", "close"))

    async def rollback():
        await _resistant_hang(session, "rollback", 1.5)

    monkeypatch.setattr(session, "rollback", rollback)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert clock.now == 14
    assert session.events == [
        ("commit", "start", 0), ("commit", "cancelled", 10),
        ("rollback", "start", 10), ("rollback", "cancelled", 12), ("rollback", "settled", 13.5),
        ("close", "start", 13.5), ("close", "cancelled", 14),
    ]
    h._assert_no_token_output(capsys.readouterr())


@pytest.mark.parametrize("stage", ["flush", "disable"])
def test_synchronous_precommit_overrun_blocks_commit(monkeypatch, capsys, factory, stage):
    cli, clock, session = _setup(monkeypatch, factory)

    async def overrun(_session=None):
        # Simulate synchronous work that finishes before a timeout callback can run.
        clock.now = 10.25

    if stage == "flush":
        monkeypatch.setattr(session, "flush", overrun)
    else:
        monkeypatch.setattr(cli, "disable_rls_bypass", overrun)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert "commit" not in session.log
    assert session.log[-2:] == ["rollback", "close"]
    captured = capsys.readouterr()
    assert "operation failed or refused" in captured.err
    assert "commit unacknowledged" not in captured.err
    h._assert_no_token_output(captured)


@pytest.mark.parametrize("stage", ["flush", "commit"])
@pytest.mark.parametrize("owned", [True, False], ids=["owned-session", "injected-session"])
def test_external_cancellation_reraises_after_bounded_cleanup(monkeypatch, capsys, factory, stage, owned):
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit", "rollback", "close"))

    async def flush():
        await session._step("flush")

    if stage == "flush":
        session._hang = session._hang | {"flush"}
        monkeypatch.setattr(session, "flush", flush)

    async def cancel_run():
        loop = asyncio.get_running_loop()
        task = loop.create_task(cli.run(_argv("create"), **({} if owned else {"session": session})))
        loop.call_later(1, task.cancel)
        await task

    with pytest.raises(asyncio.CancelledError):
        h._drive(clock, cancel_run())
    assert clock.now == (5 if owned else 3)
    assert session.events[:4] == [
        (stage, "start", 0), (stage, "cancelled", 1),
        ("rollback", "start", 1), ("rollback", "cancelled", 3),
    ]
    assert session.events[4:] == ([("close", "start", 3), ("close", "cancelled", 5)] if owned else [])
    assert factory.calls == int(owned)
    h._assert_no_token_output(capsys.readouterr())


def test_expired_cleanup_caps_skip_operations_after_resistant_commit(monkeypatch, capsys, factory):
    # C82R-CLI2-02: cancellation settlement occurs beyond BOTH absolute caps.
    cli, clock, session = _setup(monkeypatch, factory, hang=("rollback", "close"))
    async def commit():
        await _resistant_hang(session, "commit", 5)
    monkeypatch.setattr(session, "commit", commit)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert clock.now == 15
    assert session.events == [
        ("commit", "start", 0), ("commit", "cancelled", 10), ("commit", "settled", 15),
    ]
    h._assert_no_token_output(capsys.readouterr())


def test_injected_session_invalidated_after_failed_rollback(monkeypatch, capsys, factory):
    # C82R-CLI2-05: state persists until invalidation, unlike the trusted RLS stub.
    cli, clock, session = _setup(monkeypatch, factory, hang=("rollback",))
    session.bypass = False
    session.invalidated = False
    async def enable(_session):
        session.bypass = True
    async def fail_flush():
        raise RuntimeError("fixture failure")
    async def invalidate():
        session.log.append("invalidate")
        session.invalidated = True
        session.bypass = False
    monkeypatch.setattr(cli, "enable_rls_bypass", enable)
    monkeypatch.setattr(session, "flush", fail_flush)
    monkeypatch.setattr(session, "invalidate", invalidate, raising=False)
    assert h._drive(clock, cli.run(_argv("create"), session=session)) == 1
    assert session.invalidated
    assert not session.bypass
    assert clock.now == 2
    assert "commit" not in session.log
    h._assert_no_token_output(capsys.readouterr())


def test_resistant_rollback_guarantee_is_cooperative(monkeypatch, capsys, factory):
    # C82R-CLI2-06: pin the narrowed guarantee, including skipped expired close.
    cli, clock, session = _setup(monkeypatch, factory, hang=("commit", "close"))
    async def rollback():
        await _resistant_hang(session, "rollback", 4)
    monkeypatch.setattr(session, "rollback", rollback)
    assert h._drive(clock, cli.run(_argv("create"))) == 1
    assert clock.now == 16
    assert session.events == [
        ("commit", "start", 0), ("commit", "cancelled", 10),
        ("rollback", "start", 10), ("rollback", "cancelled", 12), ("rollback", "settled", 16),
    ]
    assert cli.run.__doc__ is not None and "cooperative" in cli.run.__doc__
    h._assert_no_token_output(capsys.readouterr())


@pytest.mark.parametrize("host", ["LOCALHOST", "LoCaLhOsT", "POSTGRES", "PoStGrEs", "127.0.0.1"])
def test_fir_host_admission_is_case_insensitive(monkeypatch, capsys, factory, host):
    # C82R-CLI2-03: the FIR allowlist must preserve uppercase loopback/Compose names.
    _assert_fir_target(monkeypatch, capsys, factory, host=host, admitted=True)
