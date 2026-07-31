"""E15-33 Slice 3: deploy-time compose+unit+edge convergence contract.

`recognition-service.sh deploy <env>` must converge the deployed
`docker-compose.env.yml` + systemd unit + shared Caddy edge with the repo (or
fail), instead of restarting the image against whatever compose/unit already sit
on the VM. A read-only `deploy <env> --check` reports drift without mutating.

Structural assertions parse the script; behavioral ones run it with fake
ssh/scp on PATH so no VM is required.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"
SCRIPT_TEXT = SCRIPT.read_text()
SERVICE_DIR = REPO_ROOT / "apps" / "prototype-description-service"
CADDYFILE = SERVICE_DIR / "Caddyfile"
CADDY_COMPOSE = SERVICE_DIR / "docker-compose.caddy.yml"
ENV_FIR_EXAMPLE = SERVICE_DIR / ".env.fir.example"
PROVENANCE = (
    SERVICE_DIR
    / "recognition"
    / "infrastructure"
    / "face_pipeline"
    / "provenance.py"
)


def _fake_ssh_bin(tmp_path: Path) -> Path:
    """A bin dir whose `ssh` succeeds with empty stdout and `scp` records a call.

    Empty `ssh` stdout makes the drift diff in --check see "deployed != repo",
    and the scp marker lets a test assert --check never mutates the VM.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text("#!/bin/sh\nexit 0\n")
    marker = tmp_path / "scp-was-called"
    (bindir / "scp").write_text(f"#!/bin/sh\necho called >> {marker}\nexit 0\n")
    for name in ("ssh", "scp"):
        (bindir / name).chmod(0o755)
    return bindir


def _run(args: list[str], tmp_path: Path, extra_env: dict[str, str] | None = None):
    env = {k: v for k, v in os.environ.items() if k != "CONFIRM"}
    env["PATH"] = f"{_fake_ssh_bin(tmp_path)}:{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=30,
    )


# ---- structural contract ------------------------------------------------


