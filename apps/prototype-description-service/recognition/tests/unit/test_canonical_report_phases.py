"""Unit tests for the pure phase functions extracted from generate_canonical_report.

PERSREG-5: ``generate_canonical_report`` was a 394-line god-function mixing
query, transform, dedup, and metrics. It is now a thin orchestrator delegating
to named phase functions. These pin the four pure-logic phases that fake
cleanly without a DB session — duplicate/transitivity analysis, the two
locator->label/cluster map builders, and the metrics-payload assembler. The
DB-query phases stay covered by the integration suite.
"""

from __future__ import annotations

from typing import Any

from recognition.application.regression_harness.report_builder import (
    _analyze_duplicates,
    _build_canonical_labels_from_clusters,
    _build_predicted_clusters_map,
    _compute_metrics_payload,
    _DuplicatesAnalysis,
)
from recognition.domain.locator import IdentityLocator


def _bbox(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": x, "y": y, "width": w, "height": h}


def _predicted_member(
    *, identity_id: str, media_id: int, phash: str, bbox: dict[str, int], cluster_id: str
) -> dict[str, Any]:
    """A pre_curation_state predicted-cluster member entry (carries original_assignment)."""
    return {
        "identity_id": identity_id,
        "media_id": media_id,
        "image_phash": phash,
        "bbox": bbox,
        "embedding_fingerprint": "fp",
        "original_assignment": {"cluster_id": cluster_id},
    }


def _pre_curation(members: list[dict[str, Any]]) -> dict[str, object]:
    return {"predicted_clusters": [{"members": members}]}


# --- _analyze_duplicates -------------------------------------------------------


def test_analyze_duplicates_flags_transitivity_failure() -> None:
    """Same phash + same bbox assigned to two different clusters -> one issue."""
    bbox = _bbox(10, 20, 30, 40)
    members = [
        _predicted_member(identity_id="i1", media_id=1, phash="HASH", bbox=bbox, cluster_id="cA"),
        _predicted_member(identity_id="i2", media_id=2, phash="HASH", bbox=bbox, cluster_id="cB"),
    ]
    result = _analyze_duplicates(_pre_curation(members), [])

    assert isinstance(result, _DuplicatesAnalysis)
    assert len(result.consistency_issues) == 1
    issue = result.consistency_issues[0]
    assert issue["issue"] == "transitivity_failure"
    assert issue["image_hash"] == "HASH"
    assert set(issue["clusters"]) == {"cA", "cB"}
    assert issue["bbox"] == bbox


def test_analyze_duplicates_no_issue_for_single_cluster() -> None:
    """Same phash + same bbox + same cluster is not a transitivity failure."""
    bbox = _bbox(10, 20, 30, 40)
    members = [
        _predicted_member(identity_id="i1", media_id=1, phash="HASH", bbox=bbox, cluster_id="cA"),
        _predicted_member(identity_id="i2", media_id=2, phash="HASH", bbox=bbox, cluster_id="cA"),
    ]
    result = _analyze_duplicates(_pre_curation(members), [])

    assert result.consistency_issues == []
    assert len(result.by_image_hash["HASH"]) == 2


def test_analyze_duplicates_dedupes_by_identity_id_and_skips_missing_phash() -> None:
    bbox = _bbox(1, 2, 3, 4)
    members = [
        _predicted_member(identity_id="dup", media_id=1, phash="HASH", bbox=bbox, cluster_id="cA"),
        _predicted_member(identity_id="dup", media_id=1, phash="HASH", bbox=bbox, cluster_id="cA"),
        {"identity_id": "no_phash", "media_id": 9, "bbox": bbox},  # no image_phash -> skipped
    ]
    result = _analyze_duplicates(_pre_curation(members), [])

    assert list(result.by_image_hash.keys()) == ["HASH"]
    assert len(result.by_image_hash["HASH"]) == 1  # deduped on identity_id


def test_analyze_duplicates_handles_none_pre_curation_state() -> None:
    result = _analyze_duplicates(None, [])
    assert result.by_image_hash == {}
    assert result.consistency_issues == []


def _canonical_member(
    *, identity_id: str, media_id: int, phash: str, bbox: dict[str, int], label: str
) -> dict[str, Any]:
    """A canonical-cluster member entry (curation.final_label, no original_assignment)."""
    return {
        "identity_id": identity_id,
        "media_id": media_id,
        "image_phash": phash,
        "bbox": bbox,
        "embedding_fingerprint": "fp",
        "curation": {"final_label": label},
    }


def test_analyze_duplicates_collects_canonical_cluster_members() -> None:
    """canonical_clusters branch: members land in by_image_hash with their curation
    label and a None cluster_id (no original_assignment/final_cluster_id on the member)."""
    bbox = _bbox(7, 8, 9, 10)
    canonical_clusters = [
        {
            "canonical_label": "Alice",
            "member_identities": [
                _canonical_member(identity_id="c1", media_id=3, phash="CHASH", bbox=bbox, label="Alice")
            ],
        }
    ]
    result = _analyze_duplicates(None, canonical_clusters)

    grouped = result.by_image_hash["CHASH"]
    assert len(grouped) == 1
    assert grouped[0]["label"] == "Alice"
    assert grouped[0]["cluster_id"] is None  # canonical members carry no cluster id
    # A lone canonical member never fabricates a transitivity issue.
    assert result.consistency_issues == []


def test_analyze_duplicates_canonical_member_does_not_collide_with_predicted() -> None:
    """A canonical member (cluster_id None) sharing phash+bbox with one predicted
    cluster does not create a transitivity failure: the None id is filtered out."""
    bbox = _bbox(1, 1, 2, 2)
    pre_curation = _pre_curation(
        [_predicted_member(identity_id="p1", media_id=1, phash="HASH", bbox=bbox, cluster_id="cA")]
    )
    canonical_clusters = [
        {
            "canonical_label": "Alice",
            "member_identities": [
                _canonical_member(identity_id="c1", media_id=2, phash="HASH", bbox=bbox, label="Alice")
            ],
        }
    ]
    result = _analyze_duplicates(pre_curation, canonical_clusters)

    assert len(result.by_image_hash["HASH"]) == 2  # both predicted + canonical entries grouped
    assert result.consistency_issues == []  # only one non-None cluster id -> no failure


# --- _build_canonical_labels_from_clusters -------------------------------------


def test_build_canonical_labels_maps_locators_to_label() -> None:
    clusters = [
        {
            "canonical_label": "Alice",
            "member_identities": [
                {"identity_locator": {"media_id": 101, "bbox_x": 10, "bbox_y": 20, "bbox_width": 30, "bbox_height": 40}}
            ],
        }
    ]
    labels = _build_canonical_labels_from_clusters(clusters)

    assert labels[IdentityLocator(media_id=101, bbox_x=10, bbox_y=20, bbox_width=30, bbox_height=40)] == "Alice"


def test_build_canonical_labels_skips_non_str_label_and_bad_members() -> None:
    clusters = [
        {"canonical_label": 123, "member_identities": [{"identity_locator": {}}]},  # non-str label -> skipped
        {"canonical_label": "Bob", "member_identities": "not-a-list"},  # bad members -> skipped
    ]
    assert _build_canonical_labels_from_clusters(clusters) == {}


# --- _build_predicted_clusters_map ---------------------------------------------


def test_build_predicted_clusters_map_maps_locators_to_cluster_id() -> None:
    state = {
        "predicted_clusters": [
            {
                "predicted_cluster_id": "p1",
                "member_identity_locators": [
                    {"media_id": 5, "bbox_x": 1, "bbox_y": 2, "bbox_width": 3, "bbox_height": 4}
                ],
            }
        ]
    }
    mapping = _build_predicted_clusters_map(state)

    assert mapping[IdentityLocator(media_id=5, bbox_x=1, bbox_y=2, bbox_width=3, bbox_height=4)] == "p1"


def test_build_predicted_clusters_map_skips_non_str_cluster_id_and_none_state() -> None:
    bad = {"predicted_clusters": [{"predicted_cluster_id": 99, "member_identity_locators": [{}]}]}
    assert _build_predicted_clusters_map(bad) == {}
    assert _build_predicted_clusters_map(None) == {}


# --- _compute_metrics_payload --------------------------------------------------


def test_compute_metrics_payload_empty_when_either_map_empty() -> None:
    loc = IdentityLocator(media_id=1, bbox_x=0, bbox_y=0, bbox_width=1, bbox_height=1)
    assert _compute_metrics_payload(canonical_labels={loc: "A"}, predicted_clusters_map={}, baseline_source=None) == {}
    assert _compute_metrics_payload(canonical_labels={}, predicted_clusters_map={loc: "p"}, baseline_source=None) == {}


def test_compute_metrics_payload_includes_pairwise_curation_and_baseline_source() -> None:
    loc_a = IdentityLocator(media_id=1, bbox_x=0, bbox_y=0, bbox_width=1, bbox_height=1)
    loc_b = IdentityLocator(media_id=2, bbox_x=0, bbox_y=0, bbox_width=1, bbox_height=1)
    canonical_labels = {loc_a: "Alice", loc_b: "Alice"}
    predicted_clusters_map = {loc_a: "p1", loc_b: "p1"}

    metrics = _compute_metrics_payload(
        canonical_labels=canonical_labels,
        predicted_clusters_map=predicted_clusters_map,
        baseline_source="baseline.json (curated)",
    )

    assert isinstance(metrics["pairwise"], dict)
    curation_cost = metrics["curation_cost"]
    assert isinstance(curation_cost, dict)
    assert set(curation_cost) == {"labels_evaluated", "estimated_merges", "estimated_removals"}
    assert metrics["baseline_source"] == "baseline.json (curated)"


def test_compute_metrics_payload_omits_baseline_source_when_none() -> None:
    loc_a = IdentityLocator(media_id=1, bbox_x=0, bbox_y=0, bbox_width=1, bbox_height=1)
    loc_b = IdentityLocator(media_id=2, bbox_x=0, bbox_y=0, bbox_width=1, bbox_height=1)
    metrics = _compute_metrics_payload(
        canonical_labels={loc_a: "Alice", loc_b: "Alice"},
        predicted_clusters_map={loc_a: "p1", loc_b: "p1"},
        baseline_source=None,
    )
    assert "baseline_source" not in metrics
