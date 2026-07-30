"""FIR23-01: label inference in-process path must not cross embedding spaces."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.suggestions.label_inference import infer_suggested_label
from recognition.domain.suggestion import SuggestedLabelSource


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


class _FakeResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def first(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        if isinstance(self._value, list):
            return self._value
        return []


@pytest.mark.asyncio
async def test_in_process_nn_excludes_foreign_embedding_model() -> None:
    """Cross-space labeled reps must not win nearest-label inference.

    Unfixed code compared all labeled reps and returned the foreign label when
    its cosine cleared the threshold, then short-circuited before the FIR23-01
    SQL filter.
    """
    tenant_id = uuid4()
    target_id = uuid4()
    same_cluster_id = str(uuid4())
    foreign_cluster_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    foreign_model = "opencv-sface@128d/l2/cosine"

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    # Foreign rep is *closer* in raw cosine if compared — must still be excluded.
    foreign_rep_vec = _normalize(np.array([0.99, 0.01, 0.0]))
    same_rep_vec = _normalize(np.array([0.8, 0.2, 0.0]))

    same_identity_id = str(uuid4())
    foreign_identity_id = str(uuid4())

    target_cluster = SimpleNamespace(
        id=target_id,
        tenant_id=tenant_id,
        roster_id=None,
        representative_identity=SimpleNamespace(
            embedding=target_vec,
            embedding_model=same_model,
        ),
    )

    labeled_same = SimpleNamespace(id=same_cluster_id, label="SameSpace")
    labeled_foreign = SimpleNamespace(id=foreign_cluster_id, label="ForeignSpace")
    rep_same = SimpleNamespace(
        embedding=same_rep_vec,
        embedding_model=same_model,
        identity_id=same_identity_id,
    )
    rep_foreign = SimpleNamespace(
        embedding=foreign_rep_vec,
        embedding_model=foreign_model,
        identity_id=foreign_identity_id,
    )

    labeled_with_reps = [
        (labeled_same, [rep_same]),
        (labeled_foreign, [rep_foreign]),
    ]

    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=labeled_with_reps),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}

    async def _execute(stmt):
        call_count["n"] += 1
        # 1st execute: target cluster load
        if call_count["n"] == 1:
            return _FakeResult(target_cluster)
        # identity match query → none
        if call_count["n"] == 2:
            return _FakeResult(None)
        # merge match → none
        if call_count["n"] == 3:
            return _FakeResult(None)
        # same-model identity id lookup for FIR23-01 in-process filter
        if call_count["n"] == 4:
            return _FakeResult([same_identity_id])
        # SQL NN fallback (should not be required when same-space rep wins)
        return _FakeResult(None)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    # suggestion_floor default is low enough that same_rep cosine clears it
    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,  # type: ignore[arg-type]
    )

    assert result is not None
    assert result.label == "SameSpace"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert result.target_cluster_id == same_cluster_id
    assert result.label != "ForeignSpace"


@pytest.mark.asyncio
async def test_in_process_nn_no_match_falls_through_when_model_known() -> None:
    """When model-filtered in-process finds nothing, do not exclusive-return None
    without attempting the FIR23-01 SQL path (sqlite short-circuits to None).
    """
    tenant_id = uuid4()
    target_id = uuid4()
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    foreign_model = "opencv-sface@128d/l2/cosine"
    foreign_identity_id = str(uuid4())

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    foreign_rep_vec = _normalize(np.array([0.99, 0.01, 0.0]))

    target_cluster = SimpleNamespace(
        id=target_id,
        tenant_id=tenant_id,
        roster_id=None,
        representative_identity=SimpleNamespace(
            embedding=target_vec,
            embedding_model=same_model,
        ),
    )

    labeled_foreign = SimpleNamespace(id=str(uuid4()), label="ForeignOnly")
    rep_foreign = SimpleNamespace(
        embedding=foreign_rep_vec,
        embedding_model=foreign_model,
        identity_id=foreign_identity_id,
    )

    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=[(labeled_foreign, [rep_foreign])]),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}

    async def _execute(stmt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResult(target_cluster)
        if call_count["n"] in (2, 3):
            return _FakeResult(None)
        # same-model ids: empty → foreign rep excluded
        if call_count["n"] == 4:
            return _FakeResult([])
        # SQL path would run next on non-sqlite; dialect guard returns None.
        return _FakeResult(None)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    # Force sqlite dialect path so cosine_distance is not invoked.
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,  # type: ignore[arg-type]
    )

    # Foreign-only labeled set must not produce a cross-space suggestion.
    assert result is None
