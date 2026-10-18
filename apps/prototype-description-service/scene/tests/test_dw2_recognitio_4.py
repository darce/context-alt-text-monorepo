import json
from pathlib import Path


SCHEMA_PATH = (
    Path(__file__).resolve().parents[4]
    / "packages/shared-contracts/schemas/recognition-cluster-merge-candidates-response.schema.json"
)


def test_merge_candidates_schema_does_not_claim_roster_candidates_shape_family():
    schema = json.loads(SCHEMA_PATH.read_text())

    assert "Same shape family as GET /recognition/clusters/{cluster_id}/roster-candidates" not in schema[
        "description"
    ]
