"""Contract tests for the opt-in demo GPU environment preflight."""

from __future__ import annotations

import base64
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"
BOOTSTRAP_SCRIPT = REPO_ROOT / "infra" / "oci" / "demo" / "bootstrap-wp.sh"
DEMO_ENV_TEMPLATE = REPO_ROOT / "infra" / "oci" / "demo" / ".env.example"

# Isolated workspaces plant zips here so auto-discovery cannot see the
# developer's untracked repo dist/. Do not write under REPO_ROOT / "dist".
_OLDER_DIST_ZIP = "alt-context-0.0.4.zip"
_NEWER_DIST_ZIP = "alt-context-0.0.9.zip"
_OLDER_MTIME = 1_700_000_000
_NEWER_MTIME = 1_700_000_100


def _repo_dist_zip_names() -> set[str]:
    dist = REPO_ROOT / "dist"
    if not dist.is_dir():
        return set()
    return {path.name for path in dist.glob("alt-context-*.zip")}


def _isolated_repo(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("apps", "infra", "scripts", "docs"):
        target = REPO_ROOT / name
        if target.exists():
            (workspace / name).symlink_to(target, target_is_directory=target.is_dir())
    (workspace / "dist").mkdir()
    return workspace


def _plant_dist_zip(workspace: Path, name: str, content: bytes, mtime: int) -> Path:
    path = workspace / "dist" / name
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))
    return path


def _plant_stale_and_newest_dist_zips(workspace: Path) -> tuple[Path, Path]:
    older = _plant_dist_zip(workspace, _OLDER_DIST_ZIP, b"older plugin", _OLDER_MTIME)
    newer = _plant_dist_zip(workspace, _NEWER_DIST_ZIP, b"newer plugin", _NEWER_MTIME)
    return older, newer


