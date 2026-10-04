"""APP-1 R1 reconcile-fix-retry receipts for RV06 (DB-only audited retry)."""

from __future__ import annotations

import io
import os
import sys
import types
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from recognition.domain.portal_contracts import QuarantineStatus
from recognition.tests.unit.test_app1_billing_reconcile_recovery import _SELLER, _Clock, _Recovery
from scripts import billing_reconcile as billing_reconcile_module
from scripts import billing_reconcile_retry as retry_cli
from scripts.billing_reconcile import audited_retry_quarantine

_NOW = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)
_PROVIDER_ENV = (
    "POLAR_ACCESS_TOKEN",
    "POLAR_API_TOKEN",
    "POLAR_WEBHOOK_SECRET",
    "POLAR_ORGANIZATION_ID",
    "POLAR_SELLER_ACCOUNT",
    "POLAR_ORGANIZATION",
    "POLAR_PRODUCT_IDS",
    "POLAR_BASE_URL",
    "POLAR_API_BASE_URL",
    "POLAR_ENVIRONMENT",
    "POLAR_PAYMENTS_ENABLED",
)
_RETRY_ARGV = (
    "--remote-id",
    "sub-x",
    "--environment",
    "sandbox",
    "--seller-account",
    _SELLER,
    "--operator-identity",
    "ops@example.test",
    "--operator-reason",
    "mapped seller confirmed",
)


class _CloseSession:
    def __init__(self) -> None:
        self.closed = 0
        self.commits = 0
        self.writes = 0

    def mark_write(self) -> None:
        self.writes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def close(self) -> None:
        self.closed += 1


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    for name in list(os.environ):
        if name.startswith("POLAR_"):
            monkeypatch.delenv(name, raising=False)


def _quarantined_recovery(session: _CloseSession | None = None) -> _Recovery:
    recovery = _Recovery(session=session)
    recovery.quarantine["sub-x"] = SimpleNamespace(
        remote_id="sub-x",
        status=QuarantineStatus.OPEN,
        operator_identity=None,
        operator_reason=None,
        attempt_count=1,
    )
    return recovery


def _forbid_provider(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _boom(name: str):
        def _raise(*_args: object, **_kwargs: object) -> object:
            calls.append(name)
            raise AssertionError(f"{name} must not be constructed for audited retry")

        return _raise

    monkeypatch.setattr(billing_reconcile_module, "_build_runtime", _boom("_build_runtime"))
    monkeypatch.setattr(retry_cli, "_build_runtime", _boom("_build_runtime"), raising=False)
    monkeypatch.setattr(
        "recognition.infrastructure.billing.polar_provider.PolarBillingProvider",
        _boom("PolarBillingProvider"),
    )
    monkeypatch.setattr("httpx.AsyncClient", _boom("httpx.AsyncClient"))
    return calls


def _install_session_factory(monkeypatch: pytest.MonkeyPatch, session_factory: object) -> None:
    existing = sys.modules.get("db.session")
    if existing is not None:
        monkeypatch.setattr(existing, "async_session_factory", session_factory)
        return
    fake = types.ModuleType("db.session")
    fake.async_session_factory = session_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "db.session", fake)


def _install_db_runtime(monkeypatch: pytest.MonkeyPatch) -> tuple[list[_CloseSession], list[_Recovery]]:
    sessions: list[_CloseSession] = []
    recoveries: list[_Recovery] = []

    def session_factory() -> _CloseSession:
        session = _CloseSession()
        sessions.append(session)
        return session

    def repository_ctor(session: _CloseSession) -> _Recovery:
        recovery = _quarantined_recovery(session)
        recoveries.append(recovery)
        return recovery

    _install_session_factory(monkeypatch, session_factory)
    monkeypatch.setattr(
        "recognition.infrastructure.repositories.billing_reconciliation_repository.BillingReconciliationRepository",
        repository_ctor,
    )
    return sessions, recoveries


@pytest.mark.asyncio
async def test_missing_provider_env_does_not_block_retry_or_construct_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    provider_calls = _forbid_provider(monkeypatch)
    sessions, recoveries = _install_db_runtime(monkeypatch)
    err = io.StringIO()

    code = await retry_cli.run(
        [*_RETRY_ARGV, "--apply"],
        stderr=err,
        clock=_Clock(_NOW),
    )

    assert code == 0
    assert provider_calls == []
    assert len(recoveries) == 1
    assert recoveries[0].retries[0]["operator_identity"] == "ops@example.test"
    assert recoveries[0].retries[0]["operator_reason"] == "mapped seller confirmed"
    assert sessions[0].closed == 1
    assert "polar_access" not in err.getvalue().lower()


@pytest.mark.asyncio
async def test_db_runtime_closes_session_after_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _forbid_provider(monkeypatch)
    sessions, _recoveries = _install_db_runtime(monkeypatch)

    code = await retry_cli.run(
        _RETRY_ARGV,
        stderr=io.StringIO(),
        clock=_Clock(_NOW),
    )

    assert code == 0
    assert sessions[0].closed == 1


@pytest.mark.asyncio
async def test_dry_run_does_not_write() -> None:
    recovery = _quarantined_recovery()
    err = io.StringIO()

    code = await retry_cli.run(
        _RETRY_ARGV,
        recovery_repository=recovery,
        stderr=err,
        clock=_Clock(_NOW),
    )

    assert code == 0
    assert recovery.retries == []
    assert recovery.session.commits == 0
    assert recovery.session.in_txn is False
    assert "dry_run=True" in err.getvalue()
    assert "would_change=1" in err.getvalue()


def test_operator_identity_and_reason_required() -> None:
    err = io.StringIO()

    code = retry_cli.main(
        ["--remote-id", "sub-x", "--environment", "sandbox", "--seller-account", _SELLER],
        stderr=err,
    )

    joined = err.getvalue().lower()
    assert code == 2
    assert "operator" in joined
    assert "whsec_" not in joined
    assert "polar_access" not in joined


@pytest.mark.asyncio
async def test_caller_injected_repository_skips_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_provider_env(monkeypatch)
    _forbid_provider(monkeypatch)
    recovery = _quarantined_recovery()

    def _forbidden_factory() -> object:
        raise AssertionError("injected recovery repository must not open a database session")

    _install_session_factory(monkeypatch, _forbidden_factory)
    code = await retry_cli.run(
        [*_RETRY_ARGV, "--apply"],
        recovery_repository=recovery,
        stderr=io.StringIO(),
        clock=_Clock(_NOW),
    )

    assert code == 0
    assert recovery.retries[0]["remote_id"] == "sub-x"
    assert retry_cli.audited_retry_quarantine is audited_retry_quarantine


def test_audited_retry_quarantine_public_cli_import_is_worker_function() -> None:
    assert retry_cli.audited_retry_quarantine is billing_reconcile_module.audited_retry_quarantine
