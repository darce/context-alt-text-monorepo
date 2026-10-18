"""Mappings from persistence models to recognition domain identities."""

from __future__ import annotations

import uuid

import numpy as np

from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.identity import MediaIdentity


def media_identity_from_model(model: MediaIdentityModel) -> MediaIdentity:
    """Build a domain identity while preserving embedding provenance."""
    moved_by_merge_id = model.moved_by_merge_id
    embedding_model = model.embedding_model
    return MediaIdentity(
        id=str(model.id),
        tenant_id=str(model.tenant_id),
        media_id=str(model.media_id),
        embedding=np.asarray(model.embedding, dtype=np.float32),
        confidence=float(model.confidence),
        bbox_width=int(model.bbox_width),
        bbox_height=int(model.bbox_height),
        bbox_x=int(model.bbox_x),
        bbox_y=int(model.bbox_y),
        pose_pitch=float(model.pose_pitch) if model.pose_pitch is not None else None,
        pose_yaw=float(model.pose_yaw) if model.pose_yaw is not None else None,
        pose_roll=float(model.pose_roll) if model.pose_roll is not None else None,
        image_phash=str(model.image_phash) if model.image_phash is not None else None,
        sharpness=float(model.sharpness) if model.sharpness is not None else None,
        embedding_norm=float(model.embedding_norm) if model.embedding_norm is not None else None,
        occlusion_severity=float(model.occlusion_severity) if model.occlusion_severity is not None else None,
        moved_by_merge_id=(
            str(moved_by_merge_id) if isinstance(moved_by_merge_id, (str, uuid.UUID)) and moved_by_merge_id else None
        ),
        embedding_model=embedding_model if isinstance(embedding_model, str) and embedding_model else None,
    )
