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


def _flatten_binds(stmt) -> set[str]:
    """Flatten compiled bind params (including expanding IN-list values) to strings."""
    binds = stmt.compile().params
    bind_values: set[str] = set()
    for value in binds.values():
        if isinstance(value, (list, tuple, set)):
            bind_values.update(str(item) for item in value)
        else:
            bind_values.add(str(value))
    return bind_values


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


def _session_execute_side_effect(
    *,
    target_cluster,
    call_count: dict[str, int],
    captured_stmts: list[object] | None = None,
    model_lookup_handler=None,
):
    """Shared execute stub: target → identity-miss → merge-miss → optional model lookup."""

    async def _execute(stmt):
        call_count["n"] += 1
        if captured_stmts is not None:
            captured_stmts.append(stmt)
        if call_count["n"] == 1:
            return _FakeResult(target_cluster)
        if call_count["n"] in (2, 3):
            return _FakeResult(None)
        if call_count["n"] == 4 and model_lookup_handler is not None:
            return model_lookup_handler(stmt)
        return _FakeResult(None)

    return _execute


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
        get_representative_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
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
        # CVUP1-GR-20: reps already carry embedding_model, so no corpus-wide
        # same-model id lookup should run. Any further execute is SQL NN fallback.
        return _FakeResult(None)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    # suggestion_floor default is low enough that same_rep cosine clears it
    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    assert result is not None
    assert result.label == "SameSpace"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert result.target_cluster_id == same_cluster_id
    assert result.label != "ForeignSpace"
    # Only target + identity-match + merge queries — no full-corpus model id fetch.
    assert call_count["n"] == 3


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
        get_representative_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}

    async def _execute(stmt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResult(target_cluster)
        if call_count["n"] in (2, 3):
            return _FakeResult(None)
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
        cluster_repository=cluster_repository,
    )

    # Foreign-only labeled set must not produce a cross-space suggestion.
    assert result is None


@pytest.mark.asyncio
async def test_in_process_nn_bounds_model_lookup_to_representative_ids() -> None:
    """CVUP1-GR-20: same-model provenance query must key on scored rep ids only.

    Domain representatives drop embedding_model. Provenance is recovered via a
    single MediaIdentity.id.in_(rep_ids) query — never the tenant's full corpus.
    Turns red if the filter is removed (foreign label would win) or if the
    lookup widens to an unbounded tenant-wide select.

    R3-G3-2: mock result is derived from the compiled statement so deleting
    ``MediaIdentity.embedding_model == target_model`` from the provenance SELECT
    re-opens cross-space NN and this test fails.
    """
    tenant_id = uuid4()
    target_id = uuid4()
    same_cluster_id = str(uuid4())
    foreign_cluster_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
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

    # Domain-like reps: no embedding_model attr (must resolve via id set).
    labeled_same = SimpleNamespace(id=same_cluster_id, label="SameSpace")
    labeled_foreign = SimpleNamespace(id=foreign_cluster_id, label="ForeignSpace")
    rep_same = SimpleNamespace(embedding=same_rep_vec, identity_id=same_identity_id)
    rep_foreign = SimpleNamespace(embedding=foreign_rep_vec, identity_id=foreign_identity_id)

    labeled_with_reps = [
        (labeled_same, [rep_same]),
        (labeled_foreign, [rep_foreign]),
    ]

    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=labeled_with_reps),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_representative_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    captured_stmts: list[object] = []
    call_count = {"n": 0}

    def _model_lookup(stmt):
        # Derive result from the statement: only return same-space id when the
        # embedding_model predicate is bound. Without it, both ids would match
        # the unfiltered IN-list and the closer foreign rep would win.
        bind_values = _flatten_binds(stmt)
        if same_model in bind_values:
            return _FakeResult([same_identity_id])
        return _FakeResult([same_identity_id, foreign_identity_id])

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=_session_execute_side_effect(
            target_cluster=target_cluster,
            call_count=call_count,
            captured_stmts=captured_stmts,
            model_lookup_handler=_model_lookup,
        )
    )

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    assert result is not None
    assert result.label == "SameSpace"
    assert result.target_cluster_id == same_cluster_id
    assert result.label != "ForeignSpace"

    # Provenance query ran exactly once (call 4) and was bounded to the two rep ids.
    # A tenant-wide corpus query would bind tenant_id + embedding_model only, not
    # the scored identity ids — so presence of both ids in bind params proves the
    # IN-list is the representative set (CVUP1-GR-20).
    assert call_count["n"] == 4
    model_lookup_stmt = captured_stmts[3]
    bind_values = _flatten_binds(model_lookup_stmt)
    assert same_identity_id in bind_values
    assert foreign_identity_id in bind_values
    # R3-G3-2: target_model must be a bound parameter of the provenance SELECT.
    # Deleting ``MediaIdentity.embedding_model == target_model`` drops this bind
    # and the mock then returns both ids → foreign wins above.
    assert same_model in bind_values


