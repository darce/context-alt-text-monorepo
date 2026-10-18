"""Review guards for the shared edge helper and app-portal (review 1312, findings F1-F5).

Bounded module for lane fix-portal-helper-guards. It drives scripts/deploy/lib/shared-edge.sh
and scripts/deploy/app-portal.sh through bash only, with temporary paths and scratch docker
stubs. It never opens the live VM, /opt, Caddy, the Docker daemon, a database, secrets or a GPU.

Exact return codes are asserted so that a missing function cannot pass as a refusal. The
existing 61 cases in test_gtmr_shared_edge_helper.py are not modified by this module.

  F1  protected operations are bounded and ownership is checked before each one
  F2  numeric lock arguments are canonical and range-checked before any holder starts
  F3  every supported spelling of a protected host is refused before candidate emission
  F4  producer failures under a conditional caller are refused, not reported as accepted
  F5  an END marker without a trailing newline is preserved byte for byte
"""

from __future__ import annotations

import fcntl
import os
import shlex
import shutil
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LIB = REPO_ROOT / "scripts" / "deploy" / "lib" / "shared-edge.sh"
APP_PORTAL = REPO_ROOT / "scripts" / "deploy" / "app-portal.sh"
SNIPPET = REPO_ROOT / "infra" / "oci" / "app" / "Caddyfile.app"
OVERLAY = REPO_ROOT / "infra" / "oci" / "app" / "docker-compose.app.yml"
REPO_CADDYFILE = REPO_ROOT / "apps" / "prototype-description-service" / "Caddyfile"
REAL_AWK = shutil.which("awk") or "/usr/bin/awk"

BEGIN = "# BEGIN APP_PORTAL_VHOST"
END = "# END APP_PORTAL_VHOST"
AURA_HOSTS = (
    "auraface.dev.altcontext.com",
    "auraface.staging.api.altcontext.com",
    "auraface.api.altcontext.com",
)
EXISTING_PROTECTED = ("api.altcontext.com", "demo.altcontext.com", "dl.darce.xyz")


# ----------------------------------------------------------------- shared fixtures


def _q(value: str) -> str:
    return shlex.quote(value)


def _clean_env(tmp: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
        "HOME": str(tmp),
        "TMPDIR": str(tmp),
        "EDGE_LOCK_STATE_ROOT": str(tmp / "state"),
    }
    env.update(extra or {})
    return env


