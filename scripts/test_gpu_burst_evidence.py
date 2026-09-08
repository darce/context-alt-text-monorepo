"""Contract tests for the read-only GPU burst evidence checker."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "gpu_burst_evidence.py"
SINCE = "2026-09-01T00:00:00Z"
UNTIL = "2026-09-01T01:00:00Z"


def _write_bundle(bundle: Path) -> None:
    bundle.mkdir()
    files = {
        "state_history.json": {
            "schema_version": 1,
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
    if isinstance(history, dict) and history is not _OMITTED and "schema_version" not in history:
        history = {"schema_version": 1, **history}
    payloads = {
        "state_history.json": history
        if history is not _OMITTED
        else {
            "schema_version": 1,
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


def test_manifest_path_with_nul_fails_without_traceback(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "instance.json\u0000hidden"
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "manifest_sha256" in result.stdout
    assert "NUL" in result.stdout or "null" in result.stdout.casefold()
    assert "Traceback" not in result.stderr


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


def test_unlisted_nested_manifest_json_fails_closed(tmp_path: Path) -> None:
    # Enumeration must skip only the root verification manifest. A nested
    # unlisted manifest.json is extra evidence content and must fail closed.
    bundle = _custom_bundle(tmp_path)
    nested = bundle / "subdir" / "manifest.json"
    nested.parent.mkdir()
    nested.write_text("{}\n", encoding="utf-8")

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "unlisted bundle file" in result.stdout
    assert "subdir/manifest.json" in result.stdout


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


def test_successful_start_without_current_state_is_still_counted(tmp_path: Path) -> None:
    audit = {
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
                "eventTime": "2026-09-01T00:15:00Z",
                "eventId": "start-without-current",
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
                    "stateChange": {"current": {"lifecycleState": "STOPPED"}},
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 2 StartInstance audit events" in result.stdout


def test_successful_start_after_stop_is_not_ignored_without_state_change(tmp_path: Path) -> None:
    audit = {
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
            {
                "eventName": "StartInstance",
                "eventTime": "2026-09-01T00:45:00Z",
                "eventId": "start-after-stop",
                "responseStatus": 200,
                "data": {"resourceId": INSTANCE_ID},
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "observed 2 StartInstance audit events" in result.stdout


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


def test_unformattable_snapshot_timestamp_fails_without_traceback(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        snapshot={"gpu_state": "STOPPED", "instance_id": INSTANCE_ID, "written_at": 1e308},
    )

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "reaper_snapshot" in result.stdout
    assert "invalid" in result.stdout
    assert "Traceback" not in result.stderr


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
        receipts={"items": [{"description": "one", "generatedAt": "2026-09-01T00:20:00Z"}]},
    )

    result = _run_checker(bundle)

    assert result.returncode == 0, result.stdout + result.stderr


def test_receipt_generated_at_snake_case_is_accepted(tmp_path: Path) -> None:
    bundle = _custom_bundle(
        tmp_path,
        receipts={"items": [{"description": "one", "generated_at": "2026-09-01T00:20:00Z"}]},
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


def test_unsupported_manifest_schema_fails_before_artifact_interpretation(tmp_path: Path) -> None:
    bundle = _custom_bundle(tmp_path)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = 99
    (bundle / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = _run_checker(bundle, "--json")

    assert result.returncode == 1
    verdict = json.loads(result.stdout)
    assert any(check["name"] == "manifest_schema" and not check["passed"] for check in verdict["checks"])
    assert all(
        check["name"] not in {"oci_instance_receipt", "state_history_receipt", "audit_receipt"}
        for check in verdict["checks"]
    )


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


def test_only_reaper_stop_before_start_cannot_prove_burst(tmp_path: Path) -> None:
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
                    "stateChange": {
                        "previous": {"lifecycleState": "RUNNING"},
                        "current": {"lifecycleState": "STOPPED"},
                    },
                },
            },
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-after-stop",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "stateChange": {
                        "previous": {"lifecycleState": "STOPPED"},
                        "current": {"lifecycleState": "RUNNING"},
                    },
                },
            },
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "audit transition order" in result.stdout
    assert "matching reaper StopInstance" in result.stdout


def test_state_less_stop_before_state_backed_start_cannot_prove_burst(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventName": "StopInstance",
                "eventTime": "2026-09-01T00:05:00Z",
                "eventId": "stop-before-start-no-state",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "identity": {"principalName": "gpu-reaper"},
                },
            },
            {
                "eventName": "StartInstance",
                "eventTime": RUNNING_AT,
                "eventId": "start-after-state-less-stop",
                "responseStatus": 200,
                "data": {
                    "resourceId": INSTANCE_ID,
                    "stateChange": {"current": {"lifecycleState": "RUNNING"}},
                },
            },
            {
                "eventName": "StopInstance",
                "eventTime": STOPPED_AT,
                "eventId": "stop-after-start",
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


def test_malformed_extra_state_observation_cannot_be_ignored(tmp_path: Path) -> None:
    history = {
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "RUNNING", "timestamp": RUNNING_AT},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
            {"state": "STOPPED"},
        ],
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state_history_burst" in result.stdout
    assert "invalid or missing timestamp" in result.stdout


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


def test_canonical_oci_audit_cloudevents_payload_passes(tmp_path: Path) -> None:
    audit = {
        "data": [
            {
                "eventType": "com.oraclecloud.computeapi.StartInstance.begin",
                "eventTime": "2026-09-01T00:09:59Z",
                "eventGroupingId": "canonical-start",
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
                "eventGroupingId": "canonical-start",
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
                "eventGroupingId": "canonical-stop",
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
                "eventGroupingId": "canonical-stop",
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


@pytest.mark.parametrize(
    ("variable", "target", "extra"),
    [
        ("GPU_EVIDENCE_BUNDLE", "gpu-evidence-export", ()),
        ("GPU_EVIDENCE_STATE_SNAPSHOT", "gpu-evidence-export", ()),
        ("GPU_EVIDENCE_OCI_BIN", "gpu-evidence-export", ()),
        ("GPU_EVIDENCE_PYTHON", "gpu-evidence-check", ()),
        ("GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL", "gpu-evidence-check", ()),
    ],
)
def test_gpu_evidence_make_rejects_shell_metacharacters(variable: str, target: str, extra: tuple[str, ...]) -> None:
    marker = ROOT / "scripts" / f".gpu-evidence-make-injection-{variable}"
    if marker.exists():
        marker.unlink()
    values = {
        "GPU_EVIDENCE_INSTANCE_ID": INSTANCE_ID,
        "GPU_EVIDENCE_COMPARTMENT_ID": "ocid1.compartment.example",
        "GPU_EVIDENCE_SINCE": SINCE,
        "GPU_EVIDENCE_UNTIL": UNTIL,
        "GPU_EVIDENCE_BUNDLE": str(ROOT / ".git" / "gpu-evidence" / "test-bundle"),
        "GPU_EVIDENCE_STATE_SNAPSHOT": str(ROOT / "snapshot.json"),
        "GPU_EVIDENCE_OCI_BIN": "oci",
        "GPU_EVIDENCE_PYTHON": "python3",
        "GPU_EVIDENCE_EXPECTED_STOP_PRINCIPAL": "gpu-reaper",
    }
    values[variable] = f"safe$(touch {marker})"
    command = ["make", "-n", target, *extra, *[f"{key}={value}" for key, value in values.items()]]

    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "unsafe" in result.stderr
    assert not marker.exists()


def _load_checker_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gpu_burst_evidence_under_test", CHECKER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the evidence checker module from {CHECKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _golden_oci_audit_event(
    *,
    action: str,
    phase: str,
    event_time: str,
    event_id: str,
    grouping_id: str,
    principal: str,
    state_change: dict[str, object] | None,
) -> dict[str, object]:
    """Build one OCI Audit CloudEvents record in the shape the service really emits."""

    data: dict[str, object] = {
        "compartmentId": "ocid1.compartment.example",
        "compartmentName": "gpu-burst",
        "resourceId": INSTANCE_ID,
        "resourceName": "gpu-burst-worker",
        "identity": {
            "principalName": principal,
            "principalId": f"ocid1.user.example.{principal}",
            "authType": "natv",
        },
        "request": {
            "id": f"{event_id}-request",
            "action": "POST",
            "path": f"/20160918/instances/{INSTANCE_ID}",
            "parameters": {"action": [action]},
        },
        "response": {"status": "200", "responseTime": event_time},
    }
    if state_change is not None:
        data["stateChange"] = state_change
    return {
        "cloudEventsVersion": "0.1",
        "eventType": f"com.oraclecloud.computeapi.{action.title()}Instance.{phase}",
        "source": "ComputeApi",
        "eventTime": event_time,
        "eventId": event_id,
        "eventGroupingId": grouping_id,
        "contentType": "application/json",
        "data": data,
    }


GOLDEN_OCI_AUDIT: dict[str, list[dict[str, object]]] = {
    "data": [
        _golden_oci_audit_event(
            action="START",
            phase="begin",
            event_time="2026-09-01T00:09:59Z",
            event_id="golden-start-begin",
            grouping_id="golden-start",
            principal="burst-start",
            state_change=None,
        ),
        _golden_oci_audit_event(
            action="START",
            phase="end",
            event_time=RUNNING_AT,
            event_id="golden-start-end",
            grouping_id="golden-start",
            principal="burst-start",
            state_change={
                "previous": {"lifecycleState": "STOPPED"},
                "current": {"lifecycleState": "RUNNING"},
            },
        ),
        _golden_oci_audit_event(
            action="STOP",
            phase="begin",
            event_time="2026-09-01T00:29:59Z",
            event_id="golden-stop-begin",
            grouping_id="golden-stop",
            principal="gpu-reaper",
            state_change=None,
        ),
        _golden_oci_audit_event(
            action="STOP",
            phase="end",
            event_time=STOPPED_AT,
            event_id="golden-stop-end",
            grouping_id="golden-stop",
            principal="gpu-reaper",
            state_change={
                "previous": {"lifecycleState": "RUNNING"},
                "current": {"lifecycleState": "STOPPED"},
            },
        ),
    ]
}


def _golden_audit_without(event_id: str) -> dict[str, list[dict[str, object]]]:
    return {"data": [event for event in GOLDEN_OCI_AUDIT["data"] if event["eventId"] != event_id]}


def test_golden_oci_audit_payload_survives_export_and_check(tmp_path: Path) -> None:
    checker = _load_checker_module()

    history = checker.build_state_history_document(GOLDEN_OCI_AUDIT, instance_id=INSTANCE_ID, since=SINCE, until=UNTIL)

    assert history["instance_id"] == INSTANCE_ID
    assert [observation["state"] for observation in history["observations"]] == [
        "STOPPED",
        "RUNNING",
        "STOPPED",
    ]
    assert {observation["source"] for observation in history["observations"]} == {
        "oci_audit_previous_state",
        "oci_audit_transition",
    }

    bundle = _custom_bundle(tmp_path, history=history, audit=GOLDEN_OCI_AUDIT)

    result = _run_checker(bundle)

    assert result.returncode == 0, result.stdout + result.stderr


def test_golden_oci_audit_without_stop_end_phase_cannot_prove_burst(tmp_path: Path) -> None:
    checker = _load_checker_module()
    audit = _golden_audit_without("golden-stop-end")

    history = checker.build_state_history_document(audit, instance_id=INSTANCE_ID, since=SINCE, until=UNTIL)

    assert [observation["state"] for observation in history["observations"]] == ["STOPPED", "RUNNING"]

    bundle = _custom_bundle(tmp_path, history=history, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "expected STOPPED -> RUNNING -> STOPPED" in result.stdout


def test_golden_oci_audit_with_a_second_start_fails_closed(tmp_path: Path) -> None:
    audit = {
        "data": [
            *GOLDEN_OCI_AUDIT["data"],
            _golden_oci_audit_event(
                action="START",
                phase="end",
                event_time="2026-09-01T00:40:00Z",
                event_id="golden-restart-end",
                grouping_id="golden-restart",
                principal="burst-start",
                state_change=None,
            ),
        ]
    }
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle, "--json")

    assert result.returncode == 1
    verdict = json.loads(result.stdout)
    checks = {check["name"]: check["passed"] for check in verdict["checks"]}
    assert checks["exactly_one_start_instance"] is False
    # The extra event carries no stateChange, so it is not an authoritative
    # transition; the exact-cardinality check rejects it while temporal order
    # remains true.
    assert checks["audit_transition_order"] is True


def test_history_start_after_the_recorded_stop_cannot_prove_burst(tmp_path: Path) -> None:
    history = {
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE, "action": "StopInstance"},
            {"state": "RUNNING", "timestamp": RUNNING_AT, "action": "StartInstance"},
            {"state": "STOPPED", "timestamp": STOPPED_AT, "action": "StopInstance"},
        ],
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state history transition order" in result.stdout


def test_history_transition_order_uses_observed_time_not_document_order(tmp_path: Path) -> None:
    history = {
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "RUNNING", "timestamp": "2026-09-01T00:20:00Z", "action": "StartInstance"},
            {"state": "STOPPED", "timestamp": RUNNING_AT, "action": "StopInstance"},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
        ],
    }
    bundle = _custom_bundle(tmp_path, history=history)

    result = _run_checker(bundle)

    assert result.returncode == 1
    assert "state history transition order" in result.stdout


def _audit_transition_event(
    action: str,
    event_id: str,
    event_time: str,
    *,
    principal: str | None = None,
    previous: str = "STOPPED",
    current: str = "RUNNING",
) -> dict[str, object]:
    data: dict[str, object] = {
        "resourceId": INSTANCE_ID,
        "stateChange": {
            "previous": {"lifecycleState": previous},
            "current": {"lifecycleState": current},
        },
    }
    if principal is not None:
        data["identity"] = {"principalName": principal}
    return {
        "eventName": f"{action}Instance",
        "eventTime": event_time,
        "eventId": event_id,
        "responseStatus": 200,
        "data": data,
    }


def _valid_audit() -> dict[str, list[dict[str, object]]]:
    return {
        "data": [
            _audit_transition_event("Start", "start-1", RUNNING_AT),
            _audit_transition_event(
                "Stop", "stop-1", STOPPED_AT, principal="gpu-reaper", previous="RUNNING", current="STOPPED"
            ),
        ]
    }


def _json_checks(result: subprocess.CompletedProcess[str]) -> dict[str, bool]:
    assert result.returncode == 1, result.stdout + result.stderr
    verdict = json.loads(result.stdout)
    return {check["name"]: check["passed"] for check in verdict["checks"]}


def test_principal_extraction_ignores_nested_request_principal(tmp_path: Path) -> None:
    audit = _valid_audit()
    stop = audit["data"][1]
    stop["identity"] = {"principalName": "attacker"}
    stop_data = stop["data"]
    assert isinstance(stop_data, dict)
    stop_data["request"] = {"parameters": {"principalName": "gpu-reaper"}}

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["expected_stop_principal"] is False
    assert checks["authoritative_stop_cardinality"] is False


def test_action_extraction_rejects_nested_metadata_action_conflict(tmp_path: Path) -> None:
    audit = _valid_audit()
    start = audit["data"][0]
    start["eventName"] = "GetInstance"
    start_data = start["data"]
    assert isinstance(start_data, dict)
    start_data["metadata"] = {"action": "StartInstance"}

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["audit_payload_contract"] is False
    assert checks["exactly_one_start_instance"] is False


def test_instance_id_alias_conflict_fails_closed(tmp_path: Path) -> None:
    instance = {"id": INSTANCE_ID, "data": {"id": "ocid1.instance.other", "lifecycle-state": "STOPPED"}}

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, instance=instance), "--json"))

    assert checks["instance_id_extraction"] is False
    assert checks["instance_identity"] is False


def test_unrelated_nested_data_id_does_not_collapse_distinct_starts(tmp_path: Path) -> None:
    audit = _valid_audit()
    first_start = audit["data"][0]
    assert isinstance(first_start, dict)
    first_start.pop("eventId")
    first_data = first_start["data"]
    assert isinstance(first_data, dict)
    first_data["id"] = "shared-unrelated-id"
    second_start = _audit_transition_event("Start", "unused", "2026-09-01T00:11:00Z")
    second_start.pop("eventId")
    second_data = second_start["data"]
    assert isinstance(second_data, dict)
    second_data["id"] = "shared-unrelated-id"
    audit["data"].insert(1, second_start)

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["exactly_one_start_instance"] is False
    assert checks["audit_action_sequence"] is False


def test_multiple_completed_records_for_one_group_fail_closed(tmp_path: Path) -> None:
    first_start = _audit_transition_event("Start", "start-end-1", RUNNING_AT)
    second_start = _audit_transition_event("Start", "start-end-2", "2026-09-01T00:11:00Z")
    for event in (first_start, second_start):
        event["eventType"] = "com.oraclecloud.computeapi.StartInstance.end"
        event["eventGroupingId"] = "same-start-group"
    audit = {
        "data": [
            first_start,
            second_start,
            _audit_transition_event(
                "Stop", "stop-end-1", STOPPED_AT, principal="gpu-reaper", previous="RUNNING", current="STOPPED"
            ),
        ]
    }

    result = _run_checker(_custom_bundle(tmp_path, audit=audit), "--json")
    checks = _json_checks(result)
    verdict = json.loads(result.stdout)
    details = " ".join(check["detail"] for check in verdict["checks"] if check["name"] == "audit_payload_contract")

    assert checks["audit_payload_contract"] is False
    assert "completed records" in details


def test_status_text_with_code_and_error_word_is_not_success(tmp_path: Path) -> None:
    audit = _valid_audit()
    start = audit["data"][0]
    start["responseStatus"] = "error 200"

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["audit_payload_contract"] is False
    assert checks["exactly_one_start_instance"] is False


def test_two_authoritative_reaper_stops_fail_cardinality(tmp_path: Path) -> None:
    audit = _valid_audit()
    audit["data"].append(
        _audit_transition_event(
            "Stop", "stop-2", "2026-09-01T00:40:00Z", principal="gpu-reaper", previous="RUNNING", current="STOPPED"
        )
    )

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["authoritative_stop_cardinality"] is False
    assert checks["audit_action_sequence"] is False


def test_successful_stop_with_contradictory_current_state_fails_before_filtering(tmp_path: Path) -> None:
    audit = _valid_audit()
    audit["data"].insert(
        1,
        _audit_transition_event(
            "Stop",
            "stop-contradictory",
            "2026-09-01T00:20:00Z",
            principal="gpu-reaper",
            previous="RUNNING",
            current="RUNNING",
        ),
    )

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["audit_current_state_consistency"] is False
    assert checks["audit_action_sequence"] is False


def test_stop_previous_state_must_be_running(tmp_path: Path) -> None:
    audit = _valid_audit()
    bad_stop = audit["data"][1]
    bad_data = bad_stop["data"]
    assert isinstance(bad_data, dict)
    bad_change = bad_data["stateChange"]
    assert isinstance(bad_change, dict)
    bad_change["previous"] = {"lifecycleState": "STOPPED"}

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["audit_transition_states"] is False


def test_state_history_envelope_version_is_checked_before_observations(tmp_path: Path) -> None:
    history = {
        "schema_version": 99,
        "state": "unknown",
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "RUNNING", "timestamp": RUNNING_AT},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
        ],
    }

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, history=history), "--json"))

    assert checks["state_history_schema"] is False
    assert checks["state_history_burst"] is False


def test_unknown_state_history_lifecycle_value_is_named_failure(tmp_path: Path) -> None:
    history = {
        "schema_version": 1,
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "unknown", "timestamp": RUNNING_AT},
            {"state": "STOPPED", "timestamp": STOPPED_AT},
        ],
    }

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, history=history), "--json"))

    assert checks["state_history_lifecycle"] is False
    assert checks["state_history_burst"] is False


def test_state_action_without_timestamp_is_not_silently_dropped(tmp_path: Path) -> None:
    history = {
        "schema_version": 1,
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "RUNNING", "generated_at": RUNNING_AT, "action": "StartInstance"},
            {"state": "STOPPED", "written_at": STOPPED_AT, "action": "StopInstance"},
            {"state": "STOPPED", "action": "StopInstance"},
        ],
    }

    result = _run_checker(_custom_bundle(tmp_path, history=history), "--json")
    checks = _json_checks(result)
    verdict = json.loads(result.stdout)
    action_detail = next(check["detail"] for check in verdict["checks"] if check["name"] == "state_history_actions")

    assert checks["state_history_actions"] is False
    assert "invalid or missing timestamp" in action_detail


def test_state_action_time_aliases_are_shared_and_supported(tmp_path: Path) -> None:
    history = {
        "schema_version": 1,
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "generated_at": SINCE},
            {"state": "RUNNING", "generated_at": RUNNING_AT, "action": "StartInstance"},
            {"state": "STOPPED", "written_at": STOPPED_AT, "action": "StopInstance"},
        ],
    }

    result = _run_checker(_custom_bundle(tmp_path, history=history), "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    verdict = json.loads(result.stdout)
    checks = {check["name"]: check["passed"] for check in verdict["checks"]}
    assert checks["state_history_actions"] is True


def test_state_action_sequence_rejects_trailing_start(tmp_path: Path) -> None:
    history = {
        "schema_version": 1,
        "instance_id": INSTANCE_ID,
        "observations": [
            {"state": "STOPPED", "timestamp": SINCE},
            {"state": "RUNNING", "timestamp": RUNNING_AT, "action": "StartInstance"},
            {"state": "STOPPED", "timestamp": STOPPED_AT, "action": "StopInstance"},
            {"state": "STOPPED", "timestamp": "2026-09-01T00:40:00Z", "action": "StartInstance"},
        ],
    }

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, history=history), "--json"))

    assert checks["state_history_actions"] is False
    assert checks["state_history_burst"] is False


@pytest.mark.parametrize("receipt_time", [RUNNING_AT, STOPPED_AT])
def test_wp_receipt_at_running_interval_boundary_is_not_work(tmp_path: Path, receipt_time: str) -> None:
    bundle = _custom_bundle(
        tmp_path,
        receipts={"items": [{"description": "boundary", "timestamp": receipt_time}]},
    )

    checks = _json_checks(_run_checker(bundle, "--json"))

    assert checks["wp_descriptions"] is False


def test_deeply_nested_state_history_fails_without_recursion_crash(tmp_path: Path) -> None:
    nested: object = [
        {"state": "STOPPED", "timestamp": SINCE},
        {"state": "RUNNING", "timestamp": RUNNING_AT},
        {"state": "STOPPED", "timestamp": STOPPED_AT},
    ]
    for _ in range(80):
        nested = {"observations": nested}
    history = {"schema_version": 1, "instance_id": INSTANCE_ID, "observations": nested}

    result = _run_checker(_custom_bundle(tmp_path, history=history), "--json")

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    verdict = json.loads(result.stdout)
    checks = {check["name"]: check for check in verdict["checks"]}
    assert checks["state_history_burst"]["passed"] is False
    assert "maximum nested depth" in checks["state_history_burst"]["detail"]


def test_history_builder_does_not_derive_stop_from_wrong_previous_state(tmp_path: Path) -> None:
    checker = _load_checker_module()
    audit = _valid_audit()
    bad_stop = audit["data"][1]
    bad_data = bad_stop["data"]
    assert isinstance(bad_data, dict)
    bad_change = bad_data["stateChange"]
    assert isinstance(bad_change, dict)
    bad_change["previous"] = {"lifecycleState": "STOPPED"}

    history = checker.build_state_history_document(audit, instance_id=INSTANCE_ID, since=SINCE, until=UNTIL)

    assert [observation["state"] for observation in history["observations"]] == ["STOPPED", "RUNNING"]


_MISSING_CLI_ATTR = object()


def _cli_util_to_dict_replica(obj: Any) -> Any:
    """Local replica of oci_cli.cli_util.to_dict hyphen conversion.

    Official CLI replaces '_' with '-' on model swagger_types keys only;
    Mapping keys are preserved. Used when oci_cli is not installed.
    """

    if isinstance(obj, str):
        return obj
    if isinstance(obj, (dt.datetime, dt.time)):
        if obj.tzinfo is None:
            obj = obj.replace(tzinfo=dt.UTC)
        if isinstance(obj, dt.datetime):
            return obj.isoformat(sep="T")
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, Mapping):
        return {key: _cli_util_to_dict_replica(value) for key, value in obj.items()}
    if isinstance(obj, Iterable):
        return [_cli_util_to_dict_replica(value) for value in obj]
    if not hasattr(obj, "swagger_types"):
        return obj
    as_dict: dict[str, Any] = {}
    for key in obj.swagger_types:
        value = getattr(obj, key, _MISSING_CLI_ATTR)
        if value is not _MISSING_CLI_ATTR:
            as_dict[key.replace("_", "-")] = _cli_util_to_dict_replica(value)
    return as_dict


def _serialize_oci_audit_event_cli_hyphens(model: Any) -> tuple[dict[str, Any], str]:
    """Serialize an official AuditEvent model the way `oci audit` JSON output does."""

    try:
        from oci_cli.cli_util import to_dict as cli_to_dict
        from oci_cli.version import __version__ as cli_version

        payload = cli_to_dict(model)
        if not isinstance(payload, dict):
            raise TypeError("oci_cli.cli_util.to_dict did not return a mapping")
        origin = f"oci_cli.cli_util.to_dict oci_cli=={cli_version}; NOT a live OCI audit capture"
        return payload, origin
    except ImportError:
        payload = _cli_util_to_dict_replica(model)
        if not isinstance(payload, dict):
            raise TypeError("CLI to_dict replica did not return a mapping")
        origin = (
            "local replica of oci_cli.cli_util.to_dict "
            "(https://raw.githubusercontent.com/oracle/oci-cli/master/src/oci_cli/cli_util.py); "
            "oci_cli not installed; NOT a live OCI audit capture"
        )
        return payload, origin


def _oci_cli_hyphen_audit_event(
    *,
    action: str,
    phase: str,
    event_time: str,
    event_id: str,
    grouping_id: str,
    principal: str,
    previous: str | None = None,
    current: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Build one hyphen-keyed AuditEvent dict from the installed OCI SDK when present."""

    try:
        import oci
        from oci.audit.models import AuditEvent, Data, Identity, Request, Response, StateChange
    except ImportError:
        data: dict[str, Any] = {
            "event-grouping-id": grouping_id,
            "event-name": f"{action.title()}Instance",
            "resource-id": INSTANCE_ID,
            "identity": {"principal-name": principal},
            "request": {
                "id": f"{event_id}-request",
                "action": "POST",
                "parameters": {"action": [action]},
            },
            "response": {"status": "200"},
        }
        if previous is not None or current is not None:
            data["state-change"] = {
                "previous": {"lifecycleState": previous} if previous is not None else None,
                "current": {"lifecycleState": current} if current is not None else None,
            }
        payload = {
            "cloud-events-version": "0.1",
            "content-type": "application/json",
            "data": data,
            "event-id": event_id,
            "event-time": event_time,
            "event-type": f"com.oraclecloud.computeapi.{action.title()}Instance.{phase}",
            "event-type-version": "2.0",
            "source": "ComputeApi",
        }
        origin = (
            "synthetic hyphen-key contract fixture matching oci_cli.cli_util.to_dict; "
            "oci SDK unavailable; NOT a live OCI audit capture"
        )
        return payload, origin

    parsed_time = dt.datetime.fromisoformat(event_time.replace("Z", "+00:00"))
    state_change = None
    if previous is not None or current is not None:
        state_change = StateChange(
            previous={"lifecycleState": previous} if previous is not None else None,
            current={"lifecycleState": current} if current is not None else None,
        )
    model = AuditEvent(
        event_type=f"com.oraclecloud.computeapi.{action.title()}Instance.{phase}",
        cloud_events_version="0.1",
        event_type_version="2.0",
        source="ComputeApi",
        event_id=event_id,
        event_time=parsed_time,
        content_type="application/json",
        data=Data(
            event_grouping_id=grouping_id,
            event_name=f"{action.title()}Instance",
            resource_id=INSTANCE_ID,
            identity=Identity(principal_name=principal),
            request=Request(
                id=f"{event_id}-request",
                action="POST",
                path=f"/20160918/instances/{INSTANCE_ID}",
                parameters={"action": [action]},
            ),
            response=Response(status="200"),
            state_change=state_change,
        ),
    )
    payload, serializer_origin = _serialize_oci_audit_event_cli_hyphens(model)
    origin = f"oci.audit.models.AuditEvent oci=={oci.__version__} file={oci.__file__}; {serializer_origin}"
    return payload, origin


