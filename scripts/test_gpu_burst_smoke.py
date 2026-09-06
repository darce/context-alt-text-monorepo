"""Red/green contract tests for the offline GPU burst smoke proof."""

from __future__ import annotations

import ast
import json
import os
import re
import signal
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import gpu_burst_smoke as smoke
import httpx
import pytest

from db.models.scene import DescribeRun, DescribeRunItem
from scene.domain.description import DescriptionResultTier
from scene.interface_adapters.http.routers.describe_run import _run_items_response

FIXTURE_DENYLIST = Path(__file__).resolve().parent / "deploy" / "lib" / "fixture-denylist.sh"


def _args(tmp_path: Path, *extra: str):
    return smoke.build_parser().parse_args(
        [
            "--evidence-out",
            str(tmp_path / "evidence.json"),
            "--gpu-state-json",
            str(tmp_path / "missing-gpu-state.json"),
            "--load-json",
            str(tmp_path / "missing-load.json"),
            *extra,
        ]
    )


def _run(
    tmp_path: Path,
    *,
    scenario: smoke.DryScenario | None = None,
    oci: smoke.FakeOci | None = None,
    app_password: str = "not-a-secret",
    service_api_key: str = "dry-service-key",
    extra: tuple[str, ...] = (),
    transport: httpx.BaseTransport | None = None,
) -> tuple[smoke.SmokeResult, smoke.FakeOci]:
    scenario = scenario or smoke.DryScenario()
    scenario.service_api_key = service_api_key
    fake_oci = oci or smoke.FakeOci(gpu_states=scenario.gpu_states)
    clock = smoke.FastClock()

    def load_snapshot_reader(_path: str) -> dict[str, object]:
        if scenario.load_snapshot_after_trigger is None:
            return {"availability": "unavailable", "path": _path}
        written_at = scenario.submitted_at or clock.now()
        return {
            "availability": "available",
            "path": _path,
            "value": {
                **scenario.load_snapshot_after_trigger,
                "written_at": written_at.timestamp() + scenario.load_snapshot_written_offset_seconds,
            },
        }

    client = httpx.Client(
        transport=transport or smoke.make_mock_transport(scenario, now=clock.now),
        follow_redirects=False,
    )
    try:
        result = smoke.run_smoke(
            _args(tmp_path, *extra),
            client=client,
            oci=fake_oci,
            app_password=app_password,
            service_api_key=service_api_key,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            now=clock.now,
            load_snapshot_reader=load_snapshot_reader,
        )
    finally:
        client.close()
    return result, fake_oci


def _check(result: smoke.SmokeResult, name: str) -> bool:
    matches = [check for check in result.evidence["checks"] if check["name"] == name]
    assert len(matches) == 1, (name, result.evidence["checks"])
    return bool(matches[0]["passed"])


def _detail(result: smoke.SmokeResult, name: str) -> str:
    return next(check["detail"] for check in result.evidence["checks"] if check["name"] == name)


def _valid_boundary_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "media_id": 101,
        "status": "completed",
        "tier": "final_gpu",
        "result_generation": 2,
        "caption": "A red bicycle leans beside a brick library wall.",
        "alt_text_draft": "Red bicycle beside a brick library wall",
        "provenance": {
            "model_id": f"{smoke.EXPECTED_PROFILE.hub_repo}@{smoke.EXPECTED_REVISION}",
        },
    }
    item.update(overrides)
    return item


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"not": "a list"}, r"items.*list.*dict"),
        ([_valid_boundary_item(), "malformed"], r"items\[1\].*object.*str"),
        (
            [{key: value for key, value in _valid_boundary_item().items() if key != "media_id"}],
            r"items\[0\]\.media_id",
        ),
        ([_valid_boundary_item(status=7)], r"items\[0\]\.status.*str"),
        (
            [{key: value for key, value in _valid_boundary_item().items() if key != "tier"}],
            r"items\[0\].*contract_tier_missing",
        ),
        (
            [_valid_boundary_item(result_generation="two")],
            r"items\[0\]\.result_generation.*int",
        ),
        ([_valid_boundary_item(provenance=None)], r"items\[0\]\.provenance.*object"),
        (
            [_valid_boundary_item(provenance={"model_id": smoke.EXPECTED_PROFILE.hub_repo})],
            r"items\[0\]\.provenance\.model_id.*@",
        ),
    ],
)
def test_items_boundary_rejects_malformed_payload(payload: object, message: str) -> None:
    with pytest.raises(smoke.SmokeFailure, match=message):
        smoke._validate_items_payload(payload)


def test_items_boundary_preserves_a_well_formed_list() -> None:
    items = [_valid_boundary_item()]

    assert smoke._validate_items_payload(items) is items


def test_items_boundary_rejects_a_foreign_tenant_or_run_envelope(tmp_path: Path) -> None:
    scenario = smoke.DryScenario()
    base_transport = smoke.make_mock_transport(scenario)

    def misroute_items(request: httpx.Request) -> httpx.Response:
        response = base_transport.handle_request(request)
        if request.method == "GET" and request.url.path.endswith("/items"):
            payload = response.json()
            payload["tenant_id"] = "foreign-tenant"
            return httpx.Response(response.status_code, json=payload)
        return response

    result, _ = _run(
        tmp_path,
        scenario=scenario,
        transport=httpx.MockTransport(misroute_items),
    )

    assert result.exit_code == 1
    assert "tenant" in _detail(result, "flow_completed")


def test_service_router_items_satisfy_smoke_contract() -> None:
    """Keep the dry validator tied to the service's real persisted-item shape."""

    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    run = DescribeRun(
        id=run_id,
        tenant_id=tenant_id,
        media_ids=[101],
        total_items=1,
    )
    provenance = {
        "adapter": "gpu_remote",
        "model_id": f"{smoke.EXPECTED_PROFILE.hub_repo}@{smoke.EXPECTED_REVISION}",
        "model_version": smoke.EXPECTED_MODEL_ID,
        "prompt_or_task_version": "3",
        "image_hash": "image-hash",
        "context_hash": "context-hash",
        "cached": False,
        "duration_ms": 125,
    }
    item = DescribeRunItem(
        run_id=run_id,
        tenant_id=tenant_id,
        media_id=101,
        status="completed",
        alt_text_draft="Red bicycle beside a brick library wall",
        caption="A red bicycle leans beside a brick library wall.",
        provenance=provenance,
        tier=DescriptionResultTier.FINAL_GPU.value,
        result_generation=2,
    )

    items = _run_items_response(run, [item]).model_dump(mode="json")["items"]

    assert smoke._validate_items_payload(items) is items
    assert items[0]["tier"] == "final_gpu"
    assert items[0]["result_generation"] == 2
    assert items[0]["provenance"] == provenance

    for field_name, message in (
        ("tier", r"contract_tier_missing"),
        ("result_generation", r"result_generation.*non-negative int"),
    ):
        without_required_field = [{**items[0]}]
        without_required_field[0].pop(field_name)
        with pytest.raises(smoke.SmokeFailure, match=message):
            smoke._validate_items_payload(without_required_field)


