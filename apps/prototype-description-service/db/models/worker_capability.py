"""Worker-published capability rows read by the API intake gate."""

from __future__ import annotations

from datetime import datetime

from db.models.base_imports import TIMESTAMP, Base, Boolean, Mapped, String, Text, func, mapped_column

SCAN_WORKER_KIND = "scan_worker"
EMBEDDING_RUNTIME_CAPABILITY = "embedding_runtime"


class WorkerCapability(Base):
    """Heartbeat + availability fact published by background workers."""

    __tablename__ = "worker_capabilities"

    worker_kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
