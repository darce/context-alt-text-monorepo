"""Fenced known-item lease for inbox and projection reconciliation.

N1 owns this type. R1 may duck-type the same fields until this module lands.
Caller must COMMIT the claim transaction before any provider GET. Vendor I/O
never holds this row lock. ``fence`` is the monotonic generation; ``lease_until``
is not a fence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class BillingWorkKind(StrEnum):
    INBOX = "inbox"
    PROJECTION = "projection"


class BillingWorkLeaseConflictError(Exception):
    """The caller no longer owns the item: expired, stolen, or stale fence."""


class BillingNamespaceConflictError(Exception):
    """A tenant projection already belongs to a different billing namespace."""


class BillingNamespaceRequiredError(Exception):
    """Bound billing operations require an explicit environment and seller_account."""


@dataclass(frozen=True, slots=True)
class BillingWorkLease:
    """Opaque fenced lease returned by ``claim_reconcile_item``.

    Fields are public so R1 can duck-type without importing this module.
    """

    provider: str
    environment: str
    seller_account: str
    kind: str
    remote_id: str
    owner: str
    fence: int
    lease_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider is required")
        if self.environment not in {"sandbox", "live"}:
            raise ValueError("environment must be sandbox or live")
        if not isinstance(self.seller_account, str) or not self.seller_account.strip():
            raise ValueError("seller_account is required")
        try:
            kind = BillingWorkKind(self.kind)
        except ValueError as exc:
            raise ValueError("kind must be inbox or projection") from exc
        if not isinstance(self.remote_id, str) or not self.remote_id.strip():
            raise ValueError("remote_id is required")
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise ValueError("owner is required")
        if not isinstance(self.fence, int) or isinstance(self.fence, bool) or self.fence < 1:
            raise ValueError("lease fence must be a positive integer")
        if not isinstance(self.lease_until, datetime) or self.lease_until.tzinfo is None:
            raise ValueError("lease_until must be a timezone-aware datetime")
        object.__setattr__(self, "provider", self.provider.strip())
        object.__setattr__(self, "seller_account", self.seller_account.strip())
        object.__setattr__(self, "kind", kind.value)
        object.__setattr__(self, "remote_id", self.remote_id.strip())
        object.__setattr__(self, "owner", self.owner.strip())


__all__ = [
    "BillingNamespaceConflictError",
    "BillingNamespaceRequiredError",
    "BillingWorkKind",
    "BillingWorkLease",
    "BillingWorkLeaseConflictError",
]