def test_subprocess_oci_uses_supported_exact_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(argv)
        if argv[1:4] == ["compute", "instance", "get"]:
            payload = {"data": {"id": "instance-placeholder"}}
        elif argv[1:4] == ["audit", "event", "list"]:
            payload = {
                "data": [
                    {
                        "eventType": "com.oraclecloud.computeapi.instanceaction.end",
                        "eventId": "start-event-placeholder",
                        "eventTime": "2026-01-01T00:01:00Z",
                        "data": {
                            "resourceId": "instance-placeholder",
                            "request": {
                                "id": "request-placeholder",
                                "parameters": {"action": ["START"]},
                            },
                        },
                    },
                    {
                        "eventType": "com.oraclecloud.computeapi.instanceaction.end",
                        "eventId": "stop-event-placeholder",
                        "eventTime": "2026-01-01T00:05:00Z",
                        "data": {
                            "resourceId": "instance-placeholder",
                            "identity": {
                                "principalName": "gpu_lifecycle",
                                "principalId": "ocid1.dynamicgroup.oc1..gpu-lifecycle",
                            },
                            "request": {
                                "id": "stop-request-placeholder",
                                "parameters": {"action": ["StopInstance"]},
                            },
                        },
                    },
                ]
            }
        else:
            payload = {"data": []}
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(payload))

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    oci = smoke.SubprocessOci("oci-placeholder")

    oci.get_instance("instance-placeholder", timeout=3)
    oci.stop_instance("instance-placeholder", timeout=3)
    oci.list_instances("compartment-placeholder", timeout=3)
    events = oci.list_start_events(
        "compartment-placeholder",
        "instance-placeholder",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T00:05:00Z",
        timeout=3,
    )
    stop_events = oci.list_stop_events(
        "compartment-placeholder",
        "instance-placeholder",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T00:05:00Z",
        timeout=3,
    )

    assert len(events) == 1
    assert len(stop_events) == 1

    assert calls == [
        [
            "oci-placeholder",
            "compute",
            "instance",
            "get",
            "--instance-id",
            "instance-placeholder",
            "--output",
            "json",
        ],
        [
            "oci-placeholder",
            "compute",
            "instance",
            "action",
            "--instance-id",
            "instance-placeholder",
            "--action",
            "STOP",
            "--output",
            "json",
        ],
        [
            "oci-placeholder",
            "compute",
            "instance",
            "list",
            "--compartment-id",
            "compartment-placeholder",
            "--all",
            "--output",
            "json",
        ],
        [
            "oci-placeholder",
            "audit",
            "event",
            "list",
            "--compartment-id",
            "compartment-placeholder",
            "--start-time",
            "2026-01-01T00:00:00Z",
            "--end-time",
            "2026-01-01T00:05:00Z",
            "--all",
            "--output",
            "json",
        ],
        [
            "oci-placeholder",
            "audit",
            "event",
            "list",
            "--compartment-id",
            "compartment-placeholder",
            "--start-time",
            "2026-01-01T00:00:00Z",
            "--end-time",
            "2026-01-01T00:05:00Z",
            "--all",
            "--output",
            "json",
        ],
    ]


def test_default_dry_run_writes_evidence_outside_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)

    assert smoke.main([]) == 0
    assert not (tmp_path / "docs").exists()
    assert list((tmp_path / ".workbay" / "tmp" / "gpu-burst-smoke").glob("*.json"))


def test_default_evidence_name_has_second_resolution() -> None:
    name = Path(smoke.build_parser().parse_args([]).evidence_out).name

    assert re.fullmatch(r"GPUSMOKE-1-evidence-\d{8}T\d{6}Z\.json", name)


