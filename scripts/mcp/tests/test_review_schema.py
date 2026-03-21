import json
from scripts.mcp.review_runner import REVIEW_OUTPUT_SCHEMA

def test_schema():
    print("Testing REVIEW_OUTPUT_SCHEMA...")
    
    # Simulate a payload that has nullable fields
    payload = {
        "findings": [
            {
                "severity": "high",
                "category": "bug",
                "file_path": "test.py",
                "line_start": 10,
                "line_end": 12,
                "description": "test",
                "fix": "test fix"
            },
            {
                "severity": "medium",
                "category": "style",
                "file_path": "test.py",
                "line_start": None,
                "line_end": None,
                "description": "missing start/end",
                "fix": None
            }
        ],
        "summary": "all good"
    }
    
    # In a real scenario, we'd use jsonschema.validate
    # But here we just want to ensure that if a field is in 'properties', it is also in 'required'
    # per OpenAI's strict mode rules.
    
    findings_props = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["properties"]
    findings_req = REVIEW_OUTPUT_SCHEMA["properties"]["findings"]["items"]["required"]
    
    missing_req = [p for p in findings_props if p not in findings_req]
    if missing_req:
        print(f"FAILED: Missing from 'required': {missing_req}")
        return False
    
    print("SUCCESS: All properties are in 'required'.")
    return True

if __name__ == "__main__":
    if test_schema():
        exit(0)
    else:
        exit(1)
