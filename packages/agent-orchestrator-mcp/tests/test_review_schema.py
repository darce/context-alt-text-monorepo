import json
import sys
from pathlib import Path

_ORCHESTRATION_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_orchestrator_mcp" / "orchestration"
if str(_ORCHESTRATION_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATION_DIR))

from review_runner import REVIEW_OUTPUT_SCHEMA


def _schema_has_all_required_fields() -> bool:
    # In a real scenario, we'd use jsonschema.validate
    # But here we just want to ensure that if a field is in 'properties', it is also in 'required'
    # per OpenAI's strict mode rules.

    findings_props = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["properties"]
    findings_req = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["required"]

    missing_req = [p for p in findings_props if p not in findings_req]
    return not missing_req


def test_schema() -> None:
    findings_props = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["properties"]
    findings_req = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["required"]
    missing_req = [p for p in findings_props if p not in findings_req]
    assert not missing_req, f"Missing from 'required': {missing_req}"


if __name__ == "__main__":
    print("Testing REVIEW_OUTPUT_SCHEMA...")
    if _schema_has_all_required_fields():
        print("SUCCESS: All properties are in 'required'.")
        exit(0)
    else:
        findings_props = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["properties"]
        findings_req = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["required"]
        missing_req = [p for p in findings_props if p not in findings_req]
        print(f"FAILED: Missing from 'required': {missing_req}")
        exit(1)
