"""Similarity helpers used during cluster curation."""

from __future__ import annotations

import logging
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusterRepresentative as RepModel
from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.suggestions.embedding_space import models_are_same_space
from recognition.shared.similarity import compute_face_similarity

logger = logging.getLogger(__name__)


async def compute_curation_similarity(
    *,
    identity_embedding: np.ndarray,
    target_cluster_id: str,
    session: AsyncSession,
    identity_embedding_model: str | None = None,
) -> float:
    """Compute similarity between an identity and same-space cluster representatives."""
    result = await session.execute(
        select(RepModel, MediaIdentityModel.embedding_model)
        .join(MediaIdentityModel, MediaIdentityModel.id == RepModel.identity_id)
        .where(RepModel.cluster_id == uuid.UUID(target_cluster_id))
    )
    rows = result.all()

    if not rows:
        return 0.0

    max_sim = 0.0
    compared = False
    for rep, rep_model in rows:
        if rep.embedding is None:
            continue
        if not models_are_same_space(identity_embedding_model, rep_model if isinstance(rep_model, str) else None):
            continue
        rep_embedding = np.asarray(rep.embedding, dtype=np.float32)
        sim = compute_face_similarity(identity_embedding, rep_embedding)
        max_sim = max(max_sim, sim)
        compared = True

    if not compared:
        logger.info(
            "[curation] skipped cross-space cosine cluster_id=%s identity_model=%s",
            target_cluster_id,
            identity_embedding_model,
        )
        return 0.0

    return float(max_sim)


async def check_and_refresh_representatives(
    *,
    cluster_id: str,
    removed_identity_id: str,
    assignment_writer: AssignmentWriter,
    session: AsyncSession,
    refresh: bool = True,
) -> bool:
    """Check if removed identity was a representative and trigger refresh if so."""
    result = await session.execute(
        select(RepModel).where(
            RepModel.cluster_id == uuid.UUID(cluster_id),
            RepModel.identity_id == uuid.UUID(removed_identity_id),
        )
    )
    rep = result.scalar_one_or_none()

    if rep is None:
        return False

    await session.delete(rep)
    await session.flush()

    logger.info(
        "[curation] REPRESENTATIVE_REMOVED identity=%s cluster=%s triggered_refresh=%s",
        removed_identity_id,
        cluster_id,
        str(refresh).lower(),
    )

    if refresh:
        await assignment_writer.refresh_representatives_for_cluster(cluster_id)
        return True

    return False