def _source_env_map(fn: str, env_arg: str) -> str:
    """Invoke an env_to_* helper from recognition-service.sh and return stdout."""
    proc = subprocess.run(
        ["/bin/bash", "-c", f'source "{SCRIPT}"; {fn} {env_arg}'],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_defines_converge_functions() -> None:
    assert "converge_runtime()" in SCRIPT_TEXT
    assert "converge_check()" in SCRIPT_TEXT
    assert "render_unit()" in SCRIPT_TEXT


def test_dev_fir_env_mappings() -> None:
    """FIR23-STACK Slice 1: acx-dev-fir isolated FIR/SFace stack identity."""
    assert _source_env_map("env_to_tag", "dev-fir") == "dev"
    assert _source_env_map("env_to_unit", "dev-fir") == "acx-dev-fir"
    assert _source_env_map("env_to_remote_dir", "dev-fir") == "/opt/acx-backend/dev-fir"
    assert (
        _source_env_map("env_to_health_url", "dev-fir")
        == "https://fir.dev.api.altcontext.com/health"
    )
    assert (
        _source_env_map("env_to_ready_url", "dev-fir")
        == "https://fir.dev.api.altcontext.com/ready"
    )
    assert (
        _source_env_map("env_to_compose_files", "dev-fir")
        == "-f docker-compose.env.yml"
    )


def _parse_env_example_key(text: str, key: str) -> str:
    """Return the value of KEY= from a dotenv-style file (first match)."""
    for line in text.splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise AssertionError(f"{key} not found in env example")


def _strip_caddy_comment(line: str) -> str:
    """Strip a Caddy `#` comment that is not inside quotes."""
    in_quote = False
    quote_char = ""
    out: list[str] = []
    for i, ch in enumerate(line):
        if in_quote:
            out.append(ch)
            if ch == quote_char and (i == 0 or line[i - 1] != "\\"):
                in_quote = False
            continue
        if ch in ("'", '"'):
            in_quote = True
            quote_char = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _caddy_site_top_level_directives(caddyfile: str, host: str) -> list[str]:
    """Return top-level directive texts for the site block that includes host.

    Comments are ignored. Directives inside nested blocks are not returned, so a
    `reverse_proxy` in another site or nested under `handle` cannot satisfy a
    check for this host (C-04).
    """
    lines = caddyfile.splitlines()
    start: int | None = None
    for i, raw in enumerate(lines):
        stripped = _strip_caddy_comment(raw).strip()
        if not stripped:
            continue
        if stripped.endswith("{"):
            addresses = stripped[:-1].strip()
            host_tokens = [h.strip() for h in addresses.split(",") if h.strip()]
            if host in host_tokens:
                start = i
                break
    assert start is not None, f"Caddyfile has no vhost for host {host!r}"

    directives: list[str] = []
    depth = 0
    for raw in lines[start:]:
        stripped = _strip_caddy_comment(raw).strip()
        if not stripped:
            continue
        opens = stripped.count("{")
        closes = stripped.count("}")
        if depth == 1:
            if stripped != "}":
                dir_text = stripped[:-1].strip() if stripped.endswith("{") else stripped
                if dir_text:
                    directives.append(dir_text)
        depth += opens - closes
        if depth == 0:
            break
    return directives


def _site_has_reverse_proxy(directives: list[str], upstream: str) -> bool:
    """True iff a top-level reverse_proxy targets upstream (not a substring hit)."""
    prefix = f"reverse_proxy {upstream}"
    for d in directives:
        if d == prefix or d.startswith(prefix + " ") or d.startswith(prefix + "{"):
            return True
    return False


def test_caddy_reverse_proxy_in_wrong_site_does_not_count() -> None:
    """C-04 RED fixture: reverse_proxy present only on another vhost must fail."""
    fixture = """
other.example.com {
	reverse_proxy dev-fir-api:8000
}

fir.dev.api.altcontext.com {
	respond / 200
}
"""
    directives = _caddy_site_top_level_directives(
        fixture, "fir.dev.api.altcontext.com"
    )
    assert not _site_has_reverse_proxy(directives, "dev-fir-api:8000"), (
        "reverse_proxy on a different site block must not satisfy the fir vhost check"
    )


def test_caddy_reverse_proxy_in_comment_does_not_count() -> None:
    """C-04: commented reverse_proxy must not satisfy the directive check."""
    fixture = """
fir.dev.api.altcontext.com {
	# reverse_proxy dev-fir-api:8000
	respond / 200
}
"""
    directives = _caddy_site_top_level_directives(
        fixture, "fir.dev.api.altcontext.com"
    )
    assert not _site_has_reverse_proxy(directives, "dev-fir-api:8000")


def test_caddy_reverse_proxy_nested_does_not_count_as_top_level() -> None:
    """C-04: reverse_proxy inside a nested block is not a top-level site directive."""
    fixture = """
fir.dev.api.altcontext.com {
	handle /api/* {
		reverse_proxy dev-fir-api:8000
	}
}
"""
    directives = _caddy_site_top_level_directives(
        fixture, "fir.dev.api.altcontext.com"
    )
    assert not _site_has_reverse_proxy(directives, "dev-fir-api:8000")


def test_dev_fir_ready_url_routable_via_caddy() -> None:
    """Ready URL host must be a Caddy vhost whose upstream network Caddy joins.

    Host is taken from env_to_ready_url (script); network from .env.fir.example
    (ACX_NETWORK_NAME). Neither is hard-coded as a parallel expected string, so
    a missing vhost or missing network attachment fails this test (C1+C3).
    """
    ready_url = _source_env_map("env_to_ready_url", "dev-fir")
    host = urlparse(ready_url).hostname
    assert host, f"could not parse host from ready URL {ready_url!r}"

    caddyfile = CADDYFILE.read_text()
    directives = _caddy_site_top_level_directives(caddyfile, host)

    fir_env = ENV_FIR_EXAMPLE.read_text()
    acx_env = _parse_env_example_key(fir_env, "ACX_ENV")
    network = _parse_env_example_key(fir_env, "ACX_NETWORK_NAME")
    expected_upstream = f"{acx_env}-api:8000"
    assert _site_has_reverse_proxy(directives, expected_upstream), (
        f"vhost {host} must reverse_proxy to {expected_upstream} "
        f"(compose alias ${{ACX_ENV}}-api); top-level directives={directives}"
    )

    # C-03: parse compose as YAML and assert against the specific keys — not the
    # first networks: list in the file, and not a whole-file external:true grep.
    compose_data = yaml.safe_load(CADDY_COMPOSE.read_text())
    assert isinstance(compose_data, dict), "docker-compose.caddy.yml must parse as a mapping"
    services = compose_data.get("services") or {}
    caddy_svc = services.get("caddy") or {}
    caddy_nets = caddy_svc.get("networks")
    assert caddy_nets is not None, "caddy service has no networks list"
    if isinstance(caddy_nets, dict):
        caddy_net_names = list(caddy_nets.keys())
    else:
        caddy_net_names = list(caddy_nets)
    assert network in caddy_net_names, (
        f"caddy is not attached to {network} (fir stack network from "
        f".env.fir.example ACX_NETWORK_NAME); attached={caddy_net_names}"
    )
    top_nets = compose_data.get("networks") or {}
    assert network in top_nets, (
        f"{network} must be declared under top-level networks (parsed YAML keys)"
    )


def test_shared_caddy_compose_does_not_require_fir_external_network() -> None:
    """C-09: shared docker-compose.caddy.yml must not require acx-dev-fir-net to pre-exist.

    external:true on a fir-specific network makes `docker compose up` of the
    shared caddy file fail when the fir stack has never created that network,
    taking down demo/dev deploys.
    """
    fir_env = ENV_FIR_EXAMPLE.read_text()
    network = _parse_env_example_key(fir_env, "ACX_NETWORK_NAME")
    compose_data = yaml.safe_load(CADDY_COMPOSE.read_text())
    top_nets = compose_data.get("networks") or {}
    assert network in top_nets, f"{network} must appear under top-level networks"
    net_cfg = top_nets[network]
    # null / empty mapping / name-only are fine; external:true is not.
    if isinstance(net_cfg, dict):
        external = net_cfg.get("external", False)
        if external is True or external == "true":
            raise AssertionError(
                f"{network} must not be external:true on the shared caddy compose "
                f"(breaks non-fir deploys when fir stack is absent); got {net_cfg!r}"
            )


def test_dev_fir_remote_dir_basename_matches_env() -> None:
    # systemd template hardcodes WorkingDirectory=/opt/acx-backend/{{ENV}};
    # remote dir basename MUST equal the ENV token (not a short alias like "fir").
    remote = _source_env_map("env_to_remote_dir", "dev-fir")
    assert remote.endswith("/dev-fir"), remote
    assert remote == f"/opt/acx-backend/dev-fir"


def test_dev_fir_status_loop_includes_env() -> None:
    # do_status hardcodes the env list; unknown envs stay fail-closed elsewhere.
    status_body = SCRIPT_TEXT.split("do_status()", 1)[1].split("\n}\n", 1)[0]
    assert "for env in dev dev-fir staging prod" in status_body


def test_legacy_env_mappings_unchanged() -> None:
    assert _source_env_map("env_to_tag", "dev") == "dev"
    assert _source_env_map("env_to_tag", "staging") == "staging"
    assert _source_env_map("env_to_tag", "prod") == "latest"
    assert _source_env_map("env_to_unit", "dev") == "acx-dev"
    assert _source_env_map("env_to_unit", "prod") == "acx-prod"
    assert (
        _source_env_map("env_to_compose_files", "prod")
        == "-f docker-compose.env.yml -f docker-compose.admin.yml"
    )


def test_unknown_env_still_fails_closed() -> None:
    for fn in (
        "env_to_tag",
        "env_to_unit",
        "env_to_remote_dir",
        "env_to_health_url",
        "env_to_ready_url",
        "env_to_compose_files",
    ):
        proc = subprocess.run(
            ["/bin/bash", "-c", f'source "{SCRIPT}"; {fn} bogus'],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert proc.returncode != 0, f"{fn} must fail closed for unknown env"
        assert "Unknown env" in (proc.stdout + proc.stderr)


def test_convergence_gated_by_env_flag_default_on() -> None:
    # Default-on: image-only restart only when ACX_CONVERGE_RUNTIME=0.
    assert "ACX_CONVERGE_RUNTIME:-1" in SCRIPT_TEXT


def test_converge_runs_before_restart_via_gate() -> None:
    # Convergence now runs inside promote_gate; do_deploy must gate before restart.
    deploy = SCRIPT_TEXT.split("do_deploy()", 1)[1].split("do_promote()", 1)[0]
    assert deploy.index("promote_gate") < deploy.index("do_restart")
    gate = SCRIPT_TEXT.split("promote_gate()", 1)[1].split("\n}\n", 1)[0]
    assert "converge_runtime" in gate


def test_caddy_edge_shipped_and_reloaded_by_converge() -> None:
    """C-08/C-12: converge_runtime must ship Caddyfile + caddy compose and reload."""
    start = SCRIPT_TEXT.index("converge_runtime()")
    end = SCRIPT_TEXT.index("converge_check()")
    converge_body = SCRIPT_TEXT[start:end]
    assert "Caddyfile" in converge_body, "converge_runtime must ship Caddyfile"
    assert "docker-compose.caddy.yml" in converge_body, (
        "converge_runtime must ship docker-compose.caddy.yml"
    )
    assert "caddy validate" in converge_body, (
        "converge_runtime must validate Caddy config before reload"
    )
    assert "docker compose -f docker-compose.caddy.yml up -d" in converge_body, (
        "converge_runtime must recreate/reload the caddy edge"
    )


# ---- face_pipeline models deploy preflight (FIR stack) -----------------


def test_defines_face_pipeline_models_preflight() -> None:
    assert "preflight_remote_face_pipeline_models()" in SCRIPT_TEXT
    assert "verify_face_pipeline_models_dir()" in SCRIPT_TEXT
    # Weights stay excluded from rsync; preflight is the gate, not bake-in.
    assert (
        "--exclude='recognition/infrastructure/face_pipeline/models/*.onnx'"
        in SCRIPT_TEXT
    )
    assert "face_detection_yunet_2026may.onnx" in SCRIPT_TEXT
    assert "face_recognition_sface_2021dec.onnx" in SCRIPT_TEXT


def _function_body(name: str) -> str:
    """Return the body of `name()` from SCRIPT_TEXT (definition line, not a mention)."""
    marker = f"{name}() {{"
    # Prefer the definition form `name() {` on its own line.
    idx = SCRIPT_TEXT.find(f"\n{marker}")
    if idx < 0:
        idx = SCRIPT_TEXT.find(marker)
        assert idx >= 0, f"function {name}() not found"
        start = idx
    else:
        start = idx + 1  # skip leading newline
    # Body ends at the next top-level `}` that closes this function — use the
    # existing section-splitter convention: next `\n}\n` after the definition
    # that is followed by a blank line or section banner is imperfect for nested
    # braces, so brace-count from the opening `{`.
    depth = 0
    i = SCRIPT_TEXT.find("{", start)
    assert i >= 0
    for j in range(i, len(SCRIPT_TEXT)):
        ch = SCRIPT_TEXT[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return SCRIPT_TEXT[start : j + 1]
    raise AssertionError(f"unclosed function {name}")


def test_deploy_calls_face_pipeline_preflight_before_build() -> None:
    deploy = _function_body("do_deploy")
    # Read-only --check path returns early; the mutation path must preflight models.
    assert "preflight_remote_face_pipeline_models" in deploy
    assert deploy.index("preflight_remote_face_pipeline_models") < deploy.index(
        "do_build"
    )


def test_promote_calls_face_pipeline_preflight() -> None:
    """C-02: promote re-points the to_env runtime and must preflight models."""
    promote = _function_body("do_promote")
    assert "preflight_remote_face_pipeline_models" in promote, (
        "do_promote must call preflight_remote_face_pipeline_models (C-02)"
    )


def test_reset_calls_face_pipeline_preflight() -> None:
    """C-02: reset restarts the runtime and must preflight models."""
    reset = _function_body("do_reset")
    assert "preflight_remote_face_pipeline_models" in reset, (
        "do_reset must call preflight_remote_face_pipeline_models (C-02)"
    )


def test_face_pipeline_preflight_does_not_swallow_ssh_failures() -> None:
    """C-06: local ssh invocations in the preflight path must not end in `|| true`."""
    body = _function_body("preflight_remote_face_pipeline_models")
    # Ban the two historical forms: `$(ssh ...) || true` and `<<REMOTE || true`.
    # Remote-side `grep ... || true` inside a double-quoted remote command is OK
    # (expected missing-key path) and does not match these patterns.
    assert re.search(r"<<REMOTE\s*\|\|\s*true", body) is None, (
        "preflight must not append || true to the remote verify ssh heredoc"
    )
    # Drop comments and double-quoted remote strings, then forbid local || true
    # attached to an ssh invocation (not prose that merely mentions the anti-pattern).
    def _code_only(text: str) -> str:
        no_comments = re.sub(r"(?m)^\s*#.*$", "", text)
        return re.sub(r'"([^"\\]|\\.)*"', '""', no_comments)

    stripped = _code_only(body)
    assert re.search(r"(?:^|[^#])\s*\$?\(?ssh\b[\s\S]{0,200}\|\|\s*true", stripped) is None, (
        "preflight must not swallow local ssh failures with || true"
    )
    if "_remote_dotenv_value()" in SCRIPT_TEXT:
        helper = _code_only(_function_body("_remote_dotenv_value"))
        assert re.search(
            r"(?:^|[^#])\s*\$?\(?ssh\b[\s\S]{0,200}\|\|\s*true", helper
        ) is None, (
            "_remote_dotenv_value must not swallow local ssh failures with || true"
        )


def test_face_pipeline_preflight_reads_authoritative_models_dir() -> None:
    """C-10 [sr-007]: preflight must read RECOGNITION_FACE_PIPELINE_MODELS_DIR."""
    body = _function_body("preflight_remote_face_pipeline_models")
    assert "RECOGNITION_FACE_PIPELINE_MODELS_DIR" in body
    assert re.search(
        r'models_dir="\$\{models_path\}/face_pipeline"', body
    ) is None, "must not hardcode models_dir=${ACX_MODELS_PATH}/face_pipeline (sr-007)"


def test_face_pipeline_sha_pins_match_provenance() -> None:
    """C-11: deploy pins must match provenance.py MODEL_MANIFEST sha256 values."""
    # Parse MODEL_MANIFEST pins from provenance.py text (avoid package import path).
    text = PROVENANCE.read_text(encoding="utf-8")
    # Match file_name=... sha256=... pairs inside MODEL_MANIFEST entries.
    blocks = re.findall(
        r'ModelProvenance\(\s*file_name="([^"]+)",\s*sha256="([0-9a-f]{64})"',
        text,
    )
    assert blocks, "could not parse MODEL_MANIFEST pins from provenance.py"
    for file_name, sha in blocks:
        pin = f"{file_name}:{sha}"
        assert pin in SCRIPT_TEXT, (
            f"recognition-service.sh must pin {pin} from MODEL_MANIFEST"
        )


def _run_face_pipeline_preflight(
    env_arg: str, tmp_path: Path, ssh_script: str
) -> subprocess.CompletedProcess[str]:
    """Source the deploy script and run the models preflight with a fake ssh."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "ssh").write_text(ssh_script)
    (bindir / "ssh").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'source "{SCRIPT}"; preflight_remote_face_pipeline_models {env_arg}',
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_verify_models_dir(
    models_dir: Path, *, sha_overrides: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    """C-07: execute verify_face_pipeline_models_dir locally against models_dir."""
    override = ""
    if sha_overrides is not None:
        # Rebuild the pin array after sourcing so hermetic tests need no real ONNX.
        quoted = " ".join(f'"{p}"' for p in sha_overrides)
        override = f"FACE_PIPELINE_ONNX_SHA256=({quoted})\n"
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            f'source "{SCRIPT}"; {override}verify_face_pipeline_models_dir "{models_dir}"',
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_verify_face_pipeline_models_dir_absent_fails(tmp_path: Path) -> None:
    """C-07: extracted body exits non-zero when the models dir is missing."""
    missing = tmp_path / "no-such-models"
    proc = _run_verify_models_dir(missing)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "DIR_FAIL:" in (proc.stdout + proc.stderr)


def test_verify_face_pipeline_models_dir_missing_file_fails(tmp_path: Path) -> None:
    """C-07: extracted body exits non-zero when an ONNX file is absent."""
    models = tmp_path / "models"
    models.mkdir()
    # Override pins to tiny synthetic names so we do not need real ONNX blobs.
    content = b"good-bytes"
    digest = hashlib.sha256(content).hexdigest()
    (models / "a.onnx").write_bytes(content)
    # b.onnx intentionally missing
    proc = _run_verify_models_dir(
        models, sha_overrides=[f"a.onnx:{digest}", f"b.onnx:{digest}"]
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "FILE_FAIL:b.onnx" in (proc.stdout + proc.stderr)


def test_verify_face_pipeline_models_dir_corrupt_hash_fails(tmp_path: Path) -> None:
    """C-11: corrupt/truncated weights must fail the integrity preflight."""
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.onnx").write_bytes(b"corrupt")
    (models / "b.onnx").write_bytes(b"also-corrupt")
    wrong = "0" * 64
    proc = _run_verify_models_dir(
        models, sha_overrides=[f"a.onnx:{wrong}", f"b.onnx:{wrong}"]
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "HASH_FAIL:" in (proc.stdout + proc.stderr)


def test_verify_face_pipeline_models_dir_present_passes(tmp_path: Path) -> None:
    """C-07: extracted body exits 0 when weights are present and hash-match."""
    models = tmp_path / "models"
    models.mkdir()
    a = b"yunet-fixture-bytes"
    b = b"sface-fixture-bytes"
    (models / "a.onnx").write_bytes(a)
    (models / "b.onnx").write_bytes(b)
    pins = [
        f"a.onnx:{hashlib.sha256(a).hexdigest()}",
        f"b.onnx:{hashlib.sha256(b).hexdigest()}",
    ]
    proc = _run_verify_models_dir(models, sha_overrides=pins)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip().endswith("OK")


def test_face_pipeline_preflight_skips_non_fir(tmp_path: Path) -> None:
    # Non-fir envs must not require face_pipeline ONNX on the host.
    proc = _run_face_pipeline_preflight(
        "dev",
        tmp_path,
        "#!/bin/sh\necho 'ssh should not run for non-fir' >&2\nexit 99\n",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_face_pipeline_preflight_fails_when_models_dir_missing(tmp_path: Path) -> None:
    # Fail closed: missing/unreadable dir is a failure (never a silent pass).
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "RECOGNITION_FACE_PIPELINE_MODELS_DIR"; then
  echo "/data/cache/face_pipeline"
  exit 0
fi
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
# Remote bash -s body: directory missing/unreadable.
cat >/dev/null
echo "DIR_FAIL:/opt/acx-backend/data/dev-fir-models/face_pipeline"
exit 1
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "face_pipeline" in combined
    assert "missing or unreadable" in combined.lower()
    assert "/opt/acx-backend/data/dev-fir-models/face_pipeline" in combined


def test_face_pipeline_preflight_fails_when_onnx_missing(tmp_path: Path) -> None:
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "RECOGNITION_FACE_PIPELINE_MODELS_DIR"; then
  echo "/data/cache/face_pipeline"
  exit 0
fi
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
cat >/dev/null
echo "FILE_FAIL:face_recognition_sface_2021dec.onnx:/opt/acx-backend/data/dev-fir-models/face_pipeline"
exit 1
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "face_recognition_sface_2021dec.onnx" in combined
    assert "/opt/acx-backend/data/dev-fir-models/face_pipeline" in combined


def test_face_pipeline_preflight_fails_when_models_path_unset(tmp_path: Path) -> None:
    ssh = r"""#!/bin/sh
# Empty RECOGNITION_FACE_PIPELINE_MODELS_DIR (missing key) must fail closed.
if echo "$*" | grep -q "RECOGNITION_FACE_PIPELINE_MODELS_DIR"; then
  echo ""
  exit 0
fi
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
exit 0
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined
    assert "RECOGNITION_FACE_PIPELINE_MODELS_DIR" in combined


def test_face_pipeline_preflight_fails_on_ssh_error(tmp_path: Path) -> None:
    """C-06: ssh failure is indistinguishable from success when swallowed — must fail closed."""
    proc = _run_face_pipeline_preflight(
        "dev-fir",
        tmp_path,
        "#!/bin/sh\nexit 255\n",
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, combined


def test_face_pipeline_preflight_preserves_interior_spaces_in_env(tmp_path: Path) -> None:
    """C-05: remote dotenv values with interior spaces must not be mangled."""
    # Host-absolute models dir containing a space; no /data/cache mapping.
    # Fake ssh returns a value with interior spaces; the verify body must receive
    # that path (printf %q-escaped is fine — stripping spaces is not).
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "RECOGNITION_FACE_PIPELINE_MODELS_DIR"; then
  printf '%s' "/opt/acx models/face pipeline"
  exit 0
fi
body=$(cat)
# Accept either literal spaces or shell-escaped spaces from printf %q.
echo "$body" | grep -E '/opt/acx(\\ | )models/face(\\ | )pipeline' >/dev/null || {
  echo "SPACE_MANGLED body=$body"
  exit 1
}
# Fail if the old tr -d "\"' " style collapsed interiors to /opt/acxmodels/facepipeline
echo "$body" | grep -F '/opt/acxmodels/facepipeline' >/dev/null && {
  echo "SPACE_MANGLED_COLLAPSED"
  exit 1
}
echo OK
exit 0
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "SPACE_MANGLED" not in combined


def test_face_pipeline_preflight_passes_when_models_present(tmp_path: Path) -> None:
    ssh = r"""#!/bin/sh
if echo "$*" | grep -q "RECOGNITION_FACE_PIPELINE_MODELS_DIR"; then
  echo "/data/cache/face_pipeline"
  exit 0
fi
if echo "$*" | grep -q "ACX_MODELS_PATH"; then
  echo "/opt/acx-backend/data/dev-fir-models"
  exit 0
fi
cat >/dev/null
echo "OK"
exit 0
"""
    proc = _run_face_pipeline_preflight("dev-fir", tmp_path, ssh)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "face_pipeline ONNX weights present" in combined


# ---- behavioral (hermetic) ---------------------------------------------


def test_check_unknown_env_fails_fast() -> None:
    # Env validated before any network; unknown env fails with a clear message.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        result = _run(["deploy", "bogus", "--check"], Path(d))
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Unknown env" in combined


def test_check_reports_drift_without_mutating(tmp_path: Path) -> None:
    result = _run(["deploy", "prod", "--check"], tmp_path)
    combined = result.stdout + result.stderr
    # Deployed compose is empty (fake ssh) → drift detected → non-zero exit.
    assert result.returncode != 0
    assert "drift" in combined.lower()
    # Read-only: --check must never scp anything to the VM.
    assert not (tmp_path / "scp-was-called").exists(), "--check must not mutate the VM"


def test_check_does_not_require_promote_confirm(tmp_path: Path) -> None:
    # --check is read-only, so it must not demand CONFIRM=PROMOTE for prod.
    result = _run(["deploy", "prod", "--check"], tmp_path)
    combined = result.stdout + result.stderr
    assert "CONFIRM=PROMOTE" not in combined


# ---- converge_runtime mutation path (hermetic, sourced) -----------------


def _run_converge_runtime(env_arg: str, tmp_path: Path) -> str:
    """Source the script and run `converge_runtime <env>` with recording fakes.

    Returns the recorded ssh/scp command log so tests can assert which files
    were shipped (env compose always, admin overlay only for prod, Caddy edge
    always) and which remote edge reload commands ran.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    scp_log = tmp_path / "ship.log"
    # Record argv and any stdin body (edge validate/reload travels via bash -s).
    (bindir / "ssh").write_text(
        f"""#!/bin/sh
echo "$@" >> {scp_log}
if [ ! -t 0 ]; then
  body=$(cat)
  if [ -n "$body" ]; then
    echo "STDIN:$body" >> {scp_log}
  fi
fi
exit 0
"""
    )
    (bindir / "scp").write_text(f'#!/bin/sh\necho "SCP $@" >> {scp_log}\nexit 0\n')
    for name in ("ssh", "scp"):
        (bindir / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    subprocess.run(
        ["/bin/bash", "-c", f'source "{SCRIPT}"; converge_runtime {env_arg}'],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return scp_log.read_text() if scp_log.exists() else ""


def test_converge_runtime_ships_both_compose_files_for_prod(tmp_path: Path) -> None:
    log = _run_converge_runtime("prod", tmp_path)
    assert "sudo cp '/tmp/docker-compose.env.yml'" in log
    assert "sudo cp '/tmp/docker-compose.admin.yml'" in log, "prod must ship the admin overlay"
    assert "SCP " not in log, "compose files must not travel via direct scp (root-owned targets)"
    # C-08/C-12: shared edge must be shipped on every converge path.
    assert "sudo cp '/tmp/Caddyfile'" in log, "converge_runtime must ship Caddyfile"
    assert "sudo cp '/tmp/docker-compose.caddy.yml'" in log, (
        "converge_runtime must ship docker-compose.caddy.yml"
    )


def test_converge_runtime_ships_only_env_compose_for_dev(tmp_path: Path) -> None:
    log = _run_converge_runtime("dev", tmp_path)
    assert "sudo cp '/tmp/docker-compose.env.yml'" in log
    # Ship helper installs via /tmp/<basename>; admin overlay must not be installed for dev.
    assert "sudo cp '/tmp/docker-compose.admin.yml'" not in log, (
        "dev must not ship the admin overlay"
    )
    assert "sudo cp '/tmp/Caddyfile'" in log, "dev converge must still ship shared Caddy edge"


def test_converge_runtime_ships_only_env_compose_for_dev_fir(tmp_path: Path) -> None:
    log = _run_converge_runtime("dev-fir", tmp_path)
    assert "sudo cp '/tmp/docker-compose.env.yml'" in log
    assert "sudo cp '/tmp/docker-compose.admin.yml'" not in log, (
        "dev-fir must not ship the admin overlay"
    )
    assert "/opt/acx-backend/dev-fir" in log
    assert "sudo cp '/tmp/Caddyfile'" in log, "dev-fir converge must ship shared Caddy edge"
    assert "sudo cp '/tmp/docker-compose.caddy.yml'" in log
    # Edge validate + reload commands must be issued over ssh (stdin body).
    assert "caddy validate" in log, "converge_runtime must run caddy validate on the edge"
    assert "docker compose -f docker-compose.caddy.yml up -d" in log, (
        "converge_runtime must recreate the caddy edge"
    )


def test_check_passes_clean_when_deployed_matches_repo(tmp_path: Path) -> None:
    # BR2-11: the no-drift branch of converge_check must exit 0 — a fake ssh
    # cats the repo's own compose/admin/rendered-unit content back, so every
    # diff matches.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "ssh").write_text(
        """#!/bin/sh
case "$*" in
  *docker-compose.env.yml*) cat "$REPO_ENV_COMPOSE" ;;
  *docker-compose.admin.yml*) cat "$REPO_ADMIN_COMPOSE" ;;
  *.service*) cat "$RENDERED_UNIT" ;;
esac
exit 0
"""
    )
    (bindir / "ssh").chmod(0o755)
    unit_file = tmp_path / "unit.txt"
    script = (
        f'source "{SCRIPT}"; '
        f'render_unit prod > "{unit_file}"; '
        f'export REPO_ENV_COMPOSE="$SERVICE_DIR/docker-compose.env.yml"; '
        f'export REPO_ADMIN_COMPOSE="$SERVICE_DIR/docker-compose.admin.yml"; '
        f'export RENDERED_UNIT="{unit_file}"; '
        "converge_check prod"
    )
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    proc = subprocess.run(
        ["/bin/bash", "-c", script], env=env, capture_output=True, text=True, timeout=30
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "no runtime drift" in combined


def test_converge_ships_compose_files_via_sudo_install(tmp_path: Path) -> None:
    # E15-34-DEPLOYFIX: compose files on the VM can be root-owned (the E15-29
    # admin overlay was installed via sudo), so a plain `scp` to the final path
    # fails with Permission denied. Both compose ships must go through the same
    # /tmp + `sudo cp` pattern the unit file uses.
    body = SCRIPT_TEXT.split("converge_runtime()", 1)[1].split("\n}\n", 1)[0]
    assert 'scp "' not in body, "converge_runtime must not scp directly to the target path"
    # Structural: the shared ship helper stages under /tmp and installs with
    # sudo cp; the behavioral tests above assert the expanded per-file commands.
    assert "sudo cp '/tmp/" in body, "compose ship must go via /tmp + sudo cp"
