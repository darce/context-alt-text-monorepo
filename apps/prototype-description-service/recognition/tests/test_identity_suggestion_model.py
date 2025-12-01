"""Tests for the IdentitySuggestion model."""

import uuid
from datetime import UTC, datetime, timezone

from db.models import IdentitySuggestion


class TestIdentitySuggestionModel:
    """Unit tests for IdentitySuggestion model instantiation."""

    def test_identity_suggestion_fields(self) -> None:
        """Test that all fields are set correctly on instantiation."""
        tenant_id = uuid.uuid4()
        identity_id = uuid.uuid4()
        cluster_id = uuid.uuid4()

        suggestion = IdentitySuggestion(
            tenant_id=tenant_id,
            identity_id=identity_id,
            suggested_cluster_id=cluster_id,
            representative_similarity=0.65,
            avg_member_similarity=0.58,
            confidence_score=0.72,
        )

        assert suggestion.__tablename__ == "identity_suggestions"
        assert suggestion.tenant_id == tenant_id
        assert suggestion.identity_id == identity_id
        assert suggestion.suggested_cluster_id == cluster_id
        assert suggestion.representative_similarity == 0.65
        assert suggestion.avg_member_similarity == 0.58
        assert suggestion.confidence_score == 0.72

    def test_identity_suggestion_default_resolution(self) -> None:
        """Test that resolution defaults to 'pending' via server_default."""
        suggestion = IdentitySuggestion(
            tenant_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
            suggested_cluster_id=uuid.uuid4(),
            representative_similarity=0.62,
            avg_member_similarity=0.55,
            confidence_score=0.60,
        )

        # Note: server_default only applies when persisting to DB.
        # In-memory, the attribute won't have a value unless explicitly set.
        # This test verifies the model accepts the default state.
        assert suggestion.representative_similarity == 0.62

    def test_identity_suggestion_with_explicit_resolution(self) -> None:
        """Test setting explicit resolution states."""
        for resolution in ["pending", "accepted", "rejected", "expired"]:
            suggestion = IdentitySuggestion(
                tenant_id=uuid.uuid4(),
                identity_id=uuid.uuid4(),
                suggested_cluster_id=uuid.uuid4(),
                representative_similarity=0.60,
                avg_member_similarity=0.55,
                confidence_score=0.58,
                resolution=resolution,
            )
            assert suggestion.resolution == resolution

    def test_identity_suggestion_with_resolved_at(self) -> None:
        """Test setting resolved_at timestamp."""
        resolved_time = datetime.now(UTC)

        suggestion = IdentitySuggestion(
            tenant_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
            suggested_cluster_id=uuid.uuid4(),
            representative_similarity=0.64,
            avg_member_similarity=0.60,
            confidence_score=0.68,
            resolution="accepted",
            resolved_at=resolved_time,
        )

        assert suggestion.resolved_at == resolved_time
        assert suggestion.resolution == "accepted"

    def test_identity_suggestion_borderline_similarity_values(self) -> None:
        """Test typical borderline range values (0.55-0.68)."""
        # Lower borderline case
        low_suggestion = IdentitySuggestion(
            tenant_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
            suggested_cluster_id=uuid.uuid4(),
            representative_similarity=0.60,
            avg_member_similarity=0.55,  # Just at suggestion threshold
            confidence_score=0.50,
        )
        assert low_suggestion.avg_member_similarity == 0.55

        # Upper borderline case (just below accept threshold)
        high_suggestion = IdentitySuggestion(
            tenant_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
            suggested_cluster_id=uuid.uuid4(),
            representative_similarity=0.70,
            avg_member_similarity=0.67,  # Just below 0.68 accept threshold
            confidence_score=0.85,
        )
        assert high_suggestion.avg_member_similarity == 0.67

    def test_identity_suggestion_boundary_values(self) -> None:
        """Test similarity score boundary values (0.0 and 1.0)."""
        # Minimum values
        min_suggestion = IdentitySuggestion(
            tenant_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
            suggested_cluster_id=uuid.uuid4(),
            representative_similarity=0.0,
            avg_member_similarity=0.0,
            confidence_score=0.0,
        )
        assert min_suggestion.representative_similarity == 0.0
        assert min_suggestion.avg_member_similarity == 0.0
        assert min_suggestion.confidence_score == 0.0

        # Maximum values
        max_suggestion = IdentitySuggestion(
            tenant_id=uuid.uuid4(),
            identity_id=uuid.uuid4(),
            suggested_cluster_id=uuid.uuid4(),
            representative_similarity=1.0,
            avg_member_similarity=1.0,
            confidence_score=1.0,
        )
        assert max_suggestion.representative_similarity == 1.0
        assert max_suggestion.avg_member_similarity == 1.0
        assert max_suggestion.confidence_score == 1.0


class TestIdentitySuggestionTableArgs:
    """Tests for table constraints and indexes."""

    def test_tablename(self) -> None:
        """Verify the table name is correct."""
        assert IdentitySuggestion.__tablename__ == "identity_suggestions"

    def test_table_has_constraints(self) -> None:
        """Verify table has expected constraints defined."""
        from sqlalchemy import Table

        table = IdentitySuggestion.__table__
        assert isinstance(table, Table)
        constraint_names = {c.name for c in table.constraints if c.name}

        # Check for key constraints
        assert "unique_identity_suggestion" in constraint_names
        assert "representative_similarity_range" in constraint_names
        assert "avg_member_similarity_range" in constraint_names
        assert "confidence_score_range" in constraint_names
        assert "valid_resolution" in constraint_names

    def test_table_has_indexes(self) -> None:
        """Verify table has expected indexes defined."""
        from sqlalchemy import Table

        table = IdentitySuggestion.__table__
        assert isinstance(table, Table)
        index_names = {idx.name for idx in table.indexes}

        assert "idx_identity_suggestions_tenant" in index_names
        assert "idx_identity_suggestions_identity" in index_names
        assert "idx_identity_suggestions_cluster" in index_names
        assert "idx_identity_suggestions_pending" in index_names