def _run_sync(
    tmp_path: Path,
    *,
    preflight: str | None = None,
    fail_preflight: bool = False,
    permission_aware: bool = False,
    describe_chunk: str | None = None,
    describe_max: str | None = None,
    with_plugin: bool = False,
    unset_plugin_zip: bool = False,
    execute_remote_smoke: bool = False,
    cwd: Path | None = None,
    build_source_stamp: Path | None = None,
    package_plugin_script: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    (bin_dir / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'ssh %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        f"if [[ \"${{PERMISSION_AWARE:-0}}\" == 1 && \"$*\" == *\"sudo install -d -m 700 '/tmp/acx-gpu-preflight/lib'\"* ]]; then exit 23; fi\n"
        f"if [[ \"${{PERMISSION_AWARE:-0}}\" == 1 && \"$*\" == *\"install -d -m 700 '/tmp/acx-gpu-preflight/lib'\"* ]]; then : > {log_path}.staging; fi\n"
        "if [[ \"$*\" == *--check-reaper* ]] && [[ \"${FAIL_PREFLIGHT:-0}\" == 1 ]]; then exit 17; fi\n"
        "if [[ \"$1\" == *bash* || \"$*\" == *' bash -se'* ]]; then\n"
        "  remote_body=$(cat)\n"
        f"  printf '%s\\n' \"$remote_body\" >> {log_path}.stdin\n"
        "  if [[ \"${EXECUTE_REMOTE_SMOKE:-0}\" == 1 && \"$remote_body\" == *'smoke_fail=0'* ]]; then\n"
        "    bash -se <<<\"$remote_body\"\n"
        "    remote_rc=$?\n"
        "    exit \"$remote_rc\"\n"
        "  fi\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "scp").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'scp %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        f"if [[ \"${{PERMISSION_AWARE:-0}}\" == 1 && \"$*\" == *'/tmp/acx-gpu-preflight/'* && ! -f {log_path}.staging ]]; then exit 24; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for shim in (bin_dir / "ssh", bin_dir / "scp"):
        shim.chmod(0o755)
    if execute_remote_smoke:
        (bin_dir / "curl").write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "body=''\n"
            "headers=''\n"
            "format=''\n"
            "url=''\n"
            "while (( $# > 0 )); do\n"
            "  case \"$1\" in\n"
            "    -D|-o|-w)\n"
            "      target=\"$1\"\n"
            "      value=\"$2\"\n"
            "      case \"$target\" in\n"
            "        -D) headers=\"$value\" ;;\n"
            "        -o) body=\"$value\" ;;\n"
            "        -w) format=\"$value\" ;;\n"
            "      esac\n"
            "      shift 2\n"
            "      ;;\n"
            "    http://*|https://*) url=\"$1\"; shift ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            "if [[ -n \"$headers\" ]]; then\n"
            "  printf 'x-wp-total: 1\\n' >\"$headers\"\n"
            "fi\n"
            "if [[ \"$url\" == */wp-json/wp/v2/media* ]]; then\n"
            "  printf '%s\\n' '[{\"id\":1,\"alt_text\":\"A woman in a red coat speaks at a podium.\",\"acx_alt_provenance\":{\"adapter\":\"florence_small\"}}]' >\"$body\"\n"
            "elif [[ \"$format\" == *'%{url_effective}'* ]]; then\n"
            "  printf '200 %s' \"$url\"\n"
            "else\n"
            "  printf '200'\n"
            "fi\n",
            encoding="utf-8",
        )
        (bin_dir / "curl").chmod(0o755)

    env = os.environ.copy()
    env["ACX_BUILD_SOURCE_STAMP"] = str(build_source_stamp or tmp_path / "missing-stamp")
    if package_plugin_script is None:
        package_plugin_script = tmp_path / "digest-stub.sh"
        package_plugin_script.write_text("printf '%s\\n' current-digest\n", encoding="utf-8")
    env["PACKAGE_PLUGIN_SCRIPT"] = str(package_plugin_script)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if with_plugin and unset_plugin_zip:
        raise ValueError("with_plugin and unset_plugin_zip are mutually exclusive")
    if with_plugin:
        plugin_zip = tmp_path / "alt-context.zip"
        plugin_zip.write_bytes(b"test plugin")
        env["PLUGIN_ZIP"] = str(plugin_zip)
    elif unset_plugin_zip:
        env.pop("PLUGIN_ZIP", None)
    else:
        env["PLUGIN_ZIP"] = ""
    env["OCI_HOST"] = "test-host.invalid"
    env["OCI_USER"] = "test-user"
    env["PERMISSION_AWARE"] = "1" if permission_aware else "0"
    env["EXECUTE_REMOTE_SMOKE"] = "1" if execute_remote_smoke else "0"
    if preflight is None:
        env.pop("ACX_DEMO_GPU_PREFLIGHT", None)
    else:
        env["ACX_DEMO_GPU_PREFLIGHT"] = preflight
    if describe_chunk is not None:
        env["ACX_DEMO_DESCRIBE_CHUNK"] = describe_chunk
    else:
        env.pop("ACX_DEMO_DESCRIBE_CHUNK", None)
    if describe_max is not None:
        env["ACX_DEMO_DESCRIBE_MAX"] = describe_max
    else:
        env.pop("ACX_DEMO_DESCRIBE_MAX", None)
    env["FAIL_PREFLIGHT"] = "1" if fail_preflight else "0"
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=cwd or REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    return (tmp_path / "commands.log").read_text(encoding="utf-8")


def _run_sync_remote_fs(
    tmp_path: Path,
    *,
    container_checksum: str = "matching",
    reject_live_validation: bool = False,
    fail_staged_copy: bool = False,
    fail_restore_write: bool = False,
    api_smoke: str = "healthy",
    script: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the public deploy command against local remote-filesystem shims."""
    remote_root = tmp_path / "remote"
    remote_backend = remote_root / "opt" / "acx-backend"
    remote_tmp = remote_root / "tmp"
    (remote_backend / "demo" / "secrets").mkdir(parents=True)
    remote_tmp.mkdir(parents=True)
    (remote_backend / "demo" / "secrets" / ".env").write_text(
        DEMO_ENV_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (remote_backend / "Caddyfile").write_text("# previous valid Caddy config\n", encoding="utf-8")
    (tmp_path / "initial-caddy-inode").write_text(
        str((remote_backend / "Caddyfile").stat().st_ino), encoding="utf-8"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    command_log = tmp_path / "commands.log"
    docker_log = tmp_path / "docker.log"
    curl_log = tmp_path / "curl.log"
    event_log = tmp_path / "events.log"
    real_cat = shutil.which("cat")
    assert real_cat is not None

    path_mapper = """map_remote_paths() {
  printf '%s' "$1" | sed \
    -e 's|/tmp|__ACX_REMOTE_TMP__|g' \
    -e 's|/opt/acx-backend|__ACX_REMOTE_BACKEND__|g' \
    -e "s|__ACX_REMOTE_TMP__|$FAKE_REMOTE_TMP_DIR|g" \
    -e "s|__ACX_REMOTE_BACKEND__|$FAKE_REMOTE_BACKEND_DIR|g"
}"""
    (bin_dir / "ssh").write_text(
        f"""#!/usr/bin/env bash
set -u
printf 'ssh %q ' "$@" >> "$COMMAND_LOG"
printf '\\n' >> "$COMMAND_LOG"
shift
{path_mapper}
if [[ "$*" == 'bash -se' ]]; then
  remote_body="$(</dev/stdin)"
  printf '%s\\n' "$remote_body" >> "$COMMAND_LOG.stdin"
  mapped_body="$(map_remote_paths "$remote_body")"
  bash -se <<<"$mapped_body"
  exit "$?"
fi
remote_command="$(map_remote_paths "$*")"
bash -c "$remote_command"
exit "$?"
""",
        encoding="utf-8",
    )
    (bin_dir / "scp").write_text(
        f"""#!/usr/bin/env bash
set -u
printf 'scp %q ' "$@" >> "$COMMAND_LOG"
printf '\\n' >> "$COMMAND_LOG"
{path_mapper}
source_count=$(( $# - 1 ))
source_paths=''
for ((index = 0; index < source_count; index++)); do
  if [[ -n "$source_paths" ]]; then source_paths="$source_paths"$'\\n'; fi
  source_paths="$source_paths$1"
  shift
done
destination="$1"
remote_path="$(printf '%s' "$destination" | sed 's/^[^:]*://')"
remote_path="$(map_remote_paths "$remote_path")"
if (( source_count <= 0 )); then exit 0; fi
if (( source_count > 1 )) || [[ "$remote_path" == */ ]]; then
  mkdir -p "$remote_path"
  while IFS= read -r source_path; do
    [[ -n "$source_path" ]] && cp -a "$source_path" "$remote_path/"
  done <<<"$source_paths"
else
  mkdir -p "$(dirname "$remote_path")"
  cp -a "$source_paths" "$remote_path"
fi
""",
        encoding="utf-8",
    )
    (bin_dir / "cat").write_text(
        """#!/usr/bin/env bash
if [[ "$FAIL_STAGED_COPY" == 1 && "$#" == 1 && "$1" == Caddyfile.new ]]; then printf 'partial replacement'; exit 23; fi
if [[ "$FAIL_RESTORE_WRITE" == 1 && "$#" == 1 && "$1" == "$FAKE_REMOTE_TMP_DIR"/* ]]; then
  printf 'partial restore'
  exit 23
fi
exec "$REAL_CAT" "$@"
""",
        encoding="utf-8",
    )
    (bin_dir / "docker").write_text(
        """#!/usr/bin/env bash
set -u
printf 'COMMAND\\t%s\\n' "$*" >> "$DOCKER_LOG"
printf 'docker %s\\n' "$*" >> "$EVENT_LOG"
if [[ "$*" == *'caddy validate'* ]]; then
  mount="$4"
  source_file="$(printf '%s' "$mount" | cut -d: -f1)"
  content="$(base64 < "$source_file" | tr -d '\\n')"
  printf 'VALIDATE\\t%s\\t%s\\n' "$mount" "$content" >> "$DOCKER_LOG"
  if [[ "$REJECT_LIVE_VALIDATION" == 1 && "$mount" != *'.new:'* ]]; then exit 31; fi
fi
if [[ "$*" == *'network inspect'* ]]; then exit 1; fi
if [[ "$*" == *'network ls'* ]]; then printf 'NETWORK ID NAME\\n0001 acx-demo-net\\n'; exit 0; fi
if [[ "$*" == *'exec -T caddy sha256sum /etc/caddy/Caddyfile'* ]]; then
  case "$CONTAINER_CHECKSUM" in
    matching) sha256sum Caddyfile ;;
    differing) printf '%064d  /etc/caddy/Caddyfile\\n' 0 ;;
    failure) exit 17 ;;
  esac
fi
exit 0
""",
        encoding="utf-8",
    )
    (bin_dir / "sudo").write_text(
        """#!/usr/bin/env bash
set -u
printf 'SUDO\\t%s\\n' "$*" >> "$DOCKER_LOG"
if [[ "$1" == chown ]]; then exit 0; fi
if [[ "$1" == cp ]]; then
  if [[ "$3" == /etc/systemd/system/acx-demo.service ]]; then exit 0; fi
fi
exec "$@"
""",
        encoding="utf-8",
    )
    (bin_dir / "systemctl").write_text(
        "#!/usr/bin/env bash\nprintf 'SYSTEMCTL\\t%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n",
        encoding="utf-8",
    )
    (bin_dir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "curl").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
body=''
headers=''
format=''
url=''
while (( $# > 0 )); do
  case "$1" in
    -D|-o|-w)
      target="$1"
      value="$2"
      case "$target" in
        -D) headers="$value" ;;
        -o) body="$value" ;;
        -w) format="$value" ;;
      esac
      shift 2
      ;;
    http://*|https://*) url="$1"; shift ;;
    *) shift ;;
  esac
done
code=200
kind=baseline
if [[ "$format" == *'%{url_effective}'* ]]; then
  kind=smoke
  if [[ "$url" == https://*.altcontext.com/health ]]; then
    case "$API_SMOKE" in
      transient) [[ "$(grep -Fc "smoke $url " "$CURL_LOG" || true)" -gt 0 ]] && code=200 || code=500 ;;
      persistent) code=500 ;;
    esac
  fi
fi
if [[ "$url" == */wp-json/wp/v2/media* ]]; then
  kind=media
  if [[ -n "$headers" ]]; then printf 'x-wp-total: 1\\n' >"$headers"; fi
  printf '%s%s\\n' \\
    '[{"id":1,"alt_text":"A woman in a red coat speaks at a podium.",' \\
    '"acx_alt_provenance":{"adapter":"florence_small"}}]' >"$body"
  printf 'media %s 200\\n' "$url" >> "$CURL_LOG"
  printf 'curl media %s 200\\n' "$url" >> "$EVENT_LOG"
elif [[ "$format" == *'%{url_effective}'* ]]; then
  printf 'smoke %s %s\\n' "$url" "$code" >> "$CURL_LOG"
  printf 'curl smoke %s %s\\n' "$url" "$code" >> "$EVENT_LOG"
  printf '%s %s' "$code" "$url"
else
  printf '%s %s %s\\n' "$kind" "$url" "$code" >> "$CURL_LOG"
  printf 'curl %s %s %s\\n' "$kind" "$url" "$code" >> "$EVENT_LOG"
  if [[ "$format" == *'%{http_code}'* ]]; then printf '%s' "$code"; fi
fi
""",
        encoding="utf-8",
    )
    for shim in (
        bin_dir / "ssh",
        bin_dir / "scp",
        bin_dir / "cat",
        bin_dir / "docker",
        bin_dir / "sudo",
        bin_dir / "systemctl",
        bin_dir / "sleep",
        bin_dir / "curl",
    ):
        shim.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "REAL_CAT": real_cat,
            "COMMAND_LOG": str(command_log),
            "DOCKER_LOG": str(docker_log),
            "CURL_LOG": str(curl_log),
            "EVENT_LOG": str(event_log),
            "FAKE_REMOTE_BACKEND_DIR": str(remote_backend),
            "FAKE_REMOTE_TMP_DIR": str(remote_tmp),
            "TMPDIR": str(remote_tmp),
            "CONTAINER_CHECKSUM": container_checksum,
            "REJECT_LIVE_VALIDATION": "1" if reject_live_validation else "0",
            "FAIL_STAGED_COPY": "1" if fail_staged_copy else "0",
            "FAIL_RESTORE_WRITE": "1" if fail_restore_write else "0",
            "API_SMOKE": api_smoke,
            "PLUGIN_ZIP": "",
            "OCI_HOST": "test-host.invalid",
            "OCI_USER": "test-user",
            "ACX_BUILD_SOURCE_STAMP": str(tmp_path / "missing-stamp"),
            "PACKAGE_PLUGIN_SCRIPT": str(tmp_path / "digest-stub.sh"),
        }
    )
    Path(env["PACKAGE_PLUGIN_SCRIPT"]).write_text("exit 1\n", encoding="utf-8")
    return subprocess.run(
        ["bash", str(script or SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _remote_backend(tmp_path: Path) -> Path:
    return tmp_path / "remote" / "opt" / "acx-backend"


def _curl_log(tmp_path: Path) -> str:
    return (tmp_path / "curl.log").read_text(encoding="utf-8")


def _docker_log(tmp_path: Path) -> str:
    return (tmp_path / "docker.log").read_text(encoding="utf-8")


def _event_log(tmp_path: Path) -> str:
    return (tmp_path / "events.log").read_text(encoding="utf-8")


def _validation_observations(tmp_path: Path) -> list[tuple[str, str]]:
    observations = []
    for line in _docker_log(tmp_path).splitlines():
        if line.startswith("VALIDATE\t"):
            _, mount, content = line.split("\t", maxsplit=2)
            observations.append((mount, base64.b64decode(content).decode("utf-8")))
    return observations


def _run_bootstrap_cli(tmp_path: Path, env_text: str) -> tuple[subprocess.CompletedProcess[str], str]:
    demo_dir = tmp_path / "demo"
    secrets_dir = demo_dir / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / ".env").write_text(env_text, encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
        "exit 79\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    bootstrap = BOOTSTRAP_SCRIPT
    if bootstrap != (REPO_ROOT / "infra" / "oci" / "demo" / "bootstrap-wp.sh"):
        contract_dir = bootstrap.parent / "lib"
        contract_dir.mkdir(parents=True, exist_ok=True)
        for contract_name, source in (
            ("gpu-env-contract.sh", REPO_ROOT / "scripts" / "deploy" / "lib" / "gpu-env-contract.sh"),
            ("describe-gate.sh", REPO_ROOT / "infra" / "oci" / "demo" / "lib" / "describe-gate.sh"),
        ):
            shutil.copy2(source, contract_dir / contract_name)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DOCKER_LOG": str(docker_log),
            "DEMO_DIR": str(demo_dir),
            "PLUGIN_ZIP": str(tmp_path / "plugin.zip"),
        }
    )
    result = subprocess.run(
        ["bash", str(bootstrap)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result, docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""


def _stdin(tmp_path: Path) -> str:
    return (tmp_path / "commands.log.stdin").read_text(encoding="utf-8")


def _plugin_bootstrap_invoked(tmp_path: Path) -> bool:
    return "PLUGIN_ZIP='/tmp/alt-context.zip' ./bootstrap-wp.sh" in _stdin(tmp_path)


def test_gpu_preflight_runs_once_when_opted_in(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1")

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert log.count("--check-reaper") == 1
    assert "/opt/acx-backend/prod/.env" in log
    assert "/opt/acx-backend/prod/secrets/.env" not in log
    assert "/opt/acx-backend/demo/secrets/.env" in log
    assert log.count("docker-compose.demo.yml") >= 1


def test_gpu_preflight_staging_is_writable_by_oci_user(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1", permission_aware=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "commands.log.staging").exists()
    assert "sudo install -d -m 700 '/tmp/acx-gpu-preflight/lib'" not in _log(tmp_path)


def test_gpu_preflight_is_off_by_default(tmp_path: Path) -> None:
    result = _run_sync(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert "--check-reaper" not in log
    assert log.count("docker-compose.demo.yml") >= 1


def test_failed_gpu_preflight_aborts_before_demo_compose_scp(tmp_path: Path) -> None:
    result = _run_sync(tmp_path, preflight="1", fail_preflight=True)

    assert result.returncode == 4, result.stdout + result.stderr
    assert "GPU environment preflight failed" in result.stderr
    assert "docker-compose.demo.yml" not in _log(tmp_path)


def test_no_plugin_artifact_skips_first_burst_assertion(tmp_path: Path) -> None:
    result = _run_sync_remote_fs(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SKIP demo first describe burst (bootstrap did not run" in result.stdout
    assert "PASS demo first describe burst" not in result.stdout
    assert "FAIL demo first describe burst" not in result.stdout
    assert not _plugin_bootstrap_invoked(tmp_path)

    curl_responses = _curl_log(tmp_path)
    for host in ("api.altcontext.com", "staging.api.altcontext.com", "dev.api.altcontext.com"):
        assert f"baseline https://{host}/health 200" in curl_responses
        assert f"smoke https://{host}/health 200" in curl_responses
    assert "smoke https://demo.altcontext.com/ 200" in curl_responses
    assert "media https://demo.altcontext.com/wp-json/wp/v2/media?" in curl_responses


def test_empty_plugin_zip_skips_artifact_even_when_dist_has_zips(tmp_path: Path) -> None:
    """PLUGIN_ZIP="" must mean no artifact; must FAIL against pre-BR-06 auto-discover."""
    before = _repo_dist_zip_names()
    workspace = _isolated_repo(tmp_path)
    older, newer = _plant_stale_and_newest_dist_zips(workspace)

    result = _run_sync(tmp_path, execute_remote_smoke=True, cwd=workspace)

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert newer.name not in log
    assert older.name not in log
    assert "Rsync plugin package" not in result.stdout
    assert not _plugin_bootstrap_invoked(tmp_path)
    assert 'BOOTSTRAP_RAN="0"' in _stdin(tmp_path)
    assert "SKIP demo first describe burst (bootstrap did not run" in result.stdout
    assert _repo_dist_zip_names() == before


def test_unset_plugin_zip_auto_discovers_newest_dist_zip(tmp_path: Path) -> None:
    before = _repo_dist_zip_names()
    workspace = _isolated_repo(tmp_path)
    older, newer = _plant_stale_and_newest_dist_zips(workspace)

    stamp = tmp_path / "build-source-stamp"
    stamp.write_text("current-digest\n", encoding="utf-8")
    os.utime(stamp, (_OLDER_MTIME, _OLDER_MTIME))
    result = _run_sync(
        tmp_path, unset_plugin_zip=True, cwd=workspace, build_source_stamp=stamp
    )

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    assert f"Auto-discovered plugin artifact: dist/{newer.name}" in result.stdout
    assert "Plugin artifact freshness verified against build source stamp" in result.stdout
    assert str(newer) in log or f"dist/{newer.name}" in log
    assert older.name not in log
    assert _plugin_bootstrap_invoked(tmp_path)
    assert 'BOOTSTRAP_RAN="1"' in _stdin(tmp_path)
    assert _repo_dist_zip_names() == before


@pytest.mark.parametrize("failure", ["missing", "mismatch", "older", "digest-command"])
def test_auto_discovered_zip_fails_closed(tmp_path: Path, failure: str) -> None:
    workspace = _isolated_repo(tmp_path)
    _plant_stale_and_newest_dist_zips(workspace)
    stamp = tmp_path / "build source stamp"
    script = tmp_path / "digest stub.sh"
    script.write_text(
        "exit 1\n" if failure == "digest-command" else "printf '%s\\n' current-digest\n",
        encoding="utf-8",
    )
    if failure != "missing":
        stamp.write_text(
            "stale-digest\n" if failure == "mismatch" else "current-digest\n",
            encoding="utf-8",
        )
        mtime = _NEWER_MTIME + 1 if failure == "older" else _OLDER_MTIME
        os.utime(stamp, (mtime, mtime))

    result = _run_sync(
        tmp_path, unset_plugin_zip=True, cwd=workspace,
        build_source_stamp=stamp, package_plugin_script=script,
    )

    assert result.returncode == 3, result.stdout + result.stderr
    assert result.stderr.count("ERROR:") == 1
    assert "bash apps/prototype-wp-alt-context/scripts/release/package-plugin.sh" in result.stderr
    assert "PLUGIN_ZIP=<path>" in result.stderr
    if failure == "missing":
        assert "Missing build source stamp" in result.stderr
    elif failure == "mismatch":
        assert "expected current-digest, found stale-digest" in result.stderr
    elif failure == "older":
        assert "older than stamp" in result.stderr
    else:
        assert "Cannot compute build source digest" in result.stderr
    assert not (tmp_path / "commands.log").exists()


def test_unset_plugin_zip_without_dist_zip_skips_freshness_check(tmp_path: Path) -> None:
    workspace = _isolated_repo(tmp_path)
    result = _run_sync(tmp_path, unset_plugin_zip=True, cwd=workspace)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No plugin artifact auto-discovered" in result.stdout
    assert not _plugin_bootstrap_invoked(tmp_path)


def test_explicit_plugin_zip_ignores_dist_zips(tmp_path: Path) -> None:
    before = _repo_dist_zip_names()
    workspace = _isolated_repo(tmp_path)
    older, newer = _plant_stale_and_newest_dist_zips(workspace)

    result = _run_sync(tmp_path, with_plugin=True, cwd=workspace)

    assert result.returncode == 0, result.stdout + result.stderr
    log = _log(tmp_path)
    explicit = tmp_path / "alt-context.zip"
    assert str(explicit) in log
    assert newer.name not in log
    assert older.name not in log
    assert _plugin_bootstrap_invoked(tmp_path)
    assert 'BOOTSTRAP_RAN="1"' in _stdin(tmp_path)
    assert _repo_dist_zip_names() == before


def test_bootstrap_template_passes_required_input_validation(tmp_path: Path) -> None:
    result, docker_calls = _run_bootstrap_cli(tmp_path, DEMO_ENV_TEMPLATE.read_text(encoding="utf-8"))

    assert result.returncode == 79, result.stdout + result.stderr
    assert "compose -f docker-compose.demo.yml up -d mariadb wordpress" in docker_calls


@pytest.mark.parametrize(
    "input_key",
    (
        "WP_ADMIN_USER",
        "WP_ADMIN_PASSWORD",
        "WP_ADMIN_EMAIL",
        "WP_CI_USER",
        "WP_CI_PASSWORD",
        "WP_CI_EMAIL",
        "WORDPRESS_CONFIG_EXTRA",
    ),
)
@pytest.mark.parametrize("change", ("removed", "blank"))
def test_bootstrap_rejects_missing_or_blank_required_input(
    tmp_path: Path, input_key: str, change: str
) -> None:
    template = DEMO_ENV_TEMPLATE.read_text(encoding="utf-8")
    lines = template.splitlines()
    edited: list[str] = []
    for line in lines:
        if line.startswith(f"{input_key}="):
            if change == "removed":
                continue
            if change == "blank":
                line = f"{input_key}="
        edited.append(line)

    result, docker_calls = _run_bootstrap_cli(tmp_path, "\n".join(edited) + "\n")

    assert result.returncode == 2, result.stdout + result.stderr
    assert f"{input_key} must be set in secrets/.env before bootstrap" in result.stderr
    assert not docker_calls


def test_describe_bounds_are_forwarded_to_remote_bootstrap(tmp_path: Path) -> None:
    result = _run_sync(
        tmp_path,
        describe_chunk="7",
        describe_max="23",
        with_plugin=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    bootstrap_input = (tmp_path / "commands.log.stdin").read_text(encoding="utf-8")
    assert "ACX_DEMO_DESCRIBE_CHUNK='7'" in bootstrap_input
    assert "ACX_DEMO_DESCRIBE_MAX='23'" in bootstrap_input


def test_demo_env_template_uses_bootstrap_ci_keys_only() -> None:
    env_example = DEMO_ENV_TEMPLATE.read_text(encoding="utf-8")
    lines = env_example.splitlines()

    for key in ("WP_CI_USER", "WP_CI_PASSWORD", "WP_CI_EMAIL"):
        key_lines = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
        assert len(key_lines) == 1, f"{key} must have exactly one VM-template assignment"
        annotation = lines[key_lines[0] - 1]
        assert "domain: demo-wp" in annotation
        assert "source: operator secret" in annotation
        assert "consumer: bootstrap-wp.sh" in annotation

    assert "ACX_E2E_WP_CI_USER=" not in env_example
    assert "ACX_E2E_WP_CI_PASS=" not in env_example


def test_ci_secret_mapping_and_gpu_deploy_order_are_documented() -> None:
    env_example = (REPO_ROOT / "infra" / "oci" / "demo" / ".env.example").read_text(encoding="utf-8")
    deploy_runbook = (REPO_ROOT / "docs" / "runbooks" / "deploy-demo-cicd.md").read_text(encoding="utf-8")
    gpu_runbook = (REPO_ROOT / "docs" / "runbooks" / "gpu-demo-env-flip.md").read_text(encoding="utf-8")

    assert "ACX_E2E_WP_CI_USER -> WP_CI_USER" in env_example
    assert "ACX_E2E_WP_CI_PASS -> WP_CI_PASSWORD" in env_example
    assert "ACX_E2E_WP_CI_USER" in deploy_runbook
    assert "ACX_E2E_WP_CI_PASS" in deploy_runbook

    producer = gpu_runbook.index("Flip the description SERVICE producer profile")
    prod_redeploy = gpu_runbook.index("Redeploy the prod API", producer)
    deploy_demo = gpu_runbook.index("Run `deploy-demo`", prod_redeploy)
    assert producer < prod_redeploy < deploy_demo


@pytest.mark.parametrize("container_checksum", ("matching", "differing", "failure"))
def test_caddy_promote_preserves_the_mounted_inode(
    tmp_path: Path, container_checksum: str
) -> None:
    replacement = (REPO_ROOT / "apps" / "prototype-description-service" / "Caddyfile").read_bytes()

    result = _run_sync_remote_fs(tmp_path, container_checksum=container_checksum)

    live_caddyfile = _remote_backend(tmp_path) / "Caddyfile"
    initial_inode = int((tmp_path / "initial-caddy-inode").read_text(encoding="utf-8"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert live_caddyfile.stat().st_ino == initial_inode
    assert live_caddyfile.read_bytes() == replacement

    docker_calls = _docker_log(tmp_path)
    if container_checksum == "matching":
        assert "caddy reload --config /etc/caddy/Caddyfile" in docker_calls
        assert "--force-recreate caddy" not in docker_calls
    else:
        assert "up -d --force-recreate caddy" in docker_calls
        assert "caddy reload --config /etc/caddy/Caddyfile" not in docker_calls


@pytest.mark.parametrize("api_smoke", ("transient", "persistent"))
def test_sync_demo_smoke_confirms_transient_api_recovery_and_fails_persistent_regression(
    tmp_path: Path, api_smoke: str
) -> None:
    result = _run_sync_remote_fs(tmp_path, api_smoke=api_smoke)
    assert result.returncode == (1 if api_smoke == "persistent" else 0), result.stdout + result.stderr

    responses = _curl_log(tmp_path).splitlines()
    for host in ("api.altcontext.com", "staging.api.altcontext.com", "dev.api.altcontext.com"):
        host_responses = [line for line in responses if line.startswith(f"smoke https://{host}/health ")]
        if api_smoke == "transient":
            assert host_responses == [f"smoke https://{host}/health 500", f"smoke https://{host}/health 200"]
            assert f"PASS {host}/health (200)" in result.stdout
        elif api_smoke == "persistent":
            assert host_responses == [f"smoke https://{host}/health 500", f"smoke https://{host}/health 500"]
            assert f"FAIL {host}/health (500; was 200 pre-promote — deploy-caused edge regression)" in result.stdout
        else:
            assert host_responses == [f"smoke https://{host}/health 200"]


def test_failed_caddy_copy_restores_the_previous_file(tmp_path: Path) -> None:
    previous = b"# previous valid Caddy config\n"

    result = _run_sync_remote_fs(tmp_path, fail_staged_copy=True)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "Failed to promote Caddyfile; prior contents restored" in result.stderr
    assert (_remote_backend(tmp_path) / "Caddyfile").read_bytes() == previous


@pytest.mark.parametrize("reject_live_validation", (False, True), ids=("accepted", "rejected"))
def test_promoted_caddyfile_is_validated_after_the_in_place_copy(
    tmp_path: Path, reject_live_validation: bool
) -> None:
    previous = b"# previous valid Caddy config\n"
    replacement = (REPO_ROOT / "apps" / "prototype-description-service" / "Caddyfile").read_bytes()

    result = _run_sync_remote_fs(tmp_path, reject_live_validation=reject_live_validation)

    if reject_live_validation:
        assert result.returncode != 0, result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
    validations = _validation_observations(tmp_path)
    assert len(validations) == 2
    assert validations[0][0].endswith("/Caddyfile.new:/etc/caddy/Caddyfile:ro")
    assert validations[0][1].encode() == replacement
    assert validations[1][0].endswith("/Caddyfile:/etc/caddy/Caddyfile:ro")
    assert validations[1][1].encode() == replacement
    expected_live = previous if reject_live_validation else replacement
    assert (_remote_backend(tmp_path) / "Caddyfile").read_bytes() == expected_live


def test_failed_container_checksum_takes_the_force_recreate_path(tmp_path: Path) -> None:
    result = _run_sync_remote_fs(tmp_path, container_checksum="failure")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "up -d --force-recreate caddy" in _docker_log(tmp_path)
    assert "caddy reload --config /etc/caddy/Caddyfile" not in _docker_log(tmp_path)
    events = _event_log(tmp_path).splitlines()
    recreate = next(index for index, event in enumerate(events) if "up -d --force-recreate caddy" in event)
    health_recovery = next(
        index for index, event in enumerate(events) if event.startswith("curl smoke https://api.altcontext.com/health ")
    )
    assert recreate < health_recovery


def test_failed_caddyfile_restore_retains_rollback_copy(tmp_path: Path) -> None:
    previous = b"# previous valid Caddy config\n"

    result = _run_sync_remote_fs(
        tmp_path,
        reject_live_validation=True,
        fail_restore_write=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    retained_notice = "rollback file retained at "
    assert retained_notice in result.stderr, result.stdout + result.stderr
    rollback_file = Path(result.stderr.split(retained_notice, 1)[1].splitlines()[0])
    assert rollback_file.read_bytes() == previous
