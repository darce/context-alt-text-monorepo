"""Contract tests for scripts/deploy/app-portal.sh (APP-1 app host).

Filesystem-only: stub caddy/docker on PATH. Never SSH to the OCI host.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "app-portal.sh"
SNIPPET = REPO_ROOT / "infra" / "oci" / "app" / "Caddyfile.app"
OVERLAY = REPO_ROOT / "infra" / "oci" / "app" / "docker-compose.app.yml"
ENV_EXAMPLE = REPO_ROOT / "infra" / "oci" / "app" / "env.example"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "app-portal-deploy.md"
LIVE_CADDY_SRC = REPO_ROOT / "apps" / "prototype-description-service" / "Caddyfile"

EXISTING_HOSTS = (
    "api.altcontext.com",
    "staging.api.altcontext.com",
    "dev.api.altcontext.com",
    "fir.dev.api.altcontext.com",
    "demo.altcontext.com",
    "129-213-40-111.sslip.io",
    "dl.darce.xyz",
)

SECRET_MARKERS = (
    "pk_live_",
    "pk_test_",
    "sk_live_",
    "sk_test_",
    "CLERK_SECRET_KEY",
    "POLAR_ACCESS_TOKEN",
    "POLAR_WEBHOOK_SECRET",
    "RECOGNITION_ADMIN_TOKEN",
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _frontend_index(label: str) -> str:
    return (
        f'<link rel="stylesheet" href="/assets/index.css">'
        f'<script type="module" src="/assets/index.js"></script><!-- {label} -->'
    )


def _write_frontend(
    root: Path,
    *,
    index: str | None = None,
) -> Path:
    dist = root / "frontend-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    if index is None:
        index = _frontend_index("app")
    (dist / "index.html").write_text(index, encoding="utf-8")
    (assets / "index.js").write_text("console.log('app-portal');\n", encoding="utf-8")
    (assets / "index.css").write_text("body { color: black; }\n", encoding="utf-8")
    return dist


def _write_live_caddy(path: Path, body: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body is not None else LIVE_CADDY_SRC.read_text(encoding="utf-8"), encoding="utf-8")


def _write_caddy_compose(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("services:\n  caddy:\n    image: caddy:2\n", encoding="utf-8")
    return path


def _caddy_stub(log_path: str, *, fail: bool = False) -> str:
    exit_code = 1 if fail else 0
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'caddy' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        f"if [ {exit_code} -ne 0 ]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )


def _docker_stub(
    log_path: str, compose_marker: str, *, fail_first_reload: bool = False,
    mount_root: Path | None = None, readiness_polls: int = 0,
    compose_config: str | None = None,
    compose_overlay_config: str | None = None,
) -> str:
    if compose_config is None:
        compose_config = json.dumps({"services": {"caddy": {"volumes": [{
            "type": "bind", "source": str(Path(compose_marker).parent / "opt/acx-backend/Caddyfile"),
            "target": "/etc/caddy/Caddyfile",
        }]}}})
    compose_marker_quoted = shlex.quote(compose_marker)
    reload_failure_marker = shlex.quote(f"{compose_marker}.failed-first-reload")
    failure_rule = (
        f'  if [ "$compose_reload" -eq 1 ] && [ ! -e {reload_failure_marker} ]; then\n'
        f'    : > {reload_failure_marker}\n'
        "    exit 1\n"
        "  fi\n"
        if fail_first_reload else ""
    )
    readiness_state = shlex.quote(f"{compose_marker}.readiness")
    startup_state = shlex.quote(f"{compose_marker}.startups")
    readiness_rule = (
        '  if [ "$compose_up" -eq 1 ]; then\n'
        f'    startup=$(cat {startup_state} 2>/dev/null || echo 0)\n'
        f'    echo "$((startup + 1))" > {startup_state}\n'
        f'    polls={readiness_polls}\n'
        # An exhausted first startup still allows rollback to become ready.
        '    [ "$startup" -eq 0 ] || polls=2\n'
        f'    echo "$polls" > {readiness_state}\n'
        '  fi\n'
        '  if [ "$compose_probe" -eq 1 ]; then\n'
        f'    polls=$(cat {readiness_state})\n'
        '    if [ "$polls" -gt 0 ]; then\n'
        f'      echo "$((polls - 1))" > {readiness_state}\n'
        '      exit 1\n'
        '    fi\n'
        '  fi\n'
        '  if [ "$compose_reload" -eq 1 ]; then\n'
        f'    polls=$(cat {readiness_state} 2>/dev/null || echo 0)\n'
        '    [ "$polls" -eq 0 ] || exit 1\n'
        '  fi\n'
    ) if readiness_polls else ""
    # Model a bind mount that retains the original directory after a host swap.
    # Only creating/recreating the service captures the new frontend contents.
    mount_rule = ""
    if mount_root is not None:
        source = shlex.quote(str(mount_root / "index.html"))
        snapshot = shlex.quote(f"{compose_marker}.mounted-index")
        mount_rule = (
            '  if [ "$compose_up" -eq 1 ] && '
            f'{{ [ "$compose_recreate" -eq 1 ] || [ ! -e {snapshot} ]; }}; then\n'
            f'    cp {source} {snapshot} || exit 1\n'
            "  fi\n"
            '  if [ "$compose_reload" -eq 1 ]; then\n'
            f"    printf 'mounted-index %q\\n' \"$(cat {snapshot})\" >> {log_path}\n"
            "  fi\n"
        )
    return (
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'docker' >> {log_path}\n"
        f"printf ' %q' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        'if [ "${1:-}" = "compose" ]; then\n'
        "  compose_up=0\n"
        "  compose_probe=0\n"
        "  compose_reload=0\n"
        "  compose_recreate=0\n"
        "  compose_config_request=0\n"
        f"  resolved_config={shlex.quote(compose_config)}\n"
        '  for arg in "$@"; do\n'
        '    [ "$arg" != "config" ] || compose_config_request=1\n'
        + (f'    case "$arg" in -|*/docker-compose.app.yml) resolved_config={shlex.quote(compose_overlay_config)} ;; esac\n'
           if compose_overlay_config is not None else "")
        + '    [ "$arg" != "-" ] || cat >/dev/null\n'
        '    [ "$arg" = "wget" ] && compose_probe=1\n'
        '    [ "$arg" = "up" ] && compose_up=1\n'
        '    [ "$arg" = "reload" ] && compose_reload=1\n'
        '    [ "$arg" = "--force-recreate" ] && compose_recreate=1\n'
        "  done\n"
        '  if [ "$compose_config_request" -eq 1 ]; then\n'
        '    printf "%s\\n" "$resolved_config"\n'
        '    exit 0\n'
        '  fi\n'
        f'  [ "$compose_up" -eq 0 ] || : > {compose_marker_quoted}\n'
        + readiness_rule + mount_rule + failure_rule
        + "fi\n"
        + "exit 0\n"
    )


def _expected_compose_reload(backend_root: Path, overlay: Path | None = None) -> list[str]:
    argv = ["docker", "compose", "-f", str(backend_root / "docker-compose.caddy.yml")]
    if overlay is not None:
        argv.extend(["-f", str(overlay)])
    argv.extend(
        [
            "exec", "-T", "caddy", "caddy", "reload", "--config",
            "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
        ]
    )
    return argv


def _compose_reload_calls(tmp_path: Path) -> list[list[str]]:
    calls = []
    for line in _log(tmp_path).splitlines():
        argv = shlex.split(line)
        if argv[:2] == ["docker", "compose"] and "exec" in argv and "reload" in argv:
            calls.append(argv)
    return calls


def _run(
    tmp_path: Path,
    *,
    args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    frontend: Path | None | str = "",
    live_caddy: Path | None | str = "",
    upstream: str | None = "prod-api:8000",
    hostname: str | None = "app.altcontext.com",
    caddy_fail: bool = False,
    docker_fail_first_reload: bool = False,
    fail_mv_dest: Path | None = None,
    corrupt_staged_frontend: bool = False,
    include_caddy: bool = True,
    include_docker: bool = True,
    model_mount: bool = False,
    readiness_polls: int = 0,
    compose_config: str | None = None,
    compose_overlay_config: str | None = None,
    timeout: int = 20,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    app_root.mkdir(parents=True, exist_ok=True)
    backend_root = tmp_path / "opt" / "acx-backend"
    backend_root.mkdir(parents=True, exist_ok=True)
    caddy_compose = backend_root / "docker-compose.caddy.yml"
    if not caddy_compose.exists():
        _write_caddy_compose(caddy_compose)
    compose_marker = tmp_path / "compose-applied"

    if include_caddy:
        _write_executable(
            bin_dir / "caddy",
            _caddy_stub(log_path, fail=caddy_fail),
        )
    if include_docker:
        _write_executable(
            bin_dir / "docker",
            _docker_stub(
                log_path,
                str(compose_marker),
                fail_first_reload=docker_fail_first_reload,
                mount_root=app_root / "www" if model_mount else None,
                readiness_polls=readiness_polls,
                compose_config=compose_config,
                compose_overlay_config=compose_overlay_config,
            ),
        )
    if readiness_polls:
        _write_executable(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
    health = bin_dir / "health-check"
    _write_executable(health, "#!/usr/bin/env bash\nexit 0\n")
    if fail_mv_dest is not None:
        dest = shlex.quote(str(fail_mv_dest))
        _write_executable(
            bin_dir / "mv",
            "#!/usr/bin/env bash\n"
            "set -u\n"
            'dest="${@: -1}"\n'
            f'if [ "$dest" = {dest} ]; then\n'
            '  echo "ERROR: simulated mv failure" >&2\n'
            "  exit 1\n"
            "fi\n"
            'exec /bin/mv "$@"\n',
        )
    if corrupt_staged_frontend:
        _write_executable(
            bin_dir / "cp",
            "#!/usr/bin/env bash\n"
            "set -u\n"
            '/bin/cp "$@" || exit $?\n'
            'if [ "${1:-}" = "-a" ] && [ "${2:-}" = "${FRONTEND_DIST}/." ]; then\n'
            '  printf \'<script type="module" src="/assets/missing.js"></script>\\n\' > "$3/index.html"\n'
            "fi\n",
        )

    if live_caddy is None:
        caddy_path = None
    elif live_caddy == "":
        caddy_path = backend_root / "Caddyfile"
        _write_live_caddy(caddy_path)
    else:
        caddy_path = Path(live_caddy)
        if not caddy_path.exists():
            _write_live_caddy(caddy_path)

    if frontend is None:
        frontend_path = None
    elif frontend == "":
        frontend_path = _write_frontend(tmp_path)
    else:
        frontend_path = Path(frontend)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    env["APP_ROOT"] = str(app_root)
    env["APP_WWW"] = str(app_root / "www")
    env["CADDY_COMPOSE"] = str(caddy_compose)
    env.pop("DRY_RUN", None)
    env.pop("APP_PORTAL_APPLY", None)
    env.pop("FRONTEND_DIST", None)
    env.pop("CADDYFILE", None)
    env.pop("APP_UPSTREAM", None)
    env.pop("APP_HOSTNAME", None)
    env.pop("SSH", None)
    env.pop("OCI_HOST", None)

    if caddy_path is not None:
        env["CADDYFILE"] = str(caddy_path)
    if frontend_path is not None:
        env["FRONTEND_DIST"] = str(frontend_path)
    if upstream is not None:
        env["APP_UPSTREAM"] = upstream
    if hostname is not None:
        env["APP_HOSTNAME"] = hostname
    env["APP_SNIPPET"] = str(SNIPPET)
    env["APP_OVERLAY"] = str(OVERLAY)
    env["APP_APPROVED_ROOTS"] = str(backend_root)
    env["APP_RELOAD_CMD"] = ""
    env["APP_HEALTH_CMD"] = str(health)
    if extra_env:
        env.update(extra_env)

    argv = ["bash", str(SCRIPT)]
    if args:
        argv.extend(args)

    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    path = tmp_path / "commands.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _tree_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def _mounted_indexes(tmp_path: Path) -> list[str]:
    return [
        shlex.split(line)[1] for line in _log(tmp_path).splitlines()
        if line.startswith("mounted-index ")
    ]


def _assert_caddy_recreated(tmp_path: Path, count: int) -> None:
    calls = [
        shlex.split(line) for line in _log(tmp_path).splitlines()
        if line.startswith("docker compose ") and " up -d" in line
    ]
    assert len(calls) == count
    assert all(call[-5:] == ["up", "-d", "--force-recreate", "--no-deps", "caddy"] for call in calls)


def test_second_apply_and_rollback_refresh_container_mount(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    first_index = _frontend_index("first frontend")
    frontend = _write_frontend(tmp_path, index=first_index)
    first = _run(tmp_path, args=["--apply"], live_caddy=live, frontend=frontend, model_mount=True)
    assert first.returncode == 0, first.stdout + first.stderr
    second_index = _frontend_index("second frontend")
    (frontend / "index.html").write_text(second_index)
    second = _run(tmp_path, args=["--apply"], live_caddy=live, frontend=frontend, model_mount=True)
    assert second.returncode == 0, second.stdout + second.stderr
    failed_index = _frontend_index("failed frontend")
    (frontend / "index.html").write_text(failed_index)
    failed = _run(
        tmp_path, args=["--apply"], live_caddy=live, frontend=frontend,
        model_mount=True, docker_fail_first_reload=True,
    )
    assert failed.returncode != 0
    assert _mounted_indexes(tmp_path) == [
        first_index, second_index, failed_index, second_index,
    ]
    assert (live.parent / "app" / "www" / "index.html").read_text() == second_index
    assert not (live.parent / "app" / "activation.journal").exists()
    _assert_caddy_recreated(tmp_path, 4)


@pytest.mark.parametrize("invalid_frontend", ["unset", "empty_index", "deleted_directory"])
def test_recovery_precedes_replacement_frontend_validation(tmp_path: Path, invalid_frontend: str) -> None:
    from test_app_portal_activation_journal import _interrupt_after_caddy

    live = tmp_path / "opt/acx-backend/Caddyfile"
    original_caddy, www, app_root, overlay, original_overlay = _interrupt_after_caddy(tmp_path, live)
    journal = app_root / "activation.journal"
    assert journal.is_file()
    assert live.read_text() != original_caddy
    frontend = None if invalid_frontend == "unset" else _write_frontend(tmp_path, index="")
    if invalid_frontend == "deleted_directory":
        shutil.rmtree(frontend)
        assert not frontend.exists()
    before_log = _log(tmp_path)

    result = _run(tmp_path, args=["--apply"], live_caddy=live, frontend=frontend,
                  extra_env={"BASH_ENV": ""})

    assert result.returncode != 0, result.stdout + result.stderr
    assert "FRONTEND_DIST" in result.stderr
    assert "applied:" not in result.stdout
    assert live.read_text() == original_caddy
    assert (www / "keep.txt").read_text() == "active\n"
    assert not (www / "index.html").exists()
    assert overlay.read_text() == original_overlay
    assert not journal.exists()
    calls = _log(tmp_path)[len(before_log):]
    assert " up -d --force-recreate --no-deps caddy" in calls
    assert " reload " in calls
    assert " validate " not in calls

    # A retry still rejects the build, without repeating completed recovery.
    before_retry_log = _log(tmp_path)
    retry = _run(tmp_path, args=["--apply"], live_caddy=live, frontend=frontend,
                 extra_env={"BASH_ENV": ""})
    assert retry.returncode != 0, retry.stdout + retry.stderr
    assert live.read_text() == original_caddy
    assert not journal.exists()
    retry_calls = _log(tmp_path)[len(before_retry_log):]
    assert " up " not in retry_calls and " reload " not in retry_calls


@pytest.mark.parametrize("phase", ["prepared", "caddy_promoted", "www_promoted", "overlay_promoted"])
def test_recovery_refreshes_container_mount_after_restore(tmp_path: Path, phase: str) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    original_index = _frontend_index("original frontend")
    frontend = _write_frontend(tmp_path, index=original_index)
    first = _run(tmp_path, args=["--apply"], live_caddy=live, frontend=frontend, model_mount=True)
    assert first.returncode == 0, first.stdout + first.stderr
    replacement_index = _frontend_index("replacement frontend")
    (frontend / "index.html").write_text(replacement_index)
    hook = tmp_path / "interrupt.sh"
    _write_executable(
        hook,
        "sync() {\n"
        '  /bin/sync "$@" || return $?\n'
        '  if [ "${@: -1}" = "$APP_ROOT" ] && [ -f "$ACTIVATION_JOURNAL" ] && '
        f'grep -qx "phase={phase}" "$ACTIVATION_JOURNAL"; then\n'
        '    kill -KILL "$BASHPID"\n'
        "  fi\n}\n",
    )
    interrupted = _run(
        tmp_path, args=["--apply"], live_caddy=live, frontend=frontend,
        model_mount=True, extra_env={"BASH_ENV": str(hook)},
    )
    assert interrupted.returncode == -9, interrupted.stdout + interrupted.stderr
    prior_probes = _log(tmp_path).count(" wget ")
    recovered = _run(
        tmp_path, args=["--apply"], live_caddy=live, frontend=frontend,
        model_mount=True, readiness_polls=2, extra_env={"BASH_ENV": ""},
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert _log(tmp_path).count(" wget ") - prior_probes == 6
    # Recovery must recreate after copying the snapshot, before the next apply.
    assert _mounted_indexes(tmp_path) == [
        original_index, original_index, replacement_index,
    ]
    _assert_caddy_recreated(tmp_path, 3)


def test_owned_artifacts_exist() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert SNIPPET.is_file(), f"missing {SNIPPET}"
    assert OVERLAY.is_file(), f"missing {OVERLAY}"
    assert ENV_EXAMPLE.is_file(), f"missing {ENV_EXAMPLE}"
    assert RUNBOOK.is_file(), f"missing {RUNBOOK}"


def test_default_is_dry_run_and_side_effect_free(tmp_path: Path) -> None:
    caddy_path = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(caddy_path)
    _write_caddy_compose(caddy_path.parent / "docker-compose.caddy.yml")
    before = caddy_path.read_text(encoding="utf-8")
    before_files = _tree_files(tmp_path / "opt")
    result = _run(tmp_path, live_caddy=caddy_path)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "dry-run" in output.lower() or "plan:" in output.lower(), output
    assert caddy_path.read_text(encoding="utf-8") == before
    assert _tree_files(tmp_path / "opt") == before_files
    assert _log(tmp_path) == ""
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "www").exists()


def test_explicit_dry_run_does_not_copy_frontend(tmp_path: Path) -> None:
    result = _run(tmp_path, args=["--dry-run"])
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "app.altcontext.com" in output
    assert "prod-api:8000" in output
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "www").exists()
    assert _log(tmp_path) == ""


@pytest.mark.parametrize("apply", [False, True])
def test_missing_compose_plans_but_refuses_apply_without_mutation(tmp_path: Path, apply: bool) -> None:
    backend = tmp_path / "opt" / "acx-backend"
    live = backend / "Caddyfile"
    _write_live_caddy(live)
    _write_caddy_compose(backend / "docker-compose.caddy.yml")
    missing = backend / "not-installed" / "docker-compose.caddy.yml"
    before = _tree_files(tmp_path / "opt")
    live_before = live.read_bytes()
    result = _run(tmp_path, args=["--apply" if apply else "--dry-run"],
                  live_caddy=live, extra_env={"CADDY_COMPOSE": str(missing)})
    output = result.stdout + result.stderr
    if apply:
        assert result.returncode != 0, output
        assert "CADDY_COMPOSE" in result.stderr
        assert "applied:" not in result.stdout
    else:
        assert result.returncode == 0, output
        assert "plan:" in result.stdout
        assert f"CADDY_COMPOSE is absent: {missing}" in result.stdout
        assert "dry-run: no files changed" in result.stdout
    assert live.read_bytes() == live_before
    assert _tree_files(tmp_path / "opt") == before
    for name in ("staging", "rollback", "www", "activation.journal", "activation.journal.lock"):
        assert not (backend / "app" / name).exists()
    assert not missing.exists()
    assert _log(tmp_path) == ""


def test_apply_refuses_missing_frontend(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], frontend=None, live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "FRONTEND_DIST" in output
    assert live.read_text(encoding="utf-8") == before
    # Binding checks precede build validation; permit only these read-only calls.
    compose = ["docker", "compose", "-f", str(live.parent / "docker-compose.caddy.yml")]
    assert [shlex.split(line) for line in _log(tmp_path).splitlines()] == [
        ["docker", "compose", "version"],
        [*compose, "config", "--format", "json"],
        [*compose, "-f", "-", "config", "--format", "json"],
    ]
    assert not (live.parent / "app/staging").exists()
    assert not (live.parent / "app/activation.journal").exists()


def test_apply_refuses_empty_index(tmp_path: Path) -> None:
    dist = tmp_path / "empty-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("", encoding="utf-8")
    (dist / "assets" / "index.js").write_text("x\n", encoding="utf-8")
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "index.html" in output
    assert live.read_text(encoding="utf-8") == before


def test_apply_refuses_missing_assets(tmp_path: Path) -> None:
    dist = tmp_path / "no-assets"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "assets" in output.lower()
    assert live.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("index", "assets", "expected_error"),
    [
        (
            '<script type="module" src="/assets/app.js"></script>\n',
            {"old.css": "old stylesheet\n"},
            "app.js",
        ),
        (
            '<script type="module" src="/assets/ready.js"></script>'
            '<link rel="stylesheet" href="/assets/app.css">',
            {"ready.js": "app bundle\n", "old.css": "old stylesheet\n"},
            "app.css",
        ),
        (
            '<script type="module" src="/assets/app.js"></script>'
            '<link rel="stylesheet" href="/assets/empty.css">',
            {"app.js": "app bundle\n", "empty.css": ""},
            "empty asset",
        ),
        ("<!doctype html><html></html>\n", {"old.css": "old stylesheet\n"}, "no /assets/"),
    ],
)
def test_apply_refuses_invalid_referenced_assets_without_touching_live_tree(
    tmp_path: Path, index: str, assets: dict[str, str], expected_error: str
) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    www = app_root / "www"
    (www / "assets").mkdir(parents=True)
    (www / "index.html").write_text("existing portal\n", encoding="utf-8")
    (www / "assets" / "keep.js").write_text("existing asset\n", encoding="utf-8")
    overlay = app_root / "docker-compose.app.yml"
    overlay.write_text("existing overlay\n", encoding="utf-8")
    before_caddy = live.read_bytes()
    before_index = (www / "index.html").read_bytes()
    before_asset = (www / "assets" / "keep.js").read_bytes()
    before_overlay = overlay.read_bytes()

    dist = tmp_path / "partial-dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(index, encoding="utf-8")
    for name, contents in assets.items():
        (dist / "assets" / name).write_text(contents, encoding="utf-8")

    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert expected_error in output
    assert "applied:" not in result.stdout
    assert live.read_bytes() == before_caddy
    assert (www / "index.html").read_bytes() == before_index
    assert (www / "assets" / "keep.js").read_bytes() == before_asset
    assert overlay.read_bytes() == before_overlay
    assert not (app_root / "staging").exists()
    assert not (app_root / "activation.journal").exists()


def test_apply_refuses_css_only_frontend_without_touching_live_tree(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    www = _prior_www(tmp_path)
    live_before = live.read_bytes()
    www_before = (www / "keep.txt").read_bytes()
    dist = tmp_path / "css-only-dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<link rel="stylesheet" href="/assets/old.css">\n', encoding="utf-8"
    )
    (assets / "old.css").write_text("body { color: black; }\n", encoding="utf-8")

    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "module" in output.lower(), output
    assert live.read_bytes() == live_before
    assert (www / "keep.txt").read_bytes() == www_before
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "staging").exists()


@pytest.mark.parametrize(
    "module_markup",
    [
        pytest.param(
            '<template><script type="module" src="/assets/index.js"></script></template>',
            id="template",
        ),
        pytest.param(
            '<noscript><script type="module" src="/assets/index.js"></script></noscript>',
            id="noscript",
        ),
        pytest.param(
            '<script type="module" nomodule src="/assets/index.js"></script>',
            id="nomodule",
        ),
        pytest.param(
            '<script>const markup = "<script type=module src=/assets/index.js>";</script>',
            id="script-body",
        ),
        pytest.param(
            '<style>/* <script type="module" src="/assets/index.js"> */</style>',
            id="style-body",
        ),
        pytest.param(
            '<textarea><script type="module" src="/assets/index.js"></script></textarea>',
            id="textarea-body",
        ),
        pytest.param(
            '<title><script type="module" src="/assets/index.js"></script></title>',
            id="title-body",
        ),
        pytest.param(
            '<iframe><script type="module" src="/assets/index.js"></script></iframe>',
            id="iframe-body",
        ),
        pytest.param(
            '<xmp><script type="module" src="/assets/index.js"></script></xmp>',
            id="xmp-body",
        ),
        pytest.param(
            '<noembed><script type="module" src="/assets/index.js"></script></noembed>',
            id="noembed-body",
        ),
        pytest.param(
            '<noframes><script type="module" src="/assets/index.js"></script></noframes>',
            id="noframes-body",
        ),
        pytest.param(
            '<plaintext></plaintext><script type="module" src="/assets/index.js"></script>',
            id="plaintext-body",
        ),
    ],
)
def test_apply_refuses_inert_module_frontend_before_staging(
    tmp_path: Path, module_markup: str
) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    www = _prior_www(tmp_path)
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay.write_text("existing overlay\n", encoding="utf-8")
    rollback = tmp_path / "opt" / "acx-backend" / "app" / "rollback"
    rollback.mkdir()
    (rollback / "operator-notes").write_text("keep\n", encoding="utf-8")
    live_before = live.read_bytes()
    www_before = _tree_files(www)
    overlay_before = overlay.read_bytes()
    rollback_before = _tree_files(rollback)
    dist = _write_frontend(
        tmp_path,
        index=f'<link rel="stylesheet" href="/assets/index.css">{module_markup}',
    )

    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "has no /assets/*.js module script entry" in output, output
    assert "applied:" not in result.stdout
    assert live.read_bytes() == live_before
    assert _tree_files(www) == www_before
    assert overlay.read_bytes() == overlay_before
    assert _tree_files(rollback) == rollback_before
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    assert not (app_root / "staging").exists()
    assert not (app_root / "activation.journal").exists()
    assert not any(" up -d " in f" {line} " for line in _log(tmp_path).splitlines())


def test_apply_refuses_frontend_symlink_without_touching_live_tree(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    www = _prior_www(tmp_path)
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay.write_text("existing overlay\n", encoding="utf-8")
    rollback = tmp_path / "opt" / "acx-backend" / "app" / "rollback"
    rollback.mkdir()
    (rollback / "operator-notes").write_text("keep\n", encoding="utf-8")
    live_before = live.read_bytes()
    www_before = (www / "keep.txt").read_bytes()
    overlay_before = overlay.read_bytes()
    rollback_before = _tree_files(rollback)

    dist = _write_frontend(tmp_path)
    external_asset = tmp_path / "outside.js"
    external_asset.write_text("console.log('outside');\n", encoding="utf-8")
    asset = dist / "assets" / "index.js"
    asset.unlink()
    asset.symlink_to(external_asset)

    result = _run(tmp_path, args=["--apply"], frontend=dist, live_caddy=live)
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "symlink" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_bytes() == live_before
    assert (www / "keep.txt").read_bytes() == www_before
    assert overlay.read_bytes() == overlay_before
    assert _tree_files(rollback) == rollback_before
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "activation.journal").exists()


def test_apply_refuses_invalid_staged_frontend_without_touching_live_or_rollback(
    tmp_path: Path,
) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    www = _prior_www(tmp_path)
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay.write_text("existing overlay\n", encoding="utf-8")
    rollback = tmp_path / "opt" / "acx-backend" / "app" / "rollback"
    rollback.mkdir()
    (rollback / "operator-notes").write_text("keep\n", encoding="utf-8")
    live_before = live.read_bytes()
    www_before = (www / "keep.txt").read_bytes()
    overlay_before = overlay.read_bytes()
    rollback_before = _tree_files(rollback)
    dist = _write_frontend(tmp_path)

    result = _run(
        tmp_path,
        args=["--apply"],
        frontend=dist,
        live_caddy=live,
        corrupt_staged_frontend=True,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "missing asset" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_bytes() == live_before
    assert (www / "keep.txt").read_bytes() == www_before
    assert overlay.read_bytes() == overlay_before
    assert _tree_files(rollback) == rollback_before
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "staging").exists()
    assert not (tmp_path / "opt" / "acx-backend" / "app" / "activation.journal").exists()


def test_apply_refuses_path_traversal(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(
        tmp_path,
        args=["--apply"],
        frontend=tmp_path / "frontend-dist" / ".." / "frontend-dist",
        live_caddy=live,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "traversal" in output.lower() or "unsafe" in output.lower() or ".." in output
    assert live.read_text(encoding="utf-8") == before
    assert _log(tmp_path) == ""


def test_apply_refuses_unsafe_shell_values(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_UPSTREAM": "prod-api:8000;reboot"},
        upstream=None,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "unsafe" in output.lower() or "APP_UPSTREAM" in output
    assert live.read_text(encoding="utf-8") == before
    assert _log(tmp_path) == ""


def test_apply_refuses_empty_upstream(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"APP_UPSTREAM": ""}, upstream=None)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "APP_UPSTREAM" in output
    assert live.read_text(encoding="utf-8") == before


def test_apply_refuses_protected_existing_hostname(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], live_caddy=live, hostname="api.altcontext.com")
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "api.altcontext.com" in output
    assert live.read_text(encoding="utf-8") == before
    assert "reverse_proxy prod-api:8000" in live.read_text(encoding="utf-8")


def test_apply_merges_vhost_preserves_existing_hosts_and_copies_frontend(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    result = _run(tmp_path, args=["--apply"], live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    updated = live.read_text(encoding="utf-8")
    for host in EXISTING_HOSTS:
        assert host in updated, host
    assert "app.altcontext.com {" in updated
    assert "handle /portal*" not in updated
    assert "@portal path /portal /portal/*" in updated
    assert "handle @portal" in updated
    assert "reverse_proxy prod-api:8000" in updated
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    assert (www / "index.html").is_file()
    assert (www / "index.html").stat().st_size > 0
    assert any((www / "assets").iterdir())
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_text = overlay_dest.read_text(encoding="utf-8")
    assert str(www) in overlay_text
    assert f"{www}:/srv/app-portal" in overlay_text or f"{www}:/srv/app-portal:ro" in overlay_text
    assert "__APP_WWW__" not in overlay_text
    log = _log(tmp_path)
    assert "caddy" in log
    assert "validate" in log
    assert not any(line.startswith("caddy reload ") for line in log.splitlines())
    assert _compose_reload_calls(tmp_path) == [
        _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay_dest)
    ]
    assert "ssh" not in log
    rollback_dir = tmp_path / "opt" / "acx-backend" / "app" / "rollback"
    assert rollback_dir.is_dir()
    backups = list(rollback_dir.glob("Caddyfile.*"))
    assert backups, f"missing rollback artifact in {list(rollback_dir.iterdir())}"
    rollback_text = backups[0].read_text(encoding="utf-8")
    assert "app.altcontext.com {" not in rollback_text
    assert "api.altcontext.com {" in rollback_text


def test_apply_mounts_static_root_before_live_health_check(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    marker = tmp_path / "compose-applied"
    log_path = shlex.quote(str(tmp_path / "commands.log"))
    health = tmp_path / "bin" / "health-requires-compose"
    health.parent.mkdir()
    _write_executable(
        health,
        "#!/usr/bin/env bash\n"
        f"[ -f {shlex.quote(str(marker))} ] || exit 1\n"
        f"printf 'health\\n' >> {log_path}\n",
    )

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_HEALTH_CMD": str(health)},
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    log_lines = _log(tmp_path).splitlines()
    compose_index = next(i for i, line in enumerate(log_lines) if line.startswith("docker compose ") and " up -d" in line)
    reload_index = next(
        i for i, line in enumerate(log_lines)
        if line.startswith("docker compose ") and " exec -T caddy caddy reload " in line
    )
    health_index = log_lines.index("health")
    assert "docker-compose.caddy.yml" in log_lines[compose_index]
    assert "docker-compose.app.yml" in log_lines[compose_index]
    assert compose_index < reload_index < health_index
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    assert shlex.split(log_lines[reload_index]) == _expected_compose_reload(
        tmp_path / "opt" / "acx-backend", overlay
    )
    assert not any(line.startswith("caddy reload ") for line in log_lines)


def test_apply_failed_validation_leaves_live_config_and_www_intact(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    www.mkdir(parents=True)
    (www / "keep.txt").write_text("active\n", encoding="utf-8")
    result = _run(tmp_path, args=["--apply"], live_caddy=live, caddy_fail=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "validate" in output.lower() or "caddy" in output.lower()
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    for host in EXISTING_HOSTS:
        assert host in live.read_text(encoding="utf-8")


def test_apply_staging_caddy_symlink_to_live_preserves_live_config(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_bytes()
    staged_caddy = live.parent / "app" / "staging" / "Caddyfile"
    staged_caddy.parent.mkdir(parents=True)
    staged_caddy.symlink_to(live)

    result = _run(tmp_path, args=["--apply"], live_caddy=live, caddy_fail=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "staged caddy validation failed" in output.lower(), output
    assert any("caddy validate" in line for line in _log(tmp_path).splitlines())
    assert live.read_bytes() == before


def test_apply_staging_caddy_hardlink_to_live_preserves_active_files(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_bytes()
    app_root = live.parent / "app"
    www = app_root / "www"
    www.mkdir(parents=True)
    (www / "keep.txt").write_bytes(b"active frontend\n")
    overlay = app_root / "docker-compose.app.yml"
    overlay.write_bytes(b"active overlay\n")
    staged_caddy = app_root / "staging" / "Caddyfile"
    staged_caddy.parent.mkdir()
    os.link(live, staged_caddy)

    result = _run(tmp_path, args=["--apply"], live_caddy=live, caddy_fail=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert live.read_bytes() == before
    assert (www / "keep.txt").read_bytes() == b"active frontend\n"
    assert sorted(path.name for path in www.iterdir()) == ["keep.txt"]
    assert overlay.read_bytes() == b"active overlay\n"
    assert "staged Caddy path is the same file as CADDYFILE" in output, output
    assert not any("caddy validate" in line for line in _log(tmp_path).splitlines())


@pytest.mark.parametrize("target", ["backend", "app"])
def test_apply_refuses_symlink_staging_directory(tmp_path: Path, target: str) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_bytes()
    app_root = live.parent / "app"
    www = app_root / "www"
    www.mkdir(parents=True)
    (www / "keep.txt").write_bytes(b"active frontend\n")
    overlay = app_root / "docker-compose.app.yml"
    overlay.write_bytes(b"active overlay\n")
    staging = app_root / "staging"
    staging.symlink_to(live.parent if target == "backend" else app_root, target_is_directory=True)

    result = _run(tmp_path, args=["--apply"], live_caddy=live, caddy_fail=True)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert live.read_bytes() == before
    assert (www / "keep.txt").read_bytes() == b"active frontend\n"
    assert sorted(path.name for path in www.iterdir()) == ["keep.txt"]
    assert overlay.read_bytes() == b"active overlay\n"
    assert "STAGING_DIR rejects symlink component" in output, output
    assert staging.is_symlink()
    assert not any("caddy validate" in line for line in _log(tmp_path).splitlines())


def test_apply_is_idempotent_for_existing_app_vhost(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    first = _run(tmp_path, args=["--apply"], live_caddy=live)
    assert first.returncode == 0, first.stdout + first.stderr
    once = live.read_text(encoding="utf-8")
    second = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"APP_UPSTREAM": "prod-api:8000"})
    assert second.returncode == 0, second.stdout + second.stderr
    twice = live.read_text(encoding="utf-8")
    assert twice.count("app.altcontext.com {") == 1
    assert once.count("app.altcontext.com {") == 1
    for host in EXISTING_HOSTS:
        assert host in twice


def test_snippet_denies_admin_and_unrelated_api_surfaces() -> None:
    text = SNIPPET.read_text(encoding="utf-8")
    assert "app.altcontext.com {" in text
    assert "@admin path /admin /admin/*" in text
    assert "respond @admin 404" in text
    assert "/portal" in text
    assert "handle /portal*" not in text
    assert "@portal path /portal /portal/*" in text
    assert "handle @portal" in text
    assert "reverse_proxy" in text
    for surface in ("/recognition", "/roster", "/scene", "/billing/webhooks", "/health"):
        assert surface in text, surface
    assert "file_server" in text
    assert "try_files" in text


def test_artifacts_contain_no_vendor_credentials() -> None:
    paths = [SCRIPT, SNIPPET, OVERLAY, ENV_EXAMPLE, RUNBOOK]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in SECRET_MARKERS:
            assert marker.lower() not in lowered, f"{path} contains {marker}"
        assert "ssh " not in lowered
        assert "scp " not in lowered


def test_script_does_not_open_production_ssh() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\bssh\b", text)
    assert not re.search(r"\bscp\b", text)
    assert "129.213.40.111" not in text


def test_runbook_documents_later_integration_and_env_ownership() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "app.altcontext.com" in text
    assert "129.213.40.111" in text
    assert "/opt/acx-backend/app/www" in text
    assert "docker-compose.caddy.yml" in text
    assert "docker-compose.app.yml" in text
    assert "/srv/app-portal" in text
    assert "RECOGNITION_PORTAL_ENABLED" in text
    assert "/opt/acx-backend/prod/.env" in text
    assert "VITE_CLERK_PUBLISHABLE_KEY" in text
    assert "FRONTEND_DIST" in text
    assert "--apply" in text
    assert "dry-run" in text.lower()
    assert "do not" in text.lower() or "never" in text.lower()
    assert "symlink" in text.lower()
    assert "APP_APPROVED_ROOTS" in text
    assert "`/portal` plus `/portal/*`" in text or "path /portal /portal/*" in text
    assert "APP_HEALTH_CMD=/usr/local/bin/app-portal-health-check" in text
    assert "sudo install -m 0755 scripts/deploy/app-portal.sh /usr/local/bin/app-portal-health-check" in text
    assert "before frontend health runs" in text.lower()
    assert "https://app.altcontext.com/" in text
    assert "https://api.altcontext.com/ready" in text
    assert "local artifact checks" not in text
    assert "If reload is skipped" not in text
    assert "reload" in text.lower()
    assert "health" in text.lower()
    assert "atomic" in text.lower() or "rename" in text.lower()
    assert "trap" in text.lower() or "restor" in text.lower()
    lowered = text.lower()
    for marker in SECRET_MARKERS:
        assert marker.lower() not in lowered, marker


def test_checked_in_health_check_covers_root_ready_and_portal_api(tmp_path: Path) -> None:
    health = tmp_path / "app-portal-health-check"
    _write_executable(health, SCRIPT.read_text(encoding="utf-8"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    curl = bin_dir / "curl"
    _write_executable(
        curl,
        "#!/usr/bin/env bash\n"
        'for url in "$@"; do :; done\n'
        'printf "%s\\n" "$url" >> "$CURL_LOG"\n'
        'if [ "$url" = "https://app.altcontext.com/portal/me" ]; then printf "%s" "${CURL_PORTAL_STATUS:-401}"; fi\n'
        '[ "$url" = "${CURL_FAIL_URL:-}" ] && exit 22\n'
        "exit 0\n",
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["CURL_LOG"] = str(curl_log)

    success = subprocess.run([str(health)], env=env, text=True, capture_output=True, check=False)
    assert success.returncode == 0, success.stdout + success.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://app.altcontext.com/",
        "https://api.altcontext.com/ready",
        "https://app.altcontext.com/portal/me",
    ]

    curl_log.unlink()
    portal_missing_env = {**env, "CURL_PORTAL_STATUS": "404"}
    portal_missing = subprocess.run(
        [str(health)], env=portal_missing_env, text=True, capture_output=True, check=False,
    )
    portal_url = "https://app.altcontext.com/portal/me"
    assert portal_missing.returncode != 0, portal_missing.stdout + portal_missing.stderr
    assert portal_url in portal_missing.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://app.altcontext.com/",
        "https://api.altcontext.com/ready",
        portal_url,
    ]

    curl_log.unlink()
    spa_fallback_env = {**env, "CURL_PORTAL_STATUS": "200"}
    spa_fallback = subprocess.run(
        [str(health)], env=spa_fallback_env, text=True, capture_output=True, check=False,
    )
    assert spa_fallback.returncode != 0, spa_fallback.stdout + spa_fallback.stderr
    assert portal_url in spa_fallback.stderr

    curl_log.unlink()
    failing_env = {**env, "CURL_FAIL_URL": "https://api.altcontext.com/ready"}
    failure = subprocess.run([str(health)], env=failing_env, text=True, capture_output=True, check=False)
    assert failure.returncode != 0, failure.stdout + failure.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://app.altcontext.com/",
        "https://api.altcontext.com/ready",
        portal_url,
    ]


def _prior_www(tmp_path: Path) -> Path:
    www = tmp_path / "opt" / "acx-backend" / "app" / "www"
    www.mkdir(parents=True, exist_ok=True)
    (www / "keep.txt").write_text("active\n", encoding="utf-8")
    return www


def test_apply_health_checks_selected_hostname(tmp_path: Path) -> None:
    health = tmp_path / "app-portal-health-check"
    _write_executable(health, SCRIPT.read_text(encoding="utf-8"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl_log = tmp_path / "curl.log"
    _write_executable(
        bin_dir / "curl",
        "#!/usr/bin/env bash\n"
        'for url in "$@"; do :; done\n'
        'printf "%s\\n" "$url" >> "$CURL_LOG"\n'
        'if [ "$url" = "https://preview.altcontext.com/portal/me" ]; then printf "401"; fi\n'
        '[ "$url" = "https://preview.altcontext.com/" ] && exit 22\n'
        "exit 0\n",
    )
    result = _run(
        tmp_path,
        args=["--apply"],
        hostname="preview.altcontext.com",
        extra_env={"APP_HEALTH_CMD": str(health), "CURL_LOG": str(curl_log)},
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert curl_log.read_text(encoding="utf-8").splitlines() == [
        "https://preview.altcontext.com/",
        "https://api.altcontext.com/ready",
        "https://preview.altcontext.com/portal/me",
    ]
    assert "applied:" not in result.stdout


def test_recovery_refuses_changed_base_compose_without_mutation(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    hook = tmp_path / "interrupt.sh"
    hook.write_text(
        "sync() {\n"
        '  /bin/sync "$@" || return $?\n'
        '  if [ "${@: -1}" = "$CADDYFILE" ]; then kill -KILL "$BASHPID"; fi\n'
        "}\n",
        encoding="utf-8",
    )
    interrupted = _run(tmp_path, args=["--apply"], extra_env={"BASH_ENV": str(hook)})
    assert interrupted.returncode == -9, interrupted.stdout + interrupted.stderr
    app_root = live.parent / "app"
    journal = app_root / "activation.journal"
    before_caddy = live.read_bytes()
    before_journal = journal.read_bytes()
    before_log = _log(tmp_path)
    alternate = _write_caddy_compose(live.parent / "alternate-compose.yml")
    result = _run(
        tmp_path, args=["--apply"], live_caddy=live,
        extra_env={"BASH_ENV": "", "CADDY_COMPOSE": str(alternate)},
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "journal paths do not match" in result.stderr
    assert live.read_bytes() == before_caddy
    assert journal.read_bytes() == before_journal
    assert _log(tmp_path) == before_log
    assert f"caddy_compose={live.parent / 'docker-compose.caddy.yml'}\n" in journal.read_text()


def test_runbook_first_deploy_rollback_uses_base_only_compose() -> None:
    rollback = RUNBOOK.read_text(encoding="utf-8").split("## Rollback", 1)[1]
    assert "no prior overlay" in rollback
    assert "docker compose -f docker-compose.caddy.yml up -d" in rollback
    assert "docker compose -f docker-compose.caddy.yml exec -T caddy" in rollback


def test_apply_refuses_filesystem_root_paths(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    for name, value in (
        ("APP_WWW", "/"),
        ("APP_ROOT", "/"),
        ("APP_FRONTEND_ROOT", "/"),
        ("CADDYFILE", "/"),
    ):
        result = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={name: value})
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert "root" in output.lower() or name in output, output
        assert live.read_text(encoding="utf-8") == before
        assert _log(tmp_path) == ""


def test_apply_refuses_symlink_caddyfile(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    link = tmp_path / "opt" / "acx-backend" / "Caddyfile.link"
    link.symlink_to(live)
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"CADDYFILE": str(link)},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "symlink" in output.lower(), output
    assert live.read_text(encoding="utf-8") == before
    assert link.is_symlink()
    assert _log(tmp_path) == ""


def test_apply_refuses_symlink_component_in_app_root(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    real_app = tmp_path / "opt" / "acx-backend" / "app"
    link_app = tmp_path / "opt" / "acx-backend" / "linked-app"
    link_app.symlink_to(real_app)
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={
            "APP_ROOT": str(link_app),
            "APP_WWW": str(link_app / "www"),
        },
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "symlink" in output.lower(), output
    assert live.read_text(encoding="utf-8") == before
    assert not (real_app / "www" / "index.html").exists()


def test_apply_refuses_path_outside_approved_roots(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    outside = tmp_path / "outside" / "app"
    outside.mkdir(parents=True)
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_ROOT": str(outside), "APP_WWW": str(outside / "www")},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "approved" in output.lower() or "outside" in output.lower(), output
    assert live.read_text(encoding="utf-8") == before
    assert not (outside / "www").exists()
    assert list(outside.iterdir()) == []


def test_apply_refuses_caddyfile_directory(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    live.mkdir(parents=True)
    result = _run(tmp_path, args=["--apply"], live_caddy=live)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "regular file" in output.lower() or "not a file" in output.lower() or "directory" in output.lower()
    assert live.is_dir()
    assert list(live.iterdir()) == []


def test_overlay_template_uses_www_placeholder() -> None:
    text = OVERLAY.read_text(encoding="utf-8")
    assert "__APP_WWW__:/srv/app-portal" in text
    assert "/opt/acx-backend/app/www:/srv/app-portal" not in text


def test_apply_failed_reload_restores_caddy_www_and_overlay(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_dest.write_text("services: {}\n", encoding="utf-8")
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        docker_fail_first_reload=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "reload" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    assert overlay_dest.read_text(encoding="utf-8") == "services: {}\n"
    expected_reload = _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay_dest)
    assert _compose_reload_calls(tmp_path) == [expected_reload, expected_reload]
    assert not any(line.startswith("caddy reload ") for line in _log(tmp_path).splitlines())
    for host in EXISTING_HOSTS:
        assert host in live.read_text(encoding="utf-8")


def test_first_apply_reload_failure_rolls_back_with_base_compose(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    overlay_dest = app_root / "docker-compose.app.yml"
    www = app_root / "www"

    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        include_caddy=False,
        docker_fail_first_reload=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert live.read_text(encoding="utf-8") == before
    assert not overlay_dest.exists()
    assert not www.exists()
    assert _compose_reload_calls(tmp_path) == [
        _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay_dest),
        _expected_compose_reload(tmp_path / "opt" / "acx-backend"),
    ]


def test_apply_default_reload_uses_compose_without_host_caddy(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    result = _run(tmp_path, args=["--apply"], live_caddy=live, include_caddy=False)
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    overlay = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    assert _compose_reload_calls(tmp_path) == [
        _expected_compose_reload(tmp_path / "opt" / "acx-backend", overlay)
    ]
    assert any(line.startswith("docker run ") and "validate" in line for line in _log(tmp_path).splitlines())
    assert not any(line.startswith("caddy ") for line in _log(tmp_path).splitlines())


def test_apply_requires_explicit_live_health_check(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_bytes()
    result = _run(tmp_path, args=["--apply"], live_caddy=live, extra_env={"APP_HEALTH_CMD": ""})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "APP_HEALTH_CMD" in output
    assert "applied:" not in output
    assert live.read_bytes() == before


def test_docker_validation_with_explicit_reload_succeeds(tmp_path: Path) -> None:
    reload_cmd = tmp_path / "reload-edge"
    marker = tmp_path / "reloaded"
    _write_executable(reload_cmd, f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\n")
    result = _run(
        tmp_path, args=["--apply"], include_caddy=False,
        extra_env={"APP_RELOAD_CMD": str(reload_cmd)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docker run" in _log(tmp_path)
    assert marker.exists()
    assert _compose_reload_calls(tmp_path) == []


def test_successful_applies_reclaim_old_snapshot_sets(tmp_path: Path) -> None:
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    rollback = app_root / "rollback"
    rollback.mkdir(parents=True)
    for stamp in (1, 2, 3):
        (rollback / f"Caddyfile.{stamp}").write_text("old config")
        (rollback / f"www.{stamp}").mkdir()
        (rollback / f"www.{stamp}" / "index.html").write_text("old frontend")
        (rollback / f"docker-compose.app.yml.{stamp}").write_text("old overlay")
    unrelated = rollback / "operator-notes"
    unrelated.write_text("keep")
    operator_caddy = rollback / "Caddyfile.operator-copy.1"
    operator_caddy.write_text("operator caddy copy")
    operator_www = rollback / "www.backup.2"
    operator_www.mkdir()
    (operator_www / "keep.txt").write_text("operator frontend copy")
    operator_overlay = rollback / "docker-compose.app.yml.local.3"
    operator_overlay.write_text("operator overlay copy")
    operator_caddy_suffix = rollback / "Caddyfile.4.bak"
    operator_caddy_suffix.write_text("operator caddy backup")
    wrong_caddy_type = rollback / "Caddyfile.9001"
    wrong_caddy_type.mkdir()
    wrong_www_type = rollback / "www.9002"
    wrong_www_type.write_text("operator file")
    wrong_overlay_type = rollback / "docker-compose.app.yml.9003"
    wrong_overlay_type.mkdir()
    _prior_www(tmp_path)
    (app_root / "docker-compose.app.yml").write_text("services: {}\n")
    for _ in range(3):
        # Freeze the clock to exercise back-to-back snapshot names as well.
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        _write_executable(bin_dir / "date", "#!/bin/sh\nprintf '100\\n'\n")
        live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
        if not live.exists():
            _write_live_caddy(live)
        before = live.read_bytes()
        prior_index = app_root / "www" / "index.html"
        prior_contents = prior_index.read_bytes() if prior_index.exists() else None
        result = _run(tmp_path, args=["--apply"], live_caddy=live)
        assert result.returncode == 0, result.stdout + result.stderr
        caddy_backups = [
            p for p in rollback.glob("Caddyfile.*")
            if re.fullmatch(r"Caddyfile\.\d+", p.name) and p.is_file()
        ]
        assert len(caddy_backups) == 1
        stamp = caddy_backups[0].name.split(".")[-1]
        assert caddy_backups[0].read_bytes() == before
        assert {p.name for p in rollback.iterdir()} == {
            f"Caddyfile.{stamp}", f"www.{stamp}", f"docker-compose.app.yml.{stamp}", "operator-notes",
            "Caddyfile.operator-copy.1", "www.backup.2", "docker-compose.app.yml.local.3",
            "Caddyfile.4.bak", "Caddyfile.9001", "www.9002", "docker-compose.app.yml.9003",
        }
        assert operator_caddy.read_text() == "operator caddy copy"
        assert (operator_www / "keep.txt").read_text() == "operator frontend copy"
        assert operator_overlay.read_text() == "operator overlay copy"
        assert operator_caddy_suffix.read_text() == "operator caddy backup"
        assert wrong_caddy_type.is_dir()
        assert wrong_www_type.read_text() == "operator file"
        assert wrong_overlay_type.is_dir()
        if prior_contents is not None:
            assert (rollback / f"www.{stamp}" / "index.html").read_bytes() == prior_contents
        assert unrelated.read_text() == "keep"
        assert not (app_root / "activation.journal").exists()


def test_apply_refuses_symlink_rollback_directory(tmp_path: Path) -> None:
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    app_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    snapshot = outside / "Caddyfile.1"
    snapshot.write_text("do not delete")
    (app_root / "rollback").symlink_to(outside, target_is_directory=True)
    result = _run(tmp_path, args=["--apply"])
    assert result.returncode != 0, result.stdout + result.stderr
    assert "symlink" in (result.stdout + result.stderr).lower()
    assert {p.name for p in outside.iterdir()} == {"Caddyfile.1"}
    assert snapshot.read_text() == "do not delete"


def test_apply_failed_health_restores_caddy_www_and_overlay(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    overlay_dest.write_text("services: {}\n", encoding="utf-8")
    rollback = overlay_dest.parent / "rollback"
    rollback.mkdir()
    old_snapshot = rollback / "Caddyfile.1"
    old_snapshot.write_text("previous recovery config")
    health = tmp_path / "opt" / "acx-backend" / "health-fail"
    _write_executable(health, "#!/usr/bin/env bash\nexit 1\n")
    result = _run(
        tmp_path,
        args=["--apply"],
        live_caddy=live,
        extra_env={"APP_HEALTH_CMD": str(health)},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "health" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not (www / "index.html").exists()
    assert overlay_dest.read_text(encoding="utf-8") == "services: {}\n"
    assert old_snapshot.read_text() == "previous recovery config"
    compose_up_lines = [line for line in _log(tmp_path).splitlines() if " compose " in line and " up -d" in line]
    assert len(compose_up_lines) == 2, _log(tmp_path)
    current_backups = [p for p in rollback.glob("Caddyfile.*") if p != old_snapshot]
    assert len(current_backups) == 1
    assert current_backups[0].read_text() == before


def test_apply_failed_www_move_restores_caddyfile(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    result = _run(tmp_path, args=["--apply"], live_caddy=live, fail_mv_dest=www)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "mv" in output.lower() or "activation" in output.lower() or "move" in output.lower(), output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"


def test_apply_failed_overlay_promote_restores_prior_www_and_caddy(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    before = live.read_text(encoding="utf-8")
    www = _prior_www(tmp_path)
    overlay_dest = tmp_path / "opt" / "acx-backend" / "app" / "docker-compose.app.yml"
    result = _run(tmp_path, args=["--apply"], live_caddy=live, fail_mv_dest=overlay_dest)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "applied:" not in result.stdout
    assert live.read_text(encoding="utf-8") == before
    assert (www / "keep.txt").read_text(encoding="utf-8") == "active\n"
    assert not overlay_dest.exists() or overlay_dest.read_text(encoding="utf-8") != OVERLAY.read_text(encoding="utf-8")


def test_dry_run_refuses_symlink_and_root_without_writes(tmp_path: Path) -> None:
    live = tmp_path / "opt" / "acx-backend" / "Caddyfile"
    _write_live_caddy(live)
    _write_caddy_compose(live.parent / "docker-compose.caddy.yml")
    before_files = _tree_files(tmp_path / "opt")
    result = _run(tmp_path, extra_env={"APP_FRONTEND_ROOT": "/"})
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "root" in output.lower() or "APP_FRONTEND_ROOT" in output
    assert _tree_files(tmp_path / "opt") == before_files
    assert _log(tmp_path) == ""


@pytest.mark.parametrize("polls,fail_reload", [(2, False), (2, True), (10, False)])
def test_recreation_waits_for_admin_and_exhaustion_rolls_back(
    tmp_path: Path, polls: int, fail_reload: bool,
) -> None:
    result = _run(tmp_path, args=["--apply"], readiness_polls=polls,
                  docker_fail_first_reload=fail_reload)
    assert (result.returncode == 0) == (polls == 2 and not fail_reload), result.stdout + result.stderr
    calls = [shlex.split(line) for line in _log(tmp_path).splitlines()]
    probes = [call for call in calls if "wget" in call]
    assert len(probes) == (6 if fail_reload else 3 if polls == 2 else 13)
    assert all(call[-1] == "http://127.0.0.1:2019/config/" for call in probes)
    assert len(_compose_reload_calls(tmp_path)) == (2 if fail_reload else 1)
    app_root = tmp_path / "opt" / "acx-backend" / "app"
    assert not (app_root / "activation.journal").exists()
    if polls == 10 or fail_reload:
        assert "applied:" not in result.stdout
        assert not (app_root / "www").exists()
        assert not (app_root / "docker-compose.app.yml").exists()


@pytest.mark.parametrize("relative", [
    "app/staging/base.yml", "app/rollback/base.yml", "app/www/base.yml",
    "app/www.prev/base.yml", "Caddyfile", "app/docker-compose.app.yml",
    "app/activation.journal", "app/activation.journal.lock",
])
def test_base_compose_refuses_activation_paths_without_mutation(tmp_path: Path, relative: str) -> None:
    source = tmp_path / "opt" / "acx-backend" / relative
    _write_caddy_compose(source)
    before = source.read_bytes()
    result = _run(tmp_path, args=["--apply"], live_caddy=source if relative == "Caddyfile" else "",
                  extra_env={"CADDY_COMPOSE": str(source)})
    assert result.returncode != 0, result.stdout + result.stderr
    assert "CADDY_COMPOSE collides with activation paths" in result.stderr
    assert source.read_bytes() == before
    assert not _log(tmp_path)


@pytest.mark.parametrize("pending", [False, True])
def test_caddyfile_bind_mismatch_refused_before_mutation(tmp_path: Path, pending: bool) -> None:
    from test_app_portal_activation_journal import _interrupt_after_caddy, _tree_snapshot

    backend = tmp_path / "opt/acx-backend"
    live = backend / "SelectedCaddyfile"
    if pending:
        # Create a valid pending activation using the default binding first.
        live = backend / "Caddyfile"
        _interrupt_after_caddy(tmp_path, live)
    else:
        _write_live_caddy(live)
        _prior_www(tmp_path)
    app_root = backend / "app"
    staging = app_root / "staging"
    staging.mkdir(exist_ok=True)
    (staging / "keep.txt").write_text("do not change\n")
    _write_caddy_compose(backend / "docker-compose.caddy.yml")
    before = _tree_snapshot(backend)
    other = backend / "OtherCaddyfile"
    config = json.dumps({"services": {"caddy": {"volumes": [{
        "type": "bind", "source": str(other), "target": "/etc/caddy/Caddyfile",
    }]}}})
    before_log = _log(tmp_path)
    result = _run(tmp_path, args=["--apply"], live_caddy=live,
                  compose_config=config, extra_env={"BASH_ENV": ""})
    assert result.returncode != 0, result.stdout + result.stderr
    assert str(other) in result.stderr and str(live) in result.stderr
    assert "applied:" not in result.stdout
    after = _tree_snapshot(backend)
    # Lock creation is allowed; no staging, journal, or live artifact may change.
    after.pop("app/activation.journal.lock", None)
    before.pop("app/activation.journal.lock", None)
    # Creating the lock may update the parent directory metadata.
    assert {k: v for k, v in after.items() if k != "app"} == {
        k: v for k, v in before.items() if k != "app"
    }
    calls = _log(tmp_path)[len(before_log):]
    assert " up " not in calls and " exec " not in calls and " validate " not in calls


@pytest.mark.parametrize("config", ["not json", "{}", '{"services":{"caddy":{"volumes":[]}}}',
    '{"services":{"caddy":{"volumes":[{"type":"volume","source":"config","target":"/etc/caddy/Caddyfile"}]}}}',
])
def test_caddyfile_binding_requires_resolved_bind(tmp_path: Path, config: str) -> None:
    result = _run(tmp_path, args=["--apply"], compose_config=config)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "cannot resolve Caddy bind source" in result.stderr
    assert not (tmp_path / "opt/acx-backend/app/staging").exists()
    assert " up " not in _log(tmp_path)


@pytest.mark.parametrize("installed", [False, True])
def test_overlay_caddyfile_bind_override_refused(tmp_path: Path, installed: bool) -> None:
    backend = tmp_path / "opt/acx-backend"
    if installed:
        app_root = backend / "app"
        app_root.mkdir(parents=True)
        (app_root / "docker-compose.app.yml").write_text("services: {}\n")
    other = backend / "OtherCaddyfile"
    config = json.dumps({"services": {"caddy": {"volumes": [{
        "type": "bind", "source": str(other), "target": "/etc/caddy/Caddyfile",
    }]}}})
    result = _run(tmp_path, args=["--apply"], compose_overlay_config=config)
    assert result.returncode != 0, result.stdout + result.stderr
    assert str(other) in result.stderr and str(backend / "Caddyfile") in result.stderr
    assert not (backend / "app/staging").exists()
    assert " up " not in _log(tmp_path)


def test_selected_caddyfile_matching_compose_binding_applies(tmp_path: Path) -> None:
    live = tmp_path / "opt/acx-backend/SelectedCaddyfile"
    config = json.dumps({"services": {"caddy": {"volumes": [{
        "type": "bind", "source": str(live), "target": "/etc/caddy/Caddyfile",
    }]}}})
    result = _run(tmp_path, args=["--apply"], live_caddy=live, compose_config=config)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "applied:" in result.stdout
    assert len(_compose_reload_calls(tmp_path)) == 1
