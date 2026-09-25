"""Regression coverage for the promotion source commit identity."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "recognition-service.sh"
DIGEST = f"registry.example.test/acx/recognition@sha256:{'d' * 64}"
SOURCE_SHA = "a" * 40
OTHER_SHA = "b" * 40


def _run_shell(driver: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("DEPLOY_SHA", None)
    env.pop("GIT_REF", None)
    env.update(extra_env)
    return subprocess.run(
        ["bash", "-c", driver],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=20,
    )


def _promote_driver(record: Path, source_sha: str, source_rc: int = 0) -> str:
    return f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORD={shlex.quote(str(record))}
DIGEST={shlex.quote(DIGEST)}
A={shlex.quote(SOURCE_SHA)}
SOURCE_SHA={shlex.quote(source_sha)}
SOURCE_RC={source_rc}
REMOTE_BUILD=1
CONFIRM=PROMOTE
fail() {{ printf 'xx %s\\n' "$*" >&2; exit 1; }}
record() {{ printf '%s\\n' "$1" >> "$RECORD"; }}
init_deploy_ocir_docker_config() {{ record init_deploy_ocir_docker_config; }}
preflight_ssh() {{ record preflight_ssh; }}
preflight_remote_face_pipeline_models() {{ record preflight_remote_face_pipeline_models; }}
preflight_remote_ocir_auth() {{ record preflight_remote_ocir_auth; }}
preserve_rollback_tag() {{ record preserve_rollback_tag; ACX_ROLLBACK_DIGEST_REF=rollback-ref; }}
capture_prior_runtime_identity() {{ record capture_prior_runtime_identity; }}
preflight_remote_docker() {{ record preflight_remote_docker; }}
assert_remote_disk_headroom_for_pull() {{ record assert_remote_disk_headroom_for_pull; }}
preflight_docker() {{ record preflight_docker; }}
preflight_ocir_auth() {{ record preflight_ocir_auth; }}
_pull_ref() {{ record _pull_ref; }}
promote_gate() {{ record promote_gate; }}
do_push_tag() {{ record do_push_tag; }}
do_restart() {{ record do_restart; }}
do_verify() {{ record do_verify; }}
image_digest_ref() {{ printf '%s\\n' "$DIGEST"; }}
pin_deploy_sha() {{ record pin_deploy_sha; DEPLOY_SHA="$A"; }}
remote_image_commit_sha() {{ record remote_image_commit_sha; printf '%s\\n' "$SOURCE_SHA"; return "$SOURCE_RC"; }}
do_promote staging prod
'''


def _records(path: Path) -> list[str]:
    return path.read_text().splitlines() if path.exists() else []


def test_promote_refuses_source_commit_mismatch(tmp_path: Path) -> None:
    record = tmp_path / "steps.txt"
    result = _run_shell(_promote_driver(record, OTHER_SHA))

    assert result.returncode != 0
    assert "promote_gate" not in _records(record)
    assert "do_push_tag" not in _records(record)
    assert "do_restart" not in _records(record)
    assert "GIT_REF=" + OTHER_SHA in result.stderr
    assert "CONFIRM=PROMOTE" in result.stderr
    assert "were not changed" in result.stderr


def test_promote_proceeds_when_source_commit_matches(tmp_path: Path) -> None:
    record = tmp_path / "steps.txt"
    result = _run_shell(_promote_driver(record, SOURCE_SHA))
    steps = _records(record)

    assert result.returncode == 0, result.stdout + result.stderr
    assert steps.index("promote_gate") < steps.index("do_push_tag")
    assert steps.index("do_push_tag") < steps.index("do_restart")
    assert steps.index("do_restart") < steps.index("do_verify")


def test_promote_fails_closed_when_source_commit_unreadable(tmp_path: Path) -> None:
    record = tmp_path / "steps.txt"
    result = _run_shell(_promote_driver(record, "", source_rc=1))

    assert result.returncode != 0
    assert "do_push_tag" not in _records(record)
    assert "cannot be proven" in result.stderr


def test_local_mode_reads_commit_from_local_inspect(tmp_path: Path) -> None:
    record = tmp_path / "steps.txt"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(f"#!/bin/sh\nprintf '%s\\n' 'APP_GIT_COMMIT_SHA={SOURCE_SHA}'\n")
    docker.chmod(0o755)
    driver = f'''
source {shlex.quote(str(SCRIPT))}
GREEN=; YELLOW=; RED=; RESET=
RECORD={shlex.quote(str(record))}
REMOTE_BUILD=0
PATH={shlex.quote(str(fake_bin))}:$PATH
fail() {{ printf 'xx %s\\n' "$*" >&2; exit 1; }}
record() {{ printf '%s\\n' "$1" >> "$RECORD"; }}
preflight_docker() {{ record preflight_docker; }}
preflight_ocir_auth() {{ record preflight_ocir_auth; }}
remote_image_commit_sha() {{ record remote_image_commit_sha; return 98; }}
actual="$(image_commit_sha {shlex.quote(DIGEST)})" || exit $?
test "$actual" = {shlex.quote(SOURCE_SHA)}
'''
    result = _run_shell(driver)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "remote_image_commit_sha" not in _records(record)
