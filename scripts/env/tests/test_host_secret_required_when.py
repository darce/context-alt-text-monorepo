from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from conftest import load_module

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_ROOT = REPO_ROOT / "config/env"
GPU_OCID = "ocid1.vaultsecret.oc1.iad." + "g" * 60
PG_OCID = "ocid1.vaultsecret.oc1.iad." + "p" * 60
ADMIN_OCID = "ocid1.vaultsecret.oc1.iad." + "a" * 60


def _gpu_manifest(write_manifest, *, minted):
    """Pin consumer switches and fake refs independently of the live mint state."""
    return write_manifest(
        """
        version = 1
        [targets.vm]
        audience = "backend"
        envs = ["dev", "staging", "prod"]
        remote_paths = { dev = "/opt/acx-backend/dev/.env", staging = "/opt/acx-backend/staging/.env", prod = "/opt/acx-backend/prod/.env" }
        sections = ["S"]
        """,
        **{
            "10-consumers": f'''
                version = 1
                [[var]]
                name = "RECOGNITION_SECRET_BACKEND"
                class = "config"
                targets = ["vm"]
                section = "S"
                example = "env"
                values = {{ dev = "env", staging = "env", prod = "oci_vault" }}

                [[var]]
                name = "RECOGNITION_ADMIN_ENABLED"
                class = "config"
                targets = ["vm"]
                section = "S"
                example = "false"
                values = {{ dev = "false", staging = "false", prod = "true" }}

                [[var]]
                name = "ACX_GPU_ENDPOINT_URL"
                class = "config"
                targets = ["vm"]
                section = "S"
                example = ""
                values = {{ dev = "https://gpu.example.invalid", staging = "", prod = "https://gpu.example.invalid" }}

                [[var]]
                name = "RECOGNITION_VAULT_SECRET_MAP"
                class = "config"
                targets = ["vm"]
                section = "S"
                example = "{{}}"
                derive_vault_map = true

                [[var]]
                name = "PGPASSWORD"
                class = "secret"
                targets = ["vm"]
                section = "S"
                example = ""
                required = false
                secret = {{ dev = "host:", staging = "host:", prod = "vault:{PG_OCID}" }}

                [[var]]
                name = "RECOGNITION_ADMIN_TOKEN"
                class = "secret"
                targets = ["vm"]
                section = "S"
                example = ""
                required_when = {{ RECOGNITION_SECRET_BACKEND = ["env"], RECOGNITION_ADMIN_ENABLED = ["true", "1", "yes", "on"] }}
                secret = {{ dev = "host:", staging = "host:", prod = "vault:{ADMIN_OCID}" }}

                [[var]]
                name = "ACX_GPU_ENDPOINT_API_KEY"
                class = "secret"
                targets = ["vm"]
                section = "S"
                example = ""
                required_when = {{ RECOGNITION_SECRET_BACKEND = ["env"], ACX_GPU_ENDPOINT_URL = ["*"] }}
                secret = {{ dev = "{"oci:" + GPU_OCID if minted else "host:"}", staging = "host:", prod = "{"vault:" + GPU_OCID if minted else "host:"}" }}
            ''',
            "20-postgres": "version = 1\n"
            + "\n".join(
                f'''
                [[var]]
                name = "{name}"
                class = "secret"
                targets = ["vm"]
                section = "S"
                example = ""
                secret = {{ dev = "host:", staging = "host:", prod = "host:" }}
                '''
                for name in ("POSTGRES_PASSWORD", "POSTGRES_DSN", "POSTGRES_SYNC_DSN")
            ),
        },
    )


def _repo_host_requirements():
    manifest = load_module("manifest").load_manifest(MANIFEST_ROOT)
    render = load_module("render_env")
    requirements = set()
    for target_name in ("svc-vm", "svc-fir"):
        target = manifest.targets[target_name]
        for env in target.envs:
            variables = render._target_vars(manifest, target_name)
            requirements.update(
                (target_name, env, var.name)
                for var in variables
                if var.secret.get(env) == "host:"
                and render.host_secret_required(var, variables, env)
            )
    return requirements