def _bash(
    tmp: Path, script: str, *, extra_env: dict[str, str] | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    (tmp / "state").mkdir(exist_ok=True)
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
    return _bash(tmp, f"set -euo pipefail\nsource {_q(str(LIB))}\n{body}", extra_env=extra_env, timeout=timeout)


def _flock_free(lock: Path) -> bool:
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


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _executable(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _render_block() -> str:
    text = SNIPPET.read_text(encoding="utf-8")
    text = (
        text.replace("__APP_HOSTNAME__", "app.altcontext.com")
        .replace("__APP_UPSTREAM__", "prod-api:8000")
        .replace("__APP_FRONTEND_ROOT__", "/srv/app-portal")
    )
    return text if text.endswith("\n") else text + "\n"


BASE = REPO_CADDYFILE.read_text(encoding="utf-8")
BLOCK = _render_block()


def _run_effective(tmp: Path, base: Path, live: Path) -> subprocess.CompletedProcess[str]:
    return _call(tmp, f"edge_effective_caddyfile {_q(str(base))} {_q(str(live))}")


def _holder_pids(tmp: Path) -> list[int]:
    return [int(p.read_text(encoding="utf-8").strip()) for p in (tmp / "state").glob("shared-edge-lock.*/holder.pid")]


def _kill_holder(tmp: Path, lock: Path) -> None:
    pids = _holder_pids(tmp)
    assert pids, "a live holder must have published its pid"
    for pid in pids:
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not _flock_free(lock):
        time.sleep(0.1)


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
        "EDGE_LOCK_STATE_ROOT": str(tmp / "state"),
    }


def _run_portal(
    tmp: Path, args: list[str], env: dict[str, str], *, timeout: int = 90
) -> subprocess.CompletedProcess[str]:
    (tmp / "state").mkdir(exist_ok=True)
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


def _caddy_bind_config(caddyfile: Path) -> str:
    return (
        '{"services":{"caddy":{"volumes":[{"type":"bind","source":"'
        + str(caddyfile)
        + '","target":"/etc/caddy/Caddyfile"}]}}}'
    )


def _portal_docker(tmp: Path, caddyfile: Path, prelude: str = "") -> str:
    """Docker stub: logs argv, answers `compose version`, and emits the bind-mount model.

    `prelude` runs before the `config` answer, so a test can stall or kill the holder there.
    """
    config = _caddy_bind_config(caddyfile)
    log = tmp / "docker-argv.log"
    return (
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >>{_q(str(log))}\n"
        'if [ "${1:-}" = compose ] && [ "${2:-}" = version ]; then exit 0; fi\n'
        f'case " $* " in *" config "*) {prelude}printf \'%s\\n\' {_q(config)}; exit 0 ;; esac\n'
        "exit 0\n"
    )


def _network_model_stub(tmp: Path, *, prelude: str = "") -> Path:
    model = (
        '{"services":{"caddy":{"networks":{"acx-prod-net":null,"edge-alias-net":null}}},'
        '"networks":{"acx-prod-net":{"name":"acx-prod-net","external":true},'
        '"edge-alias-net":{"name":"acx-real-edge","external":true}}}'
    )
    (tmp / "config.json").write_text(model, encoding="utf-8")
    body = (
        "#!/usr/bin/env bash\n"
        f"{prelude}"
        'case " $* " in *" config "*) cat ' + _q(str(tmp / "config.json")) + "; exit 0 ;; esac\n"
        "exit 0\n"
    )
    _executable(tmp / "bin" / "docker", body)
    return tmp / "bin"


def _networks_script(base: Path) -> str:
    absent_overlay = base.parent / "absent-overlay.yml"
    return f"edge_required_networks {_q(str(base))} {_q(str(absent_overlay))} || {{ echo REFUSED; exit 7; }}\n"


# ------------------------------------------------------ F1: bounded ownership


def test_lock_check_refuses_when_the_hold_cannot_cover_a_bounded_operation(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 2 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    try:
        checked = _call(tmp_path, f"edge_lock_check {_q(handle)} 120")
        assert checked.returncode == 3, (
            "a 2-second hold cannot cover a 120-second operation\n" + checked.stdout + checked.stderr
        )
    finally:
        _call(tmp_path, f"edge_lock_release {_q(handle)}")


def test_lock_check_accepts_a_hold_that_covers_the_operation(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    try:
        checked = _call(tmp_path, f"edge_lock_check {_q(handle)} 120")
        assert checked.returncode == 0, checked.stdout + checked.stderr
    finally:
        _call(tmp_path, f"edge_lock_release {_q(handle)}")


def test_lock_check_refuses_after_hold_expiry(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 1 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    time.sleep(3)
    checked = _call(tmp_path, f"edge_lock_check {_q(handle)} 1")
    assert checked.returncode == 3, (
        "an expired hold must not admit a protected operation\n" + checked.stdout + checked.stderr
    )
    _call(tmp_path, f"edge_lock_release {_q(handle)}")


def test_lock_check_refuses_when_the_holder_is_killed(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    _kill_holder(tmp_path, lock)
    checked = _call(tmp_path, f"edge_lock_check {_q(handle)} 1")
    assert checked.returncode == 3, (
        "a lost holder must not admit a protected operation\n" + checked.stdout + checked.stderr
    )
    _call(tmp_path, f"edge_lock_release {_q(handle)}")


def test_release_after_the_holder_is_killed_fails_closed(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    _kill_holder(tmp_path, lock)
    released = _call(tmp_path, f"edge_lock_release {_q(handle)}")
    assert released.returncode != 0, (
        "a holder that vanished while held must not report a clean release\n" + released.stdout + released.stderr
    )
    assert _state_dirs(tmp_path) == []


def test_clean_release_still_reports_zero_control(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    released = _call(tmp_path, f"edge_lock_release {_q(acquired.stdout.strip())}")
    assert released.returncode == 0, released.stdout + released.stderr
    assert _flock_free(lock)


def test_required_networks_are_bounded_by_the_operation_deadline(tmp_path: Path) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    bin_dir = _network_model_stub(tmp_path, prelude="sleep 30\n")
    started = time.monotonic()
    result = _call(
        tmp_path,
        _networks_script(base),
        extra_env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}", "EDGE_OP_DEADLINE": "2"},
        timeout=60,
    )
    elapsed = time.monotonic() - started
    assert result.returncode == 7, (
        "a stalled compose producer must be refused by the deadline\n" + result.stdout + result.stderr
    )
    assert "REFUSED" in result.stdout
    assert elapsed < 20, f"the compose read was not bounded: {elapsed:.1f}s"


@pytest.mark.parametrize("deadline", ["0", "08", "999999"])
def test_operation_deadline_must_be_canonical_and_bounded(tmp_path: Path, deadline: str) -> None:
    base = _write(tmp_path / "compose" / "docker-compose.caddy.yml", "services: {}\n")
    bin_dir = _network_model_stub(tmp_path)
    result = _call(
        tmp_path,
        _networks_script(base),
        extra_env={"PATH": f"{bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}", "EDGE_OP_DEADLINE": deadline},
    )
    assert result.returncode == 7, f"EDGE_OP_DEADLINE={deadline!r} must be refused\n" + result.stdout + result.stderr


def test_app_portal_refuses_when_a_protected_docker_call_exceeds_its_deadline(tmp_path: Path) -> None:
    env = _portal_env(tmp_path, "app.altcontext.com")
    backend = Path(env["CADDY_COMPOSE"]).parent
    _write(backend / "docker-compose.caddy.yml", "services: {}\n")
    caddyfile = Path(env["CADDYFILE"])
    _write(caddyfile, BASE)
    before = caddyfile.read_bytes()
    bin_dir = _executable(tmp_path / "bin" / "docker", _portal_docker(tmp_path, caddyfile, prelude="sleep 30; "))
    env["PATH"] = f"{bin_dir.parent}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"
    env["EDGE_OP_DEADLINE"] = "2"
    lock = Path(env["APP_ROOT"]) / "activation.journal.lock"
    lock.write_text("", encoding="utf-8")
    started = time.monotonic()
    result = _run_portal(tmp_path, ["--apply"], env)
    elapsed = time.monotonic() - started
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert elapsed < 25, f"the protected docker call ran past its deadline: {elapsed:.1f}s"
    assert "deadline" in output.lower(), output
    assert caddyfile.read_bytes() == before
    assert not (Path(env["APP_ROOT"]) / "activation.journal").exists()
    assert not (Path(env["APP_ROOT"]) / "docker-compose.app.yml").exists()
    assert _flock_free(lock), "the deploy lock must be released after a deadline refusal"


def test_app_portal_refuses_the_next_protected_operation_after_holder_loss(tmp_path: Path) -> None:
    env = _portal_env(tmp_path, "app.altcontext.com")
    backend = Path(env["CADDY_COMPOSE"]).parent
    _write(backend / "docker-compose.caddy.yml", "services: {}\n")
    caddyfile = Path(env["CADDYFILE"])
    _write(caddyfile, BASE)
    before = caddyfile.read_bytes()
    kill_holders = (
        f"for f in {_q(str(tmp_path / 'state'))}/shared-edge-lock.*/holder.pid; do "
        '[ -f "$f" ] && kill -KILL "$(cat "$f")" 2>/dev/null; done; '
    )
    bin_dir = _executable(tmp_path / "bin" / "docker", _portal_docker(tmp_path, caddyfile, prelude=kill_holders))
    env["PATH"] = f"{bin_dir.parent}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"
    lock = Path(env["APP_ROOT"]) / "activation.journal.lock"
    lock.write_text("", encoding="utf-8")
    result = _run_portal(tmp_path, ["--apply"], env)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "shared edge lock" in output.lower(), "a lost lock must refuse before the next protected step\n" + output
    log = tmp_path / "docker-argv.log"
    argv = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    assert not [line for line in argv if " up " in f" {line} " or " exec " in f" {line} "], argv
    assert caddyfile.read_bytes() == before
    assert not (Path(env["APP_ROOT"]) / "docker-compose.app.yml").exists()


# ----------------------------------------------- F2: canonical numeric arguments


@pytest.mark.parametrize("wait", ["08", "00", "007", "9223372036854775808"])
def test_lock_wait_rejects_noncanonical_or_overflowing_values_before_any_holder(tmp_path: Path, wait: str) -> None:
    lock = _lock_tree(tmp_path)
    inode = lock.stat().st_ino
    result = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} {_q(wait)} 900 0")
    assert result.returncode == 2, f"wait={wait!r}\n" + result.stdout + result.stderr
    assert result.stdout.strip() == ""
    assert lock.stat().st_ino == inode
    assert _flock_free(lock)
    assert _state_dirs(tmp_path) == [], "no holder state may be created for a refused wait"


@pytest.mark.parametrize("hold", ["08", "007", "00", "0", "9223372036854775808", "99999999999999999999"])
def test_hold_cap_rejects_noncanonical_or_overflowing_values_before_any_holder(tmp_path: Path, hold: str) -> None:
    lock = _lock_tree(tmp_path)
    inode = lock.stat().st_ino
    result = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 {_q(hold)} 0")
    assert result.returncode == 2, f"hold={hold!r}\n" + result.stdout + result.stderr
    assert result.stdout.strip() == ""
    assert lock.stat().st_ino == inode
    assert _flock_free(lock)
    assert _state_dirs(tmp_path) == [], "a refused hold must never create a holder that outlives the refusal"


@pytest.mark.parametrize("owner", ["08", "00", "9223372036854775808"])
def test_owner_pid_rejects_noncanonical_values_before_any_holder(tmp_path: Path, owner: str) -> None:
    lock = _lock_tree(tmp_path)
    result = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 900 {_q(owner)}")
    assert result.returncode == 2, f"owner={owner!r}\n" + result.stdout + result.stderr
    assert result.stdout.strip() == ""
    assert _flock_free(lock)
    assert _state_dirs(tmp_path) == []


def test_release_deadline_rejects_noncanonical_value_and_keeps_the_lock(tmp_path: Path) -> None:
    lock = _lock_tree(tmp_path)
    acquired = _call(tmp_path, f"edge_lock_acquire {_q(str(lock))} 0 900 0")
    assert acquired.returncode == 0, acquired.stdout + acquired.stderr
    handle = acquired.stdout.strip()
    refused = _call(tmp_path, f"edge_lock_release {_q(handle)} 08")
    assert refused.returncode == 2, (
        "a noncanonical release deadline must be refused\n" + refused.stdout + refused.stderr
    )
    assert not _flock_free(lock), "a refused release must leave the lock held"
    released = _call(tmp_path, f"edge_lock_release {_q(handle)}")
    assert released.returncode == 0, released.stdout + released.stderr


# ----------------------------------------------- F3: every spelling of a protected host


PROTECTED_UNDER_TEST = (*AURA_HOSTS, *EXISTING_PROTECTED)
CLAIM_FORMS: dict[str, Callable[[str], str]] = {
    "scheme": lambda h: "https://" + h + " {",
    "explicit-port": lambda h: h + ":443 {",
    "nonstandard-port": lambda h: h + ":8443 {",
    "space-separated": lambda h: "app.altcontext.com " + h + " {",
    "indented": lambda h: "    " + h + " {",
    "uppercase": lambda h: h.upper() + " {",
    "path-suffix": lambda h: h + "/portal {",
    "trailing-dot": lambda h: h + ". {",
}


def _claim(line: str) -> str:
    assert BLOCK.count("app.altcontext.com {") == 1
    return BLOCK.replace("app.altcontext.com {", line, 1)


@pytest.mark.parametrize("host", PROTECTED_UNDER_TEST)
@pytest.mark.parametrize("form", sorted(CLAIM_FORMS))
def test_effective_caddyfile_refuses_every_supported_spelling_of_a_protected_host(
    tmp_path: Path, host: str, form: str
) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + _claim(CLAIM_FORMS[form](host)))
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, f"{form} claim of {host} must be refused\n" + result.stdout
    assert "protected" in result.stderr.lower(), (
        f"{form} claim of {host} must be refused as a protected host\n" + result.stderr
    )
    assert result.stdout == ""


@pytest.mark.parametrize("line", ["*.altcontext.com {", "*.api.altcontext.com {", ":443 {", "{$APP_HOST} {", "[::1] {"])
def test_effective_caddyfile_refuses_wildcard_and_unparsed_site_addresses(tmp_path: Path, line: str) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + _claim(line))
    result = _run_effective(tmp_path, base, live)
    assert result.returncode != 0, f"unparsed or generic site address {line!r} must be refused\n" + result.stdout
    assert result.stdout == ""


@pytest.mark.parametrize(
    "line",
    [
        "app.altcontext.com {",
        "https://app.altcontext.com {",
        "    app.altcontext.com {",
        "app.altcontext.com, www.app.altcontext.com {",
    ],
)
def test_effective_caddyfile_accepts_unprotected_supported_site_spellings(tmp_path: Path, line: str) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + _claim(line))
    result = _run_effective(tmp_path, base, live)
    assert result.returncode == 0, f"unprotected site {line!r} must remain accepted\n" + result.stdout + result.stderr


@pytest.mark.parametrize(
    "hostname", [h.upper() for h in AURA_HOSTS] + ["Demo.AltContext.com", "auraface.api.altcontext.com."]
)
def test_app_portal_refuses_protected_hosts_regardless_of_case_or_trailing_dot(tmp_path: Path, hostname: str) -> None:
    result = _run_portal(tmp_path, ["--dry-run"], _portal_env(tmp_path, hostname))
    assert result.returncode == 2, f"{hostname} must be refused as a protected host\n" + result.stdout + result.stderr
    assert "existing Caddy host" in result.stderr


# ------------------------------------------- F4: producer failure under conditional callers


def _failing_tool_dir(tmp: Path, tool: str) -> Path:
    shim_dir = tmp / f"fail-{tool}"
    _executable(shim_dir / tool, "#!/bin/sh\nexit 23\n")
    return shim_dir


@pytest.mark.parametrize("with_block", [False, True], ids=["no-block", "with-block"])
def test_effective_caddyfile_refuses_when_cat_fails_under_a_conditional_caller(
    tmp_path: Path, with_block: bool
) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + BLOCK if with_block else BASE)
    shim = _failing_tool_dir(tmp_path, "cat")
    script = (
        "set -euo pipefail\n"
        f"source {_q(str(LIB))}\n"
        f"if edge_effective_caddyfile {_q(str(base))} {_q(str(live))}; then echo ACCEPTED; else echo REFUSED; fi\n"
    )
    result = _bash(tmp_path, script, extra_env={"PATH": f"{shim}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"})
    assert "ACCEPTED" not in result.stdout, (
        "a failed cat must not be reported as an accepted candidate\n" + result.stdout + result.stderr
    )
    assert "REFUSED" in result.stdout


def test_effective_caddyfile_refuses_when_the_block_producer_fails(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + BLOCK)
    shim = tmp_path / "fail-block-awk" / "awk"
    _executable(
        shim,
        f'#!/bin/sh\ncase "$*" in *"-v a="*) exit 23 ;; esac\nexec {_q(REAL_AWK)} "$@"\n',
    )
    script = (
        "set -euo pipefail\n"
        f"source {_q(str(LIB))}\n"
        f"if edge_effective_caddyfile {_q(str(base))} {_q(str(live))}; then echo ACCEPTED; else echo REFUSED; fi\n"
    )
    result = _bash(
        tmp_path, script, extra_env={"PATH": f"{shim.parent}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"}
    )
    assert "ACCEPTED" not in result.stdout, result.stdout + result.stderr
    assert "REFUSED" in result.stdout


# ----------------------------------------------- F5: byte preservation at EOF


def test_effective_caddyfile_preserves_an_end_marker_without_a_trailing_newline(tmp_path: Path) -> None:
    base = _write(tmp_path / "base" / "Caddyfile", BASE)
    block_no_eol = BLOCK.rstrip("\n")
    assert block_no_eol.endswith(END)
    live = _write(tmp_path / "live" / "Caddyfile", BASE + "\n" + block_no_eol)
    result = _run_effective(tmp_path, base, live)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == BASE + "\n" + block_no_eol, (
        "the managed block must survive exactly, including its absent final newline"
    )


@pytest.mark.parametrize("host", (*AURA_HOSTS, "api.altcontext.com"))
def test_comment_braces_cannot_hide_protected_hosts(tmp_path: Path, host: str) -> None:
    base = _write(tmp_path / "base", BASE)
    live = _write(tmp_path / "live", BEGIN + "\n# {\n" + host + " {\n respond ok\n}\n# }\n" + END + "\n")
    result = _run_effective(tmp_path, base, live)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "protected" in result.stderr.lower()
    assert result.stdout == ""


@pytest.mark.parametrize("space", ["\f", "\v", "\u00a0", "\u0085", "\u2003", "\t"])
@pytest.mark.parametrize("host", AURA_HOSTS)
def test_same_line_reopen_cannot_hide_protected_hosts(tmp_path: Path, space: str, host: str) -> None:
    base = _write(tmp_path / "base", BASE)
    block = BEGIN + "\napp.altcontext.com {\n respond ok\n}" + space + host + space + "{\n respond ok\n}\n" + END + "\n"
    result = _run_effective(tmp_path, base, _write(tmp_path / "live", block))
    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("quote", ['"', "`"])
@pytest.mark.parametrize("host", AURA_HOSTS)
def test_quoted_protected_site_address_is_refused(tmp_path: Path, quote: str, host: str) -> None:
    base = _write(tmp_path / "base", BASE)
    block = _claim(quote + "https://" + host + ":8443" + quote + " { # brace: }")
    result = _run_effective(tmp_path, base, _write(tmp_path / "live", block))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "protected" in result.stderr.lower()
    assert result.stdout == ""


def test_comments_and_quoted_directive_braces_preserve_safe_block_bytes(tmp_path: Path) -> None:
    base = _write(tmp_path / "base", BASE)
    block = (
        BEGIN
        + '\n# {\n"https://app.altcontext.com:443" { # }\n header Example "} # {"\n respond `# } {`\n}\n# }\n'
        + END
    )
    result = _run_effective(tmp_path, base, _write(tmp_path / "live", block))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == BASE + "\n" + block


def test_selective_base_cat_failure_cannot_be_masked_by_successful_final_cat(tmp_path: Path) -> None:
    base = _write(tmp_path / "base", BASE)
    live = _write(tmp_path / "live", BASE + "\n" + BLOCK)
    real_cat = shutil.which("cat")
    shim = _executable(
        tmp_path / "bin" / "cat", '#!/bin/sh\ncase "$*" in */base) exit 23 ;; esac\nexec ' + _q(real_cat) + ' "$@"\n'
    )
    result = _call(
        tmp_path,
        f"if edge_effective_caddyfile {_q(str(base))} {_q(str(live))}; then echo ACCEPTED; else echo REFUSED; fi",
        extra_env={"PATH": f"{shim.parent}:{os.environ['PATH']}"},
    )
    assert "ACCEPTED" not in result.stdout, result.stdout + result.stderr
    assert result.stdout == "REFUSED\n"


@pytest.mark.parametrize(
    "present_optional", [[], ["acx-staging-auraface-net"], ["acx-staging-auraface-net", "acx-prod-auraface-net"]]
)
def test_effective_generation_uses_actual_compose_argv_for_dev_only_networks(
    tmp_path: Path, present_optional: list[str]
) -> None:
    import json

    real_docker = shutil.which("docker")
    assert real_docker, "actual Compose config producer is required"
    base_text = (REPO_ROOT / "apps/prototype-description-service/docker-compose.caddy.yml").read_text()
    base_text = base_text.replace("- acx-prod-net", "- prod-alias").replace(
        "  acx-prod-net:\n    external: true", "  prod-alias:\n    name: acx-prod-net\n    external: true"
    )
    base = _write(tmp_path / "docker-compose.caddy.yml", base_text)
    overlay = _write(
        tmp_path / "installed-overlay.yml",
        "services:\n  caddy:\n    volumes:\n      - " + str(tmp_path / "www") + ":/srv/app-portal:ro\n",
    )
    mandatory = [
        "acx-prod-net",
        "acx-staging-net",
        "acx-dev-net",
        "acx-dev-fir-net",
        "acx-demo-net",
        "acx-dev-auraface-net",
    ]
    inventory = _write(tmp_path / "networks", "\n".join(mandatory + present_optional) + "\n")
    # Delegate ONLY the real, daemon-free Compose config producer. No Docker
    # daemon mutation (or contact) is possible through this command double.
    shim = _executable(
        tmp_path / "bin" / "docker",
        '#!/bin/bash\nif [[ "$*" == "network ls --format "* ]]; then cat '
        + _q(str(inventory))
        + '; exit; fi\nif [[ " $* " == " compose "*" config "* ]]; then exec '
        + _q(real_docker)
        + ' "$@"; fi\nexit 97\n',
    )
    body = f"""edge_compose_args {_q(str(base))} {_q(str(overlay))}
edge_bounded_run docker compose "${{EDGE_COMPOSE_ARGV[@]}}" config --format json > {_q(str(tmp_path / "actual.json"))}
# Inventory can change after selection. Required networks must describe the
# selected immutable generation, and must not delete the parent argv's model.
printf '%s\n' acx-staging-auraface-net acx-prod-auraface-net >> {_q(str(inventory))}
edge_required_networks {_q(str(base))} {_q(str(overlay))}
edge_bounded_run docker compose "${{EDGE_COMPOSE_ARGV[@]}}" config --format json > /dev/null
if declare -F edge_compose_cleanup >/dev/null; then edge_compose_cleanup; fi
"""
    result = _call(tmp_path, body, extra_env={"PATH": f"{shim.parent}:{os.environ['PATH']}"})
    assert result.returncode == 0, result.stdout + result.stderr
    model = json.loads((tmp_path / "actual.json").read_text())
    actual = {model["networks"][key]["name"] for key in model["services"]["caddy"]["networks"]}
    expected = set(mandatory + present_optional)
    assert actual == expected, "effective argv still requires absent Aura staging/production networks"
    assert set(result.stdout.splitlines()) == expected
    assert {net["name"] for net in model["networks"].values()} == expected
    assert any(mount["target"] == "/srv/app-portal" for mount in model["services"]["caddy"]["volumes"])
    assert all(net["external"] for net in model["networks"].values())
    assert not list(tmp_path.glob("shared-edge-compose.*.json")), "generated models must have explicit cleanup"


def test_effective_generation_refuses_unreadable_network_inventory(tmp_path: Path) -> None:
    real_docker = shutil.which("docker")
    assert real_docker
    base = _write(
        tmp_path / "docker-compose.caddy.yml",
        (REPO_ROOT / "apps/prototype-description-service/docker-compose.caddy.yml").read_text(),
    )
    shim = _executable(
        tmp_path / "bin" / "docker",
        '#!/bin/bash\nif [[ "$*" == "network ls --format "* ]]; then exit 23; fi\nif [[ " $* " == " compose "*" config "* ]]; then exec '
        + _q(real_docker)
        + ' "$@"; fi\nexit 97\n',
    )
    result = _call(
        tmp_path,
        f'if edge_compose_args {_q(str(base))} ""; then echo ACCEPTED; else printf "REFUSED %s\\n" "${{#EDGE_COMPOSE_ARGV[@]}}"; fi',
        extra_env={"PATH": f"{shim.parent}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "REFUSED 0\n"
    assert "inventory" in result.stderr
    assert not list(tmp_path.glob("shared-edge-compose.*.json"))


@pytest.mark.parametrize("host", (*AURA_HOSTS, "api.altcontext.com"))
@pytest.mark.parametrize("slashes", [2, 4])
def test_even_backslashes_before_quote_cannot_hide_a_protected_site(tmp_path: Path, host: str, slashes: int) -> None:
    # Caddy consumes a pair of backslashes as literal characters, then the
    # following quote closes the string. Treating the second slash as escaping
    # that quote would hide a real site through the quote in the last comment.
    base = _write(tmp_path / "base", BASE)
    block = (
        BEGIN
        + '\napp.altcontext.com {\n respond "'
        + "\\" * slashes
        + '"\n}\n'
        + host
        + ' {\n respond ok\n}\n# " }\n'
        + END
    )
    result = _run_effective(tmp_path, base, _write(tmp_path / "live", block))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "protected" in result.stderr.lower()
    assert result.stdout == ""


def test_literal_backslash_string_and_comment_quote_preserve_safe_sites(tmp_path: Path) -> None:
    base = _write(tmp_path / "base", BASE)
    block = (
        BEGIN
        + '\napp.altcontext.com {\n respond "'
        + "\\" * 2
        + '"\n}\nwww.app.altcontext.com {\n respond ok\n}\n# " }\n'
        + END
    )
    result = _run_effective(tmp_path, base, _write(tmp_path / "live", block))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == BASE + "\n" + block


@pytest.mark.parametrize("slashes", [1, 3])
def test_odd_backslashes_keep_the_following_quote_literal(tmp_path: Path, slashes: int) -> None:
    base = _write(tmp_path / "base", BASE)
    # The apparent protected address is still inside the quoted response body.
    block = (
        BEGIN
        + '\napp.altcontext.com {\n respond "'
        + "\\" * slashes
        + '"\n}\nauraface.api.altcontext.com {\n respond ok\n}\n# " }\n'
        + END
    )
    result = _run_effective(tmp_path, base, _write(tmp_path / "live", block))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == BASE + "\n" + block