def _oci_cli_hyphen_audit_payload() -> tuple[dict[str, list[dict[str, Any]]], str]:
    start_begin, origin = _oci_cli_hyphen_audit_event(
        action="START",
        phase="begin",
        event_time="2026-09-01T00:09:59Z",
        event_id="cli-start-begin",
        grouping_id="cli-start",
        principal="burst-start",
    )
    start_end, _origin = _oci_cli_hyphen_audit_event(
        action="START",
        phase="end",
        event_time=RUNNING_AT,
        event_id="cli-start-end",
        grouping_id="cli-start",
        principal="burst-start",
        previous="STOPPED",
        current="RUNNING",
    )
    stop_begin, _origin = _oci_cli_hyphen_audit_event(
        action="STOP",
        phase="begin",
        event_time="2026-09-01T00:29:59Z",
        event_id="cli-stop-begin",
        grouping_id="cli-stop",
        principal="gpu-reaper",
    )
    stop_end, _origin = _oci_cli_hyphen_audit_event(
        action="STOP",
        phase="end",
        event_time=STOPPED_AT,
        event_id="cli-stop-end",
        grouping_id="cli-stop",
        principal="gpu-reaper",
        previous="RUNNING",
        current="STOPPED",
    )
    return {"data": [start_begin, start_end, stop_begin, stop_end]}, origin


