from pathlib import Path

import pytest

from conftest import load_module


REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("target,environment", [("svc-vm", "dev"), ("svc-vm", "staging"), ("svc-vm", "prod"), ("demo", "demo"), ("svc-fir", "fir")])
def test_gpu_consumers_render_the_verified_ad2_endpoint(target, environment):
    manifest = load_module("manifest").load_manifest(REPO / "config/env")
    render = load_module("render_env")
    variables = render._target_vars(manifest, target)
    host_lines = {
        var.name: [f"{var.name}=fixture-secret"] for var in variables if var.secret.get(environment) == "host:"
    }

    output = render.render_target(
        manifest,
        target,
        environment,
        resolve=lambda name, _reference: f"fixture-{name}",
        host_lines=host_lines,
    )

    assert "ACX_GPU_ENDPOINT_URL=http://10.0.1.9:8000\n" in output
    assert "ACX_DESCRIPTION_ADAPTER=gpu_qwen30b\n" in output
