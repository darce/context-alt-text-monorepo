import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator


SCHEMA_PATH = Path(__file__).resolve().parents[4] / "packages/shared-contracts/schemas/recognition-cluster-snapshot.schema.json"
CLUSTER_SCHEMA = json.loads(SCHEMA_PATH.read_text())["properties"]["clusters"]["items"]
QUALITY_COMPONENTS = {
    "confidence": 0.94,
    "bbox_area": 7680,
    "sharpness": 42.5,
    "occlusion_severity": 0.12,
}
CLUSTER = {
    "cluster_uuid": "6c1a2e32-31b2-4d54-a4de-98b1a73d77a1",
    "label": "Alice Example",
    "curation_state": "confirmed",
    "is_user_confirmed": True,
    "identity_count": 2,
    "representative_quality": 0.82,
    "quality_components": QUALITY_COMPONENTS,
}


@pytest.mark.parametrize(
    "quality,components",
    [(0.82, None), (None, QUALITY_COMPONENTS)],
    ids=["numeric-quality-with-null-components", "null-quality-with-components"],
)
def test_snapshot_quality_fields_reject_one_sided_nulls(quality, components):
    payload = copy.deepcopy(CLUSTER)
    payload["representative_quality"] = quality
    payload["quality_components"] = components

    assert not Draft7Validator(CLUSTER_SCHEMA).is_valid(payload)


def test_snapshot_quality_fields_accept_matched_values_and_both_null():
    validator = Draft7Validator(CLUSTER_SCHEMA)
    validator.validate(CLUSTER)

    both_null = copy.deepcopy(CLUSTER)
    both_null["representative_quality"] = None
    both_null["quality_components"] = None
    validator.validate(both_null)

