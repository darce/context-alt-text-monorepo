"""Regression coverage for secrets written into child JUnit reports."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import scripts.run_app_portal_evals as runner


def test_child_junit_artifact_and_identities_are_redacted_before_persisting(tmp_path: Path) -> None:
    secret = "synthetic-review-credential"
    recognized_credential = "sk-live-abcdefghijklmnop"
    test_node = "recognition/tests/api/test_portal_1.py::test_case_1"
    payload: dict[str, Any] = {
        "version": 1,
        "suite_id": "junit-redaction-test",
        "owner": "ADVFIX-1",
        "description": "JUnit redaction regression",
        "command": "pytest",
        "threshold": {"kind": "junit_counts", "max_failures": 0, "max_skipped": 0},
        "evidence_sink": str(tmp_path / "results.jsonl"),
        "tags": ["test"],
        "cases": [
            {
                "id": "SC-1",
                "group": "deterministic",
                "criterion": "child JUnit is redacted",
                "status": "planned",
                "test": test_node,
            }
        ],
        "release_gates": {
            "beta": {"required_cases": ["SC-1"]},
            "expansion": {"required_cases": ["SC-1"]},
            "paid": {"required_cases": ["SC-1"]},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    def command_runner(command: list[str], **kwargs: Any) -> SimpleNamespace:
        if command[:3] == ["git", "rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout="d" * 40, stderr="")
        if command[:2] == ["git", "status"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        assert kwargs["env"]["ACX_RECOGNITION_API_KEY"] == secret
        xml_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", {"name": "pytest", "tests": "1", "failures": "1"})
        testcase = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "recognition.tests.api.test_portal_1",
                "name": f"test_case_1[{secret}]",
                "file": "recognition/tests/api/test_portal_1.py",
                "data-secret": secret,
            },
        )
        failure = ET.SubElement(
            testcase,
            "failure",
            {"message": f"assert False: {secret}; provider={recognized_credential}"},
        )
        failure.text = f"assert False, os.environ['ACX_RECOGNITION_API_KEY']\nE AssertionError: {secret}"
        ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)
        return SimpleNamespace(returncode=1, stdout=None, stderr=None)

    status = runner.run_evals(
        manifest_path,
        out_dir=tmp_path / "out",
        environment={"ACX_RECOGNITION_API_KEY": secret},
        command_runner=command_runner,
    )

    evidence_path = tmp_path / "results.jsonl"
    evidence_text = evidence_path.read_text(encoding="utf-8")
    evidence = json.loads(evidence_text.splitlines()[-1])
    group = evidence["groups"][0]
    xml_path = next(Path(path) for path in group["artifact_paths"] if path.endswith(".xml"))
    xml_text = xml_path.read_text(encoding="utf-8")
    ledger_identity = group["case_ledger"][0]["junit_identity"]

    assert status == 1
    assert group["case_count"] == 1
    assert group["fail_count"] == 1
    assert group["failure_element_count"] == 1
    assert ledger_identity == f"recognition/tests/api/test_portal_1.py::test_case_1[<redacted>]"
    assert secret not in xml_text
    assert recognized_credential not in xml_text
    assert secret not in ledger_identity
    assert secret not in evidence_text
    assert recognized_credential not in evidence_text
