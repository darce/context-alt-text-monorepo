"""GPUFAIL-1: ordered multi-instance START failover on OCI capacity failure."""

from __future__ import annotations

import json
from pathlib import Path

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.reaper import (
    StaticJobLoadSource,
    _build_parser,
    run_reap_cycle,
    run_start_cycle,
)

A = "ocid1.instance.oc1.phx.a"
B = "ocid1.instance.oc1.phx.b"
C = "ocid1.instance.oc1.phx.c"


class OrderedActuator:
    def __init__(self, capacity_fail: set[str] | None = None, fail_all: bool = False) -> None:
        self.attempts: list[str] = []
        self.capacity_fail = capacity_fail or set()
        self.fail_all = fail_all

    def start_instance(self, instance_id: str) -> None:
        self.attempts.append(instance_id)
        if self.fail_all or instance_id in self.capacity_fail:
            raise RuntimeError("Out of host capacity.")


def _instances(*ids: str) -> list[GpuInstance]:
    return [GpuInstance(instance_id=i, state="STOPPED", idle_for_seconds=0) for i in ids]


def test_capacity_failover_tries_next_and_names_winner(tmp_path: Path) -> None:
    actuator = OrderedActuator(capacity_fail={A})
    gpu_state = tmp_path / "gpu-state.json"
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B, C),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        gpu_state_path=gpu_state,
    )
    assert actuator.attempts == [A, B]
    assert result.actuated == [("START", B)]
    assert result.fallbacks == ()
    snapshot = json.loads(gpu_state.read_text())
    assert snapshot["instance_id"] == B
    assert snapshot["state"] == "starting"


def test_all_capacity_fail_emits_fallback() -> None:
    actuator = OrderedActuator(fail_all=True)
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert actuator.attempts == [A, B]
    assert result.actuated == []
    assert result.fallbacks
    assert all(f.reason == "start_failed" for f in result.fallbacks)


def test_first_success_short_circuits() -> None:
    actuator = OrderedActuator()
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B, C),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert actuator.attempts == [A]
    assert result.actuated == [("START", A)]
    assert result.fallbacks == ()


def test_parser_accepts_multiple_instance_ids() -> None:
    args = _build_parser().parse_args(
        ["--instance-id", A, "--instance-id", B, "--queue-depth", "1", "--in-flight", "0"]
    )
    assert args.instance_ids == [A, B]


def test_reap_all_running_idle_instances() -> None:
    class Stopper:
        def __init__(self) -> None:
            self.stopped: list[str] = []

        def stop_instance(self, instance_id: str) -> None:
            self.stopped.append(instance_id)
            return None

    stopper = Stopper()
    instances = [
        GpuInstance(instance_id=A, state="RUNNING", idle_for_seconds=999),
        GpuInstance(instance_id=B, state="RUNNING", idle_for_seconds=999),
    ]
    result = run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=0, in_flight=0),
        actuator=stopper,  # type: ignore[arg-type]
        fence_delay_seconds=0.0,
    )
    assert sorted(stopper.stopped) == sorted([A, B])
    assert sorted(i for _, i in result.actuated) == sorted([A, B])


def test_parser_accepts_instance_ids_plural_and_comma_forms() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--instance-ids", f"{A},{B}", "--queue-depth", "1", "--in-flight", "0"])
    assert args.instance_ids == [A, B]
    args = parser.parse_args(["--instance-id", f"{A},{B}", "--queue-depth", "1", "--in-flight", "0"])
    assert args.instance_ids == [A, B]
    args = parser.parse_args(
        ["--instance-id", A, "--instance-ids", B, "--instance-id", A, "--queue-depth", "1", "--in-flight", "0"]
    )
    assert args.instance_ids == [A, B]


def test_subprocess_stderr_capacity_failover_and_tracking() -> None:
    import subprocess

    class SubprocessActuator:
        def __init__(self) -> None:
            self.attempts: list[str] = []

        def start_instance(self, instance_id: str) -> None:
            self.attempts.append(instance_id)
            if instance_id == A:
                raise subprocess.CalledProcessError(1, ["oci"], stderr=b"Error: Out of host capacity.")

    actuator = SubprocessActuator()
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert actuator.attempts == [A, B]
    assert result.actuated == [("START", B)]
    assert result.capacity_failed == (A,)
    assert result.fallbacks == ()


def test_all_capacity_fail_records_capacity_failed() -> None:
    actuator = OrderedActuator(fail_all=True)
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
    )
    assert result.capacity_failed == (A, B)


