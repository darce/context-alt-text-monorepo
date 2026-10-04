"""Regression cases for ledger expiry, terminal settlement, and sweep paging."""

import pytest

from recognition.tests.unit.test_app1_usage_sweeper import (
    _advfix_ledger_h1_expiry_releases_counters,
    _advfix_ledger_h2_terminal_commit_keeps_daily_charge,
    _advfix_ledger_m1_sweeper_pages_past_active_prefix,
)


@pytest.mark.asyncio
async def test_admission_expiry_releases_global_counters_before_new_reserve(monkeypatch) -> None:
    await _advfix_ledger_h1_expiry_releases_counters(monkeypatch)


@pytest.mark.asyncio
async def test_stale_started_terminal_job_commits_and_keeps_daily_charge(monkeypatch) -> None:
    await _advfix_ledger_h2_terminal_commit_keeps_daily_charge(monkeypatch)


@pytest.mark.asyncio
async def test_sweeper_pages_past_active_prefix_to_release_missing_job() -> None:
    await _advfix_ledger_m1_sweeper_pages_past_active_prefix()
