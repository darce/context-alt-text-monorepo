"""API contract tests for GET /recognition/clusters/{id}/roster-candidates."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import numpy as np
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.roster_candidates import MAX_ROSTER_CANDIDATES_TOP_K
from recognition.tests.api.conftest import seed_cluster

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "shared-contracts"
    / "schemas"
    / "roster-candidates-response.schema.json"
)


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _rep(
    *,
    embedding: np.ndarray,
    embedding_model: str,
    quality_score: float = 1.0,
    landmark_quality: float = 1.0,
    det_score: float = 0.99,
) -> SimpleNamespace:
    return SimpleNamespace(
        embedding=embedding,
        embedding_model=embedding_model,
        identity_id=str(uuid.uuid4()),
        quality_score=quality_score,
        debug_metrics={"landmark_quality": landmark_quality, "det_score": det_score},
    )


def test_roster_candidates_empty_when_cluster_exists_without_roster(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, monkeypatch
) -> None:
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    monkeypatch.setattr(
        "recognition.application.suggestions.roster_candidates.resolve_effective_clustering_settings",
        lambda: ClusteringSettings(
            suggestion_floor=0.40,
            suggestion_ceiling=0.80,
            similarity_threshold=0.77,
            fatal_quality_floor=0.20,
            fatal_confidence_floor=0.30,
        ),
    )
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_repository.seed(
        cluster.id,
        tenant_id,
        label=None,
        representatives=[
            _rep(
                embedding=_normalize(np.array([1.0, 0.0, 0.0])),
                embedding_model=same_model,
                quality_score=0.95,
                landmark_quality=0.9,
            )
        ],
    )

    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(body, _schema())
    assert body["candidates"] == []
    assert body["probe_face_count"] > 0
    assert body["reference_face_count"] == 0
    assert body["quality_flag"] == "ok"


def test_roster_candidates_empty_probe_when_reps_have_zero_dim_embeddings(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository, monkeypatch
) -> None:
    """Zero-dim reps dropped at roster_candidates.py:186-190; flag from empty-samples default at :94."""
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    monkeypatch.setattr(
        "recognition.application.suggestions.roster_candidates.resolve_effective_clustering_settings",
        lambda: ClusteringSettings(
            suggestion_floor=0.40,
            suggestion_ceiling=0.80,
            similarity_threshold=0.77,
            fatal_quality_floor=0.20,
            fatal_confidence_floor=0.30,
        ),
    )
    probe = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    labeled = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="Ada",
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_repository.seed(
        probe.id,
        tenant_id,
        label=None,
        representatives=[
            _rep(
                embedding=np.array([]),
                embedding_model=same_model,
                quality_score=0.01,
                landmark_quality=0.01,
                det_score=0.01,
            )
        ],
    )
    fake_cluster_repository.seed(
        labeled.id,
        tenant_id,
        label="Ada",
        representatives=[_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
    )

    resp = api_client.get(
        f"/recognition/clusters/{probe.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(body, _schema())
    assert body["candidates"] == []
    assert body["quality_flag"] == "low_quality"
    assert body["probe_face_count"] == 0


def test_roster_candidates_missing_cluster_is_404(api_client, tenant_id) -> None:
    resp = api_client.get(
        f"/recognition/clusters/{uuid.uuid4()}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
    )
    assert resp.status_code == 404


def test_roster_candidates_rejects_top_k_above_max(api_client, tenant_id, fake_cluster_service, fake_cluster_repository) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
        params={"top_k": 51},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "top_k out of range"


def test_roster_candidates_accepts_top_k_at_max(
    api_client, tenant_id, fake_cluster_service, fake_cluster_repository
) -> None:
    cluster = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    resp = api_client.get(
        f"/recognition/clusters/{cluster.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
        params={"top_k": MAX_ROSTER_CANDIDATES_TOP_K},
    )
    assert resp.status_code == 200, resp.text


def test_roster_candidates_ranks_labelled_excludes_foreign_tenant_and_validates_schema(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """R1-04: non-empty candidates, live thresholds, bands, foreign tenant absent, schema."""
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    monkeypatch.setattr(
        "recognition.application.suggestions.roster_candidates.resolve_effective_clustering_settings",
        lambda: ClusteringSettings(
            suggestion_floor=0.40,
            suggestion_ceiling=0.80,
            similarity_threshold=0.77,
            fatal_quality_floor=0.20,
            fatal_confidence_floor=0.30,
        ),
    )

    probe = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    # Seed lower-similarity first so insertion order cannot pass as rank order.
    possible = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="Bea",
        fake_cluster_repository=fake_cluster_repository,
    )
    strong = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="Ada",
        fake_cluster_repository=fake_cluster_repository,
    )
    foreign = seed_cluster(
        fake_cluster_service,
        str(uuid.uuid4()),
        label="Eve",
        fake_cluster_repository=fake_cluster_repository,
    )

    fake_cluster_repository.seed(
        probe.id,
        tenant_id,
        label=None,
        representatives=[
            _rep(embedding=probe_vec, embedding_model=same_model, quality_score=0.95, landmark_quality=0.9)
        ],
    )
    fake_cluster_repository.seed(
        possible.id,
        tenant_id,
        label="Bea",
        representatives=[_rep(embedding=_normalize(np.array([0.55, 0.835, 0.0])), embedding_model=same_model)],
    )
    fake_cluster_repository.seed(
        strong.id,
        tenant_id,
        label="Ada",
        representatives=[_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
    )
    fake_cluster_repository.seed(
        foreign.id,
        foreign.tenant_id,
        label="Eve",
        representatives=[_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
    )

    resp = api_client.get(
        f"/recognition/clusters/{probe.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
        params={"top_k": 10},
    )

    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(body, _schema())
    ids = [row["cluster_id"] for row in body["candidates"]]
    assert ids == [strong.id, possible.id]
    assert foreign.id not in ids
    bands = {row["cluster_id"]: row["band"] for row in body["candidates"]}
    assert bands[strong.id] == "strong"
    assert bands[possible.id] == "possible"
    assert body["thresholds"] == {
        "suggestion_floor": 0.40,
        "suggestion_ceiling": 0.80,
        "similarity_threshold": 0.77,
    }
    assert body["quality_flag"] == "ok"
    assert "quality_flag" not in body["candidates"][0]
    assert body["probe_face_count"] == 1
    assert body["reference_face_count"] >= 2
    assert fake_cluster_repository.clusters[probe.id].representatives == []


def test_roster_candidates_low_quality_flag_caps_strong_band_on_the_wire(
    api_client,
    tenant_id,
    fake_cluster_service,
    fake_cluster_repository,
    monkeypatch,
) -> None:
    """R2-03: quality_flag is not a literal 'ok'; low probe metrics cap Strong."""
    same_model = "opencv-sface+cv5@128d/l2/cosine"
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    monkeypatch.setattr(
        "recognition.application.suggestions.roster_candidates.resolve_effective_clustering_settings",
        lambda: ClusteringSettings(
            suggestion_floor=0.40,
            suggestion_ceiling=0.80,
            similarity_threshold=0.77,
            fatal_quality_floor=0.45,
            fatal_confidence_floor=0.40,
        ),
    )

    probe = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label=None,
        fake_cluster_repository=fake_cluster_repository,
    )
    strong = seed_cluster(
        fake_cluster_service,
        tenant_id,
        label="Ada",
        fake_cluster_repository=fake_cluster_repository,
    )
    fake_cluster_repository.seed(
        probe.id,
        tenant_id,
        label=None,
        representatives=[
            _rep(
                embedding=probe_vec,
                embedding_model=same_model,
                quality_score=0.10,
                landmark_quality=0.10,
                det_score=0.99,
            )
        ],
    )
    fake_cluster_repository.seed(
        strong.id,
        tenant_id,
        label="Ada",
        representatives=[_rep(embedding=_normalize(np.array([1.0, 0.0, 0.0])), embedding_model=same_model)],
    )

    resp = api_client.get(
        f"/recognition/clusters/{probe.id}/roster-candidates",
        headers={"X-Tenant-ID": tenant_id},
        params={"top_k": 10},
    )

    assert resp.status_code == 200
    body = resp.json()
    jsonschema.validate(body, _schema())
    assert body["quality_flag"] == "low_quality"
    assert body["candidates"]
    assert body["candidates"][0]["similarity"] >= 0.80
    assert all(row["band"] != "strong" for row in body["candidates"])


def test_contract_roster_candidates_example_validates_against_schema() -> None:
    """R2-07: exactly one roster-candidates heading; its JSON example matches the schema."""
    contract_path = (
        Path(__file__).resolve().parents[5]
        / "docs"
        / "workbay"
        / "contracts"
        / "recognition-clustering.md"
    )
    text = contract_path.read_text(encoding="utf-8")
    heading = "### GET /recognition/clusters/{cluster_id}/roster-candidates"
    assert text.count(heading) == 1
    after = text.split(heading, 1)[1]
    start = after.find("```json")
    assert start != -1
    start = after.find("\n", start) + 1
    end = after.find("```", start)
    example = json.loads(after[start:end])
    jsonschema.validate(example, _schema())


def test_schema_and_contract_agree_on_php_candidate_ordering() -> None:
    desc = _schema()["properties"]["candidates"]["description"]
    assert "roster_entry_id null rows are uncommittable and kept flagged" not in desc
    assert "before uncommittable" in desc or "after every committable row" in desc
    assert "must not re-sort" in desc
    assert "Browser/SPA" in desc
    assert "mapping proxy" in desc or "PHP-layer" in desc
    old_unqualified = "Clients must render in payload order and must not re-sort client-side."
    assert old_unqualified not in desc
    contract_path = (
        Path(__file__).resolve().parents[5]
        / "docs"
        / "workbay"
        / "contracts"
        / "recognition-clustering.md"
    )
    text = contract_path.read_text(encoding="utf-8")
    heading = "### GET /recognition/clusters/{cluster_id}/roster-candidates"
    assert heading in text
    assert old_unqualified not in text
    python_body, php_block = text.split(heading, 1)[1].split(
        "PHP passthrough `GET acx/v1/recognition/clusters/{id}/roster-candidates`", 1
    )
    candidates_line = next(line for line in python_body.splitlines() if "`candidates[]`" in line)
    assert "Python cluster-grain" in candidates_line
    assert "people-grain" in php_block
    assert "Browser/SPA" in php_block
    assert "mapping proxy" in php_block or "PHP-layer" in php_block
    assert "must not re-sort" in php_block
    assert old_unqualified not in php_block
