"""Remote-build lease and diagnostic regression coverage."""

import subprocess

import pytest
from test_deploy_env_lease import _run_driver
from test_sanitize_deploy_diagnostic import (
    _GR101_107_CASES,
    _GR108_144_CASES,
    _run_sanitizer,
    _sanitize_deploy_diagnostic_src,
)


@pytest.mark.parametrize("raw,expected", _GR101_107_CASES + _GR108_144_CASES)
def test_reported_quoted_secret_and_literal_canaries(raw, expected):
    assert _run_sanitizer(raw + "\n") == expected


def test_c1_controls_removed_without_corrupting_utf8():
    text = "café 日本語 😀\tvisible\n".encode()
    result = subprocess.run(
        ["bash", "-c", _sanitize_deploy_diagnostic_src() + "\nsanitize_deploy_diagnostic"],
        input=bytes(range(128, 160)) + "\u0085\u009b".encode() + text,
        capture_output=True,
        check=True,
    )
    assert result.stdout == b"diagnostic: " + text


@pytest.mark.parametrize("remote,expected", [("0", 0), ("1", 1)])
def test_ship_lease_covers_remote_build(tmp_path, remote, expected):
    result = _run_driver(
        tmp_path,
        """
pin_deploy_sha() { DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
init_deploy_ocir_docker_config() { :; }
preflight_ssh() { :; }
preflight_remote_face_pipeline_models() { :; }
preflight_git_clean() { :; }
preflight_branch_synced() { :; }
preflight_remote_ocir_auth() { :; }
preserve_rollback_tag() { exit 0; }
_ship_selected_env dev aggregate
""",
        REMOTE_BUILD=remote,
        ACX_ENV_PREFLIGHT="0",
        ACX_REMOTE_BUILD_TIMEOUT="7200",
        ACX_DEPLOY_LOCK_TTL_SECONDS="7200",
    )
    assert result.returncode == expected, result.stdout + result.stderr


def test_lost_lease_prevents_remote_build(tmp_path):
    result = _run_driver(
        tmp_path,
        """
pin_deploy_sha() { DEPLOY_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; }
init_deploy_ocir_docker_config() { :; }
preflight_ssh() { :; }
preflight_remote_face_pipeline_models() { :; }
preflight_git_clean() { :; }
preflight_branch_synced() { :; }
preflight_remote_ocir_auth() { :; }
preserve_rollback_tag() { :; }
deploy_env_lease() { [[ "$1" == acquire ]]; }
do_build_remote() { echo BUILD_STARTED; exit 0; }
_ship_selected_env dev aggregate
""",
        REMOTE_BUILD="1",
    )
    assert "BUILD_STARTED" not in result.stdout
    assert result.returncode != 0
