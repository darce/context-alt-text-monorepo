"""Unit checks for the shared-edge helper and its app-portal integration.

Lane impl-portal-shared-helper (P). These checks drive scripts/deploy/lib/shared-edge.sh
and scripts/deploy/app-portal.sh through bash only. They touch temporary paths,
stub docker/ssh where needed, and never open the live VM, /opt, Caddy, a database,
secrets, or a GPU. Standard library and pytest only, so collection cannot fail on
imports; a missing helper is reported as a RED assertion about the missing feature.

Controls (healthy today) pin existing app-portal behaviour: the dry-run acceptance
of an unprotected host, the refusal of a held deployment lock before any mutation,
and lock release on an early exit. The joined recognition-service.sh RED tests in
test_gtmr_portal_edge_preserve.py are intentionally not duplicated here.
"""

from __future__ import annotations

import fcntl
import os
import re
import shlex
import stat
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "scripts" / "deploy" / "lib" / "shared-edge.sh"
APP_PORTAL = REPO_ROOT / "scripts" / "deploy" / "app-portal.sh"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "app-portal-deploy.md"
SNIPPET = REPO_ROOT / "infra" / "oci" / "app" / "Caddyfile.app"
OVERLAY = REPO_ROOT / "infra" / "oci" / "app" / "docker-compose.app.yml"
REPO_CADDYFILE = REPO_ROOT / "apps" / "prototype-description-service" / "Caddyfile"

BEGIN = "# BEGIN APP_PORTAL_VHOST"
END = "# END APP_PORTAL_VHOST"
AURA_HOSTS = (
    "auraface.dev.altcontext.com",
    "auraface.staging.api.altcontext.com",
    "auraface.api.altcontext.com",
)
EXISTING_PROTECTED = (
    "api.altcontext.com",
    "staging.api.altcontext.com",
    "dev.api.altcontext.com",
    "fir.dev.api.altcontext.com",
    "demo.altcontext.com",
    "129-213-40-111.sslip.io",
    "dl.darce.xyz",
)


def _require_lib() -> Path:
    if not LIB.is_file():
        pytest.fail("RED (missing feature): scripts/deploy/lib/shared-edge.sh does not exist", pytrace=False)
    return LIB


def _clean_env(tmp: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
        "HOME": str(tmp),
        "TMPDIR": str(tmp),
        "EDGE_LOCK_STATE_ROOT": str(tmp / "state"),
    }
    if extra:
        env.update(extra)
    return env


def _state_root(tmp: Path) -> Path:
    root = tmp / "state"
    root.mkdir(exist_ok=True)
    return root


