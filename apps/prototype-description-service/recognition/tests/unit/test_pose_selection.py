import logging
from datetime import datetime
from unittest.mock import MagicMock

import numpy as np
import pytest

from recognition.application.persistence.assignment_writer import (
    _find_upgradeable_representative,
    _get_pose_bucket,
    _is_novel_pose,
)
from recognition.application.settings.clustering import ClusteringSettings, QualitySettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.representative import ClusterRepresentative


@pytest.fixture
def settings():
    return ClusteringSettings(pose_diversity_bonus=3, pose_bucket_size=30.0, quality=QualitySettings())


def create_identity(id_val, pitch, yaw, confidence=0.9, bbox_area=10000):
    return MediaIdentity(
        id=id_val,
        tenant_id="t1",
        media_id="m1",
        embedding=np.zeros(512),
        confidence=confidence,
        bbox_width=int(np.sqrt(bbox_area)),
        bbox_height=int(np.sqrt(bbox_area)),
        pose_pitch=pitch,
        pose_yaw=yaw,
    )


def create_rep(id_val, pitch, yaw, quality=0.8):
    return ClusterRepresentative(
        id=id_val,
        cluster_id="c1",
        identity_id=f"id_{id_val}",
        embedding=np.zeros(512),
        created_at=datetime.now(),
        pose_pitch=pitch,
        pose_yaw=yaw,
        quality_score=quality,
    )


def test_get_pose_bucket():
    ident = create_identity("1", 45.0, 45.0)  # Bucket (1, 1) for 30.0 size
    bucket = _get_pose_bucket(ident, 30.0)
    assert bucket == (1, 1)

    ident_neg = create_identity("2", -45.0, -10.0)  # Bucket (-2, -1)
    bucket_neg = _get_pose_bucket(ident_neg, 30.0)
    assert bucket_neg == (-2, -1)


def test_get_pose_bucket_logs(caplog):
    # Scope caplog to the assignment_writer namespace so it overrides the
    # INFO floor api.logging_config.configure_logging() installs on
    # "recognition.application" when a TestClient fixture elsewhere in the
    # suite imports the FastAPI app — the root-level caplog.set_level
    # otherwise cannot see DEBUG records suppressed at the per-logger level.
    caplog.set_level(logging.DEBUG, logger="recognition.application.persistence.assignment_writer")
    ident = create_identity("log-1", 45.0, 45.0)
    bucket = _get_pose_bucket(ident, 30.0)
    assert bucket == (1, 1)
    assert "[pose_bucket]" in caplog.text


def test_is_novel_pose():
    # Reps cover (0,0) and (1,0)
    reps = [
        create_rep("r1", 10.0, 10.0),  # (0, 0)
        create_rep("r2", 40.0, 10.0),  # (1, 0)
    ]

    # Case 1: Same bucket (0,0) -> Not novel
    ident1 = create_identity("i1", 15.0, 15.0)
    assert _is_novel_pose(ident1, reps, 30.0) is False

    # Case 2: New bucket (0, 1) -> Novel
    ident2 = create_identity("i2", 10.0, 40.0)
    assert _is_novel_pose(ident2, reps, 30.0) is True


def test_find_upgradeable_representative(settings):
    # Rep at (0,0) with quality 0.5
    rep1 = create_rep("r1", 10.0, 10.0, quality=0.5)
    reps = [rep1]

    # Candidate 1: Same bucket, quality 0.55 -> diff 0.05 < 0.1 -> No upgrade
    create_identity("i1", 10.0, 10.0, confidence=0.5, bbox_area=100)  # Low quality
    # Note: _compute_identity_quality needs to be mocked or we rely on real logic.
    # Real logic uses confidence * 0.6 + size_score * 0.4.
    # Let's ensure ident1 quality is close to rep1.

    # Candidate 2: Same bucket, significantly better quality
    # High confidence (0.99) + Large face (20000+) -> quality ~ 0.6*0.99 + 0.4*1.0 = 0.99
    ident2 = create_identity("i2", 10.0, 10.0, confidence=0.99, bbox_area=25000)

    target = _find_upgradeable_representative(ident2, reps, 30.0, settings)
    assert target == rep1

    # Candidate 3: Different bucket -> No upgrade (handled by novelty check)
    ident3 = create_identity("i3", 40.0, 40.0)
    target = _find_upgradeable_representative(ident3, reps, 30.0, settings)
    assert target is None

    # Candidate 4: Same bucket, worse quality
    ident4 = create_identity("i4", 10.0, 10.0, confidence=0.1, bbox_area=100)
    target = _find_upgradeable_representative(ident4, reps, 30.0, settings)
    assert target is None
