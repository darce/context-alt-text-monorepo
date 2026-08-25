"""ORCH-LAUNCH-01 wave3: image-variant parity through compose + deploy guards.

Guards the silent VLM no-op (compose hardcoding acx-backend), the builder-vlm
remote-build bypass, and the writable /data/cache RCE surface.

TEST-15: each assertion is proven red via a synthetic mutation in this module
(and documented mutations against the real sources during the implementation
pass — see lane report).
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

# recognition/tests/deploy/<this> → parents[3] = service root;
# parents[5] = monorepo root.
SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
COMPOSE_ENV = SERVICE_ROOT / "docker-compose.env.yml"
COMPOSE_PROD = SERVICE_ROOT / "docker-compose.prod.yml"
COMPOSE_VLM = SERVICE_ROOT / "docker-compose.vlm.yml"

_DEFAULT_REPO = "iad.ocir.io/idu2kqqe2jxy/acx-backend"
_VLM_REPO = "iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm"
# image: ${ACX_IMAGE_REPO:-iad.ocir.io/idu2kqqe2jxy/acx-backend}:TAG
_IMAGE_LINE_RE = re.compile(
    r"^\s*image:\s*(?P<value>.+?)\s*$",
    re.MULTILINE,
)
_ACX_IMAGE_REPO_SUB_RE = re.compile(
    r"\$\{ACX_IMAGE_REPO:-" + re.escape(_DEFAULT_REPO) + r"\}"
)
# Bare hardcoded acx-backend without ACX_IMAGE_REPO substitution.
_BARE_ACX_BACKEND_RE = re.compile(
    r"image:\s*iad\.ocir\.io/idu2kqqe2jxy/acx-backend(?![-:])"
    r"|image:\s*iad\.ocir\.io/idu2kqqe2jxy/acx-backend:"
)


def _service_image_lines(compose_text: str) -> list[str]:
    """Return image: values for services that are not postgres/caddy infrastructure."""
    values: list[str] = []
    for match in _IMAGE_LINE_RE.finditer(compose_text):
        value = match.group("value").strip()
        # Skip infra images.
        if "pgvector" in value or value.startswith("caddy:") or "caddy:" in value:
            continue
        values.append(value)
    return values


def compose_image_default_repos(compose_text: str) -> set[str]:
    """ACX_IMAGE_REPO default values on app image lines (rg-015: parsed, not guessed)."""
    found: set[str] = set()
    for value in _service_image_lines(compose_text):
        match = re.search(r"\$\{ACX_IMAGE_REPO:-([^}]+)\}", value)
        if match:
            found.add(match.group(1))
    return found


def compose_defaults_to_vlm_image_repo(compose_text: str) -> bool:
    """True when every app image line defaults ACX_IMAGE_REPO to the VLM repo."""
    repos = compose_image_default_repos(compose_text)
    return bool(repos) and repos == {_VLM_REPO}


def compose_api_worker_images_use_image_repo(compose_text: str) -> bool:
    """True when every api/worker image line uses ACX_IMAGE_REPO substitution."""
    images = _service_image_lines(compose_text)
    if len(images) < 2:
        return False
    for value in images:
        if not _ACX_IMAGE_REPO_SUB_RE.search(value):
            return False
        # Must not be a bare hardcoded repo (no substitution).
        if re.match(r"^iad\.ocir\.io/idu2kqqe2jxy/acx-backend:", value):
            return False
    return True


def compose_data_cache_mounts_are_readonly(compose_text: str) -> bool:
    """True when every /data/cache bind mount ends with :ro."""
    mounts = re.findall(r"^\s*-\s*(.+):/data/cache(:\w+)?\s*$", compose_text, re.MULTILINE)
    if not mounts:
        return False
    for _src, mode in mounts:
        if mode != ":ro":
            return False
    return True


def script_threads_resolve_to_acx_image_repo(script_text: str) -> bool:
    """ACX_IMAGE_REPO must be derived from IMAGE_BASE / resolve_image_repo_name (one source)."""
    if "resolve_image_repo_name()" not in script_text:
        return False
    if not re.search(
        r'IMAGE_BASE="\$\{OCIR_REGISTRY\}/\$\{OCIR_NAMESPACE\}/\$\(resolve_image_repo_name\)"',
        script_text,
    ):
        return False
    # ACX_IMAGE_REPO assigned from IMAGE_BASE — not a second string concatenation.
    if not re.search(r'ACX_IMAGE_REPO="\$\{IMAGE_BASE\}"', script_text):
        return False
    # Must ship into remote .env for compose substitution.
    if "ship_remote_image_repo_env" not in script_text:
        return False
    if "ACX_IMAGE_REPO=" not in script_text:
        return False
    return True


def script_refuses_any_vlm_remote_target(script_text: str) -> bool:
    """refuse_remote_vlm_build must match *vlm*, not only the literal runtime-vlm."""
    # Extract the function body roughly.
    m = re.search(
        r"refuse_remote_vlm_build\(\)\s*\{(?P<body>.*?)\n\}",
        script_text,
        re.DOTALL,
    )
    if not m:
        return False
    body = m.group("body")
    # Must not be literal-only equality on runtime-vlm.
    if re.search(r'==\s*"runtime-vlm"', body) and "*vlm*" not in body:
        return False
    # Pattern form: [[ ... == *vlm* ]]
    if not re.search(r"==\s*\*vlm\*", body):
        return False
    # Error message must state the refused value (use $target or ${target}).
    if "ACX_BUILD_TARGET=" not in body and "ACX_BUILD_TARGET=${" not in body:
        # fail "… ACX_BUILD_TARGET=${target} …"
        if not re.search(r"ACX_BUILD_TARGET=\$\{?target", body):
            return False
    return True


def _run_refuse_probe(target: str) -> subprocess.CompletedProcess[str]:
    """Source refuse_remote_vlm_build from the real script and invoke it under a target."""
    # Extract only what we need without executing the whole deploy script.
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    # Minimal harness: redefine fail to exit 1 with message; call the real function body.
    m = re.search(
        r"refuse_remote_vlm_build\(\)\s*\{(?P<body>.*?)\n\}",
        script,
        re.DOTALL,
    )
    assert m, "refuse_remote_vlm_build not found in deploy script"
    body = m.group("body")
    probe = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        fail() {{ printf '%s\\n' "$*" >&2; exit 1; }}
        ACX_BUILD_TARGET={target!r}
        refuse_remote_vlm_build() {{
        {body}
        }}
        refuse_remote_vlm_build
        echo ACCEPTED
        """
    )
    return subprocess.run(
        ["bash", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )


# ---- positive: real tree -------------------------------------------------


def test_compose_env_uses_acx_image_repo_substitution() -> None:
    text = COMPOSE_ENV.read_text(encoding="utf-8")
    assert compose_api_worker_images_use_image_repo(text), (
        "docker-compose.env.yml api/worker must use "
        "${ACX_IMAGE_REPO:-iad.ocir.io/idu2kqqe2jxy/acx-backend}:…"
    )
    # Explicit negative: no bare hardcoded image lines for the app services.
    for value in _service_image_lines(text):
        assert "ACX_IMAGE_REPO" in value, f"hardcoded image without substitution: {value}"


def test_compose_prod_uses_acx_image_repo_substitution() -> None:
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    assert compose_api_worker_images_use_image_repo(text), (
        "docker-compose.prod.yml api/worker must use "
        "${ACX_IMAGE_REPO:-iad.ocir.io/idu2kqqe2jxy/acx-backend}:latest"
    )
    for value in _service_image_lines(text):
        assert "ACX_IMAGE_REPO" in value, f"hardcoded image without substitution: {value}"
        assert value.endswith(":latest") or ":latest" in value


def test_compose_env_default_repo_stays_recognition_slim() -> None:
    """Default compose stays torch-free; VLM is the overlay, not the default."""
    assert compose_image_default_repos(COMPOSE_ENV.read_text()) == {_DEFAULT_REPO}
    assert compose_image_default_repos(COMPOSE_PROD.read_text()) == {_DEFAULT_REPO}
    assert not compose_defaults_to_vlm_image_repo(COMPOSE_ENV.read_text())


def test_compose_vlm_overlay_defaults_to_vlm_repo() -> None:
    """PROV-01b: opt-in overlay selects acx-backend-vlm without flipping the slim default."""
    assert COMPOSE_VLM.is_file(), "docker-compose.vlm.yml overlay missing"
    text = COMPOSE_VLM.read_text(encoding="utf-8")
    assert compose_defaults_to_vlm_image_repo(text), (
        "docker-compose.vlm.yml api/worker must default "
        "${ACX_IMAGE_REPO:-iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm}"
    )
    assert _VLM_REPO in text
    active_env = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "ACX_DESCRIPTION_ADAPTER" in line
    ]
    assert not active_env, (
        "VLM overlay must not flip ACX_DESCRIPTION_ADAPTER; default stays seeded; "
        f"got {active_env}"
    )