def test_dry_validation_is_hermetic_when_old_daily_default_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "REPO_ROOT", tmp_path)
    old_default = tmp_path / smoke.DEFAULT_EVIDENCE_DIR / "GPUSMOKE-1-evidence-2026-09-03.json"
    old_default.parent.mkdir(parents=True)
    old_default.write_text("old\n", encoding="utf-8")

    args = smoke.build_parser().parse_args([])

    assert smoke._validate_args(args) == ("dry-run-only", "dry-service-key")


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("A person standing outdoors amid greenery.", True),
        ("GREENERY — person; outdoors, standing!", True),
        ("A plate of food on a wooden table", True),
        ("A red bicycle leans beside a brick library wall.", False),
        ("", False),
        ("person outdoors", False),
    ],
)
def test_fixture_denylist_python_matches_canonical_bash(sample: str, expected: bool) -> None:
    shell = subprocess.run(
        [
            "bash",
            "-c",
            'source "$2"; fixture_sample_is_denied "$1"',
            "_",
            sample,
            str(FIXTURE_DENYLIST),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert smoke.fixture_sample_is_denied(sample) is expected
    assert (shell.returncode == 0) is expected


def test_dry_run_exercises_whole_flow_and_writes_cost_evidence(tmp_path: Path) -> None:
    result, oci = _run(tmp_path)

    assert result.exit_code == 0
    assert oci.stop_calls == 0
    assert [entry["state"] for entry in result.evidence["transitions"]] == [
        "STOPPED",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "STOPPED",
    ]
    assert result.evidence["item_timeline"] == [
        {
            "elapsed_seconds": 0.0,
            "media_id": 101,
            "status": "queued",
            "tier": None,
            "result_generation": 0,
        },
        {
            "elapsed_seconds": 2.0,
            "media_id": 101,
            "status": "running",
            "tier": None,
            "result_generation": 0,
        },
        {
            "elapsed_seconds": 2.0,
            "media_id": 101,
            "status": "running",
            "tier": None,
            "result_generation": 0,
        },
        {
            "elapsed_seconds": 4.0,
            "media_id": 101,
            "status": "completed",
            "tier": "final_gpu",
            "result_generation": 1,
        },
    ]
    assert result.evidence["item_provenance"] == [
        {
            "media_id": 101,
            "tier": "final_gpu",
            "model_id": smoke.EXPECTED_PROFILE.hub_repo,
            "revision": smoke.EXPECTED_REVISION,
            "result_generation": 1,
        }
    ]
    assert _check(result, "provisional_superseded_by_final")
    assert _check(result, "load_snapshot_observed_after_trigger")
    assert result.evidence["phase_durations_seconds"]["warm_start"] >= 0
    assert {sample["phase"] for sample in result.evidence["service_health_samples"]} >= {
        "preflight",
        "warm_up",
        "processing",
        "drain",
        "recovery",
        "after_stop",
    }
    assert result.evidence["cost_estimate_usd"] > 0
    assert result.evidence["cost_estimate_ongoing"] is False
    assert (tmp_path / "evidence.json").is_file()


def test_application_password_is_absent_from_output_and_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "unique-wp-application-password"
    service_api_key = "unique-description-service-api-key"

    result, _ = _run(tmp_path, app_password=password, service_api_key=service_api_key)
    captured = capsys.readouterr()

    assert result.exit_code == 0
    assert password not in captured.out
    assert password not in captured.err
    assert password not in (tmp_path / "evidence.json").read_text(encoding="utf-8")
    assert service_api_key not in captured.out
    assert service_api_key not in captured.err
    assert service_api_key not in (tmp_path / "evidence.json").read_text(encoding="utf-8")


def test_red_final_item_remains_provisional_cpu(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(
            item_tiers=[None, "provisional_cpu", "provisional_cpu", "provisional_cpu"],
            result_generations=[0, 1, 1, 1],
        ),
    )

    assert result.exit_code == 1
    assert not _check(result, "tier_final_gpu")


def test_red_completed_provisional_observed_mid_run_is_degraded(
    tmp_path: Path,
) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(
            item_statuses=["queued", "completed", "running", "completed"],
            item_tiers=[None, "provisional_cpu", "provisional_cpu", "final_gpu"],
            result_generations=[0, 1, 1, 2],
        ),
    )

    assert result.exit_code == 1
    assert not _check(result, "no_degraded_items")
    assert "101" in _detail(result, "no_degraded_items")


def test_red_missing_one_of_two_requested_media_items(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, extra=("--media-ids", "101,102"))

    assert result.exit_code == 1
    assert not _check(result, "returned_media_ids_exact")
    assert "102" in _detail(result, "returned_media_ids_exact")


def test_red_duplicate_returned_media_id_is_rejected(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(returned_media_ids=[101, 101])
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert "duplicate media_id" in _detail(result, "flow_completed")
    assert "101" in _detail(result, "flow_completed")


def test_red_completed_with_errors_is_not_success(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(run_statuses=["running", "completed_with_errors"])
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert not _check(result, "run_terminal_success")
    assert _detail(result, "run_terminal_success") == "completed_with_errors"


def test_red_requested_item_final_status_is_not_completed(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(item_statuses=["queued", "queued", "running", "failed"])
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert not _check(result, "all_items_completed")
    assert "101" in _detail(result, "all_items_completed")


def test_red_item_terminal_before_instance_running(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(item_statuses=["completed"], item_tiers=["final_gpu"])
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert not _check(result, "no_item_terminal_before_running")
    assert "101" in _detail(result, "no_item_terminal_before_running")


def test_bulk_worker_direct_final_does_not_require_provisional_supersession(
    tmp_path: Path,
) -> None:
    scenario = smoke.DryScenario(
        item_statuses=["queued", "running", "completed"],
        item_tiers=[None, None, "final_gpu"],
        result_generations=[0, 0, 1],
    )
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 0
    assert _check(result, "provisional_superseded_by_final")


def test_red_nonincreasing_result_generation_is_not_supersession(
    tmp_path: Path,
) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(
            item_tiers=[None, "provisional_cpu", "provisional_cpu", "final_gpu"],
            result_generations=[0, 1, 1, 1],
        ),
    )

    assert result.exit_code == 1
    assert not _check(result, "provisional_superseded_by_final")


def test_red_service_health_degrades_during_processing(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(health_statuses=["ok", "ok", "ok", "degraded"]),
    )

    assert result.exit_code == 1
    assert not _check(result, "service_health_throughout")
    assert any(
        sample["phase"] == "processing" and not sample["healthy"]
        for sample in result.evidence["service_health_samples"]
    )


def test_red_missing_fresh_load_snapshot_after_trigger(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(load_snapshot_after_trigger=None)
    result, oci = _run(
        tmp_path,
        scenario=scenario,
    )

    assert result.exit_code == 1
    assert not _check(result, "load_snapshot_observed_after_trigger")
    assert scenario.transport_counts["enqueue_posts"] == 0
    assert oci.armed is False


def test_red_missing_fresh_load_snapshot_after_trigger_legacy_shape(tmp_path: Path) -> None:
    """Keep the original assertion close to the preflight regression above."""
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(load_snapshot_after_trigger=None),
    )

    assert result.exit_code == 1
    assert not _check(result, "load_snapshot_observed_after_trigger")


def test_load_snapshot_written_just_before_submit_returns_is_fresh(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(load_snapshot_written_offset_seconds=-0.5),
    )

    assert result.exit_code == 0
    assert _check(result, "load_snapshot_observed_after_trigger")


def test_load_snapshot_older_than_pre_submit_anchor_and_skew_fails(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(load_snapshot_written_offset_seconds=-3.0),
    )

    assert result.exit_code == 1
    assert not _check(result, "load_snapshot_observed_after_trigger")
    assert "freshness_anchor" in _detail(result, "load_snapshot_observed_after_trigger")


def test_service_warmup_budget_matches_service_contract() -> None:
    from scene.config.settings import DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS

    assert smoke.WARM_START_BUDGET_SECONDS == DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS


def test_warm_start_at_400_seconds_fits_default_budget(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(
        item_statuses=["queued"] * 200 + ["running", "completed"],
        item_tiers=[None] * 201 + ["final_gpu"],
        result_generations=[0] * 201 + [1],
    )
    oci = smoke.FakeOci(startup_states=["STARTING"] * 200 + ["RUNNING"])
    result, _ = _run(tmp_path, scenario=scenario, oci=oci)

    assert result.exit_code == 0
    assert _check(result, "warm_start_running")
    assert result.evidence["phase_durations_seconds"]["warm_start"] == pytest.approx(400.0)


def test_red_health_adapter_preflight_refuses(tmp_path: Path) -> None:
    result, oci = _run(tmp_path, scenario=smoke.DryScenario(health_adapter="seeded"))

    assert result.exit_code == 2
    assert not _check(result, "health_adapter_gpu_qwen30b")
    assert oci.stop_calls == 0
    assert _check(result, "finally_stop_skipped")
    assert "instance was not validated" in _detail(result, "finally_stop_skipped")


def test_service_health_preflight_sends_bearer_auth(tmp_path: Path) -> None:
    scenario = smoke.DryScenario()
    base_transport = smoke.make_mock_transport(scenario)

    def require_service_auth(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/detailed" and request.headers.get("authorization") != "Bearer dry-service-key":
            return httpx.Response(401, json={"detail": "unauthorized"})
        return base_transport.handle_request(request)

    fake_oci = smoke.FakeOci()
    clock = smoke.FastClock()
    transport = httpx.MockTransport(require_service_auth)
    transport.counts = scenario.transport_counts  # type: ignore[attr-defined]
    with httpx.Client(transport=transport) as client:
        result = smoke.run_smoke(
            _args(tmp_path),
            client=client,
            oci=fake_oci,
            app_password="not-a-secret",
            service_api_key="dry-service-key",
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            now=clock.now,
            load_snapshot_reader=lambda path: {
                "availability": "available",
                "path": path,
                "value": {
                    "queue_depth": 0,
                    "in_flight": 0,
                    "batch_in_progress": True,
                    "written_at": clock.now().timestamp(),
                },
            },
        )

    assert result.exit_code == 0
    assert _check(result, "service_auth")


def test_red_service_auth_refusal_is_distinct_and_does_not_stop(
    tmp_path: Path,
) -> None:
    def reject_service_auth(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/detailed":
            return httpx.Response(403, json={"detail": "forbidden"})
        raise AssertionError(f"unexpected request after refusal: {request.url}")

    fake_oci = smoke.FakeOci()
    clock = smoke.FastClock()
    with httpx.Client(transport=httpx.MockTransport(reject_service_auth)) as client:
        result = smoke.run_smoke(
            _args(tmp_path),
            client=client,
            oci=fake_oci,
            app_password="not-a-secret",
            service_api_key="rejected-service-key",
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            now=clock.now,
        )

    assert result.exit_code == 2
    assert not _check(result, "service_auth")
    assert all(check["name"] != "health_adapter_gpu_qwen30b" for check in result.evidence["checks"])
    assert fake_oci.stop_calls == 0
    assert _check(result, "finally_stop_skipped")


def test_red_initial_instance_not_stopped_preflight_refuses(tmp_path: Path) -> None:
    result, oci = _run(tmp_path, oci=smoke.FakeOci(current_state="RUNNING"))

    assert result.exit_code == 2
    assert not _check(result, "initial_instance_stopped")
    assert oci.stop_calls == 0


def test_refusal_after_start_still_issues_compensating_stop(tmp_path: Path) -> None:
    class RefusingAfterStartOci(smoke.FakeOci):
        def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, object]:
            if self.armed and not self.stopping:
                raise smoke.PreflightRefusal("injected refusal after START")
            return super().get_instance(instance_id, timeout=timeout)

    result, oci = _run(tmp_path, oci=RefusingAfterStartOci())

    assert result.exit_code == 2
    assert oci.stop_calls == 1
    assert _check(result, "finally_stop_issued")
    assert _check(result, "instance_stopped_finally")


def test_unowned_instance_is_not_stopped(tmp_path: Path) -> None:
    class UnownedOci(smoke.FakeOci):
        def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, object]:
            instance = super().get_instance(instance_id, timeout=timeout)
            instance["display-name"] = "unrelated-instance"
            instance["freeform-tags"] = {"role": "unrelated"}
            return instance

    result, oci = _run(tmp_path, oci=UnownedOci())

    assert result.exit_code == 2
    assert not _check(result, "instance_dedicated_gpu_burst")
    assert oci.stop_calls == 0
    assert _check(result, "finally_stop_skipped")


def test_live_preflight_requires_the_documented_gpu_identity_metadata(tmp_path: Path) -> None:
    class WronglyTaggedOci(smoke.FakeOci):
        def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, object]:
            instance = super().get_instance(instance_id, timeout=timeout)
            instance["display-name"] = "acx-gpu-burst-rogue"
            instance["shape"] = "VM.Standard.E5.Flex"
            instance["freeform-tags"] = {
                "project": "other-project",
                "env": "production",
                "role": "gpu-burst",
                "scale_to_zero": "true",
                "purpose": "gpu-spike-bench",
            }
            return instance

    result, oci = _run(tmp_path, oci=WronglyTaggedOci())

    assert result.exit_code == 2
    assert not _check(result, "instance_dedicated_gpu_burst")
    assert oci.stop_calls == 0
    assert _check(result, "finally_stop_skipped")


def test_red_failed_run_terminal(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, scenario=smoke.DryScenario(run_statuses=["failed"]))

    assert result.exit_code == 1
    assert not _check(result, "run_terminal_success")


def test_red_fixture_caption(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(caption="A person standing outdoors amid greenery."),
    )

    assert result.exit_code == 1
    assert not _check(result, "caption_not_fixture")
    assert result.evidence["denylist_verdicts"][0]["denied"] is True


def test_red_fixture_alt_text_cannot_hide_behind_safe_caption(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        scenario=smoke.DryScenario(alt_text_draft="A plate of food on a wooden table"),
    )

    assert result.exit_code == 1
    assert not _check(result, "caption_not_fixture")
    alt_verdict = next(
        verdict for verdict in result.evidence["denylist_verdicts"] if verdict["field"] == "alt_text_draft"
    )
    assert alt_verdict["denied"] is True


def test_red_wrong_model_id(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, scenario=smoke.DryScenario(model_id="wrong-model"))

    assert result.exit_code == 1
    assert not _check(result, "model_id_qwen30b")


def test_red_unpinned_revision(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, scenario=smoke.DryScenario(revision="unpinned"))

    assert result.exit_code == 1
    assert not _check(result, "model_revision_pinned")


def test_sampled_starting_states_do_not_count_as_start_actions(tmp_path: Path) -> None:
    oci = smoke.FakeOci(
        startup_states=["STARTING", "RUNNING"],
        reaper_states=["STARTING", "RUNNING", "STOPPING", "STOPPED"],
    )
    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 0
    assert _check(result, "exactly_one_start_action")


def test_red_two_authoritative_start_actions_break_idempotence(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, oci=smoke.FakeOci(start_action_count=2))

    assert result.exit_code == 1
    assert not _check(result, "exactly_one_start_action")


def test_audit_begin_and_end_pair_counts_as_one_start(tmp_path: Path) -> None:
    class BeginEndOci(smoke.FakeOci):
        def list_start_events(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
            del args, kwargs
            request = {"parameters": {"action": ["START"]}, "id": "request-placeholder"}
            return [
                {
                    "eventType": "com.oraclecloud.computeapi.instanceaction.begin",
                    "eventId": "begin-placeholder",
                    "data": {"resourceId": "<burst-instance-ocid>", "request": request},
                },
                {
                    "eventType": "com.oraclecloud.computeapi.instanceaction.end",
                    "eventId": "end-placeholder",
                    "data": {"resourceId": "<burst-instance-ocid>", "request": request},
                },
            ]

    result, _ = _run(tmp_path, oci=BeginEndOci())

    assert result.exit_code == 0
    assert _check(result, "exactly_one_start_action")


def test_audit_index_retry_records_lag(tmp_path: Path) -> None:
    class LaggedAuditOci(smoke.FakeOci):
        audit_reads = 0

        def list_start_events(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
            self.audit_reads += 1
            if self.audit_reads == 1:
                return []
            return super().list_start_events(*args, **kwargs)

    oci = LaggedAuditOci()
    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 0
    assert oci.audit_reads == 2
    assert result.evidence["start_action_evidence"]["audit_lag_seconds"] == pytest.approx(2.0)


def test_zero_audit_events_has_distinct_indexing_failure(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, oci=smoke.FakeOci(start_action_count=0))

    assert result.exit_code == 1
    assert not _check(result, "exactly_one_start_action")
    assert "zero START events indexed" in _detail(result, "exactly_one_start_action")
    assert result.evidence["start_action_evidence"]["status"] == "not_indexed"


def test_red_warm_start_deadline_still_issues_stop(tmp_path: Path) -> None:
    oci = smoke.FakeOci(startup_states=["STARTING"])
    result, used_oci = _run(tmp_path, oci=oci, extra=("--max-seconds", "3"))

    assert result.exit_code == 1
    assert not _check(result, "warm_start_running")
    assert not _check(result, "deadline")
    assert used_oci.stop_calls == 1
    assert _check(result, "instance_stopped_finally")


def test_red_instance_left_running_issues_compensating_stop(tmp_path: Path) -> None:
    oci = smoke.FakeOci(reaper_states=["RUNNING"])
    result, used_oci = _run(tmp_path, oci=oci, extra=("--max-seconds", "5"))

    assert result.exit_code == 1
    assert not _check(result, "instance_stopped_after_reaper")
    assert used_oci.stop_calls == 1
    assert _check(result, "instance_stopped_finally")


def test_red_orphan_running(tmp_path: Path) -> None:
    orphan = {
        "id": "orphan-id",
        "display-name": smoke.EXPECTED_GPU_BURST_DISPLAY_NAME,
        "shape": smoke.EXPECTED_GPU_BURST_SHAPE,
        "lifecycle-state": "RUNNING",
        "freeform-tags": dict(smoke.EXPECTED_GPU_BURST_TAGS),
    }
    result, _ = _run(tmp_path, oci=smoke.FakeOci(orphan_instances=[orphan]))

    assert result.exit_code == 1
    assert not _check(result, "no_orphan_running")


def test_red_tag_owned_orphan_with_changed_name_and_shape_is_reported(tmp_path: Path) -> None:
    orphan = {
        "id": "orphan-renamed-id",
        "display-name": "renamed-gpu-burst",
        "shape": "VM.GPU.A10.2",
        "lifecycle-state": "RUNNING",
        "freeform-tags": dict(smoke.EXPECTED_GPU_BURST_TAGS),
    }

    result, _ = _run(tmp_path, oci=smoke.FakeOci(orphan_instances=[orphan]))

    assert result.exit_code == 1
    assert not _check(result, "no_orphan_running")
    assert "orphan-renamed-id" in _detail(result, "no_orphan_running")
    assert not _check(result, "orphan_identity_matches")


def test_red_deadline_still_issues_stop(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(run_statuses=["running"])
    result, oci = _run(tmp_path, scenario=scenario, extra=("--max-seconds", "3"))

    assert result.exit_code == 1
    assert not _check(result, "deadline")
    assert oci.stop_calls == 1
    assert _check(result, "service_health_throughout")
    assert any(sample["phase"] == "after_stop" for sample in result.evidence["service_health_samples"])


def test_red_deadline_while_starting_issues_compensating_stop(
    tmp_path: Path,
) -> None:
    class StartingOnlyOci(smoke.FakeOci):
        begin_reaper = None

    oci = StartingOnlyOci(startup_states=["STARTING"])
    result, used_oci = _run(tmp_path, oci=oci, extra=("--max-seconds", "3"))

    assert result.exit_code == 1
    assert used_oci.stop_calls >= 1
    assert _check(result, "finally_stop_issued")
    assert _check(result, "instance_stopped_finally")


def test_red_failed_stop_command_is_reported(tmp_path: Path) -> None:
    class StopFailingOci(smoke.FakeOci):
        def stop_instance(self, instance_id: str, *, timeout: float) -> None:
            self.stop_calls += 1
            raise smoke.SmokeFailure("injected STOP failure")

    result, oci = _run(
        tmp_path,
        oci=StopFailingOci(reaper_states=["RUNNING"]),
        extra=("--max-seconds", "5"),
    )

    assert result.exit_code == 1
    assert 1 < oci.stop_calls <= smoke.MAX_EMERGENCY_STOP_ATTEMPTS
    assert not _check(result, "finally_stop_issued")


def test_red_stop_reverification_fails_if_compensating_stop_is_ineffective(
    tmp_path: Path,
) -> None:
    oci = smoke.FakeOci(reaper_states=["RUNNING"], stop_effective=False)
    result, _ = _run(tmp_path, oci=oci, extra=("--max-seconds", "5"))

    assert result.exit_code == 1
    assert not _check(result, "instance_stopped_finally")
    assert result.evidence["measurements"]["running_seconds"] > 0
    assert result.evidence["measurements"]["running_seconds_ongoing"] is True
    assert result.evidence["running_seconds_ongoing"] is True
    assert result.evidence["cost_estimate_usd"] > 0
    assert result.evidence["cost_estimate_ongoing"] is True


def test_red_compensating_stop_times_out_in_stopping(tmp_path: Path) -> None:
    oci = smoke.FakeOci(reaper_states=["RUNNING"], stop_states=["STOPPING"])
    result, _ = _run(tmp_path, oci=oci, extra=("--max-seconds", "5"))

    assert result.exit_code == 1
    assert not _check(result, "instance_stopped_finally")
    assert "STOPPING" in _detail(result, "instance_stopped_finally")


def test_red_unknown_compensation_state_still_issues_stop(tmp_path: Path) -> None:
    class UnknownAfterStartOci(smoke.FakeOci):
        begin_reaper = None

        def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, object]:
            instance = super().get_instance(instance_id, timeout=timeout)
            if self.startup_states == [] and self.current_state == "RUNNING" and self.stop_calls == 0:
                instance["lifecycle-state"] = "FUTURE_RUNNING_STATE"
            return instance

    oci = UnknownAfterStartOci()
    result, used_oci = _run(tmp_path, oci=oci, extra=("--max-seconds", "5"))

    assert result.exit_code == 1
    assert used_oci.stop_calls >= 1
    assert _check(result, "finally_stop_issued")
    assert _check(result, "instance_stopped_finally")


def test_evidence_writer_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    target = tmp_path / "evidence.json"
    target.write_text("existing evidence\n", encoding="utf-8")

    with pytest.raises(smoke.PreflightRefusal, match=r"already exists.*--force"):
        smoke._write_evidence(str(target), {"replacement": True})

    assert target.read_text(encoding="utf-8") == "existing evidence\n"

    smoke._write_evidence(str(target), {"replacement": True}, force=True)

    assert json.loads(target.read_text(encoding="utf-8")) == {"replacement": True}


def test_existing_evidence_path_refuses_before_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "evidence.json"
    target.write_text("existing evidence\n", encoding="utf-8")

    exit_code = smoke.main(["--evidence-out", str(target)])

    assert exit_code == 2
    assert "already exists" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "existing evidence\n"

    assert smoke.main(["--evidence-out", str(target), "--force"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["mode"] == "dry-run"


def test_live_without_confirmation_refuses_before_client_or_oci(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACX_GPU_SMOKE_CONFIRM", raising=False)
    calls: list[str] = []

    def forbidden_client(**kwargs):
        calls.append(f"client:{kwargs}")
        raise AssertionError("network client must not be constructed")

    def forbidden_oci(binary: str):
        calls.append(f"oci:{binary}")
        raise AssertionError("OCI client must not be constructed")

    assert (
        smoke.main(
            ["--live", "--evidence-out", str(tmp_path / "evidence.json")],
            client_factory=forbidden_client,
            oci_factory=forbidden_oci,
        )
        == 2
    )
    assert calls == []


def test_live_rejects_placeholder_service_endpoint_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACX_GPU_SMOKE_CONFIRM", "RUN")
    monkeypatch.setenv("ACX_WP_APP_PASSWORD", "password")
    monkeypatch.setenv("ACX_DESCRIPTION_API_KEY", "api-key")
    monkeypatch.setattr(smoke.shutil, "which", lambda _: "/oci-placeholder")
    args = smoke.build_parser().parse_args(
        [
            "--live",
            "--instance-id",
            "instance-placeholder",
            "--evidence-out",
            str(tmp_path / "evidence.json"),
        ]
    )

    with pytest.raises(smoke.PreflightRefusal, match="service-base-url"):
        smoke._validate_args(args)


def test_live_rejects_placeholder_service_before_existing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "existing.json"
    target.write_text("old\n", encoding="utf-8")
    monkeypatch.setenv("ACX_GPU_SMOKE_CONFIRM", "RUN")
    args = smoke.build_parser().parse_args(
        ["--live", "--instance-id", "instance-placeholder", "--evidence-out", str(target)]
    )

    with pytest.raises(smoke.PreflightRefusal, match="service-base-url"):
        smoke._validate_args(args)


def test_live_rejects_placeholder_wordpress_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACX_GPU_SMOKE_CONFIRM", "RUN")
    args = smoke.build_parser().parse_args(
        [
            "--live",
            "--service-base-url",
            "https://description.example",
            "--instance-id",
            "instance-placeholder",
            "--evidence-out",
            str(tmp_path / "evidence.json"),
        ]
    )

    with pytest.raises(smoke.PreflightRefusal, match="wp-base-url"):
        smoke._validate_args(args)


def test_live_refuses_budget_below_composed_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACX_GPU_SMOKE_CONFIRM", "RUN")
    args = smoke.build_parser().parse_args(
        [
            "--live",
            "--max-seconds",
            str(int(smoke.MIN_COMPOSED_BUDGET_SECONDS - 1)),
            "--evidence-out",
            str(tmp_path / "evidence.json"),
        ]
    )

    with pytest.raises(smoke.PreflightRefusal, match="composed"):
        smoke._validate_args(args)


def test_subprocess_oci_error_includes_output_tails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise subprocess.CalledProcessError(
            1,
            ["oci-placeholder"],
            output="stdout-detail",
            stderr="NotAuthorizedOrNotFound",
        )

    monkeypatch.setattr(smoke.subprocess, "run", fail)

    with pytest.raises(smoke.SmokeFailure, match="NotAuthorizedOrNotFound"):
        smoke.SubprocessOci("oci-placeholder").get_instance("instance-placeholder", timeout=3)


def test_oci_error_is_preserved_in_evidence_errors(tmp_path: Path) -> None:
    class FailingOci(smoke.FakeOci):
        def get_instance(self, instance_id: str, *, timeout: float) -> dict[str, object]:
            del instance_id, timeout
            raise smoke.SmokeFailure("NotAuthorizedOrNotFound")

    result, _ = _run(tmp_path, oci=FailingOci())

    assert result.exit_code == 2
    assert any("NotAuthorizedOrNotFound" in error for error in result.evidence["errors"])


def test_make_dry_smoke_uses_configured_python() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("gpu-burst-smoke:\n", 1)[1].split("\n\n", 1)[0]

    assert "$(GPU_SMOKE_PYTHON) scripts/gpu_burst_smoke.py --dry-run" in recipe


def test_make_gpu_cost_report_target_uses_the_stdlib_reporter() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    smoke_block = makefile.split(".PHONY: gpu-burst-smoke", 1)[1].split("# FIR-5", 1)[0]

    assert "gpu-cost-report" in smoke_block
    assert "scripts/gpu_cost_report.py" in smoke_block


def test_make_check_all_covers_cost_report_lint_and_tests() -> None:
    makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    lint_block = makefile.split("lint-scripts:", 1)[1].split("\n\n", 1)[0]
    test_block = makefile.split("test-scripts:", 1)[1].split("\n\n", 1)[0]

    assert "scripts/gpu_cost_report.py" in lint_block
    assert "scripts/test_gpu_cost_report.py" in lint_block
    assert "scripts/test_gpu_cost_report.py" in test_block


def test_gpu_burst_runbook_documents_all_four_smoke_proofs() -> None:
    runbook = (Path(__file__).resolve().parents[1] / "infra" / "oci" / "GPU-BURST-PROVISIONING.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "gpu_lifecycle",
        "--expected-stop-principal",
        "second_burst_no_enqueue",
        "STOPPED→STARTING→RUNNING→STOPPING→STOPPED",
        "oci usage-api usage-summary request-summarized-usages",
        "gpu_cost_report.py",
    ):
        assert required in runbook
    assert "GPUSMOKE-1-evidence.json" not in runbook
    assert "SMOKE_EVIDENCE" in runbook


def test_missing_gpu_state_json_is_recorded_not_failed(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)

    assert result.exit_code == 0
    assert result.evidence["gpu_state_json"]["availability"] == "unavailable"


def _write_load_snapshot(directory: Path, environment: str, **value: object) -> Path:
    target = directory / environment / smoke.LOAD_SNAPSHOT_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value), encoding="utf-8")
    return target


def test_default_load_source_matches_the_published_lifecycle_layout() -> None:
    """WBUX6-W4-R-04: the documented default must resolve where the API publishes."""

    install_script = (Path(__file__).resolve().parent / "deploy" / "gpu-lifecycle-install.sh").read_text(
        encoding="utf-8"
    )
    unit_load_dirs = set(re.findall(r"--load-dir\s+(\S+)", install_script))

    assert len(unit_load_dirs) == 1, unit_load_dirs
    unit_load_dir = unit_load_dirs.pop()
    defaults = smoke.build_parser().parse_args([])

    assert unit_load_dir == smoke.DEFAULT_LOAD_DIR
    assert defaults.load_json is None
    assert smoke._load_source(defaults) == unit_load_dir


def test_explicit_load_json_overrides_the_load_dir() -> None:
    args = smoke.build_parser().parse_args(["--load-json", "/tmp/explicit-load.json"])

    assert smoke._load_source(args) == "/tmp/explicit-load.json"


def test_load_snapshot_reader_takes_the_freshest_published_environment(tmp_path: Path) -> None:
    _write_load_snapshot(tmp_path, "dev", written_at=100.0, queue_depth=0, in_flight=0)
    _write_load_snapshot(tmp_path, "prod", written_at=900.0, queue_depth=3, in_flight=1)

    snapshot = smoke._read_load_snapshot(str(tmp_path))

    assert snapshot["availability"] == "available"
    assert snapshot["value"]["queue_depth"] == 3
    assert snapshot["path"] == str(tmp_path / "prod" / smoke.LOAD_SNAPSHOT_FILENAME)
    assert str(tmp_path / "dev" / smoke.LOAD_SNAPSHOT_FILENAME) in snapshot["scanned"]


def test_load_environment_pins_the_environment_this_run_drove() -> None:
    """WBUX6-W5-04: the sensor must be able to name the stock it observes."""

    args = smoke.build_parser().parse_args(["--load-dir", "/run/acx-write", "--load-environment", "staging"])

    assert smoke._load_source(args) == f"/run/acx-write/staging/{smoke.LOAD_SNAPSHOT_FILENAME}"

    explicit = smoke.build_parser().parse_args(
        ["--load-environment", "staging", "--load-json", "/tmp/explicit-load.json"]
    )

    assert smoke._load_source(explicit) == "/tmp/explicit-load.json"


def test_multi_environment_load_snapshot_is_refused_not_attributed(tmp_path: Path) -> None:
    """WBUX6-W5-04: freshest-of-many is not evidence that THIS run drove the load.

    The smoke triggers exactly one service. On a host publishing several
    environments the freshest snapshot may belong to an environment this run
    never touched, so certifying on it would attribute another environment's
    work to this run (OBS-12). The reading must fail loudly and name the fix.
    """

    anchor = datetime.now(UTC)
    fresh = anchor.timestamp() + 1.0
    _write_load_snapshot(tmp_path, "dev", written_at=fresh, queue_depth=1, in_flight=0, batch_in_progress=False)
    _write_load_snapshot(tmp_path, "prod", written_at=fresh + 5, queue_depth=2, in_flight=0, batch_in_progress=False)

    ambiguous = smoke._read_load_snapshot(str(tmp_path))
    assert ambiguous["attribution"] == "freshest-of-many"
    observed, detail = smoke._load_snapshot_has_fresh_work(ambiguous, freshness_anchor=anchor)
    assert observed is False, detail
    assert "--load-environment" in detail

    # Pinning the environment makes the same evidence certifiable.
    pinned = smoke._read_load_snapshot(str(tmp_path / "prod" / smoke.LOAD_SNAPSHOT_FILENAME))
    pinned_observed, pinned_detail = smoke._load_snapshot_has_fresh_work(pinned, freshness_anchor=anchor)
    assert pinned_observed is True, pinned_detail

    # A host publishing exactly one environment is unambiguous by construction.
    single = tmp_path / "solo"
    _write_load_snapshot(single, "prod", written_at=fresh, queue_depth=2, in_flight=0, batch_in_progress=False)
    solo = smoke._read_load_snapshot(str(single))
    assert solo["attribution"] == "environment-pinned"
    assert smoke._load_snapshot_has_fresh_work(solo, freshness_anchor=anchor)[0] is True


def test_load_snapshot_reader_names_what_it_scanned_when_nothing_published(tmp_path: Path) -> None:
    (tmp_path / "prod").mkdir()

    snapshot = smoke._read_load_snapshot(str(tmp_path))

    assert snapshot["availability"] == "unavailable"
    assert snapshot["scanned"] == [str(tmp_path / "prod" / smoke.LOAD_SNAPSHOT_FILENAME)]


def test_partially_readable_multi_environment_snapshot_stays_ambiguous(tmp_path: Path) -> None:
    anchor = datetime.now(UTC)
    fresh = anchor.timestamp() + 1.0
    (tmp_path / "dev").mkdir()
    _write_load_snapshot(tmp_path, "prod", written_at=fresh, queue_depth=2, in_flight=0, batch_in_progress=False)

    snapshot = smoke._read_load_snapshot(str(tmp_path))

    assert snapshot["attribution"] == "freshest-of-many"
    observed, detail = smoke._load_snapshot_has_fresh_work(snapshot, freshness_anchor=anchor)
    assert observed is False, detail
    assert "--load-environment" in detail


def test_load_snapshot_reader_still_reads_an_explicit_single_file(tmp_path: Path) -> None:
    target = tmp_path / "describe-load.json"
    target.write_text(json.dumps({"written_at": 12.0}), encoding="utf-8")

    snapshot = smoke._read_load_snapshot(str(target))

    assert snapshot["availability"] == "available"
    assert snapshot["value"] == {"written_at": 12.0}
    assert smoke._read_load_snapshot(str(tmp_path / "absent.json"))["availability"] == "unavailable"


def test_evidence_records_the_load_source_it_read(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)

    assert result.evidence["load_json"]["source"] == str(tmp_path / "missing-load.json")


# A hung run is killed with SIGTERM, so SIGTERM is an exit route the compensating
# STOP has to cover. The harness runs the real CLI entry point (smoke.main) with
# an in-memory OCI machine that wedges once the instance is RUNNING, and records
# the STOP to a file the parent process reads back.
_SIGTERM_HARNESS = """
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ["ACX_SMOKE_SCRIPTS_DIR"])

import gpu_burst_smoke as smoke

record = Path(os.environ["ACX_SMOKE_STOP_RECORD"])


class StallingOci(smoke.FakeOci):
    stalled = False

    def get_instance(self, instance_id, *, timeout):
        instance = super().get_instance(instance_id, timeout=timeout)
        if instance["lifecycle-state"] == "RUNNING" and not self.stalled:
            self.stalled = True
            print("READY", flush=True)
            time.sleep(60)
        return instance

    def stop_instance(self, instance_id, *, timeout):
        super().stop_instance(instance_id, timeout=timeout)
        record.write_text(json.dumps({"stop_calls": self.stop_calls}), encoding="utf-8")


smoke.FakeOci = StallingOci
raise SystemExit(smoke.main(["--evidence-out", os.environ["ACX_SMOKE_EVIDENCE"]]))
"""


def test_sigterm_unwinds_into_the_compensating_stop(tmp_path: Path) -> None:
    harness = tmp_path / "sigterm_harness.py"
    harness.write_text(_SIGTERM_HARNESS, encoding="utf-8")
    record = tmp_path / "stop-calls.json"
    environment = {
        **os.environ,
        "ACX_SMOKE_SCRIPTS_DIR": str(Path(__file__).resolve().parent),
        "ACX_SMOKE_STOP_RECORD": str(record),
        "ACX_SMOKE_EVIDENCE": str(tmp_path / "evidence.json"),
    }
    process = subprocess.Popen(
        [sys.executable, str(harness)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        ready = process.stdout.readline()
        assert "READY" in ready, ready
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise AssertionError("SIGTERM did not terminate the run; the compensating STOP never unwound") from None
    finally:
        if process.poll() is None:  # pragma: no cover - defensive cleanup
            process.kill()

    assert record.exists(), f"no compensating STOP was issued; stderr={stderr}"
    assert json.loads(record.read_text(encoding="utf-8"))["stop_calls"] >= 1
    assert process.returncode == 128 + signal.SIGTERM, stderr
    assert "TERMINATED" in stderr
    # WBUX6-W5-03: a partial run must not leave an artifact that reads as a
    # verdict. The stderr line and the 128+signum exit are the observability
    # substitutes, and they are asserted above -- silence is not the outcome
    # here (OBS-08, engineering.md:478).
    assert not (tmp_path / "evidence.json").exists(), (
        "a signal-terminated run wrote an evidence artifact; a partial run must not "
        "produce something a reader can mistake for a verdict"
    )


# The other half of the guarantee: the process is ALREADY unwinding (a failed
# flow, a blown deadline) when the SIGTERM lands, so `terminating_signals_raise`
# is not what covers it -- the STOP loop is ordinary Python and a signal raises
# straight through it, leaving the A10 RUNNING. Here the first STOP attempt
# signals its own process before returning, and the run must still reach STOPPED.
_STOP_INTERRUPT_HARNESS = """
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, os.environ["ACX_SMOKE_SCRIPTS_DIR"])

import gpu_burst_smoke as smoke

record = Path(os.environ["ACX_SMOKE_STOP_RECORD"])


class SignallingOci(smoke.FakeOci):
    signalled = False

    def __init__(self, *args, **kwargs):
        # Leave the instance RUNNING after the reaper window so the compensating
        # STOP in run_smoke's `finally` is the thing that actually runs.
        kwargs.setdefault("reaper_states", ["RUNNING"])
        # main() supplies the normal dry gpu_state timeline to FakeOci. This
        # harness intentionally exercises the compensating STOP path instead.
        kwargs["gpu_states"] = None
        super().__init__(*args, **kwargs)

    def stop_instance(self, instance_id, *, timeout):
        if not self.signalled:
            self.signalled = True
            os.kill(os.getpid(), signal.SIGTERM)
        super().stop_instance(instance_id, timeout=timeout)
        record.write_text(
            json.dumps({"stop_calls": self.stop_calls, "state": self.current_state}), encoding="utf-8"
        )


smoke.FakeOci = SignallingOci
raise SystemExit(smoke.main(["--evidence-out", os.environ["ACX_SMOKE_EVIDENCE"], "--max-seconds", "5"]))
"""


def test_a_signal_during_the_compensating_stop_cannot_abandon_it(tmp_path: Path) -> None:
    harness = tmp_path / "stop_interrupt_harness.py"
    harness.write_text(_STOP_INTERRUPT_HARNESS, encoding="utf-8")
    record = tmp_path / "stop-calls.json"
    evidence = tmp_path / "evidence.json"
    environment = {
        **os.environ,
        "ACX_SMOKE_SCRIPTS_DIR": str(Path(__file__).resolve().parent),
        "ACX_SMOKE_STOP_RECORD": str(record),
        "ACX_SMOKE_EVIDENCE": str(evidence),
    }
    process = subprocess.Popen(
        [sys.executable, str(harness)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    try:
        stdout, stderr = process.communicate(timeout=60)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive
        process.kill()
        process.communicate()
        raise AssertionError("the masked compensating STOP hung; masking must not outlive the bounded loop") from None

    assert record.exists(), f"the compensating STOP was abandoned mid-flight; stderr={stderr}"
    assert json.loads(record.read_text(encoding="utf-8"))["stop_calls"] >= 1
    assert evidence.exists(), f"the run did not complete past the STOP; stdout={stdout} stderr={stderr}"
    written = json.loads(evidence.read_text(encoding="utf-8"))
    stopped = [check for check in written["checks"] if check["name"] == "instance_stopped_finally"]
    assert stopped and stopped[0]["passed"], written["checks"]
    assert written["measurements"]["running_seconds_ongoing"] is False


def test_terminating_signals_are_masked_only_for_the_compensation_window() -> None:
    """Masking is a bulkhead around one bounded action, not a global disposition."""

    before = signal.getsignal(signal.SIGTERM)

    with smoke.terminating_signals_deferred():
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN

    assert signal.getsignal(signal.SIGTERM) is before


def test_terminating_signal_handlers_are_scoped_and_restored() -> None:
    at_import = signal.getsignal(signal.SIGTERM)

    assert getattr(at_import, "__module__", None) != smoke.__name__

    with smoke.terminating_signals_raise():
        installed = signal.getsignal(signal.SIGTERM)
        assert getattr(installed, "__module__", None) == smoke.__name__
        assert signal.getsignal(signal.SIGHUP) is installed

    assert signal.getsignal(signal.SIGTERM) is at_import


def test_null_measurement_guard_has_red_and_green_cases() -> None:
    smoke.assert_no_null_measurement_values({"cost": 0.0, "nested": [1, 2]})
    with pytest.raises(AssertionError, match=r"measurements\.nested\[1\]"):
        smoke.assert_no_null_measurement_values({"nested": [1, None]})


def test_dry_run_records_the_first_stop_principal_and_event_time(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)

    assert result.exit_code == 0
    assert result.stop_principal == smoke.DEFAULT_STOP_PRINCIPAL
    assert result.stop_event_time == "2026-01-01T00:00:10Z"
    assert result.evidence["stop_principal"] == smoke.DEFAULT_STOP_PRINCIPAL
    assert result.evidence["stop_event_time"] == "2026-01-01T00:00:10Z"
    assert _check(result, "stop_event_observed")
    assert _check(result, "stop_principal_allowed")


def test_warm_start_budget_is_enforced_independently_of_overall_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "WARM_START_BUDGET_SECONDS", 3.0)
    oci = smoke.FakeOci(gpu_states=None, startup_states=["STARTING"] * 4)

    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 1
    assert not _check(result, "warm_start_running")
    assert not _check(result, "warm_start_budget")


def test_idle_and_reaper_budgets_are_enforced_independently_of_overall_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "IDLE_REAPER_SECONDS", 3.0)
    monkeypatch.setattr(smoke, "REAPER_BUDGET_SECONDS", 3.0)
    oci = smoke.FakeOci(
        gpu_states=None,
        reaper_states=["RUNNING"] * 4 + ["STOPPING", "STOPPED"],
    )

    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 1
    assert not _check(result, "idle_reaper_budget")
    assert _check(result, "reaper_budget")


def test_reaper_stop_convergence_has_its_own_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "IDLE_REAPER_SECONDS", 300.0)
    monkeypatch.setattr(smoke, "REAPER_BUDGET_SECONDS", 3.0)
    oci = smoke.FakeOci(
        gpu_states=None,
        reaper_states=["RUNNING", "STOPPING", "STOPPING", "STOPPED"],
    )

    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 1
    assert _check(result, "idle_reaper_budget")
    assert not _check(result, "reaper_budget")


def test_human_stop_principal_fails_the_smoke(tmp_path: Path) -> None:
    result, _ = _run(
        tmp_path,
        oci=smoke.FakeOci(stop_principal="human-console-user"),
    )

    assert result.exit_code == 1
    assert result.stop_principal == "human-console-user"
    assert not _check(result, "stop_principal_allowed")
    assert "human-console-user" in _detail(result, "stop_principal_allowed")


def test_missing_stop_audit_event_fails_the_smoke(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, oci=smoke.FakeOci(stop_events=[]))

    assert result.exit_code == 1
    assert result.stop_principal is None
    assert result.stop_event_time is None
    assert not _check(result, "stop_event_observed")
    assert "zero STOP events" in _detail(result, "stop_event_observed")


def test_stop_audit_event_outside_the_run_window_is_not_attributed(tmp_path: Path) -> None:
    stale_event = {
        "eventType": "com.oraclecloud.computeapi.instanceaction.end",
        "eventId": "stale-stop-event",
        "eventTime": "2025-12-31T23:59:59Z",
        "data": {
            "resourceId": "<burst-instance-ocid>",
            "identity": {"principalName": smoke.DEFAULT_STOP_PRINCIPAL},
            "request": {
                "id": "stale-stop-request",
                "parameters": {"action": ["StopInstance"]},
            },
        },
    }

    result, _ = _run(tmp_path, oci=smoke.FakeOci(stop_events=[stale_event]))

    assert result.exit_code == 1
    assert result.stop_principal is None
    assert result.stop_event_time is None
    assert not _check(result, "stop_event_observed")


def test_expected_stop_principal_is_repeatable_and_overrides_default() -> None:
    args = smoke.build_parser().parse_args(
        [
            "--expected-stop-principal",
            "operator-reaper",
            "--expected-stop-principal",
            "ocid1.dynamicgroup.oc1..operator-reaper",
        ]
    )

    assert args.expected_stop_principal == [
        "operator-reaper",
        "ocid1.dynamicgroup.oc1..operator-reaper",
    ]


def test_second_burst_poll_does_not_enqueue_or_create_a_new_item(tmp_path: Path) -> None:
    scenario = smoke.DryScenario()
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 0
    assert _check(result, "second_burst_no_enqueue")
    assert result.evidence["second_burst"]["new_items"] == []
    assert result.evidence["second_burst"]["enqueue_posts_during_poll"] == 0
    assert result.evidence["second_burst"]["enqueue_posts_during_replay"] == 1
    assert result.evidence["second_burst"]["idempotent_response"] is True
    assert scenario.transport_counts["enqueue_posts"] == 2


def test_second_burst_duplicate_enqueue_fixture_fails(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(duplicate_enqueue_on_second_poll=True)
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert not _check(result, "second_burst_no_enqueue")
    assert result.evidence["second_burst"]["new_items"]


def test_second_burst_replay_issues_a_second_enqueue_and_proves_idempotency(tmp_path: Path) -> None:
    scenario = smoke.DryScenario()

    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 0
    assert scenario.transport_counts["enqueue_posts"] == 2
    assert result.evidence["second_burst"]["enqueue_posts_during_replay"] == 1
    assert result.evidence["second_burst"]["idempotent_response"] is True


def test_second_burst_without_idempotent_response_fails_closed_without_transport_telemetry(
    tmp_path: Path,
) -> None:
    scenario = smoke.DryScenario()
    base_transport = smoke.make_mock_transport(scenario)
    replay_posts = 0

    def non_idempotent_replay(request: httpx.Request) -> httpx.Response:
        nonlocal replay_posts
        response = base_transport.handle_request(request)
        if request.method == "POST" and request.url.path.endswith("/describe/runs"):
            replay_posts += 1
            if replay_posts == 2:
                payload = response.json()
                payload["run_id"] = "22222222-2222-4222-8222-222222222222"
                return httpx.Response(response.status_code, json=payload)
        return response

    result, _ = _run(
        tmp_path,
        scenario=scenario,
        transport=httpx.MockTransport(non_idempotent_replay),
    )

    assert result.exit_code == 1
    assert not _check(result, "second_burst_no_enqueue")
    assert "idempotent" in _detail(result, "second_burst_no_enqueue")


def test_dry_gpu_states_use_live_transition_shape_and_fast_clock(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(
        gpu_states=[
            {"state": "stopped", "written_at": 0.0},
            {"state": "starting", "written_at": 1.0},
            {"state": "warming", "written_at": 2.0},
            {"state": "stopping", "written_at": 3.0},
            {"state": "stopped", "written_at": 4.0},
        ]
    )
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 0
    transitions = result.evidence["transitions"]
    assert [entry["state"] for entry in transitions] == [
        "STOPPED",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "STOPPED",
    ]
    assert all(set(entry) == {"state", "timestamp", "elapsed_seconds"} for entry in transitions)
    assert [entry["elapsed_seconds"] for entry in transitions] == sorted(
        entry["elapsed_seconds"] for entry in transitions
    )
    assert [entry["timestamp"] for entry in transitions] == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:02Z",
        "2026-01-01T00:00:02Z",
        "2026-01-01T00:00:04Z",
    ]


def test_run_smoke_is_decomposed_into_phase_helpers() -> None:
    tree = ast.parse(Path(smoke.__file__).read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_smoke")

    assert function.end_lineno - function.lineno + 1 <= 300


def test_cleanup_is_decomposed_into_bounded_helpers() -> None:
    tree = ast.parse(Path(smoke.__file__).read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_compensate_and_audit_stop"
    )

    assert function.end_lineno - function.lineno + 1 <= 100
