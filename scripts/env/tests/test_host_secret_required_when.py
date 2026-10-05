from __future__ import annotations

import io
from pathlib import Path

import pytest

from conftest import load_module


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_ROOT = REPO_ROOT / "config/env"


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
    assert {
        (target, env)
        for target, env, name in requirements
        if name == "ACX_GPU_ENDPOINT_API_KEY"
    } == {("svc-vm", "dev")}


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


def test_staging_materialize_succeeds_without_admin_or_gpu_host_lines(tmp_path):
    materialize = load_module("materialize")
    render = load_module("render_env")
    into = "/opt/acx-backend/staging/.env"
    fs_root = tmp_path / "fs"
    host_file = fs_root / into.lstrip("/")
    host_file.parent.mkdir(parents=True)
    host_file.write_text(
        render.HEADER_LINE
        + "\n# materialized target=svc-vm env=staging digest=test\n"
        + "POSTGRES_PASSWORD=test-placeholder\n"
        + "POSTGRES_DSN='postgresql://test.invalid/db'\n"
        + "POSTGRES_SYNC_DSN='postgresql://test.invalid/db'\n",
        encoding="utf-8",
    )
    out, err = io.StringIO(), io.StringIO()

    result = materialize.run(
        MANIFEST_ROOT,
        env="staging",
        target="svc-vm",
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