def test_oci_cli_serializer_fixture_uses_hyphen_model_keys_not_live_capture() -> None:
    audit, origin = _oci_cli_hyphen_audit_payload()
    start_end = audit["data"][1]
    stop_end = audit["data"][3]

    assert "NOT a live OCI audit capture" in origin
    assert start_end["event-type"].endswith("StartInstance.end")
    assert "event-time" in start_end
    assert "event-id" in start_end
    assert "eventType" not in start_end
    assert "event_type" not in start_end
    data = start_end["data"]
    assert isinstance(data, dict)
    assert data["resource-id"] == INSTANCE_ID
    assert data["event-grouping-id"] == "cli-start"
    identity = data["identity"]
    assert isinstance(identity, dict)
    assert identity["principal-name"] == "burst-start"
    state_change = data["state-change"]
    assert isinstance(state_change, dict)
    current = state_change["current"]
    assert isinstance(current, dict)
    assert current["lifecycleState"] == "RUNNING"
    assert "lifecycle-state" not in current
    stop_identity = stop_end["data"]["identity"]
    assert isinstance(stop_identity, dict)
    assert stop_identity["principal-name"] == "gpu-reaper"


def test_oci_cli_hyphen_key_audit_events_prove_burst(tmp_path: Path) -> None:
    audit, _origin = _oci_cli_hyphen_audit_payload()
    bundle = _custom_bundle(tmp_path, audit=audit)

    result = _run_checker(bundle)

    assert result.returncode == 0, result.stdout + result.stderr


