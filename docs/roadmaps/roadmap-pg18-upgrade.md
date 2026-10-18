# PostgreSQL 17 → 18 Upgrade Evaluation (v0.1) — superseded

> **Status:** Superseded 2026-09-16 by [roadmap-pg19-upgrade.md](roadmap-pg19-upgrade.md) (v0.2, PG17 → 19 in one hop). This file is kept only so existing links resolve; do not extend it.

## What carried over

- **Phase 0 (session timeouts) shipped**: `SET LOCAL statement_timeout` / `idle_in_transaction_session_timeout` from `DB_STATEMENT_TIMEOUT` / `DB_IDLE_IN_TXN_TIMEOUT` in `recognition/interface_adapters/http/deps/session.py`. Server-level `transaction_timeout` is still open and now lives in the v0.2 "Now" list.
- **UUIDv7** moved app-side (`recognition/shared/ids.py::generate_id`); `uuid-ossp` has zero callers and is scheduled for removal on PG17.
- Every PG18 feature this document planned around (UUIDv7, AIO, skip scan, `RETURNING OLD/NEW`, virtual generated columns, `--no-policies`, non-btree MV unique index, OAuth, temporal PK) is present in PG19, so the phases were re-planned against 19 rather than executed twice.
- Deferred items D1–D10 are re-listed with PG19 deltas in v0.2 §12 (D8 closed; D11–D13 added).

## Why PG18 is skipped

Two major upgrades (17→18→19) cost two `pg_upgrade` windows, two pgvector image waits, and two compatibility sweeps for no feature PG19 does not also provide. See v0.2 §0 and the canon citation CARD-15 (reversible commitments).

## Historical content

The v0.1 text (Phases 0–5, D1–D10 with the PostgREST endpoint tables, code anchors, success metrics) is preserved in git history at commit `b74f91a684a3881fd37a391fe76be4e4e316e085` and earlier: `git show b74f91a684a3:docs/roadmaps/roadmap-pg18-upgrade.md`.
