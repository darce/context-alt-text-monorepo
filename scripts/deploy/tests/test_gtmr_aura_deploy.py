"""GTMSMOKE-1 causal RED for the three frozen AuraFace deploy targets.

The tests source the real ``recognition-service.sh`` and drive its selectors,
lease protocol, receipts, sync gates, model preflight, rollback bootstrap and
production confirmation guards through hermetic doubles. ssh executes each
remote command under a per-test root; docker, curl, scp, sudo and the hash tool
are test-owned. Nothing reads /opt, a real host, a secret, a database, a GPU or
a model weight; the pinned weight bytes are represented by hash-double digests.

Healthy controls pin the unchanged generic and FIR behaviour that must survive
the change. Against unchanged production the Aura assertions are expected to
fail at their first behavioural step (unsupported selector, unchecked artifact,
unbounded probe, missing guard) while controls pass.

Canon v0.26.2 [RLSE-08] — Rollback written before ship;
Continuous Delivery, ch. 10 and ch. 12. The source/digest receipt guards and
retained old generation are exercised here; no runtime quality claim follows.
https://github.com/darce/heuristics-canon/blob/v0.26.2/lexicons/engineering.md#rlse-08
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import _write_executable

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "scripts" / "deploy"
SCRIPT = DEPLOY / "recognition-service.sh"
SYNC = DEPLOY / "sync-compose.sh"
APP = REPO / "apps" / "prototype-description-service"
COMPOSE = APP / "docker-compose.env.yml"
PROVENANCE = APP / "recognition" / "infrastructure" / "face_pipeline" / "provenance.py"

AURA_HOSTS = {
    "dev-auraface": "auraface.dev.altcontext.com",
    "staging-auraface": "auraface.staging.api.altcontext.com",
    "prod-auraface": "auraface.api.altcontext.com",
}
AURA = tuple(AURA_HOSTS)
SIBLING = {
    "dev-auraface": "staging-auraface",
    "staging-auraface": "prod-auraface",
    "prod-auraface": "dev-auraface",
}
LEGACY_TAGS = {"dev": "dev", "dev-fir": "dev-fir", "staging": "staging", "prod": "latest"}
IMAGE_BASE = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
SHA = "a" * 40
DIGEST = f"{IMAGE_BASE}@sha256:" + "b" * 64
ROLLBACK_ID = "abcdef123456"
STALL_SECONDS = 6  # the fake read sleeps longer than every bound asserted below
DEADLINE_BOUND = 4.0  # 1 s advertised deadline + termination/scheduling grace

_TOOLS = {
    "ssh": r"""#!/usr/bin/env bash
# ssh double. The remote command is the final OpenSSH argument, or the words after
# the host when no "--" separator is used. Absolute remote paths are relocated under
# PROBE_ROOT; the original command text is logged before any execution.
set -uo pipefail
args=("$@")
n=${#args[@]}
host_at=-1
for ((i = 0; i < n; i++)); do
  if [[ "${args[i]}" == "--" ]]; then host_at=$((i + 1)); break; fi
done
if ((host_at < 0)); then
  i=0
  while ((i < n)) && [[ "${args[i]}" == -* ]]; do
    case "${args[i]}" in
      -l | -o) i=$((i + 2)) ;;
      *) i=$((i + 1)) ;;
    esac
  done
  host_at=$i
fi
remote=""
for ((i = host_at + 1; i < n; i++)); do
  remote+="${remote:+ }${args[i]}"
done
printf '%s\n' "${remote//$'\n'/ }" >>"$PROBE_SSH_LOG"
if [[ -n "${PROBE_FAIL:-}" && "$remote" == *"$PROBE_FAIL"* ]]; then
  exit 255
fi
if [[ -n "${PROBE_STALL:-}" && "$remote" == *"$PROBE_STALL"* ]]; then
  # Connection and authentication succeeded; the remote read then stalls.
  date +%s.%N >"$PROBE_CONNECTED"
  printf 'partial remote read\n'
  sleep 6
  exit 255
fi
if [[ "$remote" == "bash -s" ]]; then
  body="$(sed -e "s|/opt/acx-backend|${PROBE_ROOT}/opt/acx-backend|g")"
  if [[ -n "${PROBE_STALL:-}" && "$body" == *"$PROBE_STALL"* ]]; then
    # Stall keyed on the shipped operation body; connection and auth already succeeded.
    date +%s.%N >"$PROBE_CONNECTED"
    printf 'partial remote read\n'
    sleep 6
    exit 255
  fi
  printf '%s\n' "$body" | bash -s
  exit $?