def test_repo_host_secrets_are_required_only_when_consumers_read_them():
    requirements = _repo_host_requirements()

    assert not any(name == "RECOGNITION_ADMIN_TOKEN" for _, _, name in requirements)
    assert {(target, env) for target, env, name in requirements if name == "ACX_GPU_ENDPOINT_API_KEY"} == set()
    # The source now records the minted refs; staging still has an unused HOST key.
    manifest = load_module("manifest").load_manifest(MANIFEST_ROOT)
    gpu = next(var for var in manifest.vars if var.name == "ACX_GPU_ENDPOINT_API_KEY")
    assert {env: ref.partition(":")[0] for env, ref in gpu.secret.items()} == {
        "dev": "oci",
        "staging": "host",
        "prod": "vault",
    }


@pytest.mark.parametrize("minted", [False, True], ids=["unminted", "minted"])
@pytest.mark.parametrize("env", ["dev", "staging", "prod"])
def test_gpu_host_requirement_tracks_source_and_consumer(write_manifest, minted, env):
    manifest_module = load_module("manifest")
    render = load_module("render_env")
    manifest = manifest_module.load_manifest(_gpu_manifest(write_manifest, minted=minted))
    variables = render._target_vars(manifest, "vm")
    postgres_names = {"POSTGRES_PASSWORD", "POSTGRES_DSN", "POSTGRES_SYNC_DSN"}
    host_required = {
        var.name
        for var in variables
        if var.secret.get(env) == "host:" and render.host_secret_required(var, variables, env)
    }
    gpu_required = not minted and env == "dev"
    assert host_required == postgres_names | ({"ACX_GPU_ENDPOINT_API_KEY"} if gpu_required else set())

    calls = []

    def resolve(name, ref):
        # No OCI process, operator credentials, or secret bytes are used.
        assert (name, ref) == ("ACX_GPU_ENDPOINT_API_KEY", f"oci:{GPU_OCID}")
        calls.append((name, ref))
        return "test-placeholder"

    host_lines = {name: [f"{name}=test-placeholder"] for name in postgres_names}
    if gpu_required:
        with pytest.raises(manifest_module.ManifestError, match="ACX_GPU_ENDPOINT_API_KEY: host secret unavailable"):
            render.render_target(manifest, "vm", env, host_lines=host_lines, resolve=resolve)
        host_lines["ACX_GPU_ENDPOINT_API_KEY"] = ["ACX_GPU_ENDPOINT_API_KEY=test-placeholder"]

    rendered = render.render_target(manifest, "vm", env, host_lines=host_lines, resolve=resolve)
    assignments = render.shell_assignments(rendered)
    assert calls == ([("ACX_GPU_ENDPOINT_API_KEY", f"oci:{GPU_OCID}")] if minted and env == "dev" else [])
    if env == "dev":
        assert assignments["ACX_GPU_ENDPOINT_API_KEY"] == ["test-placeholder"]
    elif minted and env == "prod":
        assert assignments["ACX_GPU_ENDPOINT_API_KEY"] == [""]
    else:
        assert "ACX_GPU_ENDPOINT_API_KEY" not in assignments
    if env == "prod":
        expected_map = {"PGPASSWORD": PG_OCID, "RECOGNITION_ADMIN_TOKEN": ADMIN_OCID}
        if minted:
            expected_map["ACX_GPU_ENDPOINT_API_KEY"] = GPU_OCID
        assert json.loads(assignments["RECOGNITION_VAULT_SECRET_MAP"][0]) == expected_map
    else:
        assert "RECOGNITION_ADMIN_TOKEN" not in assignments


def test_admin_token_is_required_when_backend_and_admin_flag_enable_it(write_manifest):
    manifest_module = load_module("manifest")
    render = load_module("render_env")
    root = write_manifest(
        '''
        version = 1
        [targets.vm]
        audience = "backend"
        envs = ["dev"]
        remote_paths = { dev = "/opt/acx-backend/dev/.env" }
        sections = ["S"]
        ''',
        **{
            "10-required-when": '''
                version = 1
                [[var]]
                name = "RECOGNITION_SECRET_BACKEND"
                class = "config"
                targets = ["vm"]
                section = "S"
                example = "env"
                required = false
                values = { dev = "env" }

                [[var]]
                name = "RECOGNITION_ADMIN_ENABLED"
                class = "config"
                targets = ["vm"]
                section = "S"
                example = "false"
                values = { dev = "true" }

                [[var]]
                name = "RECOGNITION_ADMIN_TOKEN"
                class = "secret"
                targets = ["vm"]
                section = "S"
                example = ""
                required = true
                required_when = { RECOGNITION_SECRET_BACKEND = ["env"], RECOGNITION_ADMIN_ENABLED = ["true", "1", "yes", "on"] }
                secret = { dev = "host:" }
            '''
        },
    )
    manifest = manifest_module.load_manifest(root)
    variables = render._target_vars(manifest, "vm")
    token = next(var for var in variables if var.name == "RECOGNITION_ADMIN_TOKEN")

    assert render.host_secret_required(token, variables, "dev")