def test_event_time_hyphen_alias_is_read() -> None:
    checker = _load_checker_module()

    timestamp, error = checker._event_time_report({"event-time": RUNNING_AT})

    assert error is None
    assert timestamp == checker._parse_time(RUNNING_AT)


def test_resource_id_hyphen_alias_is_read() -> None:
    checker = _load_checker_module()

    resource_id, error = checker._event_resource_id_report({"data": {"resource-id": INSTANCE_ID}})

    assert error is None
    assert resource_id == INSTANCE_ID


def test_principal_hyphen_alias_is_read() -> None:
    checker = _load_checker_module()

    principals, error = checker._principal_report({"data": {"identity": {"principal-name": "gpu-reaper"}}})

    assert error is None
    assert principals == {"gpu-reaper"}


def test_data_event_grouping_id_hyphen_collapses_begin_and_end() -> None:
    checker = _load_checker_module()
    begin = {
        "event-type": "com.oraclecloud.computeapi.StartInstance.begin",
        "event-time": "2026-09-01T00:09:59Z",
        "event-id": "start-begin",
        "data": {"event-grouping-id": "start-group", "resource-id": INSTANCE_ID},
    }
    end = {
        "event-type": "com.oraclecloud.computeapi.StartInstance.end",
        "event-time": RUNNING_AT,
        "event-id": "start-end",
        "data": {"event-grouping-id": "start-group", "resource-id": INSTANCE_ID},
    }

    begin_id, begin_error = checker._event_identity_report(begin, "START", 0)
    end_id, end_error = checker._event_identity_report(end, "START", 1)

    assert begin_error is None
    assert end_error is None
    assert begin_id == "group:start-group"
    assert end_id == begin_id