fi
remote=${remote//\/opt\/acx-backend/${PROBE_ROOT}\/opt\/acx-backend}
remote=${remote//\/etc\/systemd\/system/${PROBE_ROOT}\/etc\/systemd\/system}
sed "s|/etc/systemd/system|${PROBE_ROOT}/etc/systemd/system|g" | bash -c "$remote"
""",
    "sudo": '#!/bin/sh\n# sudo double: the remote fixture user already owns PROBE_ROOT.\nexec "$@"\n',
    "docker": r"""#!/usr/bin/env bash
# docker double. Read-only observations succeed empty (no running container);
# every other verb is a recorded mutation unless a test opts in explicitly.
printf 'docker %s\n' "$*" >>"$PROBE_DOCKER_LOG"
case " $* " in
  *" ps "* | *" inspect "* | *" info "*) exit 0 ;;
esac
if [[ "${PROBE_DOCKER_OK:-0}" == "1" ]]; then exit 0; fi
printf 'docker %s\n' "$*" >>"$PROBE_MUTATIONS"
exit 97
""",
    "scp": r"""#!/usr/bin/env bash
# scp double: copies only into the relocated remote root.
dest=${!#}
path=${dest#*:}
printf 'scp %s\n' "$*" >>"$PROBE_SCP_LOG"
target=${path//\/opt\/acx-backend/${PROBE_ROOT}\/opt\/acx-backend}
cp -- "$1" "$target"
""",
    "curl": r"""#!/usr/bin/env bash
# curl double for the status report: records each probed URL and answers healthy.
printf '%s\n' "${!#}" >>"$PROBE_CURL_LOG"
printf '{"status":"ok","commit_sha":"%s"}\n200' "$(printf 'c%.0s' {1..40})"
""",
    "sha256sum": r"""#!/usr/bin/env bash
# Hash double: named fixture bytes report their pinned digest from PROBE_DIGESTS;
# any other file is hashed for real. Weight bytes are never read or loaded.
for path in "$@"; do
  name=${path##*/}
  digest="$(awk -v name="$name" '$1 == name { print $2; exit }' "$PROBE_DIGESTS")"
  if [[ -n "$digest" ]]; then
    printf '%s  %s\n' "$digest" "$path"
  else
    /usr/bin/sha256sum -- "$path"
  fi
done
""",
    "systemctl": '#!/bin/sh\nprintf \'systemctl %s\\n\' "$*" >>"$PROBE_MUTATIONS"\nexit 97\n',
    "rsync": '#!/bin/sh\nprintf \'rsync %s\\n\' "$*" >>"$PROBE_MUTATIONS"\nexit 97\n',
}


class Fixture:
    """Per-test remote root, log files and fake tool directory."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.root = tmp / "remote"
        self.root.mkdir()
        (self.root / "opt/acx-backend/app").mkdir(parents=True)
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.digests = tmp / "digests.txt"
        self.digests.write_text("")
        for name, body in _TOOLS.items():
            _write_executable(self.bin / name, body)

    def log(self, name: str) -> Path:
        return self.tmp / f"{name}.log"

    def seen(self, name: str) -> str:
        path = self.log(name)
        return path.read_text() if path.exists() else ""

    def env(self, **extra: str) -> dict[str, str]:
        base = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "LC_ALL": "C",
            "HOME": str(self.tmp),
            "TMPDIR": "/tmp",
            "EDGE_LOCK_STATE_ROOT": str(self.tmp),
            "OCI_USER": "deploy-test",
            "OCI_HOST": "fake-host.invalid",
            "ACX_REMOTE_COMMAND_TIMEOUT": "5",
            "ACX_REMOTE_INSPECT_TIMEOUT": "5",
            "PROBE_ROOT": str(self.root),
            "PROBE_DIGESTS": str(self.digests),
            "PROBE_MUTATIONS": str(self.log("mutations")),
            "PROBE_SSH_LOG": str(self.log("ssh")),
            "PROBE_SCP_LOG": str(self.log("scp")),
            "PROBE_DOCKER_LOG": str(self.log("docker")),
            "PROBE_CURL_LOG": str(self.log("curl")),
            "PROBE_MANIFEST_LOG": str(self.log("manifest")),
            "PROBE_CONNECTED": str(self.log("connected")),
        }
        base.update(extra)
        return base


@pytest.fixture
def fx(tmp_path: Path):
    fixture = Fixture(tmp_path)
    yield fixture
    # Topology tests keep the same real owner across independent SSH calls.
    for handle in tmp_path.glob("shared-edge-lock.*"):
        subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; edge_lock_release "$2" 2',
                "_",
                str(DEPLOY / "lib/shared-edge.sh"),
                str(handle),
            ],
            env=fixture.env(),
            capture_output=True,
            timeout=5,
        )


def _transcript(fx: Fixture, result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        [
            f"rc={result.returncode}",
            "stdout:",
            result.stdout,
            "stderr:",
            result.stderr,
            "ssh:",
            fx.seen("ssh"),
            "mutations:",
            fx.seen("mutations"),
            "docker:",
            fx.seen("docker"),
            "scp:",
            fx.seen("scp"),
        ]
    )


def _driver(fx: Fixture, body: str, *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Source the real script and run ``body`` under its own errexit/nounset policy.

    Production runs with ``set -euo pipefail``; a failing command substitution in an
    assignment aborts there. Probes that need a status use explicit ``|| rc=$?``.
    """
    ownership = ""
    journal = fx.root / "opt/acx-backend/app/activation.journal"
    if journal.is_file():
        fields = dict(line.split("=", 1) for line in journal.read_text().splitlines())
        ownership = f"ACX_EDGE_HANDLE={fields['handle']}\nACX_EDGE_ENV={fields['env']}\n"
    script = f'source "{SCRIPT}"\nGREEN=\nYELLOW=\nRED=\nRESET=\n{ownership}{body}\n'
    return subprocess.run(
        ["/bin/bash", "-c", script],
        cwd=REPO,
        env=fx.env(**(env_extra or {})),
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _cli(fx: Fixture, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        cwd=REPO,
        env=fx.env(**(env_extra or {})),
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def _fill(template: str, **values: str) -> str:
    """Substitute @NAME@ tokens so bash ${...} expansions stay untouched."""
    out = template
    for key, value in values.items():
        out = out.replace(f"@{key}@", value)
    return out


def _lines_with(prefix: str, text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(prefix)]


# ----------------------------------------------------------------- fixtures


@functools.lru_cache(maxsize=1)
def _manifest() -> dict:
    """Load the pinned provenance table; the module is stdlib-only and read-only."""
    # Current producer imports loaded_session relatively; load its real package,
    # keeping the stdlib-only provenance surface instead of replacing its ABI.
    sys.path.insert(0, str(APP))
    try:
        from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

        return dict(MODEL_MANIFEST)
    finally:
        sys.path.remove(str(APP))


def _pin_table(overrides: dict[str, str] | None = None) -> dict[str, str]:
    manifest = _manifest()
    table: dict[str, str] = {}
    for key in ("yunet", "sface", "auraface"):
        table[manifest[key].file_name] = manifest[key].sha256
        table[manifest[key].license_file] = manifest[key].license_sha256
    table.update(overrides or {})
    return table


def _fir_bundle() -> tuple[str, ...]:
    manifest = _manifest()
    return (manifest["yunet"].file_name, manifest["sface"].file_name)


def _sface_bundle() -> tuple[str, ...]:
    manifest = _manifest()
    return (
        manifest["yunet"].file_name,
        manifest["yunet"].license_file,
        manifest["sface"].file_name,
        manifest["sface"].license_file,
    )


def _aura_bundle() -> tuple[str, ...]:
    manifest = _manifest()
    return (
        manifest["yunet"].file_name,
        manifest["yunet"].license_file,
        manifest["auraface"].file_name,
        manifest["auraface"].license_file,
    )


def _models_host(env: str) -> str:
    return f"/opt/acx-backend/data/{env}-models"


def _seed_env(fx: Fixture, env: str) -> None:
    """Write the remote .env for one target; Aura carries the frozen profile values."""
    directory = fx.root / "opt" / "acx-backend" / env
    directory.mkdir(parents=True, exist_ok=True)
    tag = env if env in AURA else LEGACY_TAGS[env]
    lines = [
        f"ACX_ENV={env}",
        f"ACX_IMAGE_TAG={tag}",
        f"ACX_MODELS_PATH={_models_host(env)}",
        "RECOGNITION_FACE_PIPELINE_MODELS_DIR=/data/cache/face_pipeline",
        "RECOGNITION_AURAFACE_MODELS_DIR=/data/cache/face_pipeline",
    ]
    if env in AURA:
        lines += [
            "RECOGNITION_FACE_PIPELINE_PROFILE=auraface",
            "PGVECTOR_DIM=512",
            f"POSTGRES_USER=acx_{env.replace('-', '_')}",
            f"POSTGRES_DB=alt_context_{env.replace('-', '_')}",
            f"POSTGRES_DSN=postgresql+asyncpg://acx_{env.replace('-', '_')}:fixture@postgres:5432/alt_context_{env.replace('-', '_')}",
            f"POSTGRES_SYNC_DSN=postgresql+psycopg://acx_{env.replace('-', '_')}:fixture@postgres:5432/alt_context_{env.replace('-', '_')}",
            f"COMPOSE_PROJECT_NAME=acx-{env}",
            f"ACX_NETWORK_NAME=acx-{env}-net",
            f"ACX_PGDATA_PATH=/opt/acx-backend/data/{env}-pgdata",
            "RECOGNITION_AUTH_ENABLED=true",
            "RECOGNITION_ADMIN_ENABLED=false",
        ]
    (directory / ".env").write_text("\n".join(lines) + "\n")


def _seed_models(fx: Fixture, env: str, names: tuple[str, ...]) -> None:
    directory = fx.root / _models_host(env).lstrip("/") / "face_pipeline"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_bytes(b"fixture bytes; the hash double supplies the digest\n")


def _seed_preflight(fx: Fixture, env: str, names: tuple[str, ...], overrides: dict[str, str] | None = None) -> None:
    _seed_env(fx, env)
    _seed_models(fx, env, names)
    fx.digests.write_text("".join(f"{name} {digest}\n" for name, digest in _pin_table(overrides).items()))


# ----------------------------------------------------------- identity selectors

SELECTOR_PROBE = r"""
for fn in env_to_tag env_to_unit env_to_remote_dir env_to_network env_to_api_alias env_to_next_unit env_to_health_url env_to_ready_url env_to_compose_files; do
  value="$($fn @ENV@ 2>/dev/null)" || value="<refused>"
  printf '%s=%s\n' "$fn" "$value"
done
"""


def _selectors(fx: Fixture, env: str) -> dict[str, str]:
    result = _driver(fx, _fill(SELECTOR_PROBE, ENV=env))
    assert result.returncode == 0, _transcript(fx, result)
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def _aura_identity(label: str) -> dict[str, str]:
    host = AURA_HOSTS[label]
    return {
        "env_to_tag": label,
        "env_to_unit": f"acx-{label}",
        "env_to_remote_dir": f"/opt/acx-backend/{label}",
        "env_to_network": f"acx-{label}-net",
        "env_to_api_alias": f"{label}-api",
        "env_to_next_unit": f"acx-{label}-next",
        "env_to_health_url": f"https://{host}/health",
        "env_to_ready_url": f"https://{host}/ready",
        "env_to_compose_files": "-f docker-compose.env.yml",
    }


LEGACY_IDENTITY = {
    "dev": {
        "env_to_tag": "dev",
        "env_to_unit": "acx-dev",
        "env_to_remote_dir": "/opt/acx-backend/dev",
        "env_to_network": "acx-dev-net",
        "env_to_api_alias": "dev-api",
        "env_to_next_unit": "acx-dev-next",
        "env_to_health_url": "https://dev.api.altcontext.com/health",
        "env_to_ready_url": "https://dev.api.altcontext.com/ready",
        "env_to_compose_files": "-f docker-compose.env.yml",
    },
    "dev-fir": {
        "env_to_tag": "dev-fir",
        "env_to_unit": "acx-dev-fir",
        "env_to_remote_dir": "/opt/acx-backend/dev-fir",
        "env_to_network": "acx-dev-fir-net",
        "env_to_api_alias": "dev-fir-api",
        "env_to_next_unit": "acx-dev-fir-next",
        "env_to_health_url": "https://fir.dev.api.altcontext.com/health",
        "env_to_ready_url": "https://fir.dev.api.altcontext.com/ready",
        "env_to_compose_files": "-f docker-compose.env.yml",
    },
    "staging": {
        "env_to_tag": "staging",
        "env_to_unit": "acx-staging",
        "env_to_remote_dir": "/opt/acx-backend/staging",
        "env_to_network": "acx-staging-net",
        "env_to_api_alias": "staging-api",
        "env_to_next_unit": "acx-staging-next",
        "env_to_health_url": "https://staging.api.altcontext.com/health",
        "env_to_ready_url": "https://staging.api.altcontext.com/ready",
        "env_to_compose_files": "-f docker-compose.env.yml",
    },
    "prod": {
        "env_to_tag": "latest",
        "env_to_unit": "acx-prod",
        "env_to_remote_dir": "/opt/acx-backend/prod",
        "env_to_network": "acx-prod-net",
        "env_to_api_alias": "prod-api",
        "env_to_next_unit": "acx-prod-next",
        "env_to_health_url": "https://api.altcontext.com/health",
        "env_to_ready_url": "https://api.altcontext.com/ready",
        "env_to_compose_files": "-f docker-compose.env.yml -f docker-compose.admin.yml",
    },
}


@pytest.mark.parametrize("label", AURA)
def test_aura_identity_resolves_through_every_selector(fx: Fixture, label: str) -> None:
    observed = _selectors(fx, label)
    assert observed == _aura_identity(label)


@pytest.mark.parametrize("env", sorted(LEGACY_IDENTITY))
def test_existing_generic_and_fir_selectors_are_unchanged(fx: Fixture, env: str) -> None:
    assert _selectors(fx, env) == LEGACY_IDENTITY[env]


UNLISTED = ["auraface", "dev-aura", "prod-aura", "dev_auraface", "prod-auraface-next"]


@pytest.mark.parametrize("bogus", UNLISTED)
def test_unlisted_aura_like_labels_are_refused_by_primary_selectors(fx: Fixture, bogus: str) -> None:
    observed = _selectors(fx, bogus)
    primary = {k: v for k, v in observed.items() if k != "env_to_next_unit"}
    assert set(primary.values()) == {"<refused>"}, observed


@pytest.mark.parametrize("bogus", UNLISTED)
def test_next_unit_selector_is_fail_closed_for_unlisted_labels(fx: Fixture, bogus: str) -> None:
    # Existing defect: env_to_next_unit echoes "$(env_to_unit X)-next", so an unlisted
    # label prints "-next" with status 0 instead of refusing. Aura aliases depend on it.
    observed = _selectors(fx, bogus)
    assert observed["env_to_next_unit"] == "<refused>", observed


# ------------------------------------------------------------------- dispatch


@pytest.mark.parametrize("label", AURA)
def test_status_probes_each_aura_health_endpoint(fx: Fixture, label: str) -> None:
    result = _cli(fx, "status")
    assert f"https://{AURA_HOSTS[label]}/health" in fx.seen("curl").splitlines(), _transcript(fx, result)


def test_status_still_probes_each_existing_target(fx: Fixture) -> None:
    result = _cli(fx, "status")
    probed = fx.seen("curl").splitlines()
    for env in ("dev", "dev-fir", "staging", "prod"):
        assert LEGACY_IDENTITY[env]["env_to_health_url"] in probed, _transcript(fx, result)


# --------------------------------------------------------------------- lease

LEASE_PROBE = r"""
ACX_DEPLOY_TRANSACTION_ID=tx-a
rc=0; deploy_env_lease acquire @ENV@ || rc=$?; echo "RESULT acquire-a $rc"
ACX_DEPLOY_TRANSACTION_ID=tx-b
rc=0; deploy_env_lease acquire @ENV@ || rc=$?; echo "RESULT acquire-b $rc"
rc=0; deploy_env_lease renew @ENV@ || rc=$?; echo "RESULT renew-b $rc"
# Snapshot ownership while tx-a still holds the lease: the owner's later release removes the file.
echo "OWNER renew-b $(cat -- "$PROBE_LEASE_PATH" 2>/dev/null | tr -d '\n')"
rc=0; deploy_env_lease release @ENV@ || rc=$?; echo "RESULT release-b $rc"
echo "OWNER release-b $(cat -- "$PROBE_LEASE_PATH" 2>/dev/null | tr -d '\n')"
ACX_DEPLOY_TRANSACTION_ID=tx-a
rc=0; deploy_env_lease renew @ENV@ || rc=$?; echo "RESULT renew-a $rc"
rc=0; deploy_env_lease release @ENV@ || rc=$?; echo "RESULT release-a $rc"
"""


def _lease_lifecycle(fx: Fixture, env: str) -> tuple[dict[str, str], Path, subprocess.CompletedProcess[str]]:
    """Run the real lease program (remote path relocated) as one process."""
    lease = fx.root / "opt" / "acx-backend" / ".acx-deploy-backups" / "locks" / f"deploy-{env}.lease"
    result = _driver(fx, _fill(LEASE_PROBE, ENV=env), env_extra={"PROBE_LEASE_PATH": str(lease)})
    results = dict(re.findall(r"RESULT (\S+) (\d+)", result.stdout))
    return results, lease, result


@pytest.mark.parametrize("label", AURA)
def test_aura_lease_is_exclusive_renewable_and_releasable(fx: Fixture, label: str) -> None:
    results, lease, result = _lease_lifecycle(fx, label)
    context = _transcript(fx, result)
    owner = dict(re.findall(r"OWNER (\S+) (.*)", result.stdout))
    assert results.get("acquire-a") == "0", context  # first transaction takes the lease
    assert results.get("acquire-b") == "75", context  # HELD by tx-a
    assert results.get("renew-b") == "75", context
    assert json.loads(owner["renew-b"])["transaction"] == "tx-a", context  # non-owner renew changed nothing
    assert results.get("release-b") == "0", context
    assert json.loads(owner["release-b"])["transaction"] == "tx-a", context  # non-owner release changed nothing
    assert results.get("renew-a") == "0", context
    assert results.get("release-a") == "0", context
    assert not lease.exists(), context


@pytest.mark.parametrize("env", ["dev", "dev-fir", "staging", "prod"])
def test_existing_lease_lifecycle_is_healthy_control(fx: Fixture, env: str) -> None:
    results, lease, result = _lease_lifecycle(fx, env)
    assert results == {
        "acquire-a": "0",
        "acquire-b": "75",
        "renew-b": "75",
        "release-b": "0",
        "renew-a": "0",
        "release-a": "0",
    }, _transcript(fx, result)
    assert not lease.exists()


# ------------------------------------------------------------------ receipts

RECEIPT_WRITE_READ = r"""
ACX_DEPLOY_TRANSACTION_ID=tx-receipt
recognition_edge_begin @ENV@ || exit $?
rc=0; write_deployed_release_receipt @ENV@ @SHA@ @DIGEST@ || rc=$?; echo "RESULT write $rc"
rc=0; read_deployed_release_receipt @ENV@ || rc=$?; echo "RESULT read $rc"
"""

RECEIPT_READ = r"""
rc=0; read_deployed_release_receipt @ENV@ || rc=$?; echo "RESULT read $rc"
"""


@pytest.mark.parametrize("label", AURA)
def test_aura_release_receipt_round_trips_for_its_own_environment(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    result = _driver(fx, _fill(RECEIPT_WRITE_READ, ENV=label, SHA=SHA, DIGEST=DIGEST))
    assert "RESULT write 0" in result.stdout, _transcript(fx, result)
    assert "RESULT read 0" in result.stdout, _transcript(fx, result)
    assert SHA in result.stdout.splitlines() and DIGEST in result.stdout.splitlines(), _transcript(fx, result)
    receipt = json.loads((fx.root / "opt" / "acx-backend" / label / "deployed-release.json").read_text())
    assert receipt["env"] == label


@pytest.mark.parametrize("label", AURA)
def test_aura_receipt_from_sibling_environment_is_refused(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    first = _driver(fx, _fill(RECEIPT_WRITE_READ, ENV=label, SHA=SHA, DIGEST=DIGEST))
    assert "RESULT read 0" in first.stdout, _transcript(fx, first)  # positive control first
    receipt = fx.root / "opt" / "acx-backend" / label / "deployed-release.json"
    data = json.loads(receipt.read_text())
    data["env"] = SIBLING[label]
    receipt.write_text(json.dumps(data))
    second = _driver(fx, _fill(RECEIPT_READ, ENV=label))
    assert "RESULT read 1" in second.stdout, _transcript(fx, second)
    assert SHA not in second.stdout.splitlines(), _transcript(fx, second)


@pytest.mark.parametrize("label", AURA)
@pytest.mark.parametrize(
    "sha,digest",
    [("ABCDEF", DIGEST), (SHA, "registry.invalid/no-digest")],
)
def test_malformed_receipt_source_or_digest_is_refused_before_ssh(
    fx: Fixture, label: str, sha: str, digest: str
) -> None:
    _seed_env(fx, label)
    result = _driver(
        fx,
        _fill(
            'rc=0; write_deployed_release_receipt @ENV@ @SHA@ @DIGEST@ || rc=$?; echo "RESULT write $rc"',
            ENV=label,
            SHA=sha,
            DIGEST=digest,
        ),
    )
    assert "RESULT write 1" in result.stdout, _transcript(fx, result)
    assert fx.seen("ssh") == "", _transcript(fx, result)


@pytest.mark.parametrize("label", AURA)
def test_aura_receipt_read_is_deadline_bounded_when_stalled(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    started = time.monotonic()
    result = _driver(
        fx,
        _fill(RECEIPT_READ, ENV=label),
        env_extra={"PROBE_STALL": "deployed-release.json", "ACX_REMOTE_INSPECT_TIMEOUT": "1"},
    )
    elapsed = time.monotonic() - started
    assert f"/opt/acx-backend/{label}/deployed-release.json" in fx.seen("ssh"), _transcript(fx, result)
    assert fx.log("connected").exists(), "read never reached the stalled remote operation: " + _transcript(fx, result)
    assert elapsed < DEADLINE_BOUND, f"stalled receipt read took {elapsed:.2f}s: " + _transcript(fx, result)
    assert "RESULT read 1" in result.stdout, _transcript(fx, result)


# -------------------------------------------------------------- sync gates

RENDER_PROBE = 'rc=0; render_unit @ENV@ > "$PROBE_UNIT_OUT" || rc=$?\necho "RESULT render $rc"\n'
SYNC_PROBE = 'rc=0; runtime_in_sync @ENV@ || rc=$?; echo "RESULT sync $rc"\n'
CONVERGE_PROBE = 'converge_check @ENV@ || true\necho "RESULT converge done"\n'


@pytest.mark.parametrize("label", AURA)
def test_aura_runtime_gate_accepts_matching_topology_and_rejects_drift(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    shutil.copyfile(COMPOSE, fx.root / "opt" / "acx-backend" / label / "docker-compose.env.yml")
    unit = fx.root / "etc" / "systemd" / "system" / f"acx-{label}.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    rendered_path = fx.tmp / "rendered.service"
    render = _driver(fx, _fill(RENDER_PROBE, ENV=label), env_extra={"PROBE_UNIT_OUT": str(rendered_path)})
    assert "RESULT render 0" in render.stdout, _transcript(fx, render)
    rendered = rendered_path.read_text().rstrip("\n")
    assert f"WorkingDirectory=/opt/acx-backend/{label}" in rendered, rendered
    unit.write_text(rendered + "\n")

    matched = _driver(fx, _fill(SYNC_PROBE, ENV=label))
    assert "RESULT sync 0" in matched.stdout, _transcript(fx, matched)

    # Meaningful drift: the installed unit stops the whole stack instead of api/worker only.
    assert "stop api worker" in rendered, rendered
    unit.write_text(rendered.replace("stop api worker", "stop") + "\n")
    drifted = _driver(fx, _fill(SYNC_PROBE, ENV=label))
    assert "RESULT sync 1" in drifted.stdout, _transcript(fx, drifted)


@pytest.mark.parametrize("gate", ["runtime_in_sync", "converge_check"])
@pytest.mark.parametrize("label", AURA)
def test_aura_sync_gate_bounds_a_stalled_compose_read(fx: Fixture, gate: str, label: str) -> None:
    _seed_env(fx, label)
    probe = _fill(SYNC_PROBE if gate == "runtime_in_sync" else CONVERGE_PROBE, ENV=label)
    started = time.monotonic()
    result = _driver(
        fx,
        probe,
        env_extra={
            "PROBE_STALL": "docker-compose.env.yml",
            "ACX_REMOTE_COMMAND_TIMEOUT": "1",
            "ACX_REMOTE_INSPECT_TIMEOUT": "1",
        },
    )
    elapsed = time.monotonic() - started
    assert f"/opt/acx-backend/{label}/docker-compose.env.yml" in fx.seen("ssh"), _transcript(fx, result)
    assert fx.log("connected").exists(), "gate never reached the stalled read: " + _transcript(fx, result)
    assert elapsed < DEADLINE_BOUND, f"{gate} took {elapsed:.2f}s: " + _transcript(fx, result)
    if gate == "converge_check":
        assert "transport failure" in result.stdout + result.stderr, _transcript(fx, result)
        assert "runtime drift detected" not in result.stdout + result.stderr, _transcript(fx, result)
    else:
        assert "RESULT sync 0" not in result.stdout, _transcript(fx, result)


# ------------------------------------------------ YuNet + AuraFace preflight

PREFLIGHT_PROBE = 'rc=0; preflight_remote_face_pipeline_models @ENV@ || rc=$?; echo "RESULT preflight $rc"\n'


@pytest.mark.parametrize("label", AURA)
def test_aura_preflight_accepts_pinned_yunet_auraface_and_licenses_without_sface(fx: Fixture, label: str) -> None:
    _seed_preflight(fx, label, _aura_bundle())
    result = _driver(fx, _fill(PREFLIGHT_PROBE, ENV=label))
    assert f"/opt/acx-backend/{label}/.env" in fx.seen("ssh"), "preflight never resolved the target: " + _transcript(
        fx, result
    )
    assert "RESULT preflight 0" in result.stdout, _transcript(fx, result)


def test_fir_preflight_yunet_and_sface_is_healthy_control(fx: Fixture) -> None:
    _seed_preflight(fx, "dev-fir", _fir_bundle())
    result = _driver(fx, _fill(PREFLIGHT_PROBE, ENV="dev-fir"))
    assert "RESULT preflight 0" in result.stdout, _transcript(fx, result)


AURA_ALTERED = {
    # variant: (bundle, digest overrides keyed by pinned file name, names a refusal must mention)
    "sface_only": ("sface", {}, ("glintr100.onnx", "LICENSE.auraface.md")),
    "tampered_weight": ("aura", {"glintr100.onnx": "0" * 64}, ("glintr100.onnx",)),
    "tampered_license": ("aura", {"LICENSE.auraface.md": "0" * 64}, ("LICENSE.auraface.md",)),
}


@pytest.mark.parametrize("variant", sorted(AURA_ALTERED))
@pytest.mark.parametrize("label", AURA)
def test_aura_preflight_refuses_sface_substitution_or_altered_artifacts(fx: Fixture, label: str, variant: str) -> None:
    bundle_kind, overrides, mentioned = AURA_ALTERED[variant]
    bundle = _sface_bundle() if bundle_kind == "sface" else _aura_bundle()
    _seed_preflight(fx, label, bundle, overrides)
    result = _driver(fx, _fill(PREFLIGHT_PROBE, ENV=label))
    output = result.stdout + result.stderr
    assert "RESULT preflight 0" not in result.stdout, _transcript(fx, result)
    assert any(name in output for name in mentioned), _transcript(fx, result)


@pytest.mark.parametrize("env", ["dev-fir", *AURA])
def test_model_preflight_remote_verification_is_deadline_bounded(fx: Fixture, env: str) -> None:
    bundle = _fir_bundle() if env == "dev-fir" else _aura_bundle()
    _seed_preflight(fx, env, bundle)
    started = time.monotonic()
    result = _driver(
        fx,
        _fill(PREFLIGHT_PROBE, ENV=env),
        env_extra={
            "PROBE_STALL": "verify_face_pipeline_models_dir",
            "ACX_REMOTE_COMMAND_TIMEOUT": "1",
            "ACX_REMOTE_INSPECT_TIMEOUT": "1",
        },
    )
    elapsed = time.monotonic() - started
    assert f"/opt/acx-backend/{env}/.env" in fx.seen("ssh"), _transcript(fx, result)
    assert fx.log("connected").exists(), "verification never reached the stalled remote read: " + _transcript(
        fx, result
    )
    assert elapsed < DEADLINE_BOUND, f"{env}: stalled model verification took {elapsed:.2f}s: " + _transcript(
        fx, result
    )
    assert "RESULT preflight 0" not in result.stdout, _transcript(fx, result)


# ---------------------------------------------------- manifest routing

MANIFEST_STUB = '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >>"$PROBE_MANIFEST_LOG"\nexit 0\n'


def _manifest_probe(fx: Fixture, env: str) -> subprocess.CompletedProcess[str]:
    repo = fx.tmp / "repo"
    stub = repo / "scripts" / "env" / "materialize_remote.sh"
    if not stub.exists():
        stub.parent.mkdir(parents=True)
        stub.write_text(MANIFEST_STUB)
    return _driver(
        fx,
        _fill(
            'REPO_ROOT=@REPO@\nrc=0; preflight_env_manifest @ENV@ || rc=$?\necho "RESULT manifest $rc"\n',
            REPO=str(repo),
            ENV=env,
        ),
    )


def _registered_targets(env: str) -> list[str]:
    """Manifest targets that register this environment (config owns the mapping)."""
    import tomllib

    names: list[str] = []
    for path in sorted((REPO / "config" / "env" / "manifest.d").glob("*.toml")):
        table = tomllib.loads(path.read_text()).get("targets", {})
        for name, spec in table.items():
            if env in spec.get("envs", []) or env in spec.get("remote_paths", {}):
                names.append(name)
    return names


@pytest.mark.parametrize("label", AURA)
def test_aura_manifest_preflight_uses_a_dedicated_target(fx: Fixture, label: str) -> None:
    registered = _registered_targets(label)
    assert registered, f"no manifest target registers {label}; config/env/manifest.d must declare it"
    result = _manifest_probe(fx, label)
    calls = fx.seen("manifest").splitlines()
    assert "RESULT manifest 0" in result.stdout, _transcript(fx, result)
    assert len(calls) == 1, calls
    target = calls[0].split()[1]
    assert target in registered, (target, registered, calls)
    assert target not in ("svc-vm", "svc-fir"), calls


@pytest.mark.parametrize(
    "env,expected",
    [
        ("dev", "dev svc-vm --check"),
        ("dev-fir", "fir svc-fir --check"),
        ("staging", "staging svc-vm --check"),
        ("prod", "prod svc-vm --check"),
    ],
)
def test_existing_manifest_preflight_targets_are_unchanged(fx: Fixture, env: str, expected: str) -> None:
    result = _manifest_probe(fx, env)
    assert "RESULT manifest 0" in result.stdout, _transcript(fx, result)
    assert fx.seen("manifest").splitlines() == [expected]


# ------------------------------------------- bootstrap versus rollback proof

PRESERVE_PROBE = r"""
rc=0; preserve_rollback_tag @ENV@ || rc=$?; echo "RESULT preserve $rc"
echo "RESULT digest ${ACX_ROLLBACK_DIGEST_REF:-none}"
"""


@pytest.mark.parametrize("label", AURA)
def test_aura_bootstrap_is_allowed_only_on_proven_absence(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    absent = _driver(fx, _fill(PRESERVE_PROBE, ENV=label))
    probed = fx.seen("ssh")
    assert f"/opt/acx-backend/{label}" in probed, "absence was not observed on the target: " + _transcript(fx, absent)
    # Query actual Docker labels, including stopped and orphaned next generations;
    # a missing Compose file cannot prove that its containers are absent.
    queries = fx.seen("docker").splitlines()
    assert any("ps -a" in line and f"com.docker.compose.project=acx-{label} " in line for line in queries), queries
    assert any("ps -a" in line and f"com.docker.compose.project=acx-{label}-next " in line for line in queries), queries
    assert all("com.docker.compose.service=api" in line for line in queries if "ps -a" in line), queries
    assert "RESULT preserve 0" in absent.stdout, _transcript(fx, absent)
    assert "RESULT digest none" in absent.stdout, _transcript(fx, absent)


@pytest.mark.parametrize("label", AURA)
def test_aura_unknown_runtime_state_never_bootstraps(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    unknown = _driver(fx, _fill(PRESERVE_PROBE, ENV=label), env_extra={"PROBE_FAIL": "docker ps"})
    assert "RESULT preserve 0" not in unknown.stdout, _transcript(fx, unknown)
    assert f"/opt/acx-backend/{label}" in fx.seen("ssh"), _transcript(fx, unknown)


ROLLBACK_PROBE = r"""
# Digest-prefix checks isolate the registry fence; admission and real edge fencing have their own tests.
preflight_remote_face_pipeline_models() { :; }
recognition_edge_begin() { :; }
recognition_edge_finish() { :; }
init_deploy_ocir_docker_config() { :; }
preflight_ssh() { :; }
preflight_remote_ocir_auth() { :; }
deploy_env_lease() { return 0; }
_pull_ref_remote() { return 0; }
remote_image_digest_ref() {
  case "$1" in
    *:rollback-*) printf '%s\n' "$ROLLBACK_DIGEST" ;;
    *) printf '%s\n' "$CURRENT_DIGEST" ;;
  esac
}
remote_image_id_for_digest() {
  case "$1" in
    "$ROLLBACK_DIGEST") printf 'sha256:%s\n' "$(printf 'a%.0s' {1..64})" ;;
    *) printf 'sha256:%s\n' "$(printf 'c%.0s' {1..64})" ;;
  esac
}
capture_prior_runtime_identity() { return 0; }
restore_env_tag_to_rollback() { printf 'RESTORE %s %s\n' "$1" "$ACX_ROLLBACK_DIGEST_REF"; return 0; }
do_rollback @ENV@ @ID@
"""


@pytest.mark.parametrize("label", AURA)
def test_aura_rollback_restores_only_the_generation_named_by_its_id(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    matching = f"{IMAGE_BASE}@sha256:{ROLLBACK_ID}" + "0" * 52
    current = f"{IMAGE_BASE}@sha256:" + "c" * 64
    positive = _driver(
        fx,
        _fill(ROLLBACK_PROBE, ENV=label, ID=ROLLBACK_ID),
        env_extra={"ROLLBACK_DIGEST": matching, "CURRENT_DIGEST": current, "CONFIRM": "PROMOTE"},
    )
    assert positive.returncode == 0, _transcript(fx, positive)
    assert f"RESTORE {label} {matching}" in positive.stdout, _transcript(fx, positive)

    foreign = f"{IMAGE_BASE}@sha256:ffffffffffff" + "f" * 52
    negative = _driver(
        fx,
        _fill(ROLLBACK_PROBE, ENV=label, ID=ROLLBACK_ID),
        env_extra={"ROLLBACK_DIGEST": foreign, "CURRENT_DIGEST": current, "CONFIRM": "PROMOTE"},
    )
    assert negative.returncode != 0, _transcript(fx, negative)
    assert "RESTORE" not in negative.stdout, _transcript(fx, negative)


# ------------------------------------------------ production confirmation guard


@pytest.mark.parametrize(
    "argv",
    [("deploy", "prod"), ("rollback", "prod", ROLLBACK_ID)],
)
def test_production_confirmation_guard_is_unchanged_control(fx: Fixture, argv: tuple[str, ...]) -> None:
    _seed_env(fx, "prod")
    result = _cli(fx, *argv)
    assert result.returncode != 0, _transcript(fx, result)
    assert "CONFIRM=PROMOTE" in result.stdout + result.stderr, _transcript(fx, result)
    assert fx.seen("ssh") == "", _transcript(fx, result)
    assert fx.seen("mutations") == "", _transcript(fx, result)


@pytest.mark.parametrize(
    "argv",
    [("deploy", "prod-auraface"), ("rollback", "prod-auraface", ROLLBACK_ID)],
)
def test_aura_release_tier_requires_production_confirmation_before_remote_access(
    fx: Fixture, argv: tuple[str, ...]
) -> None:
    _seed_env(fx, "prod-auraface")
    result = _cli(fx, *argv)
    assert result.returncode != 0, _transcript(fx, result)
    assert "CONFIRM=PROMOTE" in result.stdout + result.stderr, _transcript(fx, result)
    assert fx.seen("ssh") == "", _transcript(fx, result)
    assert fx.seen("mutations") == "", _transcript(fx, result)


def test_aura_promotion_into_production_requires_confirmation(fx: Fixture) -> None:
    _seed_env(fx, "dev-auraface")
    _seed_env(fx, "prod-auraface")
    result = _cli(fx, "promote", "dev-auraface", "prod-auraface")
    assert result.returncode != 0, _transcript(fx, result)
    assert "CONFIRM=PROMOTE" in result.stdout + result.stderr, _transcript(fx, result)
    assert fx.seen("mutations") == "", _transcript(fx, result)


def test_production_promotion_confirmation_control(fx: Fixture) -> None:
    _seed_env(fx, "dev")
    _seed_env(fx, "prod")
    result = _cli(fx, "promote", "dev", "prod")
    assert result.returncode != 0, _transcript(fx, result)
    assert "CONFIRM=PROMOTE" in result.stdout + result.stderr, _transcript(fx, result)
    assert fx.seen("mutations") == "", _transcript(fx, result)


@pytest.mark.parametrize("label", ["prod", *AURA])
def test_unresolvable_source_is_refused_before_any_remote_access(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    result = _cli(fx, "deploy", label, env_extra={"GIT_REF": "refs/heads/gtmr-missing-source"})
    assert result.returncode != 0, _transcript(fx, result)
    assert "GIT_REF" in result.stdout + result.stderr, _transcript(fx, result)
    assert fx.seen("ssh") == "", _transcript(fx, result)


# ------------------------------------------------------ sync-compose.sh


def _sync(
    fx: Fixture, env: str, *, confirm: str | None = None, docker_ok: bool = False
) -> subprocess.CompletedProcess[str]:
    extra = {"ENV": env}
    if confirm is not None:
        extra["CONFIRM"] = confirm
    if docker_ok:
        extra["PROBE_DOCKER_OK"] = "1"
    return subprocess.run(
        ["/bin/bash", str(SYNC)],
        cwd=REPO,
        env=fx.env(**extra),
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )


def test_sync_compose_refuses_unlisted_and_unconfirmed_production_control(fx: Fixture) -> None:
    _seed_env(fx, "prod")
    unconfirmed = _sync(fx, "prod")
    assert unconfirmed.returncode != 0, _transcript(fx, unconfirmed)
    assert "CONFIRM=PROD" in unconfirmed.stdout + unconfirmed.stderr, _transcript(fx, unconfirmed)
    assert fx.seen("scp") == "", _transcript(fx, unconfirmed)
    unlisted = _sync(fx, "dev-aura")
    assert unlisted.returncode != 0, _transcript(fx, unlisted)
    assert fx.seen("scp") == "", _transcript(fx, unlisted)


def test_sync_compose_prod_auraface_requires_confirmation_before_copy(fx: Fixture) -> None:
    _seed_env(fx, "prod-auraface")
    result = _sync(fx, "prod-auraface")
    assert result.returncode != 0, _transcript(fx, result)
    assert "CONFIRM=PROD" in result.stdout + result.stderr, _transcript(fx, result)
    assert fx.seen("scp") == "", _transcript(fx, result)


def test_sync_compose_prod_auraface_refuses_unbound_mutable_image(fx: Fixture) -> None:
    _seed_env(fx, "prod-auraface")
    live = fx.root / "opt" / "acx-backend" / "prod-auraface" / "docker-compose.env.yml"
    live.write_text("previous compose\n")
    result = _sync(fx, "prod-auraface", confirm="PROD", docker_ok=True)
    assert result.returncode != 0, _transcript(fx, result)
    assert "receipt" in result.stderr, _transcript(fx, result)
    assert live.read_text() == "previous compose\n"
    assert fx.seen("scp") == "" and fx.seen("mutations") == ""
    assert "admin" not in fx.seen("ssh")


def test_sync_compose_first_install_requires_deploy_receipt(fx: Fixture) -> None:
    _seed_env(fx, "dev-auraface")
    result = _sync(fx, "dev-auraface", docker_ok=True)
    live = fx.root / "opt" / "acx-backend" / "dev-auraface" / "docker-compose.env.yml"
    assert result.returncode != 0, _transcript(fx, result)
    assert "first installation" in result.stderr, _transcript(fx, result)
    assert not live.exists()
    assert fx.seen("scp") == "" and fx.seen("mutations") == ""


# ---------------------------------------------------- unit rendering

RENDER_ONLY = "render_unit @ENV@\n"


def _unit_directives(text: str, key: str) -> list[str]:
    """Directive lines only: template comments legitimately name the admin overlay."""
    return [line for line in text.splitlines() if line.startswith(f"{key}=")]


@pytest.mark.parametrize("label", AURA)
def test_aura_unit_renders_without_admin_overlay(fx: Fixture, label: str) -> None:
    _seed_env(fx, label)
    result = _driver(fx, _fill(RENDER_ONLY, ENV=label))
    assert result.returncode == 0, _transcript(fx, result)
    out = result.stdout
    assert f"WorkingDirectory=/opt/acx-backend/{label}" in out, out
    starts = _unit_directives(out, "ExecStart")
    assert len(starts) == 1, out
    argv = starts[0].split("=", 1)[1].split()
    assert argv[:4] == ["/usr/bin/docker", "compose", "-f", "docker-compose.env.yml"], argv
    assert argv[4:] == ["up", "--remove-orphans"], argv  # start behaviour preserved
    stops = _unit_directives(out, "ExecStop")
    assert len(stops) == 1 and all("admin" not in line for line in stops), out
    assert stops[0].endswith(" stop api worker"), out  # api/worker-scoped stop preserved
    assert "{{" not in out, out


@pytest.mark.parametrize("env", ["dev", "prod"])
def test_existing_unit_rendering_is_unchanged(fx: Fixture, env: str) -> None:
    _seed_env(fx, env)
    result = _driver(fx, _fill(RENDER_ONLY, ENV=env))
    assert result.returncode == 0, _transcript(fx, result)
    compose = "-f docker-compose.env.yml" + (" -f docker-compose.admin.yml" if env == "prod" else "")
    assert f"WorkingDirectory=/opt/acx-backend/{env}" in result.stdout
    assert _unit_directives(result.stdout, "ExecStart") == [
        f"ExecStart=/usr/bin/docker compose {compose} up --remove-orphans"
    ], result.stdout


@pytest.mark.parametrize("label", AURA)
@pytest.mark.parametrize(
    "key,value",
    [
        ("ACX_ENV", "dev"),
        ("COMPOSE_PROJECT_NAME", "acx-prod"),
        ("ACX_NETWORK_NAME", "acx-prod-net"),
        ("ACX_PGDATA_PATH", "/opt/acx-backend/data/prod-pgdata"),
        ("ACX_MODELS_PATH", "/opt/acx-backend/data/dev-fir-models"),
        ("RECOGNITION_AUTH_ENABLED", "false"),
        ("RECOGNITION_ADMIN_ENABLED", "true"),
    ],
)
def test_aura_preflight_refuses_cross_stack_or_public_admin_configuration(fx, label, key, value):
    _seed_preflight(fx, label, _aura_bundle())
    path = fx.root / "opt/acx-backend" / label / ".env"
    lines = [line for line in path.read_text().splitlines() if not line.startswith(key + "=")]
    path.write_text("\n".join([*lines, f"{key}={value}"]) + "\n")
    result = _driver(fx, _fill(PREFLIGHT_PROBE, ENV=label))
    assert "RESULT preflight 0" not in result.stdout, _transcript(fx, result)
    assert key in result.stderr, _transcript(fx, result)


@pytest.mark.parametrize("label", AURA)
def test_aura_bootstrap_never_ignores_orphan_next_without_compose(fx, label):
    _seed_env(fx, label)
    assert not (fx.root / "opt/acx-backend" / label / "docker-compose.cutover.yml").exists()
    _write_executable(
        fx.bin / "docker",
        r"""#!/bin/bash
