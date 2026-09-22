"""Auditable mapping of legacy NULL billing namespace rows.

Default is dry-run. Apply requires a mapping file keyed by verified row IDs,
explicit provider namespace, and operator evidence. Does not guess environment
or seller, does not map across tenants, and does not silently merge collisions.

Uses transaction-local ``SET LOCAL app.bypass_rls = 'true'`` only. Never
``ALTER ROLE ... BYPASSRLS``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text

from db.settings import get_database_settings

_INBOX = "billing_webhook_inbox"
_PROJECTION = "billing_subscription_projection"
_ALLOWED_ENVIRONMENTS = frozenset({"sandbox", "live"})


def _uuid(value: object, *, field: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _namespace(entry: Mapping[str, Any]) -> tuple[str, str]:
    environment = str(entry.get("environment", "")).strip()
    seller = str(entry.get("seller_account", "")).strip()
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise ValueError("mapping environment must be sandbox or live")
    if not seller:
        raise ValueError("mapping seller_account is required")
    return environment, seller


def _load_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("mapping file must be a JSON object")
    evidence = payload.get("evidence") or payload.get("operator_evidence")
    identity = payload.get("operator_identity")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("mapping requires operator evidence")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("mapping requires operator_identity")
    return payload


def _list_unmapped(conn) -> dict[str, list[dict[str, Any]]]:
    inbox = [
        {"id": str(row[0]), "provider": row[1], "provider_event_id": row[2]}
        for row in conn.execute(
            text(
                "SELECT id, provider, provider_event_id FROM billing_webhook_inbox "
                "WHERE environment IS NULL OR seller_account IS NULL ORDER BY received_at, id"
            )
        )
    ]
    projections = [
        {
            "id": str(row[0]),
            "tenant_id": str(row[1]),
            "provider": row[2],
            "provider_customer_id": row[3],
        }
        for row in conn.execute(
            text(
                "SELECT id, tenant_id, provider, provider_customer_id "
                "FROM billing_subscription_projection "
                "WHERE environment IS NULL OR seller_account IS NULL ORDER BY tenant_id"
            )
        )
    ]
    return {"inbox": inbox, "projection": projections}


def _apply_inbox(conn, entry: Mapping[str, Any]) -> None:
    row_id = _uuid(entry.get("id"), field="inbox.id")
    environment, seller = _namespace(entry)
    current = (
        conn.execute(
            text(
                "SELECT provider, provider_event_id, environment, seller_account "
                "FROM billing_webhook_inbox WHERE id = :id"
            ),
            {"id": row_id},
        )
        .mappings()
        .first()
    )
    if current is None:
        raise RuntimeError(f"inbox row {row_id} was not found")
    if current["environment"] not in {None, environment} or current["seller_account"] not in {None, seller}:
        raise RuntimeError(f"inbox row {row_id} already has a different namespace")
    collision = conn.execute(
        text(
            "SELECT id FROM billing_webhook_inbox "
            "WHERE provider = :provider AND environment = :environment "
            "AND seller_account = :seller AND provider_event_id = :event_id AND id <> :id"
        ),
        {
            "provider": current["provider"],
            "environment": environment,
            "seller": seller,
            "event_id": current["provider_event_id"],
            "id": row_id,
        },
    ).scalar()
    if collision is not None:
        raise RuntimeError(f"inbox mapping for {row_id} collides with {collision}")
    conn.execute(
        text("UPDATE billing_webhook_inbox SET environment = :environment, seller_account = :seller WHERE id = :id"),
        {"environment": environment, "seller": seller, "id": row_id},
    )


def _apply_projection(conn, entry: Mapping[str, Any]) -> None:
    row_id = _uuid(entry.get("id"), field="projection.id")
    environment, seller = _namespace(entry)
    current = (
        conn.execute(
            text(
                "SELECT tenant_id, provider, provider_customer_id, environment, seller_account "
                "FROM billing_subscription_projection WHERE id = :id"
            ),
            {"id": row_id},
        )
        .mappings()
        .first()
    )
    if current is None:
        raise RuntimeError(f"projection row {row_id} was not found")
    if current["environment"] not in {None, environment} or current["seller_account"] not in {None, seller}:
        raise RuntimeError(f"projection row {row_id} already has a different namespace")
    if "tenant_id" in entry and str(entry["tenant_id"]) != str(current["tenant_id"]):
        raise RuntimeError(f"projection mapping for {row_id} cannot change tenant_id")
    collision = (
        conn.execute(
            text(
                "SELECT id, tenant_id FROM billing_subscription_projection "
                "WHERE provider = :provider AND environment = :environment "
                "AND seller_account = :seller AND provider_customer_id = :customer_id AND id <> :id"
            ),
            {
                "provider": current["provider"],
                "environment": environment,
                "seller": seller,
                "customer_id": current["provider_customer_id"],
                "id": row_id,
            },
        )
        .mappings()
        .first()
    )
    if collision is not None:
        raise RuntimeError(
            f"projection mapping for {row_id} collides with {collision['id']} "
            f"(tenant {collision['tenant_id']}); refusing silent merge"
        )
    conn.execute(
        text(
            "UPDATE billing_subscription_projection "
            "SET environment = :environment, seller_account = :seller WHERE id = :id"
        ),
        {"environment": environment, "seller": seller, "id": row_id},
    )


def run(conn, mapping: Mapping[str, Any] | None, *, apply: bool) -> dict[str, Any]:
    previous = conn.execute(text("SELECT current_setting('app.bypass_rls', true)")).scalar() or ""
    conn.execute(text("SELECT set_config('app.bypass_rls', 'true', true)"))
    try:
        unmapped = _list_unmapped(conn)
        report: dict[str, Any] = {
            "apply": apply,
            "unmapped": unmapped,
            "mapped_inbox": 0,
            "mapped_projection": 0,
        }
        if mapping is None:
            return report
        inbox_entries = mapping.get("inbox") or []
        projection_entries = mapping.get("projection") or []
        if not isinstance(inbox_entries, list) or not isinstance(projection_entries, list):
            raise ValueError("inbox and projection mapping lists are required")
        report["operator_identity"] = mapping.get("operator_identity")
        report["evidence"] = mapping.get("evidence") or mapping.get("operator_evidence")
        if apply:
            for entry in inbox_entries:
                if not isinstance(entry, Mapping):
                    raise ValueError("inbox mapping entries must be objects")
                _apply_inbox(conn, entry)
                report["mapped_inbox"] += 1
            for entry in projection_entries:
                if not isinstance(entry, Mapping):
                    raise ValueError("projection mapping entries must be objects")
                _apply_projection(conn, entry)
                report["mapped_projection"] += 1
        else:
            report["mapped_inbox"] = len(inbox_entries)
            report["mapped_projection"] = len(projection_entries)
        return report
    finally:
        conn.execute(text("SELECT set_config('app.bypass_rls', :value, true)"), {"value": previous})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, default=None, help="JSON mapping of verified row IDs")
    parser.add_argument("--apply", action="store_true", help="Write mappings (default is dry-run)")
    args = parser.parse_args(argv)
    mapping = _load_mapping(args.mapping) if args.mapping is not None else None
    if args.apply and mapping is None:
        print("apply requires --mapping", file=sys.stderr)
        return 2
    engine = create_engine(get_database_settings().postgres_sync_dsn)
    try:
        with engine.connect() as conn:
            if conn.dialect.name != "postgresql":
                print("billing namespace mapping requires PostgreSQL", file=sys.stderr)
                return 2
            trans = conn.begin()
            try:
                report = run(conn, mapping, apply=args.apply)
                print(json.dumps(report, indent=2, sort_keys=True))
                if args.apply:
                    trans.commit()
                else:
                    trans.rollback()
            except Exception:
                trans.rollback()
                raise
    except Exception as exc:
        print(f"billing namespace mapping failed: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