@pytest.mark.asyncio
async def test_empty_provenance_lookup_never_returns_foreign_label() -> None:
    """R3-G3-1: empty same-model provenance result must keep the filter active.

    Domain-shaped reps carry only identity_id. When call 4 returns [], every
    unresolved id is excluded — foreign label must not win. Turns red if empty
    set is collapsed to None (``same_model_identity_ids = {...} or None``), which
    re-opens unguarded cross-space NN.
    """
    tenant_id = uuid4()
    target_id = uuid4()
    same_cluster_id = str(uuid4())
    foreign_cluster_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    # Foreign is closer if the filter is dropped.
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
    # Domain-like: identity_id only — model must come from the provenance query.
    rep_same = SimpleNamespace(embedding=same_rep_vec, identity_id=same_identity_id)
    rep_foreign = SimpleNamespace(embedding=foreign_rep_vec, identity_id=foreign_identity_id)

    labeled_with_reps = [
        (labeled_same, [rep_same]),
        (labeled_foreign, [rep_foreign]),
    ]

    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=labeled_with_reps),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_representative_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}
    captured_stmts: list[object] = []

    def _empty_provenance(stmt):
        return _FakeResult([])

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=_session_execute_side_effect(
            target_cluster=target_cluster,
            call_count=call_count,
            captured_stmts=captured_stmts,
            model_lookup_handler=_empty_provenance,
        )
    )
    # sqlite short-circuits the SQL NN path after in-process miss.
    session.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    # Empty provenance → active-but-empty filter → no labeled rep scored → None.
    # Must never surface ForeignSpace (or SameSpace without proven same-model).
    assert result is None
    assert call_count["n"] >= 4
    bind_values = _flatten_binds(captured_stmts[3])
    assert same_model in bind_values


@pytest.mark.asyncio
async def test_missing_rep_identity_recovers_model_from_with_model_loaders() -> None:
    """R3-G1-1 / R3-G4-5: absent representative_identity must still gate NN by model.

    Production shape: query cluster has no representative_identity, embeddings
    come from representative/member fallback loaders. The model belonging to the
    averaged vectors must drive same_model_identity_ids so a closer foreign-space
    labeled rep cannot win SIMILAR_CLUSTER.
    """
    tenant_id = uuid4()
    target_id = uuid4()
    same_cluster_id = str(uuid4())
    foreign_cluster_id = str(uuid4())
    same_model = "opencv-sface+cv5.0.0.93/ort1.28@128d/l2/cosine"
    foreign_model = "opencv-sface@128d/l2/cosine"

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    foreign_rep_vec = _normalize(np.array([0.99, 0.01, 0.0]))
    same_rep_vec = _normalize(np.array([0.8, 0.2, 0.0]))

    same_identity_id = str(uuid4())
    foreign_identity_id = str(uuid4())

    # No representative_identity — the supported table-fallback production path.
    target_cluster = SimpleNamespace(
        id=target_id,
        tenant_id=tenant_id,
        roster_id=None,
        representative_identity=None,
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
        get_representative_embeddings_with_model=AsyncMock(return_value=([target_vec], same_model)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=_session_execute_side_effect(
            target_cluster=target_cluster,
            call_count=call_count,
        )
    )

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    assert result is not None
    assert result.label == "SameSpace"
    assert result.source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert result.target_cluster_id == same_cluster_id
    assert result.label != "ForeignSpace"
    cluster_repository.get_representative_embeddings_with_model.assert_awaited_once_with(str(target_id))


@pytest.mark.asyncio
async def test_unresolvable_target_model_fail_closed_no_cross_space_suggestion() -> None:
    """R3-G3-4: embedding without resolvable model must not produce a suggestion.

    Query face loads vectors from with_model loaders but chosen_embedding_model
    is None. Fail closed — never run unguarded in-process NN that would let a
    foreign-space labeled rep win.
    """
    tenant_id = uuid4()
    target_id = uuid4()
    foreign_cluster_id = str(uuid4())
    foreign_model = "opencv-sface@128d/l2/cosine"

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    # Near-identical foreign rep would clear any threshold if scored unguarded.
    foreign_rep_vec = _normalize(np.array([0.999, 0.001, 0.0]))
    foreign_identity_id = str(uuid4())

    target_cluster = SimpleNamespace(
        id=target_id,
        tenant_id=tenant_id,
        roster_id=None,
        representative_identity=None,
    )

    labeled_foreign = SimpleNamespace(id=foreign_cluster_id, label="ForeignSpace")
    rep_foreign = SimpleNamespace(
        embedding=foreign_rep_vec,
        embedding_model=foreign_model,
        identity_id=foreign_identity_id,
    )

    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=[(labeled_foreign, [rep_foreign])]),
        # Embeddings present but model unresolved — fail closed.
        get_representative_embeddings_with_model=AsyncMock(return_value=([target_vec], None)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=_session_execute_side_effect(
            target_cluster=target_cluster,
            call_count=call_count,
        )
    )

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    assert result is None
    # Must not reach in-process labeled scoring — fail closed before NN.
    cluster_repository.get_labeled_with_representatives.assert_not_awaited()