def test_data_cache_bind_mounts_are_readonly_in_both_compose_files() -> None:
    for path in (COMPOSE_ENV, COMPOSE_PROD):
        text = path.read_text(encoding="utf-8")
        assert compose_data_cache_mounts_are_readonly(text), (
            f"{path.name}: every /data/cache bind mount must be :ro "
            "(Florence-2 trust_remote_code executes cache python)"
        )


def _fn_body(script_text: str, name: str) -> str:
    """Extract a top-level ``name() { … }`` body from the deploy script."""
    m = re.search(
        rf"^{re.escape(name)}\(\)\s*\{{(?P<body>.*?)^\}}",
        script_text,
        re.DOTALL | re.MULTILINE,
    )
    assert m, f"{name}() not found in deploy script"
    return m.group("body")


def _active_call(body: str, pattern: str) -> bool:
    """True when a non-comment line in ``body`` matches ``pattern``."""
    for ln in body.splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.search(pattern, stripped):
            return True
    return False


def test_deploy_script_threads_image_repo_from_resolve() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script_threads_resolve_to_acx_image_repo(script), (
        "ACX_IMAGE_REPO must equal IMAGE_BASE from resolve_image_repo_name and be shipped remotely"
    )
    verify_body = _fn_body(script, "do_verify")
    assert _active_call(verify_body, r"verify_running_image_matches_deployed\b"), (
        "do_verify must invoke verify_running_image_matches_deployed"
    )


