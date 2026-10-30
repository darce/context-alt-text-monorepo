"""FIR's explicit GPU contract, without services, credentials, or inference."""

from dataclasses import replace
import io
from pathlib import Path

import pytest

from conftest import load_module


REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "config/env"
KEY = "ACX_GPU_ENDPOINT_API_KEY"
FAKE_KEY = "fixture-fir-gpu-only"


def _contract():
    manifest = load_module("manifest").load_manifest(ROOT)
    render = load_module("render_env")
    return manifest, render, render._target_vars(manifest, "svc-fir")


def _host_lines(variables):
    return {
        var.name: [f"{var.name}=fixture-host-value"]
        for var in variables if var.secret.get("fir") == "host:" and var.name != KEY
    }


def _no_resolve(*_args):
    pytest.fail("FIR host secrets must never invoke a secret resolver")


@pytest.mark.parametrize("env", [None, "fir"], ids=["example", "runtime"])
def test_fir_explicit_gpu_selection_and_private_endpoint(env):
    manifest, render, variables = _contract()
    host = _host_lines(variables) | {KEY: [f"{KEY}={FAKE_KEY}"]}
    output = render.render_target(manifest, "svc-fir", env, host_lines=host, resolve=_no_resolve)
    assignments = render.shell_assignments(output)

    assert assignments.get("ACX_DESCRIPTION_ADAPTER") == ["gpu_qwen30b"], "FIR must explicitly select GPU, never seeded/Florence fallback"
    assert assignments.get("ACX_GPU_ENDPOINT_URL") == ["http://10.0.1.9:8000"], "FIR must render the private GPU endpoint"
    assert assignments.get("ACX_GPU_ENDPOINT_ALLOWLIST") == [""], "FIR IP endpoint needs an explicit empty hostname allowlist"
    assert assignments["PGVECTOR_DIM"] == ["128"]
    assert assignments["RECOGNITION_FACE_PIPELINE_PROFILE"] == ["face_pipeline"]
    assert assignments["RECOGNITION_AUTH_ENABLED"] == ["true"]
    assert assignments["RECOGNITION_ADMIN_ENABLED"] == ["false"]
    if env is None:
        assert assignments.get(KEY) == [""], "GPU example must contain only a blank operator key slot"
        assert FAKE_KEY not in output


@pytest.mark.parametrize("value", [None, "", "''", '""'])
def test_fir_missing_or_empty_gpu_host_key_fails_closed(value):
    manifest, render, variables = _contract()
    host = _host_lines(variables)
    if value is not None:
        host[KEY] = [f"{KEY}={value}"]
    with pytest.raises(load_module("manifest").ManifestError, match=f"{KEY}: host secret unavailable"):
        render.render_target(manifest, "svc-fir", "fir", host_lines=host, resolve=_no_resolve)


def test_fir_operator_key_is_preserved_without_oci_or_vault_refs():
    manifest, render, variables = _contract()
    key = next((var for var in variables if var.name == KEY), None)
    assert key is not None, "FIR must declare its operator-managed GPU key"
    assert key.cls == "secret" and key.secret.get("fir") == "host:"
    assert key.required_when == {
        "RECOGNITION_SECRET_BACKEND": ("env",), "ACX_GPU_ENDPOINT_URL": ("*",)
    }
    assert render.host_secret_required(key, variables, "fir")
    line = f"export {KEY}='{FAKE_KEY}'"
    output = render.render_target(
        manifest, "svc-fir", "fir", host_lines=_host_lines(variables) | {KEY: [line]}, resolve=_no_resolve,
    )
    assert line in output.splitlines()
    assert render.shell_assignments(output)[KEY] == [f"'{FAKE_KEY}'"]
    assert load_module("manifest").vault_secret_map(manifest, "svc-fir", "fir") == {}

    for switch, disabled in [("ACX_GPU_ENDPOINT_URL", ""), ("RECOGNITION_SECRET_BACKEND", "oci_vault")]:
        changed = tuple(replace(var, values=dict(var.values) | {"fir": disabled}) if var.name == switch else var for var in variables)
        assert not render.host_secret_required(key, changed, "fir"), "retain the existing conditional key requirement"


@pytest.mark.parametrize("old_adapter", ["seeded", "florence_small"])
def test_materialize_fir_requires_key_then_replaces_old_adapter(tmp_path, old_adapter):
    _, render, variables = _contract()
    materialize = load_module("materialize")
    into = "/opt/acx-backend/dev-fir/.env"
    fs = tmp_path / "fs"
    path = fs / into.lstrip("/")
    path.parent.mkdir(parents=True)
    before = render.HEADER_LINE + "\n" + "\n".join(
        line for lines in _host_lines(variables).values() for line in lines
    ) + f"\nACX_DESCRIPTION_ADAPTER={old_adapter}\n"
    path.write_text(before)
    path.chmod(0o600)
    out, err = io.StringIO(), io.StringIO()
    args = dict(env="fir", target="svc-fir", into=into, fs_root=fs,
                backup_root=tmp_path / "backups", out=out, err=err)

    assert materialize.run(ROOT, **args) == 4, "missing FIR GPU key must block materialization"
    assert path.read_text() == before
    assert f"missing host key {KEY}" in err.getvalue()
    assert FAKE_KEY not in out.getvalue() + err.getvalue()

    path.write_text(before + f"{KEY}={FAKE_KEY}\n")
    assert materialize.run(ROOT, **args) == 0, err.getvalue()
    result = render.shell_assignments(path.read_text())
    assert result["ACX_DESCRIPTION_ADAPTER"] == ["gpu_qwen30b"]
    assert result["ACX_GPU_ENDPOINT_URL"] == ["http://10.0.1.9:8000"]
    assert result[KEY] == [FAKE_KEY]
    assert result["PGVECTOR_DIM"] == ["128"]
    assert materialize.run(ROOT, check=True, **args) == 0
    assert FAKE_KEY not in out.getvalue() + err.getvalue()


def test_generated_fir_example_matches_manifest():
    manifest, render, _ = _contract()
    assert render.check_example(manifest, "svc-fir", REPO) == []


@pytest.mark.parametrize("env", ["dev-auraface", "staging-auraface", "prod-auraface"])
def test_auraface_keeps_512d_and_no_fir_gpu_contract(env):
    manifest = load_module("manifest").load_manifest(ROOT)
    render = load_module("render_env")
    variables = render._target_vars(manifest, "svc-auraface")
    host = {var.name: [f"{var.name}=fixture-host-value"] for var in variables if var.secret.get(env) == "host:"}
    output = render.render_target(manifest, "svc-auraface", env, host_lines=host, resolve=_no_resolve)
    assignments = render.shell_assignments(output)
    assert assignments["PGVECTOR_DIM"] == ["512"]
    assert assignments["RECOGNITION_FACE_PIPELINE_PROFILE"] == ["auraface"]
    assert "ACX_GPU_ENDPOINT_URL" not in assignments
    assert KEY not in assignments
