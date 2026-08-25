"""GPU-01b: bounded warm/readiness probe with stall isolation."""

from __future__ import annotations

from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController
from infra.oci.gpu_lifecycle.probe import (
    HttpReadinessProbe,
    ProbeSample,
    ProbeStatus,
    WarmReadinessWait,
)
from infra.oci.gpu_lifecycle.reaper import StaticJobLoadSource, run_start_cycle


class NeverReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.NOT_READY, detail="cold")


class AlwaysReady:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(instance_id=instance_id, status=ProbeStatus.READY)


class RecordingStartActuator:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start_instance(self, instance_id: str) -> None:
        self.started.append(instance_id)


def test_probe_timeout_fails_loudly() -> None:
    waiter = WarmReadinessWait(max_cycles=3, stall_cycles=10, sleep_seconds=0.0)
    result = waiter.wait(["ocid1.gpu"], NeverReady())

    assert result.ready == ()
    assert result.timed_out == ("ocid1.gpu",)
    assert result.exit_code == 1
    assert any("timeout" in err for err in result.errors)


class AlwaysError:
    def probe(self, instance_id: str) -> ProbeSample:
        return ProbeSample(
            instance_id=instance_id, status=ProbeStatus.ERROR, detail="boom"
        )


def test_not_ready_does_not_count_as_stall() -> None:
    """W3-D-01: NOT_READY is pending boot, not no-progress. Stall is ERROR-only."""
    waiter = WarmReadinessWait(max_cycles=5, stall_cycles=2, sleep_seconds=0.0)
    result = waiter.wait(["ocid1.gpu"], NeverReady())

    assert result.stalled == ()
    assert result.timed_out == ("ocid1.gpu",)
    assert result.exit_code == 1
    assert any("timeout" in err for err in result.errors)
    assert not any("stalled" in err for err in result.errors)


def test_error_status_still_stalls() -> None:
    waiter = WarmReadinessWait(max_cycles=5, stall_cycles=2, sleep_seconds=0.0)
    result = waiter.wait(["ocid1.gpu"], AlwaysError())

    assert result.stalled == ("ocid1.gpu",)
    assert result.timed_out == ()
    assert result.exit_code == 1
    assert any("stalled" in err for err in result.errors)


def test_default_ready_budget_covers_five_minute_boot() -> None:
    from infra.oci.gpu_lifecycle.reaper import (
        _DEFAULT_READY_MAX_CYCLES,
        _DEFAULT_READY_SLEEP_SECONDS,
    )

    assert _DEFAULT_READY_MAX_CYCLES * _DEFAULT_READY_SLEEP_SECONDS >= 300


def test_stall_detection_exit_code_is_nonzero() -> None:
    waiter = WarmReadinessWait(max_cycles=5, stall_cycles=2, sleep_seconds=0.0)
    result = waiter.wait(["ocid1.gpu"], AlwaysError())

    assert result.stalled == ("ocid1.gpu",)
    assert result.timed_out == ()
    assert result.exit_code == 1
    assert any("stalled" in err for err in result.errors)


def test_one_instance_stall_does_not_halt_others() -> None:
    class Mixed:
        def __init__(self) -> None:
            self.calls: dict[str, int] = {"ocid1.stall": 0, "ocid1.ok": 0}

        def probe(self, instance_id: str) -> ProbeSample:
            self.calls[instance_id] += 1
            if instance_id == "ocid1.ok" and self.calls[instance_id] >= 2:
                return ProbeSample(instance_id=instance_id, status=ProbeStatus.READY)
            if instance_id == "ocid1.stall":
                return ProbeSample(
                    instance_id=instance_id, status=ProbeStatus.ERROR, detail="hung"
                )
            return ProbeSample(
                instance_id=instance_id, status=ProbeStatus.NOT_READY, detail="cold"
            )

    probe = Mixed()
    waiter = WarmReadinessWait(max_cycles=5, stall_cycles=2, sleep_seconds=0.0)
    result = waiter.wait(["ocid1.stall", "ocid1.ok"], probe)

    assert result.ready == ("ocid1.ok",)
    assert result.stalled == ("ocid1.stall",)
    assert result.exit_code == 1
    assert probe.calls["ocid1.ok"] >= 2
    assert probe.calls["ocid1.stall"] >= 2


def test_probe_ready_on_first_sample_is_quiet() -> None:
    result = WarmReadinessWait(max_cycles=3, stall_cycles=2, sleep_seconds=0.0).wait(
        ["ocid1.gpu"], AlwaysReady()
    )
    assert result.ready == ("ocid1.gpu",)
    assert result.exit_code == 0
    assert result.errors == ()


def test_run_start_cycle_probe_timeout_appends_errors() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(
        instance_id="ocid1.gpu", state="STOPPED", idle_for_seconds=0
    )
    result = run_start_cycle(
        controller=controller,
        instances=[instance],
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingStartActuator(),
        probe=NeverReady(),
        readiness_wait=WarmReadinessWait(
            max_cycles=2, stall_cycles=10, sleep_seconds=0.0
        ),
    )
    assert result.actuated == [("START", "ocid1.gpu")]
    assert result.wait_result is not None
    assert result.wait_result.exit_code == 1
    assert any("timeout" in err for err in result.errors)


def test_http_probe_templates_instance_id_into_url() -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        probe = HttpReadinessProbe(
            url=f"http://127.0.0.1:{port}/ready/{{instance_id}}"
        )
        a = probe.probe("ocid1.a")
        b = probe.probe("ocid1.b")
        assert a.status == ProbeStatus.READY
        assert b.status == ProbeStatus.READY
        assert "/ready/ocid1.a" in seen
        assert "/ready/ocid1.b" in seen
    finally:
        server.shutdown()


def test_http_probe_missing_status_is_not_ready(monkeypatch) -> None:
    import urllib.request

    class NoStatus:
        def __enter__(self) -> "NoStatus":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *args, **kwargs: NoStatus()
    )
    sample = HttpReadinessProbe(url="http://example.invalid/health").probe(
        "ocid1.gpu"
    )
    assert sample.status == ProbeStatus.NOT_READY
    assert sample.instance_id == "ocid1.gpu"


def test_shared_http_probe_refuses_multi_id_wait() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instances = [
        GpuInstance(instance_id="ocid1.a", state="STOPPED", idle_for_seconds=0),
        GpuInstance(instance_id="ocid1.b", state="STOPPED", idle_for_seconds=0),
    ]
    result = run_start_cycle(
        controller=controller,
        instances=instances,
        load_source=StaticJobLoadSource(queue_depth=1, in_flight=0),
        actuator=RecordingStartActuator(),
        probe=HttpReadinessProbe(url="http://127.0.0.1:9/health"),
        readiness_wait=WarmReadinessWait(
            max_cycles=1, stall_cycles=1, sleep_seconds=0.0
        ),
    )
    assert result.wait_result is None
    assert any("multi-id" in err for err in result.errors)