def test_refuse_remote_vlm_build_rejects_builder_vlm_and_runtime_vlm() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script_refuses_any_vlm_remote_target(script)

    for target in ("builder-vlm", "runtime-vlm", "foo-vlm-bar"):
        result = _run_refuse_probe(target)
        assert result.returncode != 0, f"expected refuse for {target!r}, got ACCEPTED"
        combined = (result.stdout or "") + (result.stderr or "")
        assert target in combined, f"error must state refused value {target!r}: {combined}"

    # Legitimate non-vlm targets must still be accepted.
    for target in ("", "runtime", "builder"):
        result = _run_refuse_probe(target)
        assert result.returncode == 0, (
            f"legitimate target {target!r} must not be refused: {result.stderr}"
        )
        assert "ACCEPTED" in (result.stdout or "")


def test_smoke_timeout_failure_names_unvalidated_vlm_budget() -> None:
    """BUG 4: timeout message must name the unvalidated VLM default + ACX_SMOKE_TIMEOUT."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "UNVALIDATED" in script or "unvalidated" in script.lower()
    assert "ACX_SMOKE_TIMEOUT" in script
    assert re.search(
        r"VLM budget is an UNVALIDATED default.*ACX_SMOKE_TIMEOUT",
        script,
        re.DOTALL | re.IGNORECASE,
    )


# ---- parsers / TEST-15 synthetic mutations -------------------------------


def test_mutation_vlm_overlay_without_vlm_repo_fails_guard() -> None:
    """TEST-15: overlay that still defaults to the slim recognition repo goes red."""
    good = textwrap.dedent(
        f"""\
        services:
          api:
            image: ${{ACX_IMAGE_REPO:-{_VLM_REPO}}}:${{ACX_IMAGE_TAG}}
          worker:
            image: ${{ACX_IMAGE_REPO:-{_VLM_REPO}}}:${{ACX_IMAGE_TAG}}
        """
    )
    bad = textwrap.dedent(
        f"""\
        services:
          api:
            image: ${{ACX_IMAGE_REPO:-{_DEFAULT_REPO}}}:${{ACX_IMAGE_TAG}}
          worker:
            image: ${{ACX_IMAGE_REPO:-{_DEFAULT_REPO}}}:${{ACX_IMAGE_TAG}}
        """
    )
    assert compose_defaults_to_vlm_image_repo(good)
    assert not compose_defaults_to_vlm_image_repo(bad)


def test_mutation_bare_image_fails_compose_guard() -> None:
    """TEST-15: hardcoded acx-backend without ACX_IMAGE_REPO goes red."""
    good = textwrap.dedent(
        f"""\
        services:
          api:
            image: ${{ACX_IMAGE_REPO:-{_DEFAULT_REPO}}}:${{ACX_IMAGE_TAG}}
          worker:
            image: ${{ACX_IMAGE_REPO:-{_DEFAULT_REPO}}}:${{ACX_IMAGE_TAG}}
        """
    )
    assert compose_api_worker_images_use_image_repo(good)

    bare = textwrap.dedent(
        """\
        services:
          api:
            image: iad.ocir.io/idu2kqqe2jxy/acx-backend:${ACX_IMAGE_TAG}
          worker:
            image: iad.ocir.io/idu2kqqe2jxy/acx-backend:${ACX_IMAGE_TAG}
        """
    )
    assert not compose_api_worker_images_use_image_repo(bare)


def test_mutation_rw_cache_mount_fails_ro_guard() -> None:
    """TEST-15: /data/cache without :ro goes red."""
    good = "volumes:\n  - ${ACX_MODELS_PATH}:/data/cache:ro\n"
    bad = "volumes:\n  - ${ACX_MODELS_PATH}:/data/cache\n"
    assert compose_data_cache_mounts_are_readonly(good)
    assert not compose_data_cache_mounts_are_readonly(bad)


def test_mutation_literal_only_refuse_fails_guard() -> None:
    """TEST-15: refuse that only matches runtime-vlm (not *vlm*) goes red."""
    good = textwrap.dedent(
        """\
        refuse_remote_vlm_build() {
          local target="${ACX_BUILD_TARGET:-}"
          if [[ "${target}" == *vlm* ]]; then
            fail "Remote build refuses ACX_BUILD_TARGET=${target} (matches *vlm*)."
          fi
        }
        """
    )
    bad = textwrap.dedent(
        """\
        refuse_remote_vlm_build() {
          if [[ "${ACX_BUILD_TARGET:-}" == "runtime-vlm" ]]; then
            fail "Remote build refuses ACX_BUILD_TARGET=runtime-vlm."
          fi
        }
        """
    )
    assert script_refuses_any_vlm_remote_target(good)
    assert not script_refuses_any_vlm_remote_target(bad)


def test_mutation_missing_acx_image_repo_thread_fails_guard() -> None:
    """TEST-15: IMAGE_BASE without ACX_IMAGE_REPO assignment goes red."""
    good = textwrap.dedent(
        """\
        resolve_image_repo_name() { printf '%s\\n' "${IMAGE_NAME}"; }
        IMAGE_BASE="${OCIR_REGISTRY}/${OCIR_NAMESPACE}/$(resolve_image_repo_name)"
        ACX_IMAGE_REPO="${IMAGE_BASE}"
        export ACX_IMAGE_REPO
        ship_remote_image_repo_env() { :; }
        """
    )
    bad = textwrap.dedent(
        """\
        resolve_image_repo_name() { printf '%s\\n' "${IMAGE_NAME}"; }
        IMAGE_BASE="${OCIR_REGISTRY}/${OCIR_NAMESPACE}/$(resolve_image_repo_name)"
        # missing ACX_IMAGE_REPO + ship helper
        """
    )
    assert script_threads_resolve_to_acx_image_repo(good)
    assert not script_threads_resolve_to_acx_image_repo(bad)


def _probe_resolve_repo_name(target: str) -> str:
    """Source the real resolve_image_repo_name and return its stdout (D-09)."""
    probe = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail
        IMAGE_NAME=acx-backend
        ACX_BUILD_TARGET={target!r}
        source "{DEPLOY_SCRIPT}"
        resolve_image_repo_name
        """
    )
    result = subprocess.run(
        ["bash", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"resolve_image_repo_name failed for {target!r}: {result.stderr}"
    )
    return (result.stdout or "").strip()


def test_resolve_image_repo_name_exact_strings() -> None:
    """D-09 / rg-005: variant parity is the exact repository string, not a grep."""
    assert _probe_resolve_repo_name("") == "acx-backend"
    assert _probe_resolve_repo_name("runtime") == "acx-backend"
    assert _probe_resolve_repo_name("runtime-vlm") == "acx-backend-vlm"
    # Distinctness is the headline claim — underscore or prefix rewrites go red.
    assert _probe_resolve_repo_name("runtime-vlm") != _probe_resolve_repo_name("")


def _probe_ship_invocations(script_text: str | None = None) -> list[str]:
    """Execute promote_gate + do_restart against fakes; return the call log.

    Behavioural, not textual: the invariant is that the deploy path ships the
    remote ``ACX_IMAGE_REPO`` exactly once before the unit restarts. Which
    function holds the call site is an implementation detail — asserting on the
    call site pinned the old converge_runtime topology and went red on an
    equivalent consolidation into promote_gate (W9-HARM-01).
    """
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "calls.log"
        source = DEPLOY_SCRIPT
        if script_text is not None:
            source = Path(tmp) / "recognition-service.sh"
            source.write_text(script_text, encoding="utf-8")
        probe = textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            IMAGE_NAME=acx-backend
            OCI_USER=probe
            OCI_HOST=probe.invalid
            source "{source}"
            LOG={str(log)!r}
            preserve_rollback_tag() {{ echo "preserve_rollback_tag $*" >> "$LOG"; }}
            do_boot_smoke() {{ echo "do_boot_smoke $*" >> "$LOG"; }}
            read_remote_image_repo() {{ printf '%s\\n' "acx/prior"; }}
            ship_remote_image_repo_env() {{ echo "ship $*" >> "$LOG"; }}
            converge_runtime() {{ echo "converge_runtime $*" >> "$LOG"; }}
            assert_remote_disk_headroom_for_pull() {{ :; }}
            repair_blob_volume_ownership() {{ echo "repair $*" >> "$LOG"; }}
            ssh() {{ echo "ssh $*" >> "$LOG"; }}
            promote_gate prod "acx/acx-backend:deadbeef"
            do_restart prod
            """
        )
        result = subprocess.run(
            ["bash", "-c", probe],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"probe failed: rc={result.returncode} err={result.stderr}"
        )
        return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_deploy_path_ships_image_repo_exactly_once_before_restart() -> None:
    """S2-A-06 behavioural: one ship, and it precedes the systemctl restart."""
    calls = _probe_ship_invocations()
    ships = [i for i, line in enumerate(calls) if line.startswith("ship ")]
    assert len(ships) == 1, (
        f"remote ACX_IMAGE_REPO must be shipped exactly once per deploy; got {calls}"
    )
    restarts = [i for i, line in enumerate(calls) if "systemctl restart" in line]
    assert restarts, f"deploy path must restart the unit; got {calls}"
    assert ships[0] < restarts[0], (
        f"ship must precede the unit restart, else the unit boots on a stale "
        f"ACX_IMAGE_REPO; got {calls}"
    )


def test_mutation_removing_ship_call_fails_behavioural_gate() -> None:
    """TEST-15: delete the real ship call site and the gate must go red."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    mutated = script.replace('  ship_remote_image_repo_env "${remote_dir}"\n', "", 1)
    assert mutated != script, "mutation anchor not found"
    calls = _probe_ship_invocations(mutated)
    assert not [line for line in calls if line.startswith("ship ")], (
        "mutation control: removing the call site must produce zero ship calls"
    )


def test_mutation_ship_after_restart_fails_ordering_gate() -> None:
    """TEST-15: shipping after the restart must not satisfy the ordering claim."""
    calls = ["ssh sudo systemctl restart acx-prod", "ship /opt/acx-backend/prod"]
    ships = [i for i, line in enumerate(calls) if line.startswith("ship ")]
    restarts = [i for i, line in enumerate(calls) if "systemctl restart" in line]
    assert not (ships[0] < restarts[0]), (
        "ordering assertion must reject ship-after-restart"
    )
