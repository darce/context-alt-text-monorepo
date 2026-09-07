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
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Mapped,
    String,
    Text,
    UniqueConstraint,
    datetime,
    func,
    mapped_column,
    relationship,
    text,
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
    prompt_or_task_version: Mapped[str] = mapped_column(String(64), nullable=False)
    visual_facts: Mapped[dict] = mapped_column(_json_col(), nullable=False)
    alt_text_draft: Mapped[str] = mapped_column(Text, nullable=False)
    # ALTQ-1: optional long-form surface persisted alongside the short draft so
    # cache hits return the same dual-length payload as the original generation.
    alt_text_long: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_used: Mapped[dict] = mapped_column(_json_col(), nullable=False)
    provider_disclosure: Mapped[dict] = mapped_column(_json_col(), nullable=False)
    # E19-4a: caption phrase-grounding boxes ([{phrase, span, box}, ...] in the
    # [0,1] top-left frame) so cache hits keep grounded-naming parity.
    phrase_boxes: Mapped[list | None] = mapped_column(_json_col(), nullable=True)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "image_hash",
            "adapter",
            "model_id",
            "model_version",
            "prompt_or_task_version",
            "context_hash",
            name="uq_image_descriptions_cache_key",
        ),
        Index("idx_image_descriptions_tenant", "tenant_id"),
    )


class DescribeRun(Base):
    __tablename__ = "image_description_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    # VLM-5: bulk multi-item runs vs single-image async supersede jobs [DATA-14].
    run_kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'bulk'"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    phase: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    media_ids: Mapped[list[int]] = mapped_column(_json_col(), nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # HARM-F1: WP recognition off-switch snapshot. Default ON matches the WP
    # RecognitionPolicy DEFAULT so omitted submits keep today's naming fusion.
    recognition_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
    # GUIDEDFIX-2 [RES-01]/[COST-10]: caller-supplied retry token. The unique
    # index below is the dedupe mechanism — a lost 202 plus a blind retry must
    # collide here rather than spend a second paid run. NULL keys stay distinct,
    # so submits without a token keep today's non-deduped behaviour.
    #
    # Lifetime (GUIDEDFIX-2 [S06], corrected): there is no TTL. Bulk runs are
    # never purged (``purge_expired_single_runs`` scans ``run_kind='single'``
    # only), so a key reserved by a bulk run is held for as long as that row
    # lives. The one release is barren-terminal: the repository nulls this column
    # when the run reaches a terminal status with zero completed items (FAILED,
    # CANCELLED, or the COMPLETED_WITH_ERRORS a restart reclaim derives when
    # every item failed), because a key naming a dead run would otherwise make
    # every later retry replay a 202 pointing at zero results, permanently. A run
    # with at least one completed item keeps its key: partial output is still
    # output, and replaying it is correct.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # GUIDEDFIX-2 [S03]: sha256 of the canonical submit payload the key is bound
    # to (sorted unique media_ids + recognition_enabled). Persisted rather than
    # re-derived from ``media_ids`` so replay/conflict is order-insensitive on
    # both sides. NULL for runs created outside the keyed submit route.
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # GUIDEDFIX-2 [RES-02]: generation budget in force at accept, snapshotted so
    # every poll discloses one stable bound instead of a re-read of settings.
    deadline_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(Integer)

    items: Mapped[list[DescribeRunItem]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed', 'cancelled')",
            name="valid_describe_run_status",
        ),
        CheckConstraint(
            "phase IN ('queued', 'warming', 'describing', 'complete', 'failed', 'cancelled')",
            name="valid_describe_run_phase",
        ),
        CheckConstraint("run_kind IN ('bulk', 'single')", name="valid_describe_run_kind"),
        # GUIDEDFIX-2: the reservation. Two concurrent retries of one key must
        # produce one run — the constraint violation IS the dedupe signal, so no
        # caller may rely on a check-then-insert window.
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_image_description_runs_idempotency_key"),
        Index("idx_image_description_runs_tenant", "tenant_id"),
        Index(
            "idx_image_description_runs_active",
            "tenant_id",
            "status",
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        # Tenant-less: purge + global load-snapshot consumers use RLS-bypassed sessions.
        Index(
            "idx_image_description_runs_single_active",
            "status",
            postgresql_where=text("run_kind = 'single' AND status IN ('pending', 'running')"),
        ),
    )


class DescribeRunItem(Base):
    __tablename__ = "image_description_run_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("image_description_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    media_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'queued'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    # WBUX-3: raw submitted image bytes, held only until the worker describes the
    # item, then cleared (set NULL) to reclaim storage.
    image_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    image_content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # WBUX-3: persisted describe output per item.
    alt_text_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(_json_col(), nullable=True)
    # VLM-5: single-run supersede envelope (provisional/final/degraded poll payload).
    visual_facts: Mapped[dict | None] = mapped_column(_json_col(), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    result_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    run: Mapped[DescribeRun] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("run_id", "media_id", name="uq_image_description_run_item_media"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'skipped')",
            name="valid_describe_item_status",
        ),
        Index("idx_image_description_run_items_run", "run_id"),
        Index(
            "idx_image_description_run_items_queued",
            "run_id",
            "status",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "idx_image_description_run_items_stale",
            "status",
            "started_at",
            postgresql_where=text("status = 'running'"),
        ),
        Index("idx_image_description_run_items_tenant", "tenant_id", "id"),
    )
