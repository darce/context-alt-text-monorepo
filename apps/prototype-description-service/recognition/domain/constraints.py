"""Domain types for pairwise identity constraints.

Constraints represent user curation signals that inform clustering decisions:
- MUST_LINK: Identities that should be in the same cluster (from merge)
- CANNOT_LINK: Identities that should never be in the same cluster (from split/wrong-person)
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ConstraintType(StrEnum):
    """Constraint types for identity pairs."""

    MUST_LINK = "must_link"
    CANNOT_LINK = "cannot_link"


class ConstraintSource(StrEnum):
    """Source of constraint creation."""

    MERGE = "merge"
    SPLIT = "split"
    WRONG_PERSON = "wrong_person"
    MANUAL_REJECT = "manual_reject"


@dataclass(frozen=True)
class IdentityConstraint:
    """Pairwise constraint between two identities.

    Constraints are stored with canonical ordering (identity_a < identity_b)
    to ensure uniqueness and simplify lookups.

    Attributes:
        id: Unique constraint ID.
        tenant_id: Tenant scope for RLS.
        identity_a: First identity (canonical ordering: a < b).
        identity_b: Second identity.
        constraint_type: MUST_LINK or CANNOT_LINK.
        source: User action that created the constraint.
        created_at: When the constraint was created.
        created_by_user_id: Optional WordPress user ID who created it.
    """

    id: UUID
    tenant_id: UUID
    identity_a: UUID
    identity_b: UUID
    constraint_type: ConstraintType
    source: ConstraintSource
    created_at: datetime
    created_by_user_id: int | None = None


def canonical_order(id_a: UUID, id_b: UUID) -> tuple[UUID, UUID]:
    """Return identity pair in canonical order (a < b).

    Args:
        id_a: First identity ID.
        id_b: Second identity ID.

    Returns:
        Tuple of (smaller_id, larger_id) based on UUID comparison.

    Example:
        >>> a = UUID("aaaaaaaa-0000-0000-0000-000000000001")
        >>> b = UUID("bbbbbbbb-0000-0000-0000-000000000002")
        >>> canonical_order(b, a)
        (UUID('aaaaaaaa-0000-0000-0000-000000000001'), UUID('bbbbbbbb-0000-0000-0000-000000000002'))
    """
    if id_a < id_b:
        return (id_a, id_b)
    return (id_b, id_a)
