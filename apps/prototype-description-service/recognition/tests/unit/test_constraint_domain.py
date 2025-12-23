"""Unit tests for IdentityConstraint domain object."""

from datetime import datetime
from uuid import UUID

import pytest

from recognition.domain.constraints import ConstraintSource, ConstraintType, IdentityConstraint


class TestIdentityConstraint:
    """Unit tests for IdentityConstraint domain object."""

    def test_canonical_ordering_enforced(self):
        """identity_a must always be less than identity_b."""
        from recognition.domain.constraints import canonical_order

        id_a = UUID("00000000-0000-0000-0000-000000000001")
        id_b = UUID("00000000-0000-0000-0000-000000000002")

        # Constraint should enforce canonical order
        constraint = IdentityConstraint(
            id=UUID("00000000-0000-0000-0000-000000000003"),
            tenant_id=UUID("00000000-0000-0000-0000-000000000004"),
            identity_a=id_a,
            identity_b=id_b,
            constraint_type=ConstraintType.MUST_LINK,
            source=ConstraintSource.MERGE,
            created_at=datetime.now(),
        )

        # Verify ordering
        first, second = canonical_order(id_a, id_b)
        assert constraint.identity_a == first
        assert constraint.identity_b == second
        assert constraint.identity_a < constraint.identity_b

    def test_cannot_link_constraint_type(self):
        """CANNOT_LINK maps to string 'cannot_link'."""
        assert ConstraintType.CANNOT_LINK.value == "cannot_link"
        assert ConstraintType.MUST_LINK.value == "must_link"