@pytest.mark.parametrize("minted", [False, True], ids=["unminted", "minted"])
def test_staging_materialize_succeeds_without_admin_or_gpu_host_lines(tmp_path, write_manifest, minted):
    materialize = load_module("materialize")
    render = load_module("render_env")
    into = "/opt/acx-backend/staging/.env"
    fs_root = tmp_path / "fs"
    host_file = fs_root / into.lstrip("/")
    host_file.parent.mkdir(parents=True)
    host_file.write_text(
        render.HEADER_LINE
        + "\n# materialized target=vm env=staging digest=test\n"
        + "POSTGRES_PASSWORD=test-placeholder\n"
        + "POSTGRES_DSN='postgresql://test.invalid/db'\n"
        + "POSTGRES_SYNC_DSN='postgresql://test.invalid/db'\n",
        encoding="utf-8",
    )
    out, err = io.StringIO(), io.StringIO()

    result = materialize.run(
        _gpu_manifest(write_manifest, minted=minted),
        env="staging",
        target="vm",
        into=into,
        check=False,
        fs_root=fs_root,
        backup_root=tmp_path / "backups",
        out=out,
        err=err,
    )

    assert result == 0, err.getvalue()
    assignments = render.shell_assignments(host_file.read_text(encoding="utf-8"))
    assert "RECOGNITION_ADMIN_TOKEN" not in assignments
    assert "ACX_GPU_ENDPOINT_API_KEY" not in assignments


_CONDITION_TARGETS = '''
    version = 1
    [targets.vm]
    audience = "backend"
    envs = ["dev"]
    remote_paths = { dev = "/opt/acx-backend/dev/.env" }
    sections = ["S"]

    [targets.other]
    audience = "backend"
    envs = ["dev"]
    sections = ["S"]
'''


def _condition_manifest(write_manifest, condition: str, switch_class="config", switch_targets='["vm"]'):
    switch = "" if switch_class is None else f'''
        [[var]]
        name = "SWITCH"
        class = "{switch_class}"
        targets = {switch_targets}
        section = "S"
        example = "on"
        values = {{ dev = "on" }}
    '''
    return write_manifest(
        _CONDITION_TARGETS,
        **{
            "10-condition": f'''
                version = 1
                [[var]]
                name = "TOKEN"
                class = "secret"
                targets = ["vm"]
                section = "S"
                example = ""
                required_when = {condition}
                secret = {{ dev = "host:" }}
                {switch}
            '''
        },
    )


@pytest.mark.parametrize(
    ("condition", "switch_class", "switch_targets", "needle"),
    [
        pytest.param(
            '{ UNKNOWN = ["on"] }',
            "config",
            '["vm"]',
            "references unknown var",
            id="unknown-var",
        ),
        pytest.param('{ SWITCH = ["on"] }', "public", '["vm"]', "config", id="non-config-var"),
        pytest.param('{ SWITCH = ["on"] }', "config", '["other"]', "target", id="not-on-target"),
        pytest.param('{ SWITCH = [] }', "config", '["vm"]', "empty", id="empty-values"),
        pytest.param('{ SWITCH = [1] }', "config", '["vm"]', "string", id="non-string-value"),
    ],
)
def test_invalid_required_when_references_fail_manifest_load(
    write_manifest, condition, switch_class, switch_targets, needle
):
    root = _condition_manifest(write_manifest, condition, switch_class, switch_targets)

    with pytest.raises(load_module("manifest").ManifestError, match="TOKEN") as error:
        load_module("manifest").load_manifest(root)

    assert needle in str(error.value).lower()