def test_installer_supports_plural_instance_ids_backward_compatible() -> None:
    repo = Path(__file__).resolve().parents[4]
    script = (repo / "scripts/deploy/gpu-lifecycle-install.sh").read_text()
    assert "GPU_INSTANCE_IDS" in script
    assert "--instance-ids" in script
    assert "GPU_INSTANCE_ID" in script  # legacy singular env/flag retained


# --- Winner-aware routing and per-candidate readiness (AD2 first) ---

AD2_URL = "http://10.0.1.9:8000"
AD3_URL = "http://10.0.2.7:8000"
ENDPOINTS = {A: AD2_URL, B: AD3_URL}


class RecordingUrlopen:
    """Answer 200 for ready hosts; record every probed URL."""

    def __init__(self, ready: set[str]) -> None:
        self.urls: list[str] = []
        self.ready = ready

    def __call__(self, url: str, timeout: float = 0.0):
        import urllib.error

        self.urls.append(url)
        if not any(url.startswith(host) for host in self.ready):
            raise urllib.error.URLError("connection refused")

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        return _Resp()


def test_active_winner_blocks_starting_another_candidate() -> None:
    for winner_state in ("RUNNING", "STARTING"):
        actuator = OrderedActuator()
        result = run_start_cycle(
            controller=GpuLifecycleController(idle_seconds=60),
            instances=[
                GpuInstance(instance_id=A, state="STOPPED", idle_for_seconds=0),
                GpuInstance(instance_id=B, state=winner_state, idle_for_seconds=0),
            ],
            load_source=StaticJobLoadSource(queue_depth=3, in_flight=1),
            actuator=actuator,
        )
        assert actuator.attempts == [], winner_state
        assert result.actuated == []
        assert result.decided == []


def test_start_failover_publishes_winner_endpoint(tmp_path: Path) -> None:
    gpu_state = tmp_path / "gpu-state.json"
    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=OrderedActuator(capacity_fail={A}),
        gpu_state_path=gpu_state,
        candidate_endpoints=ENDPOINTS,
    )
    snapshot = json.loads(gpu_state.read_text())
    assert snapshot["instance_id"] == B
    assert snapshot["endpoint_url"] == AD3_URL


def test_ad2_first_success_publishes_ad2_endpoint(tmp_path: Path) -> None:
    gpu_state = tmp_path / "gpu-state.json"
    actuator = OrderedActuator()
    run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=actuator,
        gpu_state_path=gpu_state,
        candidate_endpoints=ENDPOINTS,
    )
    assert actuator.attempts == [A]
    assert json.loads(gpu_state.read_text())["endpoint_url"] == AD2_URL


def test_per_candidate_probe_waits_on_winner_endpoint_only(tmp_path: Path, monkeypatch) -> None:
    import urllib.request

    from infra.oci.gpu_lifecycle.probe import CandidateEndpointProbe, WarmReadinessWait

    opener = RecordingUrlopen(ready={AD3_URL})
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    gpu_state = tmp_path / "gpu-state.json"
    result = run_start_cycle(
        controller=GpuLifecycleController(idle_seconds=60),
        instances=_instances(A, B),
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=OrderedActuator(capacity_fail={A}),
        probe=CandidateEndpointProbe(ENDPOINTS),
        readiness_wait=WarmReadinessWait(max_cycles=2, stall_cycles=2),
        gpu_state_path=gpu_state,
        candidate_endpoints=ENDPOINTS,
    )
    assert result.capacity_failed == (A,)
    assert result.wait_result is not None and result.wait_result.ready == (B,)
    assert opener.urls == [f"{AD3_URL}/health"]
    snapshot = json.loads(gpu_state.read_text())
    assert (snapshot["state"], snapshot["instance_id"], snapshot["endpoint_url"]) == ("ready", B, AD3_URL)


def test_candidate_probe_without_endpoint_is_error_not_ready() -> None:
    from infra.oci.gpu_lifecycle.probe import CandidateEndpointProbe, ProbeStatus

    sample = CandidateEndpointProbe({A: AD2_URL}).probe(C)
    assert sample.status is ProbeStatus.ERROR
    assert "no candidate endpoint" in sample.detail


