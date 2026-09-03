"""Red/green contract tests for the offline GPU burst smoke proof."""

from __future__ import annotations

import subprocess
from pathlib import Path

import gpu_burst_smoke as smoke
import httpx
import pytest

FIXTURE_DENYLIST = (
    Path(__file__).resolve().parent / "deploy" / "lib" / "fixture-denylist.sh"
)


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
    extra: tuple[str, ...] = (),
) -> tuple[smoke.SmokeResult, smoke.FakeOci]:
    scenario = scenario or smoke.DryScenario()
    fake_oci = oci or smoke.FakeOci()
    clock = smoke.FastClock()
    client = httpx.Client(
        transport=smoke.make_mock_transport(scenario), follow_redirects=False
    )
    try:
        result = smoke.run_smoke(
            _args(tmp_path, *extra),
            client=client,
            oci=fake_oci,
            app_password=app_password,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            now=clock.now,
        )
    finally:
        client.close()
    return result, fake_oci


def _check(result: smoke.SmokeResult, name: str) -> bool:
    matches = [check for check in result.evidence["checks"] if check["name"] == name]
    assert len(matches) == 1, (name, result.evidence["checks"])
    return bool(matches[0]["passed"])


def _detail(result: smoke.SmokeResult, name: str) -> str:
    return next(
        check["detail"] for check in result.evidence["checks"] if check["name"] == name
    )


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
def test_fixture_denylist_python_matches_canonical_bash(
    sample: str, expected: bool
) -> None:
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
    assert oci.stop_calls == 1
    assert [entry["state"] for entry in result.evidence["transitions"]] == [
        "STOPPED",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "STOPPED",
        "STOPPING",
        "STOPPED",
    ]
    assert result.evidence["item_timeline"] == [
        {"elapsed_seconds": 0.0, "media_id": 101, "status": "queued", "tier": None},
        {"elapsed_seconds": 2.0, "media_id": 101, "status": "queued", "tier": None},
        {"elapsed_seconds": 2.0, "media_id": 101, "status": "running", "tier": None},
        {
            "elapsed_seconds": 4.0,
            "media_id": 101,
            "status": "completed",
            "tier": "final_gpu",
        },
    ]
    assert result.evidence["item_provenance"] == [
        {
            "media_id": 101,
            "tier": "final_gpu",
            "model_id": smoke.EXPECTED_MODEL_ID,
            "revision": smoke.EXPECTED_REVISION,
        }
    ]
    assert result.evidence["cost_estimate_usd"] > 0
    assert result.evidence["cost_estimate_ongoing"] is False
    assert (tmp_path / "evidence.json").is_file()


def test_application_password_is_absent_from_output_and_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    password = "unique-wp-application-password"

    result, _ = _run(tmp_path, app_password=password)
    captured = capsys.readouterr()

    assert result.exit_code == 0
    assert password not in captured.out
    assert password not in captured.err
    assert password not in (tmp_path / "evidence.json").read_text(encoding="utf-8")


def test_red_tier_provisional_cpu(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, scenario=smoke.DryScenario(tier="provisional_cpu"))

    assert result.exit_code == 1
    assert not _check(result, "tier_final_gpu")


def test_red_missing_one_of_two_requested_media_items(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, extra=("--media-ids", "101,102"))

    assert result.exit_code == 1
    assert not _check(result, "returned_media_ids_exact")
    assert "102" in _detail(result, "returned_media_ids_exact")


def test_red_completed_with_errors_is_not_success(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(run_statuses=["running", "completed_with_errors"])
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert not _check(result, "run_terminal_success")
    assert _detail(result, "run_terminal_success") == "completed_with_errors"


def test_red_requested_item_final_status_is_not_completed(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(
        item_statuses=["queued", "queued", "running", "failed"]
    )
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


def test_red_provisional_cpu_observed_mid_run(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(
        item_tiers=[None, None, "provisional_cpu", "final_gpu"]
    )
    result, _ = _run(tmp_path, scenario=scenario)

    assert result.exit_code == 1
    assert not _check(result, "no_provisional_or_degraded_items")
    assert "101" in _detail(result, "no_provisional_or_degraded_items")


def test_red_health_adapter_preflight_refuses(tmp_path: Path) -> None:
    result, oci = _run(tmp_path, scenario=smoke.DryScenario(health_adapter="seeded"))

    assert result.exit_code == 2
    assert not _check(result, "health_adapter_gpu_qwen30b")
    assert oci.stop_calls == 1


def test_red_initial_instance_not_stopped_preflight_refuses(tmp_path: Path) -> None:
    result, oci = _run(tmp_path, oci=smoke.FakeOci(current_state="RUNNING"))

    assert result.exit_code == 2
    assert not _check(result, "initial_instance_stopped")
    assert oci.stop_calls == 1


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
        verdict
        for verdict in result.evidence["denylist_verdicts"]
        if verdict["field"] == "alt_text_draft"
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


def test_red_second_start_transition_breaks_idempotence(tmp_path: Path) -> None:
    oci = smoke.FakeOci(
        startup_states=["STARTING", "RUNNING"],
        reaper_states=["STARTING", "RUNNING", "STOPPING", "STOPPED"],
    )
    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 1
    assert not _check(result, "exactly_one_start_transition")


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
        "display-name": "acx-gpu-burst-orphan",
        "lifecycle-state": "RUNNING",
        "freeform-tags": {"role": "gpu-burst"},
    }
    result, _ = _run(tmp_path, oci=smoke.FakeOci(orphan_instances=[orphan]))

    assert result.exit_code == 1
    assert not _check(result, "no_orphan_running")


def test_red_deadline_still_issues_stop(tmp_path: Path) -> None:
    scenario = smoke.DryScenario(run_statuses=["running"])
    result, oci = _run(tmp_path, scenario=scenario, extra=("--max-seconds", "3"))

    assert result.exit_code == 1
    assert not _check(result, "deadline")
    assert oci.stop_calls == 1


def test_red_failed_stop_command_is_reported(tmp_path: Path) -> None:
    class StopFailingOci(smoke.FakeOci):
        def stop_instance(self, instance_id: str, *, timeout: float) -> None:
            self.stop_calls += 1
            raise smoke.SmokeFailure("injected STOP failure")

    result, oci = _run(tmp_path, oci=StopFailingOci())

    assert result.exit_code == 1
    assert oci.stop_calls == 1
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
    oci = smoke.FakeOci(stop_states=["STOPPING"])
    result, _ = _run(tmp_path, oci=oci)

    assert result.exit_code == 1
    assert not _check(result, "instance_stopped_finally")
    assert "STOPPING" in _detail(result, "instance_stopped_finally")


def test_live_without_confirmation_refuses_before_client_or_oci(
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
            ["--live"], client_factory=forbidden_client, oci_factory=forbidden_oci
        )
        == 2
    )
    assert calls == []


def test_missing_gpu_state_json_is_recorded_not_failed(tmp_path: Path) -> None:
    result, _ = _run(tmp_path)

    assert result.exit_code == 0
    assert result.evidence["gpu_state_json"]["availability"] == "unavailable"


def test_null_measurement_guard_has_red_and_green_cases() -> None:
    smoke.assert_no_null_measurement_values({"cost": 0.0, "nested": [1, 2]})
    with pytest.raises(AssertionError, match=r"measurements\.nested\[1\]"):
        smoke.assert_no_null_measurement_values({"nested": [1, None]})