printf '%s\n' "$*" >>"$PROBE_DOCKER_LOG"
case " $* " in
  *" ps "*"com.docker.compose.project=acx-"*"-next"*) printf 'aaaaaaaaaaaa\n' ;;
  *" inspect "*) printf 'RUNTIME|aaaaaaaaaaaa|sha256:%s|exited|acx-%s-next|api|config-v1\n' "$(printf 'a%.0s' {1..64})" "$PROBE_LABEL" ;;
esac
""",
    )
    result = _driver(fx, _fill(PRESERVE_PROBE, ENV=label), env_extra={"PROBE_LABEL": label})
    assert "RESULT preserve 0" not in result.stdout, _transcript(fx, result)
    assert "com.docker.compose.project=acx-" + label + "-next" in fx.seen("docker")


@pytest.mark.parametrize("label", ["dev", *AURA])
def test_topology_snapshot_records_immutable_prior_absence_for_first_install(fx, label):
    _seed_env(fx, label)
    (fx.root / "etc/systemd/system").mkdir(parents=True)
    result = _driver(fx, f"ACX_DEPLOY_TRANSACTION_ID=first-install\nprepare_runtime_topology_backups {label} 0\n")
    assert result.returncode == 0, _transcript(fx, result)
    snapshot = fx.root / "opt/acx-backend/.acx-deploy-backups" / label / "first-install"
    assert (snapshot / "docker-compose.env.yml.absent").is_file(), (
        "rollback needs immutable absence, not only mutable .bak.absent"
    )


@pytest.mark.parametrize("present", [False, True])
def test_first_install_snapshot_restores_compose_and_bootstrap_bind(fx, present):
    label = "dev-auraface"
    _seed_env(fx, label)
    (fx.root / "etc/systemd/system").mkdir(parents=True)
    _write_executable(fx.bin / "systemctl", "#!/bin/sh\nexit 0\n")
    env_root = fx.root / "opt/acx-backend" / label
    sql = env_root / "db/docker-prod-init/001-extensions.sql"
    sql.parent.mkdir(parents=True)
    compose = env_root / "docker-compose.env.yml"
    if present:
        sql.write_text("previous bootstrap\n")
        compose.write_text("previous compose\n")
    snapshot = _driver(fx, f"ACX_DEPLOY_TRANSACTION_ID=backout\nprepare_runtime_topology_backups {label} 0\n")
    assert snapshot.returncode == 0, _transcript(fx, snapshot)
    sql.write_text("candidate bootstrap\n")
    compose.write_text("candidate compose\n")
    restored = _driver(fx, f"ACX_DEPLOY_TRANSACTION_ID=backout\nrestore_topology_backups {label} current-only\n")
    assert restored.returncode == 0, _transcript(fx, restored)
    if present:
        assert sql.read_text() == "previous bootstrap\n"
        assert compose.read_text() == "previous compose\n"
    else:
        assert not sql.exists() and not compose.exists()


def test_unit_install_does_not_continue_after_dotenv_transport_failure(fx):
    _seed_env(fx, "dev-auraface")
    systemd = fx.root / "etc/systemd/system"
    systemd.mkdir(parents=True)
    result = _driver(
        fx,
        "recognition_edge_begin dev-auraface || exit $?\nif install_rendered_unit dev-auraface; then echo FALSE_GREEN; else echo REFUSED; fi\n",
        env_extra={"PROBE_FAIL": "RECOGNITION_SECRET_BACKEND"},
    )
    assert "REFUSED" in result.stdout, _transcript(fx, result)
    assert not (systemd / "acx-dev-auraface.service").exists(), "dotenv failure reached a unit write"
    assert fx.seen("mutations") == ""