def test_reap_keeps_running_winner_identity_and_ready(tmp_path: Path, monkeypatch) -> None:
    import urllib.request

    from infra.oci.gpu_lifecycle.probe import CandidateEndpointProbe
    from infra.oci.gpu_lifecycle.state_snapshot import write_gpu_state_snapshot

    class NoStop:
        def stop_instance(self, instance_id: str) -> None:
            raise AssertionError(f"unexpected STOP {instance_id}")

    monkeypatch.setattr(urllib.request, "urlopen", RecordingUrlopen(ready={AD3_URL}))
    gpu_state = tmp_path / "gpu-state.json"
    write_gpu_state_snapshot("ready", instance_id=B, path=gpu_state, endpoint_url=AD3_URL)
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=600),
        instances=[
            GpuInstance(instance_id=A, state="STOPPED", idle_for_seconds=0),
            GpuInstance(instance_id=B, state="RUNNING", idle_for_seconds=5),
        ],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=NoStop(),  # type: ignore[arg-type]
        probe=CandidateEndpointProbe(ENDPOINTS),
        fence_delay_seconds=0.0,
        gpu_state_path=gpu_state,
        candidate_endpoints=ENDPOINTS,
    )
    snapshot = json.loads(gpu_state.read_text())
    assert (snapshot["state"], snapshot["instance_id"], snapshot["endpoint_url"]) == ("ready", B, AD3_URL)


def test_ambiguous_candidates_publish_no_winner(tmp_path: Path) -> None:
    gpu_state = tmp_path / "gpu-state.json"
    run_reap_cycle(
        controller=GpuLifecycleController(idle_seconds=600),
        instances=[
            GpuInstance(instance_id=A, state="RUNNING", idle_for_seconds=5),
            GpuInstance(instance_id=B, state="RUNNING", idle_for_seconds=5),
        ],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=OrderedActuator(),  # type: ignore[arg-type]
        fence_delay_seconds=0.0,
        gpu_state_path=gpu_state,
        candidate_endpoints=ENDPOINTS,
    )
    snapshot = json.loads(gpu_state.read_text())
    assert snapshot["instance_id"] is None
    assert "endpoint_url" not in snapshot


def test_parser_reads_ordered_candidate_endpoints() -> None:
    args = _build_parser().parse_args(
        [
            "--instance-ids", f"{A},{B}",
            "--candidate-endpoint", f"{A}={AD2_URL}",
            "--candidate-endpoint", f"{B}={AD3_URL}/",
            "--queue-depth", "1", "--in-flight", "0",
        ]
    )
    assert args.candidate_endpoints == {A: AD2_URL, B: AD3_URL}


def test_parser_rejects_unsafe_or_unknown_candidate_endpoints(capsys) -> None:
    import pytest

    base = ["--instance-ids", f"{A},{B}", "--queue-depth", "1", "--in-flight", "0"]
    good_b = ["--candidate-endpoint", f"{B}={AD3_URL}"]
    _build_parser().parse_args([*base, *good_b, "--candidate-endpoint", f"{A}={AD2_URL}"])
    bad_a = [
        "ftp://10.0.1.9:8000",
        "http://8.8.8.8:8000",
        "http://127.0.0.1:8000",
        "http://user@10.0.1.9:8000",
        "http://10.0.1.9:8000/v1",
        "http://10.0.1.9:99999",
        "",
    ]
    for url in bad_a:
        with pytest.raises(SystemExit):
            _build_parser().parse_args([*base, *good_b, "--candidate-endpoint", f"{A}={url}"])
    rejected = [
        [*good_b, "--candidate-endpoint", f"{C}={AD2_URL}"],  # not a configured candidate
        good_b,  # A has no endpoint
        [*good_b, "--candidate-endpoint", f"{B}={AD2_URL}", "--candidate-endpoint", f"{A}={AD2_URL}"],
        [*good_b, "--candidate-endpoint", f"{A}={AD2_URL}", "--ready-url", f"{AD2_URL}/health"],
    ]
    for extra in rejected:
        with pytest.raises(SystemExit):
            _build_parser().parse_args([*base, *extra])
    capsys.readouterr()


def test_every_service_env_routes_burst_gpu_to_ad2() -> None:
    import tomllib

    repo = Path(__file__).resolve().parents[4]
    manifest = tomllib.loads((repo / "config/env/manifest.d/10-service-shared.toml").read_text())
    by_name = {var["name"]: var for var in manifest["var"]}
    for env in ("dev", "staging", "prod", "demo"):
        assert by_name["ACX_GPU_ENDPOINT_URL"]["values"][env] == AD2_URL, env
        assert by_name["ACX_DESCRIPTION_ADAPTER"]["values"][env] == "gpu_qwen30b", env
    example = (repo / "apps/prototype-description-service/.env.prod.example").read_text()
    assert "florence_small applies to staging" not in example