def test_mixed_case_hyphen_aliases_are_not_accepted() -> None:
    checker = _load_checker_module()

    timestamp, time_error = checker._event_time_report({"Event-Time": RUNNING_AT})
    resource_id, resource_error = checker._event_resource_id_report({"data": {"Resource-Id": INSTANCE_ID}})
    principals, principal_error = checker._principal_report(
        {"data": {"identity": {"Principal-Name": "gpu-reaper"}}}
    )
    grouping, grouping_error = checker._event_identity_report(
        {"Event-Id": "start-1", "data": {"Event-Grouping-Id": "start-group"}},
        "START",
        0,
    )

    assert timestamp is None and time_error is None
    assert resource_id is None and resource_error is None
    assert principals == set() and principal_error is None
    assert grouping.startswith("fallback:")
    assert grouping_error is None


def test_conflicting_hyphen_and_camel_event_time_fails_closed() -> None:
    checker = _load_checker_module()

    timestamp, error = checker._event_time_report(
        {"eventTime": RUNNING_AT, "event-time": STOPPED_AT, "event_time": RUNNING_AT}
    )

    assert timestamp is None
    assert error is not None
    assert "conflict" in error


def test_conflicting_hyphen_and_camel_resource_id_fails_closed() -> None:
    checker = _load_checker_module()

    resource_id, error = checker._event_resource_id_report(
        {"resourceId": INSTANCE_ID, "data": {"resource-id": "ocid1.instance.other"}}
    )

    assert resource_id is None
    assert error is not None
    assert "conflict" in error


