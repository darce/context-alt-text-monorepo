"""Image-description cache/provenance model (E19-1 S3).

One row per generated description, keyed by the six-tuple cache key so repeat
requests are cache hits. Follows db/models/jobs.py conventions; tenant-scoped so
the migration's RLS loop (image_descriptions is in TENANT_TABLES) applies a
tenant-isolation policy. ``cached`` and the per-request ``duration_ms`` of a hit
are response-envelope fields, not stored; ``duration_ms`` here is the original
generation cost (provenance).
"""

from __future__ import annotations

from db.models.base_imports import (
    JSON,
    JSONB,
    TIMESTAMP,
    UUID,
    Base,
    ForeignKey,
    Index,
    Integer,
    Mapped,
    String,
    Text,
    UniqueConstraint,
    datetime,
    func,
    mapped_column,
    uuid,
)


def _json_col():
    """JSONB on Postgres, JSON on sqlite (test) — a fresh type per column."""
    return JSONB().with_variant(JSON(), "sqlite")


class ImageDescription(Base):
    __tablename__ = "image_descriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(Integer, nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    adapter: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_or_task_version: Mapped[str] = mapped_column(String(32), nullable=False)
    visual_facts: Mapped[dict] = mapped_column(_json_col(), nullable=False)
    alt_text_draft: Mapped[str] = mapped_column(Text, nullable=False)
    context_used: Mapped[dict] = mapped_column(_json_col(), nullable=False)
    provider_disclosure: Mapped[dict] = mapped_column(_json_col(), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "image_hash",
            "adapter",
            "model_version",
            "prompt_or_task_version",
            "context_hash",
            name="uq_image_descriptions_cache_key",
        ),
        Index("idx_image_descriptions_tenant", "tenant_id"),
    )
