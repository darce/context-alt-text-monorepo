"""Installer entrypoints share the source/digest/lease/recovery transaction."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def installers(tmp_path):
    deploy = tmp_path / "scripts/deploy"
    service = tmp_path / "apps/prototype-description-service/scripts"
    deploy.mkdir(parents=True)
    service.mkdir(parents=True)
    shutil.copy(ROOT / "scripts/deploy/sync-compose.sh", deploy)
    shutil.copy(ROOT / "apps/prototype-description-service/scripts/deploy-env.sh", service)
    canonical = deploy / "recognition-service.sh"
    canonical.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" >"$ENTRY_RECORD"\nprintf "%s %s %s\\n" "${OCI_USER:-}" "${OCI_HOST:-}" "${CONFIRM:-}" >>"$ENTRY_RECORD"\nexit "${ENTRY_EXIT:-0}"\n'
    )
    record = tmp_path / "entry.log"
    binary = tmp_path / "bin"
    binary.mkdir()
    for name in ("ssh", "scp", "docker"):
        command = binary / name
        command.write_text('#!/bin/sh\necho forbidden >>"$EXTERNAL_RECORD"\nexit 97\n')
        command.chmod(0o755)
    env = dict(
        os.environ,
        PATH=f"{binary}:{os.environ['PATH']}",
        ENTRY_RECORD=str(record),
        EXTERNAL_RECORD=str(tmp_path / "external.log"),
    )
    return deploy, service, record, env


@pytest.mark.parametrize(
    "env", ["dev", "dev-fir", "staging", "prod", "dev-auraface", "staging-auraface", "prod-auraface"]
)
def test_installer_uses_canonical_selected_env_ship(installers, env):
    deploy, service, record, variables = installers
    variables = dict(variables, CONFIRM="PROMOTE", ENTRY_EXIT="19")
    result = subprocess.run(
        ["bash", str(service / "deploy-env.sh"), env, "fixture@vm.invalid"],
        env=variables,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 19, result.stdout + result.stderr
    assert record.read_text().splitlines() == ["deploy", env, "fixture vm.invalid PROMOTE"]
    assert not Path(variables["EXTERNAL_RECORD"]).exists()


@pytest.mark.parametrize("env", ["prod", "prod-auraface"])
def test_installer_production_guard_precedes_even_dispatch(installers, env):
    _, service, record, variables = installers
    variables = dict(variables, CONFIRM="")
    result = subprocess.run(
        ["bash", str(service / "deploy-env.sh"), env], env=variables, text=True, capture_output=True, timeout=10
    )
    assert result.returncode != 0
    assert "CONFIRM=PROMOTE" in result.stderr
    assert not record.exists()


@pytest.mark.parametrize("env", ["dev-fir", "dev-auraface", "prod-auraface"])
def test_sync_uses_canonical_runtime_sync_and_propagates_failure(installers, env):
    deploy, _, record, variables = installers
    variables = dict(variables, ENV=env, CONFIRM="PROD", ENTRY_EXIT="23")
    result = subprocess.run(
        ["bash", str(deploy / "sync-compose.sh")], env=variables, text=True, capture_output=True, timeout=10
    )
    assert result.returncode == 23, result.stdout + result.stderr
    assert record.read_text().splitlines()[:2] == ["sync-runtime", env]
    assert record.read_text().splitlines()[2].endswith("PROMOTE")
    assert not Path(variables["EXTERNAL_RECORD"]).exists()


@pytest.mark.parametrize("wrong_image_source", [False, True])
def test_receipted_sync_preserves_digest_through_admission_and_restart(tmp_path, wrong_image_source):
    from test_gtmr_aura_deploy import DIGEST, SHA, Fixture, _driver, _seed_env

    fx = Fixture(tmp_path)
    _seed_env(fx, "dev-auraface")
    observed = "b" * 40 if wrong_image_source else SHA
    result = _driver(
        fx,
        f"""
write_deployed_release_receipt dev-auraface {SHA} {DIGEST}
pin_deploy_sha() {{ DEPLOY_SHA={SHA}; }}
# This test covers receipt-to-ship wiring; real edge ownership is exercised
# separately with the P helper, including dead holders and pending journals.
recognition_edge_begin() {{ :; }}
preflight_ssh() {{ :; }}
preflight_remote_face_pipeline_models() {{ :; }}
preflight_env_manifest() {{ :; }}
preflight_remote_ocir_auth() {{ :; }}
deploy_env_lease() {{ echo "LEASE $*"; }}
remote_image_commit_sha() {{ echo {observed}; }}
verify_running_image_digest() {{ echo "RUNNING $*"; }}
preserve_rollback_tag() {{ ACX_PRIOR_IMAGE_ID=sha256:fixture; echo PRESERVED; }}
capture_prior_runtime_identity() {{ echo CAPTURED; }}
promote_gate() {{ echo "ADMIT $*"; }}
do_restart() {{ echo "RESTART $*"; }}
do_verify() {{ echo "VERIFY $*"; }}
recognition_edge_finish() {{ echo FINISH; }}
do_sync_runtime dev-auraface
""",
    )
    if wrong_image_source:
        assert result.returncode != 0
        assert "ADMIT " not in result.stdout and "RESTART " not in result.stdout
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        lines = result.stdout.splitlines()
        assert f"RUNNING dev-auraface {DIGEST}" in lines
        assert f"ADMIT dev-auraface {DIGEST}" in lines
        assert f"RESTART dev-auraface {DIGEST}" in lines
        assert lines.index("PRESERVED") < lines.index("CAPTURED") < lines.index(f"ADMIT dev-auraface {DIGEST}")
        assert lines.index("LEASE renew dev-auraface") < lines.index(f"RESTART dev-auraface {DIGEST}")
        assert lines[-2:] == ["VERIFY dev-auraface", "FINISH"]