def test_conflicting_hyphen_and_camel_principal_fails_closed() -> None:
    checker = _load_checker_module()

    principals, error = checker._principal_report(
        {
            "identity": {"principalName": "gpu-reaper"},
            "data": {"identity": {"principal-name": "attacker"}},
        }
    )

    assert principals == set()
    assert error is not None
    assert "conflict" in error


def test_hyphen_key_wrong_stop_principal_still_fails(tmp_path: Path) -> None:
    audit, _origin = _oci_cli_hyphen_audit_payload()
    stop_end = audit["data"][3]
    stop_end["data"]["identity"]["principal-name"] = "operator"

    checks = _json_checks(_run_checker(_custom_bundle(tmp_path, audit=audit), "--json"))

    assert checks["exactly_one_start_instance"] is True
    assert checks["expected_stop_principal"] is False


def test_duplicate_hyphen_grouping_completed_records_fail_closed(tmp_path: Path) -> None:
    first, _origin = _oci_cli_hyphen_audit_event(
        action="START",
        phase="end",
        event_time=RUNNING_AT,
        event_id="start-end-1",
        grouping_id="same-start-group",
        principal="burst-start",
        previous="STOPPED",
        current="RUNNING",
    )
    second, _origin = _oci_cli_hyphen_audit_event(
        action="START",
        phase="end",
        event_time="2026-09-01T00:11:00Z",
        event_id="start-end-2",
        grouping_id="same-start-group",
        principal="burst-start",
        previous="STOPPED",
        current="RUNNING",
    )
    stop, _origin = _oci_cli_hyphen_audit_event(
        action="STOP",
        phase="end",
        event_time=STOPPED_AT,
        event_id="stop-end-1",
        grouping_id="stop-group",
        principal="gpu-reaper",
        previous="RUNNING",
        current="STOPPED",
    )
    audit = {"data": [first, second, stop]}

    result = _run_checker(_custom_bundle(tmp_path, audit=audit), "--json")
    checks = _json_checks(result)
    verdict = json.loads(result.stdout)
    details = " ".join(check["detail"] for check in verdict["checks"] if check["name"] == "audit_payload_contract")

    assert checks["audit_payload_contract"] is False
    assert "completed records" in details
