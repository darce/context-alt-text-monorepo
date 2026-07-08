from infra.oci.gpu_lifecycle.controller import GpuInstance, GpuLifecycleController


def test_idle_reaper_stops_running_instance_when_queue_drained() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.instance.oc1..gpu", state="RUNNING", idle_for_seconds=90)

    actions = controller.reap_idle_instances([instance], queue_depth=0, in_flight=0)

    assert actions == [("STOP", "ocid1.instance.oc1..gpu")]


def test_idle_reaper_does_not_stop_with_in_flight_work() -> None:
    controller = GpuLifecycleController(idle_seconds=60)
    instance = GpuInstance(instance_id="ocid1.instance.oc1..gpu", state="RUNNING", idle_for_seconds=90)

    assert controller.reap_idle_instances([instance], queue_depth=0, in_flight=1) == []
