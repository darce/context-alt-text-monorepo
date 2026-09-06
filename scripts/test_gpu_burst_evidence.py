"""Contract tests for the read-only GPU burst evidence checker."""

from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "gpu_burst_evidence.py"
SINCE = "2026-09-01T00:00:00Z"
UNTIL = "2026-09-01T01:00:00Z"


def _write_bundle(bundle: Path) -> None:
    bundle.mkdir()
    files = {
        "state_history.json": {
            "instance_id": "ocid1.instance.example",
            "observations": [
                {"state": "STOPPED", "timestamp": SINCE},
                {"state": "RUNNING", "timestamp": "2026-09-01T00:10:00Z"},
                {"state": "STOPPED", "timestamp": "2026-09-01T00:30:00Z"},
            ],
        },
        "audit-events.json": {
            "data": [
                {
                    "eventName": "StartInstance",
                    "eventTime": "2026-09-01T00:10:00Z",
                    "eventId": "start-1",
                    "responseStatus": 200,
                    "data": {
                        "resourceId": "ocid1.instance.example",
                        "identity": {"principalName": "burst-start"},
                        "stateChange": {
                            "previous": {"lifecycleState": "STOPPED"},
                            "current": {"lifecycleState": "RUNNING"},
                        },
                    },
                },
                {
                    "eventName": "StopInstance",
                    "eventTime": "2026-09-01T00:30:00Z",
                    "eventId": "stop-1",
                    "responseStatus": 200,
                    "data": {
                        "resourceId": "ocid1.instance.example",
                        "identity": {"principalName": "gpu-reaper"},
                        "stateChange": {
                            "previous": {"lifecycleState": "RUNNING"},
                            "current": {"lifecycleState": "STOPPED"},
                        },
                    },
                },
            ]
        },
        "instance.json": {
            "data": {
                "id": "ocid1.instance.example",
                "lifecycle-state": "STOPPED",
            }
        },
    }
    entries = []
    for name, payload in files.items():
        target = bundle / name
        target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        entries.append(
            {
                "path": name,
                "sha256": sha256(target.read_bytes()).hexdigest(),
                "command": "fixture",
                "capture_time": "2026-09-01T00:35:00Z",
            }
        )
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "format": "oci-gpu-burst-evidence-v1",
                "instance_id": "ocid1.instance.example",
                "since": SINCE,
                "until": UNTIL,
                "files": entries,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_complete_burst_passes(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_bundle(bundle)

    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--bundle",
            str(bundle),
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--expected-stop-principal",
            "gpu-reaper",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


_OMITTED = object()
RUNNING_AT = "2026-09-01T00:10:00Z"
STOPPED_AT = "2026-09-01T00:30:00Z"
INSTANCE_ID = "ocid1.instance.example"


def _custom_bundle(
    tmp_path: Path,
    *,
    history: object = _OMITTED,
    audit: object = _OMITTED,
    instance: object = _OMITTED,
    snapshot: object = _OMITTED,
    receipts: object = _OMITTED,
    manifest: object = _OMITTED,
    extra_file: bool = False,
) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    payloads = {
        "state_history.json": history
        if history is not _OMITTED
        else {
            "instance_id": INSTANCE_ID,
            "observations": [
                {"state": "STOPPED", "timestamp": SINCE},
                {"state": "RUNNING", "timestamp": RUNNING_AT},
                {"state": "STOPPED", "timestamp": STOPPED_AT},
            ],
        },
        "audit-events.json": audit
        if audit is not _OMITTED
        else {
            "data": [
                {
                    "eventName": "StartInstance",
                    "eventTime": RUNNING_AT,
                    "eventId": "start-1",
                    "responseStatus": 200,
                    "data": {
                        "resourceId": INSTANCE_ID,
                        "identity": {"principalName": "burst-start"},
                        "stateChange": {
                            "previous": {"lifecycleState": "STOPPED"},
                            "current": {"lifecycleState": "RUNNING"},
                        },
                    },
                },
                {
                    "eventName": "StopInstance",
                    "eventTime": STOPPED_AT,
                    "eventId": "stop-1",
                    "responseStatus": 200,
                    "data": {
                        "resourceId": INSTANCE_ID,
                        "identity": {"principalName": "gpu-reaper"},
                        "stateChange": {
                            "previous": {"lifecycleState": "RUNNING"},
                            "current": {"lifecycleState": "STOPPED"},
                        },
                    },
                },
            ]
        },
        "instance.json": instance
        if instance is not _OMITTED
        else {"data": {"id": INSTANCE_ID, "lifecycle-state": "STOPPED"}},
    }
    if snapshot is not _OMITTED:
        payloads["state_snapshot.json"] = snapshot
    if receipts is not _OMITTED:
        payloads["wp_describe_receipts.json"] = receipts
    entries = []
    for name, payload in payloads.items():
        target = bundle / name
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        else:
            target.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        entries.append(
            {
                "path": name,
                "sha256": sha256(target.read_bytes()).hexdigest(),
                "command": "fixture",
                "capture_time": "2026-09-01T00:35:00Z",
            }
        )
    if manifest is _OMITTED:
        manifest = {
            "schema_version": 1,
            "format": "oci-gpu-burst-evidence-v1",
            "instance_id": INSTANCE_ID,
            "since": SINCE,
            "until": UNTIL,
            "files": entries,
        }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if extra_file:
        (bundle / "unlisted.txt").write_text("not in the manifest\n", encoding="utf-8")
    return bundle


def _run_checker(bundle: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--bundle",
            str(bundle),
            "--since",
            SINCE,
            "--until",
            UNTIL,
            "--expected-stop-principal",
            "gpu-reaper",
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _rewrite_manifest(bundle: Path) -> None:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        target = bundle / entry["path"]
        if target.exists():
            entry["sha256"] = sha256(target.read_bytes()).hexdigest()
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_json_verdict_and_optional_receipts_pass(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        snapshot={"gpu_state": "STOPPED", "instance_id": INSTANCE_ID, "written_at": STOPPED_AT},
        receipts={"items": [{"description": "A red bicycle", "timestamp": "2026-09-01T00:20:00Z"}]},
    )

    result = _run_checker(bundle, "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    verdict = json.loads(result.stdout)
    assert verdict["verdict"] == "PASS"
    assert verdict["passed"] is True
    assert all(check["passed"] for check in verdict["checks"])


def test_missing_bundle_fails(tmp_path: Path) -> None:
    result = _run_checker(tmp_path / "missing")

    assert result.returncode == 1
    assert "bundle_directory" in result.stdout


def test_missing_manifest_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    (bundle / "manifest.json").unlink()

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "manifest_sha256" in result.stdout


def test_malformed_manifest_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    (bundle / "manifest.json").write_text("{not-json}\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "manifest_sha256" in result.stdout


def test_manifest_hash_mismatch_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    (bundle / "instance.json").write_text('{"tampered":true}\n', encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "sha256 mismatch" in result.stdout


def test_manifest_rejects_non_mapping_file_entry(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"].append("not-an-entry")
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "manifest file entry 3 must be an object" in result.stdout


def test_unlisted_file_fails_closed(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path, extra_file=True)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "unlisted bundle file" in result.stdout


def test_invalid_window_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER),
            "--bundle",
            str(bundle),
            "--since",
            UNTIL,
            "--until",
            SINCE,
            "--expected-stop-principal",
            "gpu-reaper",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "since must not be later than until" in result.stdout


def test_missing_instance_receipt_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    (bundle / "instance.json").unlink()
    _rewrite_manifest(bundle)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "instance.json receipt is missing" in result.stdout


def test_missing_state_history_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    (bundle / "state_history.json").unlink()
    _rewrite_manifest(bundle)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state_history.json receipt is missing" in result.stdout


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        (
            {"observations": [{"state": "STOPPED", "timestamp": SINCE}, {"state": "RUNNING", "timestamp": RUNNING_AT}]},
            "expected STOPPED -> RUNNING -> STOPPED",
        ),
        (
            {
                "observations": [
                    {"state": "STOPPED"},
                    {"state": "RUNNING", "timestamp": RUNNING_AT},
                    {"state": "STOPPED", "timestamp": STOPPED_AT},
                ]
            },
            "expected STOPPED -> RUNNING -> STOPPED",
        ),
    ],
)
def test_incomplete_or_malformed_state_history_fails(tmp_path: Path, history: object, expected: str) -> None:
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert expected in result.stdout


def test_final_oci_state_must_be_stopped(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path, instance={"data": {"id": INSTANCE_ID, "lifecycle-state": "RUNNING"}})

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "final OCI lifecycle state is RUNNING" in result.stdout


def test_missing_audit_receipt_fails(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    (bundle / "audit-events.json").unlink()
    _rewrite_manifest(bundle)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "audit-events.json receipt is missing" in result.stdout


@pytest.mark.parametrize(
    ("audit", "expected"),
    [
        ({"data": []}, "observed 0 StartInstance audit events"),
        (
            {
                "data": [
                    {
                        "eventName": "StartInstance",
                        "eventTime": RUNNING_AT,
                        "eventId": "start-1",
                        "responseStatus": 200,
                        "data": {
                            "resourceId": INSTANCE_ID,
                            "stateChange": {"current": {"lifecycleState": "RUNNING"}},
                        },
                    },
                    {
                        "eventName": "StartInstance",
                        "eventTime": RUNNING_AT,
                        "eventId": "start-2",
                        "responseStatus": 200,
                        "data": {
                            "resourceId": INSTANCE_ID,
                            "stateChange": {"current": {"lifecycleState": "RUNNING"}},
                        },
                    },
                    {
                        "eventName": "StopInstance",
                        "eventTime": STOPPED_AT,
                        "eventId": "stop-1",
                        "responseStatus": 200,
                        "data": {
                            "resourceId": INSTANCE_ID,
                            "identity": {"principalName": "gpu-reaper"},
                            "stateChange": {"current": {"lifecycleState": "STOPPED"}},
                        },
                    },
                ]
            },
            "observed 2 StartInstance audit events",
        ),
    ],
)
def test_start_event_count_is_exact(tmp_path: Path, audit: object, expected: str) -> None:
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert expected in result.stdout


def test_duplicate_start_records_without_event_ids_fail_closed(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "stateChange": {"current": {"lifecycleState": "RUNNING"}},
                },
            },
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "stateChange": {"current": {"lifecycleState": "RUNNING"}},
                },
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                    "stateChange": {"current": {"lifecycleState": "STOPPED"}},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 2 StartInstance audit events" in result.stdout


def test_stop_principal_must_match(tmp_path: Path) -> None:
    audit = {
        "data": [
            {"eventName": "StartInstance", "eventTime": RUNNING_AT, "eventId": "start-1"},
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-1",
                "data": {"identity": {"principalName": "operator"}},
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "no StopInstance audit event matched principal" in result.stdout


@pytest.mark.parametrize(
    "snapshot",
    [
        {"gpu_state": "STOPPED", "written_at": "2026-09-01T02:00:00Z"},
        {"gpu_state": "RUNNING", "written_at": STOPPED_AT},
        {"gpu_state": "STOPPED"},
    ],
)
def test_reaper_snapshot_must_be_in_window_and_agree(tmp_path: Path, snapshot: object) -> None:
    bundle = _custom_bundle(tmp_path, snapshot=snapshot)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "reaper_snapshot" in result.stdout


def test_reaper_snapshot_must_match_selected_instance(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        snapshot={
            "gpu_state": "STOPPED",
            "instance_id": "ocid1.instance.other",
            "written_at": STOPPED_AT,
        },
    )

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "reaper_snapshot" in result.stdout
    assert "identifies ocid1.instance.other" in result.stdout


def test_wp_receipts_need_nonempty_descriptions_inside_running_interval(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        receipts={
            "items": [
                {"description": "", "timestamp": "2026-09-01T00:20:00Z"},
                {"description": "outside", "timestamp": "2026-09-01T00:45:00Z"},
            ]
        },
    )

    result = _run_checker(bundle, "--min-descriptions", "1")

    assert result.returncode == 1
    assert "0 description receipt(s) inside RUNNING interval" in result.stdout


def test_wp_receipts_minimum_is_enforced(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        receipts={"items": [{"description": "one", "timestamp": "2026-09-01T00:20:00Z"}]},
    )

    result = _run_checker(bundle, "--min-descriptions", "2")

    assert result.returncode == 1
    assert "required 2" in result.stdout


def test_receipt_generated_at_is_accepted(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        receipts={"items": [{"description": "one", "generatedAt": RUNNING_AT}]},
    )

    result = _run_checker(bundle)

    assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_schema_version_is_validated(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = 99
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "manifest_schema" in result.stdout
    assert "unsupported schema_version" in result.stdout


def test_manifest_format_is_validated(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["format"] = "foreign-evidence-format"
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "manifest_schema" in result.stdout
    assert "unsupported format" in result.stdout


def test_audit_event_without_resource_id_cannot_match_instance(tmp_path: Path) -> None:
    audit = {
        "data": [
            {"eventName": "StartInstance", "eventTime": RUNNING_AT, "eventId": "start-1", "responseStatus": 200},
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-1",
                "responseStatus": 200,
                "data": {"identity": {"principalName": "gpu-reaper"}},
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_instance_id_alias_without_resource_id_cannot_match_instance(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-instance-id-only",
                "responseStatus": 200,
                "instanceId": INSTANCE_ID,
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-instance-id-only",
                "responseStatus": 200,
                "instanceId": INSTANCE_ID,
                "identity": {"principalName": "gpu-reaper"},
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_audit_event_for_other_instance_cannot_match_target(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-other",
                "responseStatus": 200,
                "data": {"resourceId": "ocid1.instance.other"},
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-other",
                "responseStatus": 200,
                "data": {
                    "resourceId": "ocid1.instance.other",
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_manifest_instance_id_is_required(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("instance_id")
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "instance_identity" in result.stdout
    assert "manifest instance_id is required" in result.stdout


def test_history_instance_id_must_match_manifest(tmp_path: Path) -> None:
    history = {
        "instance_id": "ocid1.instance.other",
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "RUNNING", "timestamp": RUNNING_AT},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
        ],
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state_history_identity" in result.stdout
    assert "identifies ocid1.instance.other" in result.stdout


def test_history_instance_id_is_required(tmp_path: Path) -> None:
    history = {
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "RUNNING", "timestamp": RUNNING_AT},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
        ],
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state_history_identity" in result.stdout
    assert "missing instance_id" in result.stdout


def test_inferred_history_observation_cannot_prove_burst(tmp_path: Path) -> None:
    history = {
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE, "inferred": True},
            {"state": "RUNNING", "timestamp": RUNNING_AT},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
        ]
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state_history_burst" in result.stdout
    assert "inferred" in result.stdout


def test_not_start_instance_is_not_a_start_event(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "NotStartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "not-start",
                "responseStatus": 200,
                "data": {"resourceId": INSTANCE_ID},
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-1",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_failed_audit_action_is_not_evidence(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-failed",
                "responseStatus": 500,
                "data": {"resourceId": INSTANCE_ID},
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-1",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_audit_current_state_must_match_requested_transition(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventType": "com.oraclecloud.computeapi.StartInstance.end",
                "eventTime": RUNNING_AT,
                "eventId": "start-still-starting",
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"parameters": {"action": "START"}},
                    "response": {"status": "200"},
                    "stateChange": {
                        "previous": {"lifecycleState": "STOPPED"},
                        "current": {"lifecycleState": "STARTING"},
                    },
                },
            },
            {
                "eventType": "com.oraclecloud.computeapi.StopInstance.end",
                "eventTime": STOPPED_AT,
                "eventId": "stop-complete",
                "identity": {"principalName": "gpu-reaper"},
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"parameters": {"action": "STOP"}},
                    "response": {"status": "200"},
                    "stateChange": {
                        "previous": {"lifecycleState": "RUNNING"},
                        "current": {"lifecycleState": "STOPPED"},
                    },
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_request_status_cannot_override_conflicting_response_status(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-conflicting-status",
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"status": 200},
                    "response": {"status": 500},
                },
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-1",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_missing_response_status_cannot_prove_audit_action(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-missing-status",
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"status": 200},
                },
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-1",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 0 StartInstance audit events" in result.stdout


def test_stop_before_start_cannot_prove_burst(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StopInstance",
                "eventTime": "2026-09-01T00:05:00Z",
                "eventId": "stop-before-start",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-1",
                "responseStatus": 200,
                "data": {"resourceId": INSTANCE_ID},
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-after-start",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "audit transition order" in result.stdout


def test_raw_state_transition_order_is_checked_before_collapsing_states(tmp_path: Path) -> None:
    history = {
        "observations": [
            {
                "state": "STOPPED",
                "timestamp": "2026-09-01T00:05:00Z",
                "action": "StopInstance",
            },
            {"state": "STOPPED", "timestamp": RUNNING_AT, "action": "StartInstance"},
            {"state": "RUNNING", "timestamp": RUNNING_AT, "action": "StartInstance"},
            {"state": "STOPPED", "timestamp": STOPPED_AT, "action": "StopInstance"},
        ]
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state history transition order" in result.stdout


def test_nested_oci_audit_event_fields_are_supported(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventType": "com.oraclecloud.computeapi.StartInstance.begin",
                "eventTime": "2026-09-01T00:09:59Z",
                "eventId": "start-begin",
                "eventGroupingId": "start-group",
                "identity": {"principalName": "burst-start"},
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"parameters": {"action": "START"}},
                    "response": {"status": "200"},
                },
            },
            {
                "eventType": "com.oraclecloud.computeapi.StartInstance.end",
                "eventTime": RUNNING_AT,
                "eventId": "start-end",
                "eventGroupingId": "start-group",
                "identity": {"principalName": "burst-start"},
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"parameters": {"action": "START"}},
                    "response": {"status": "200"},
                    "stateChange": {
                        "previous": {"lifecycleState": "STOPPED"},
                        "current": {"lifecycleState": "RUNNING"},
                    },
                },
            },
            {
                "eventType": "com.oraclecloud.computeapi.StopInstance.begin",
                "eventTime": "2026-09-01T00:29:59Z",
                "eventId": "stop-begin",
                "eventGroupingId": "stop-group",
                "identity": {"principalName": "gpu-reaper"},
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"parameters": {"action": "STOP"}},
                    "response": {"status": "200"},
                },
            },
            {
                "eventType": "com.oraclecloud.computeapi.StopInstance.end",
                "eventTime": STOPPED_AT,
                "eventId": "stop-end",
                "eventGroupingId": "stop-group",
                "identity": {"principalName": "gpu-reaper"},
                "data": {
                    "resourceId": INSTANCE_ID,
                    "request": {"parameters": {"action": "STOP"}},
                    "response": {"status": "200"},
                    "stateChange": {
                        "previous": {"lifecycleState": "RUNNING"},
                        "current": {"lifecycleState": "STOPPED"},
                    },
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 0, result.stdout + result.stderr


def test_gpu_evidence_make_target_does_not_duplicate_deploy_shell_suite() -> None:
    fragment = (ROOT / "mk" / "gpu-evidence.mk").read_text(encoding="utf-8")
    target = fragment.split("gpu-evidence-tests:", 1)[1].split(".PHONY:", 1)[0]

    assert "scripts/test_gpu_burst_evidence.py" in target
    assert "scripts/deploy/tests/test_export_gpu_evidence_shell.py" not in target