@pytest.mark.asyncio
async def test_rep_identity_present_path_unchanged_when_model_known() -> None:
    """Regression: representative_identity with model must not call with_model loaders."""
    tenant_id = uuid4()
    target_id = uuid4()
    same_cluster_id = str(uuid4())
    same_model = "opencv-sface+cv5@128d/l2/cosine"

    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    same_rep_vec = _normalize(np.array([0.95, 0.05, 0.0]))
    same_identity_id = str(uuid4())

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
    rep_same = SimpleNamespace(
        embedding=same_rep_vec,
        embedding_model=same_model,
        identity_id=same_identity_id,
    )

    with_model_mock = AsyncMock(return_value=([], None))
    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=[(labeled_same, [rep_same])]),
        get_representative_embeddings_with_model=with_model_mock,
        get_member_fallback_embeddings_with_model=with_model_mock,
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    call_count = {"n": 0}
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=_session_execute_side_effect(
            target_cluster=target_cluster,
            call_count=call_count,
        )
    )

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    assert result is not None
    assert result.label == "SameSpace"
    with_model_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_provenance_lookup_chunks_ids_below_bind_ceiling(monkeypatch) -> None:
    """CVUP1-R3-09: the IN-list must be chunked, and the union must be lossless.

    ``in_()`` compiles to one expanding parameter but *executes* as one bind per
    element; asyncpg rejects statements past 32,767 arguments, so an unbounded
    rep-id list turns the suggestion endpoint into a hard 500 on a large tenant.

    Discrimination: the winning label lives in the LAST chunk. Dropping the loop
    (single query) makes the query count assertion fail; dropping any chunk's
    result from the union makes the label assertion fail.
    """
    monkeypatch.setattr(
        "recognition.application.suggestions.label_inference._MODEL_LOOKUP_CHUNK_SIZE",
        2,
    )

    tenant_id = uuid4()
    target_id = uuid4()
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    target_vec = _normalize(np.array([1.0, 0.0, 0.0]))

    target_cluster = SimpleNamespace(
        id=target_id,
        tenant_id=tenant_id,
        roster_id=None,
        representative_identity=SimpleNamespace(embedding=target_vec, embedding_model=same_model),
    )

    # Five unresolved reps => three chunks at size 2. Only the last one is in the
    # active space, and it is also the closest, so it must win.
    identity_ids = [str(uuid4()) for _ in range(5)]
    winner_identity_id = identity_ids[-1]
    labeled_with_reps = []
    for index, identity_id in enumerate(identity_ids):
        off_axis = 0.5 if index < len(identity_ids) - 1 else 0.05
        labeled_with_reps.append(
            (
                SimpleNamespace(id=str(uuid4()), label=f"Label{index}"),
                [SimpleNamespace(embedding=_normalize(np.array([1.0, off_axis, 0.0])), identity_id=identity_id)],
            )
        )
    winner_label = f"Label{len(identity_ids) - 1}"

    cluster_repository = SimpleNamespace(
        get_labeled_with_representatives=AsyncMock(return_value=labeled_with_reps),
        get_representative_embeddings=AsyncMock(return_value=[]),
        get_member_fallback_embeddings=AsyncMock(return_value=[]),
        get_representative_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_member_fallback_embeddings_with_model=AsyncMock(return_value=([], None)),
        get_roster_entry_name=AsyncMock(return_value=None),
    )

    chunk_binds: list[set[str]] = []

    def _model_lookup(stmt):
        bind_values = _flatten_binds(stmt)
        chunk_ids = {value for value in bind_values if value in set(identity_ids)}
        chunk_binds.append(chunk_ids)
        return _FakeResult([i for i in identity_ids if i in chunk_ids and i == winner_identity_id])

    call_count = {"n": 0}

    async def _execute(stmt):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeResult(target_cluster)
        if call_count["n"] in (2, 3):
            return _FakeResult(None)
        return _model_lookup(stmt)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    result = await infer_suggested_label(
        tenant_id=str(tenant_id),
        cluster_id=str(target_id),
        session=session,
        cluster_repository=cluster_repository,
    )

    # ceil(5 / 2) == 3 provenance queries, none exceeding the chunk size.
    assert len(chunk_binds) == 3
    assert all(len(ids) <= 2 for ids in chunk_binds)
    # Union is lossless: every rep id was looked up exactly once.
    assert sorted(i for ids in chunk_binds for i in ids) == sorted(identity_ids)
    # The same-space winner lives in the final chunk, so its result was merged.
    assert result is not None
    assert result.label == winner_label