def _bash(
    tmp: Path, script: str, *, extra_env: dict[str, str] | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    _state_root(tmp)
    return subprocess.run(
        ["bash", "-c", script],
        env=_clean_env(tmp, extra_env),
        cwd=str(tmp),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _call(
    tmp: Path, body: str, *, extra_env: dict[str, str] | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    lib = _require_lib()
    return _bash(
        tmp, f"set -euo pipefail\nsource {shlex.quote(str(lib))}\n{body}", extra_env=extra_env, timeout=timeout
    )


def _flock_free(lock: Path) -> bool:
    """A separate process proves the lock is free by briefly taking it."""
    result = subprocess.run(["flock", "-n", str(lock), "true"], capture_output=True, text=True, check=False, timeout=20)
    return result.returncode == 0


@contextmanager
def _held(lock: Path) -> Iterator[None]:
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _lock_tree(tmp: Path) -> Path:
    app = tmp / "opt" / "acx-backend" / "app"
    app.mkdir(parents=True, exist_ok=True)
    lock = app / "activation.journal.lock"
    lock.write_text("persistent deployment lock\n", encoding="utf-8")
    return lock


def _state_dirs(tmp: Path) -> list[str]:
    root = tmp / "state"
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def _render_block() -> str:
    text = SNIPPET.read_text(encoding="utf-8")
    text = (
        text.replace("__APP_HOSTNAME__", "app.altcontext.com")
        .replace("__APP_UPSTREAM__", "prod-api:8000")
        .replace("__APP_FRONTEND_ROOT__", "/srv/app-portal")
    )
    return text if text.endswith("\n") else text + "\n"


def _block_of(text: str) -> str | None:
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    if len(starts) != 1:
        return None
    for j in range(starts[0], len(lines)):
        if lines[j].strip() == END:
            return "".join(lines[starts[0] : j + 1])
    return None


BASE = REPO_CADDYFILE.read_text(encoding="utf-8")
BLOCK = _render_block()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run_effective(tmp: Path, base: Path, live: Path) -> subprocess.CompletedProcess[str]:
    return _call(tmp, f"edge_effective_caddyfile {shlex.quote(str(base))} {shlex.quote(str(live))}")


def _portal_env(tmp: Path, hostname: str) -> dict[str, str]:
    backend = tmp / "opt" / "acx-backend"
    (backend / "app").mkdir(parents=True, exist_ok=True)
    return {
        "APP_HOSTNAME": hostname,
        "APP_UPSTREAM": "prod-api:8000",
        "APP_ROOT": str(backend / "app"),
        "APP_WWW": str(backend / "app" / "www"),
        "CADDYFILE": str(backend / "Caddyfile"),
        "CADDY_COMPOSE": str(backend / "docker-compose.caddy.yml"),
        "APP_APPROVED_ROOTS": str(backend),
        "APP_FRONTEND_ROOT": "/srv/app-portal",
        "APP_SNIPPET": str(SNIPPET),
        "APP_OVERLAY": str(OVERLAY),
        "APP_RELOAD_CMD": "",
        "APP_HEALTH_CMD": "",
        "FRONTEND_DIST": "",
        "APP_PORTAL_ENV_ROOT": str(REPO_ROOT / "config" / "env"),
    }


def _run_portal(
    tmp: Path, args: list[str], env: dict[str, str], *, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
        "HOME": str(tmp),
        "TMPDIR": str(tmp),
    }
    base_env.update(env)
    return subprocess.run(
        ["bash", str(APP_PORTAL), *args],
        cwd=str(REPO_ROOT),
        env=base_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# ------------------------------------------------------------ controls (healthy)


def test_detector_control_flock_probe_sees_a_python_held_lock(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    assert _flock_free(lock), "fixture lock must start free"
    with _held(lock):
        assert not _flock_free(lock), "a separate flock probe must observe a held lock"
    assert _flock_free(lock)


def test_app_portal_accepts_unprotected_hostname_control(tmp_path: Path) -> None:
    result = _run_portal(tmp_path, ["--dry-run"], _portal_env(tmp_path, "app.altcontext.com"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "dry-run: no files changed" in result.stdout


def test_app_portal_held_deploy_lock_refuses_before_mutation_control(tmp_path: Path) -> None:
    env = _portal_env(tmp_path, "app.altcontext.com")
    backend = Path(env["CADDY_COMPOSE"]).parent
    compose = _write(backend / "docker-compose.caddy.yml", "services: {}\n")
    env["CADDY_COMPOSE"] = str(compose)
    env["APP_DEPLOY_LOCK_WAIT"] = "0"
    lock = Path(env["APP_ROOT"]) / "activation.journal.lock"
    lock.write_text("", encoding="utf-8")
    before = (lock.stat().st_ino, lock.read_bytes())
    with _held(lock):
        result = _run_portal(tmp_path, ["--apply"], env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "could not acquire deployment lock" in result.stderr
    assert not (Path(env["APP_ROOT"]) / "staging").exists()
    assert not (Path(env["APP_ROOT"]) / "activation.journal").exists()
    assert (lock.stat().st_ino, lock.read_bytes()) == before


def test_app_portal_releases_deploy_lock_on_early_exit_control(tmp_path: Path) -> None:
    env = _portal_env(tmp_path, "app.altcontext.com")
    backend = Path(env["CADDY_COMPOSE"]).parent
    _write(backend / "docker-compose.caddy.yml", "services: {}\n")
    _write(Path(env["CADDYFILE"]), BASE)
    docker = _write(tmp_path / "bin" / "docker", _docker_compose_stub(Path(env["CADDYFILE"])))
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env["PATH"] = f"{docker.parent}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"
    lock = Path(env["APP_ROOT"]) / "activation.journal.lock"
    lock.write_text("", encoding="utf-8")
    # Reaches the deploy lock, binding gate, then refuses for a missing build directory.
    result = _run_portal(tmp_path, ["--apply"], env)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "FRONTEND_DIST is required for --apply" in result.stderr, result.stdout + result.stderr
    assert _flock_free(lock), "the deploy lock must be released when app-portal exits early"


def _docker_compose_stub(caddyfile: Path) -> str:
    config = (
        '{"services":{"caddy":{"volumes":[{"type":"bind","source":"'
        + str(caddyfile)
        + '","target":"/etc/caddy/Caddyfile"}]}}}'
    )
    return (
        "#!/usr/bin/env bash\n"
        'if [ "${1:-}" = compose ] && [ "${2:-}" = version ]; then exit 0; fi\n'
        'case " $* " in *" config "*) printf \'%s\\n\' ' + shlex.quote(config) + "; exit 0 ;; esac\n"
        "exit 0\n"
    )


# -------------------------------------------------------- RED: app-portal integration


def test_helper_file_exists_and_parses() -> None:
    lib = _require_lib()
    result = subprocess.run(["bash", "-n", str(lib)], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr


def test_sourcing_helper_leaves_caller_options_and_traps_unchanged(tmp_path: Path) -> None:
    lib = _require_lib()
    script = (
        "set -euo pipefail\n"
        "trap 'echo caller-exit' EXIT\n"
        'before_opts="$(set +o)"; before_traps="$(trap -p)"\n'
        f"source {shlex.quote(str(lib))}\n"
        'after_opts="$(set +o)"; after_traps="$(trap -p)"\n'
        '[ "$before_opts" = "$after_opts" ] || { echo OPTS_CHANGED; exit 3; }\n'
        '[ "$before_traps" = "$after_traps" ] || { echo TRAPS_CHANGED; exit 4; }\n'
        "echo SOURCE_OK\n"
    )
    result = _bash(tmp_path, script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SOURCE_OK" in result.stdout


@pytest.mark.parametrize("hostname", AURA_HOSTS)
def test_app_portal_refuses_aura_hosts_as_existing_caddy_hosts(tmp_path: Path, hostname: str) -> None:
    result = _run_portal(tmp_path, ["--dry-run"], _portal_env(tmp_path, hostname))
    assert result.returncode == 2, f"Aura host {hostname} must be a protected host\n" + result.stdout + result.stderr
    assert "existing Caddy host" in result.stderr


@pytest.mark.parametrize("host", EXISTING_PROTECTED)
def test_app_portal_keeps_existing_protected_hosts_refused(tmp_path: Path, host: str) -> None:
    result = _run_portal(tmp_path, ["--dry-run"], _portal_env(tmp_path, host))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "existing Caddy host" in result.stderr


def test_app_portal_fails_closed_when_shared_edge_helper_is_missing(tmp_path: Path) -> None:
    env = _portal_env(tmp_path, "app.altcontext.com")
    env["APP_SHARED_EDGE_LIB"] = str(tmp_path / "missing-shared-edge.sh")
    result = _run_portal(tmp_path, ["--dry-run"], env)
    assert result.returncode != 0, (
        "a missing shared-edge helper must refuse, not run without it\n" + result.stdout + result.stderr
    )
    assert "shared-edge" in result.stderr


def _recovery_blocks() -> tuple[str, str]:
    section = RUNBOOK.read_text(encoding="utf-8").split("### Recover an interrupted frontend activation", 1)[1]
    section = section.split("### Frontend back-out", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
    assert len(blocks) == 2, "expected workstation copy and VM recovery commands"
    return blocks[0], blocks[1]


def test_runbook_recovery_packages_the_shared_edge_helper() -> None:
    copies, invocation = _recovery_blocks()
    assert "scp scripts/deploy/app-portal.sh acx-backend:/tmp/app-portal-recovery.sh" in copies
    assert "scp scripts/deploy/lib/shared-edge.sh acx-backend:/tmp/app-portal-recovery.shared-edge.sh" in copies
    assert "APP_SHARED_EDGE_LIB=/tmp/app-portal-recovery.shared-edge.sh" in invocation.replace("\\\n", " ")


def test_runbook_documents_aura_protected_hosts_and_lock_contract() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for host in AURA_HOSTS:
        assert host in text, f"runbook must name protected host {host}"
    assert "lib/shared-edge.sh" in text
    assert "APP_DEPLOY_LOCK_WAIT" in text
    assert "activation.journal.lock" in text


# --------------------------------------------- RED: effective Caddyfile (base + block)


def test_effective_caddyfile_preserves_installed_portal_block_byte_for_byte(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + BLOCK)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _block_of(result.stdout) == BLOCK, "the managed block must survive byte for byte"
    assert result.stdout.startswith(BASE), "the repository base must be the effective prefix"
    assert result.stdout.count(BEGIN) == 1


def test_effective_caddyfile_without_installed_block_emits_base_bytes(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == BASE


def test_effective_caddyfile_refuses_duplicate_managed_blocks(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + BLOCK + "\n" + BLOCK)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, result.stdout
    assert result.stdout == ""


def test_effective_caddyfile_refuses_unterminated_block(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    truncated = BLOCK.replace(END + "\n", "")
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + truncated)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, result.stdout
    assert result.stdout == ""


def test_effective_caddyfile_refuses_end_before_begin(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    reversed_block = END + "\n" + BLOCK.replace(BEGIN + "\n", "").replace(END + "\n", "") + BEGIN + "\n"
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + reversed_block)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, result.stdout
    assert result.stdout == ""


def test_effective_caddyfile_refuses_base_that_already_carries_markers(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE + "\n" + BLOCK)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + BLOCK)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, result.stdout
    assert result.stdout == ""


@pytest.mark.parametrize("host", EXISTING_PROTECTED + AURA_HOSTS)
def test_effective_caddyfile_refuses_block_claiming_a_protected_host(tmp_path: Path, host: str) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    claimed = BLOCK.replace("app.altcontext.com {", f"{host} {{", 1)
    assert claimed != BLOCK
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + claimed)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, f"a block claiming {host} must be refused\n" + result.stdout
    assert result.stdout == ""


def test_effective_caddyfile_refuses_unbalanced_block(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    unbalanced = BLOCK.replace(END, "    stray {\n" + END, 1)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + unbalanced)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, result.stdout
    assert result.stdout == ""


def test_effective_caddyfile_refuses_missing_live_file(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    result = _run_effective(tmp_path, base, tmp_path / "absent" / "Caddyfile")
    assert result.returncode != 0
    assert result.stdout == ""


def test_effective_caddyfile_is_idempotent(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + BLOCK)
    first = _run_effective(tmp_path, base, live)
    assert first.returncode == 0, first.stdout + first.stderr
    again = _write(tmp_path / "again" / "Caddyfile", first.stdout)
    second = _run_effective(tmp_path, base, again)
    assert second.returncode == 0, second.stdout + second.stderr
    assert second.stdout == first.stdout


# ------------------------------------------------ RED: compose argv (base + overlay)


def _argv_script(base: Path, overlay: str) -> str:
    return (
        f"edge_compose_args {shlex.quote(str(base))} {shlex.quote(overlay)} || {{ echo REFUSED; exit 7; }}\n"
        'printf "%s\\n" "${EDGE_COMPOSE_ARGV[@]}"\n'
    )


def test_compose_args_base_only_when_overlay_absent(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    result = _call(tmp_path, _argv_script(base, str(tmp_path / "absent.yml")))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == ["-f", str(base)]


def test_compose_args_includes_installed_overlay_after_base(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    installed = _write(
        tmp_path / "app" / "docker-compose.app.yml",
        OVERLAY.read_text(encoding="utf-8").replace("__APP_WWW__", str(tmp_path / "www")),
    )
    result = _call(tmp_path, _argv_script(base, str(installed)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == ["-f", str(base), "-f", str(installed)]


def test_compose_args_refuses_unresolved_overlay_template(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    template = _write(tmp_path / "app" / "docker-compose.app.yml", OVERLAY.read_text(encoding="utf-8"))
    result = _call(tmp_path, _argv_script(base, str(template)))
    assert "REFUSED" in result.stdout, result.stdout + result.stderr
    assert "-f" not in result.stdout


def test_compose_args_refuses_symlinked_overlay(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    real = _write(tmp_path / "elsewhere" / "overlay.yml", "services: {}\n")
    link = tmp_path / "app" / "docker-compose.app.yml"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(real)
    result = _call(tmp_path, _argv_script(base, str(link)))
    assert "REFUSED" in result.stdout, result.stdout + result.stderr


def test_compose_args_keep_paths_with_spaces_as_single_elements(tmp_path: Path) -> None:
    base = _write(tmp_path / "dir with space" / "docker compose.caddy.yml", "services: {}\n")
    installed = _write(tmp_path / "app dir" / "docker-compose.app.yml", "services: {}\n")
    result = _call(tmp_path, _argv_script(base, str(installed)))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == ["-f", str(base), "-f", str(installed)]


# ------------------------------------------ RED: required networks from compose model


def _docker_config_stub(tmp: Path, body: str) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp / "config.json").write_text(body, encoding="utf-8")
    log = tmp / "docker-argv.log"
    stub = bin_dir / "docker"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
        'case " $* " in *" config "*) cat ' + shlex.quote(str(tmp / "config.json")) + "; exit 0 ;; esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _networks_script(base: Path, overlay: str) -> str:
    return f"edge_required_networks {shlex.quote(str(base))} {shlex.quote(overlay)} || {{ echo REFUSED; exit 7; }}\n"


def test_required_networks_resolve_actual_names_from_compose_model(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    model = (
        '{"services":{"caddy":{"networks":{"acx-prod-net":null,"edge-alias-net":null}}},'
        '"networks":{"acx-prod-net":{"name":"acx-prod-net","external":true},'
        '"edge-alias-net":{"name":"acx-real-edge","external":true}}}'
    )
    bin_dir = _docker_config_stub(tmp_path, model)
    result = _call(
        tmp_path,
        _networks_script(base, str(tmp_path / "absent.yml")),
        extra_env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == ["acx-prod-net", "acx-real-edge"]
    assert "config" in (tmp_path / "docker-argv.log").read_text(encoding="utf-8")


def test_required_networks_refuse_an_empty_model(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    bin_dir = _docker_config_stub(tmp_path, "")
    result = _call(
        tmp_path,
        _networks_script(base, str(tmp_path / "absent.yml")),
        extra_env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert "REFUSED" in result.stdout, result.stdout + result.stderr


def test_required_networks_refuse_caddy_without_declared_networks(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    bin_dir = _docker_config_stub(tmp_path, '{"services":{"caddy":{"image":"caddy:2-alpine"}}}')
    result = _call(
        tmp_path,
        _networks_script(base, str(tmp_path / "absent.yml")),
        extra_env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert "REFUSED" in result.stdout, result.stdout + result.stderr


def test_required_networks_are_not_a_hardcoded_five(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    model = (
        '{"services":{"caddy":{"networks":{"acx-prod-net":null,"acx-dev-net":null}}},'
        '"networks":{"acx-prod-net":{"name":"acx-prod-net","external":true},'
        '"acx-dev-net":{"name":"acx-dev-net","external":true}}}'
    )
    bin_dir = _docker_config_stub(tmp_path, model)
    result = _call(
        tmp_path,
        _networks_script(base, str(tmp_path / "absent.yml")),
        extra_env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == ["acx-dev-net", "acx-prod-net"]


# ------------------------------------------------------ RED: retained shared lock


def test_lock_handle_holds_across_separate_processes_and_release_frees(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {shlex.quote(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    assert handle, "acquire must return an explicit handle"
    # The first process has exited. The retained handle must still exclude others.
    assert not _flock_free(lock), "the shared lock must stay held between separate operations"
    released = _call(tmp_path, f"edge_lock_release {shlex.quote(handle)}")
    assert released.returncode == 0, released.stdout + released.stderr
    assert _flock_free(lock), "release must free the shared lock"
    assert _state_dirs(tmp_path) == [], "release must leave no handle state behind"


def test_lock_busy_refusal_makes_zero_mutations(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    before = (lock.stat().st_ino, lock.read_bytes())
    with _held(lock):
        result = _call(tmp_path, f"edge_lock_acquire {shlex.quote(str(lock))} 0 900 0")
    assert result.returncode != 0, result.stdout + result.stderr
    assert result.stdout.strip() == "", "a refused acquire must not print a handle"
    assert (lock.stat().st_ino, lock.read_bytes()) == before
    assert _state_dirs(tmp_path) == []


@pytest.mark.parametrize("wait", ["", "x", "-1", "1.5", "99999999"])
def test_lock_wait_must_be_a_bounded_non_negative_integer(tmp_path: Path, wait: str) -> None:
    lock = _lock_tree(tmp_path)
    before = lock.stat().st_ino
    result = _call(tmp_path, f"edge_lock_acquire {shlex.quote(str(lock))} {shlex.quote(wait)} 900 0")
    assert result.returncode == 2, f"wait={wait!r}\n" + result.stdout + result.stderr
    assert result.stdout.strip() == ""
    assert lock.stat().st_ino == before
    assert _flock_free(lock)
    assert _state_dirs(tmp_path) == []


def test_lock_inode_is_preserved_across_acquire_and_release(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    inode = lock.stat().st_ino
    acquired = _call(tmp_path, f"edge_lock_acquire {shlex.quote(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    released = _call(tmp_path, f"edge_lock_release {shlex.quote(acquired.stdout.strip())}")
    assert released.returncode == 0, released.stdout + released.stderr
    assert lock.stat().st_ino == inode, "the lock inode must never be unlinked or replaced"
    assert lock.read_text(encoding="utf-8") == "persistent deployment lock\n"


def test_lock_holder_exits_when_its_owner_process_dies(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    owner = subprocess.Popen(
        ["sleep", "60"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        acquired = _call(tmp_path, f"edge_lock_acquire {shlex.quote(str(lock))} 0 900 {owner.pid}")
        assert acquired.returncode == 0, acquired.stdout + acquired.stderr
        assert not _flock_free(lock)
        owner.kill()
        owner.wait(timeout=10)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not _flock_free(lock):
            time.sleep(0.2)
        assert _flock_free(lock), "a dead owner must not leave the shared lock held"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)


def test_lock_hold_cap_expiry_is_reported_at_release(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {shlex.quote(str(lock))} 0 1 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    time.sleep(3)
    released = _call(tmp_path, f"edge_lock_release {shlex.quote(acquired.stdout.strip())}")
    assert released.returncode == 3, (
        "an expired hold must not look like a serialized operation\n" + released.stdout + released.stderr
    )
    assert _flock_free(lock)


def test_release_rejects_an_unknown_handle(tmp_path: Path) -> None:
    result = _call(tmp_path, f"edge_lock_release {shlex.quote(str(tmp_path / 'never-issued'))}")
    assert result.returncode != 0


def test_lock_helpers_are_safe_under_caller_errexit_and_keep_traps(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    lib = _require_lib()
    script = (
        "set -euo pipefail\n"
        "trap 'echo caller-exit' EXIT\n"
        'before_traps="$(trap -p)"\n'
        f"source {shlex.quote(str(lib))}\n"
        "rc=0\n"
        f'h="$(edge_lock_acquire {shlex.quote(str(lock))} 0 900 0)" || rc=$?\n'
        'echo "rc=${rc}"\n'
        'after_traps="$(trap -p)"\n'
        '[ "$before_traps" = "$after_traps" ] || { echo TRAPS_CHANGED; exit 4; }\n'
        'edge_lock_release "$h" || { echo RELEASE_FAILED; exit 5; }\n'
        "echo CALLER_CONTINUED\n"
    )
    result = _bash(tmp_path, script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rc=0" in result.stdout, result.stdout + result.stderr
    assert "TRAPS_CHANGED" not in result.stdout
    assert "CALLER_CONTINUED" in result.stdout
    assert _flock_free(lock)


def test_busy_acquire_under_errexit_reports_75_and_continues(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    lib = _require_lib()
    script = (
        "set -euo pipefail\n"
        f"source {shlex.quote(str(lib))}\n"
        "rc=0\n"
        f'h="$(edge_lock_acquire {shlex.quote(str(lock))} 0 900 0)" || rc=$?\n'
        'echo "rc=${rc}"\n'
        "echo CALLER_CONTINUED\n"
    )
    with _held(lock):
        result = _bash(tmp_path, script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rc=75" in result.stdout, result.stdout + result.stderr
    assert "CALLER_CONTINUED" in result.stdout


def test_lock_acquire_does_not_hang_a_caller_that_captures_output(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    result = _call(
        tmp_path, f'h=$(edge_lock_acquire {shlex.quote(str(lock))} 0 900 0); edge_lock_release "$h"', timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
