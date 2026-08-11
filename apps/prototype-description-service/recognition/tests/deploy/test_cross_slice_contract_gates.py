"""ORCH-LAUNCH-01 HARM-A-02/03: cross-slice contract gates (HF modules + bake).

Two contracts the branch depends on were enforced by nothing: a reviewer
proved six live-tree mutations each ship an unbootable container while every
gate stayed green.

BLOCKER 1 (HARM-A-02) — HF_MODULES_CACHE:
  transformers reads HF_MODULES_CACHE at import time from a module-level
  constant, so it can only be set as an image ENV. trust_remote_code needs a
  writable module cache; the secure arrangement is a private noexec tmpfs for
  modules while weights stay :ro (SEC-13). Silently losing the tmpfs means
  remote-code modules land in an executable container-layer directory.

BLOCKER 2 (HARM-A-03) — /app/.image-variant:
  ENV ACX_IMAGE_VARIANT is explicitly non-authoritative (compose env_file can
  override it). The bake at /app/.image-variant is the source of truth. The
  topology gate at test_dockerfile_stage_topology.py pins only the ENV half;
  this module pins the authoritative bake + chmod 0444 with stage-derived
  labels (do not hardcode a single string for both stages).

Assertions read the live Dockerfile + docker-compose.env.yml +
docker-compose.prod.yml. Synthetic tmp_path fixtures only prove discriminators
bite (TEST-15). Stage scoping uses recognition.tests.dockerfile_stages — not
whole-file greps. Boot-smoke / blob-repair deploy steps are parsed from the
real recognition-service.sh (sourced helpers stay behavioural; structural
body checks only pin mount flags and call sites).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from recognition.tests.dockerfile_stages import (
    DEFAULT_RUNTIME_STAGE,
    RUNTIME_BASE_STAGE,
    RUNTIME_VLM_STAGE,
    dockerfile_stages,
    effective_stage_body,
    join_continued_lines,
)

SERVICE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[5]
DOCKERFILE = SERVICE_ROOT / "Dockerfile"
COMPOSE_ENV = SERVICE_ROOT / "docker-compose.env.yml"
COMPOSE_PROD = SERVICE_ROOT / "docker-compose.prod.yml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy" / "recognition-service.sh"

# Runtime stages that must bake an identity file (not builder stages).
_RUNTIME_STAGES = (DEFAULT_RUNTIME_STAGE, RUNTIME_VLM_STAGE)

# Services that run the recognition image and need the modules tmpfs.
_APP_SERVICES = ("api", "worker")

# Compose files that ship the HF modules tmpfs + blob volume topology.
_COMPOSE_FILES = (
    ("docker-compose.env.yml", COMPOSE_ENV),
    ("docker-compose.prod.yml", COMPOSE_PROD),
)

_ENV_ASSIGN_RE = re.compile(
    r"^\s*ENV\s+([A-Za-z_][\w]*)=(.+?)\s*$",
    re.IGNORECASE,
)
_PRINTF_BAKE_RE = re.compile(
    r"""printf\s+['"](?P<label>[^'"]+)\\n['"]\s*>\s*/app/\.image-variant""",
)
_CHMOD_0444_RE = re.compile(r"chmod\s+0444\s+/app/\.image-variant")


# ---- parsers (live-tree + synthetic) -------------------------------------


def _active_lines(stage_text: str) -> list[str]:
    """Logical Dockerfile lines with comments stripped."""
    out: list[str] = []
    for ln in join_continued_lines(stage_text):
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def env_assignments(stage_text: str) -> dict[str, str]:
    """Map NAME -> value for ``ENV NAME=value`` lines (ignores ENV NAME value form)."""
    found: dict[str, str] = {}
    for ln in _active_lines(stage_text):
        m = _ENV_ASSIGN_RE.match(ln)
        if m:
            found[m.group(1)] = m.group(2).strip().strip("\"'")
    return found


def env_is_declared(stage_text: str, name: str) -> bool:
    """True when ``ENV name=…`` appears as an image ENV (not ARG / RUN export)."""
    return name in env_assignments(stage_text)


def useradd_uid(stage_text: str) -> int | None:
    """Uid from ``useradd … -u N`` in the stage body, or None."""
    joined = "\n".join(_active_lines(stage_text))
    m = re.search(r"\buseradd\b[^\n]*?-u\s+(\d+)\b", joined, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def expected_image_variant_for_stage(stage_name: str) -> str:
    """Derive bake label from stage identity — never a single hardcoded string.

    ``runtime`` / default recognition stage → recognition.
    Any stage whose name ends with ``-vlm`` (e.g. runtime-vlm) → vlm.
    """
    if stage_name.endswith("-vlm"):
        return "vlm"
    if stage_name == DEFAULT_RUNTIME_STAGE or stage_name == "runtime":
        return "recognition"
    raise ValueError(f"no image-variant mapping for stage {stage_name!r}")


def stage_bakes_image_variant(stage_text: str, expected: str) -> bool:
    """True when stage prints expected label into /app/.image-variant + chmod 0444."""
    bake_ok = False
    chmod_ok = False
    for ln in _active_lines(stage_text):
        m = _PRINTF_BAKE_RE.search(ln)
        if m and m.group("label") == expected:
            bake_ok = True
        if _CHMOD_0444_RE.search(ln):
            chmod_ok = True
        if (
            m
            and m.group("label") == expected
            and _CHMOD_0444_RE.search(ln)
        ):
            return True
    return bake_ok and chmod_ok


def hf_modules_cache_outside_hf_home(stage_text: str) -> bool:
    """HF_MODULES_CACHE path must not be nested under HF_HOME (SEC-13)."""
    envs = env_assignments(stage_text)
    modules = envs.get("HF_MODULES_CACHE")
    home = envs.get("HF_HOME")
    if not modules:
        return False
    if not home:
        # No HF_HOME → cannot nest; ENV alone is enough for this half.
        return True
    modules_n = modules.rstrip("/")
    home_n = home.rstrip("/")
    if modules_n == home_n:
        return False
    if modules_n.startswith(home_n + "/"):
        return False
    return True


def _load_compose(path: Path = COMPOSE_ENV) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name}: expected mapping, got {type(data)}")
    return data


def service_tmpfs_specs(compose: dict, service: str) -> list[str]:
    """Raw tmpfs mount strings for a compose service (e.g. '/path:mode=…')."""
    services = compose.get("services") or {}
    svc = services.get(service)
    if not isinstance(svc, dict):
        return []
    raw = svc.get("tmpfs")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def parse_tmpfs_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Split ``/path:mode=0700,uid=1,noexec`` into (path, options)."""
    if ":" in spec:
        path, opt_str = spec.split(":", 1)
    else:
        path, opt_str = spec, ""
    opts: dict[str, str] = {}
    flags: list[str] = []
    for part in opt_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            opts[k.strip()] = v.strip()
        else:
            flags.append(part)
            opts[part] = ""
    # Preserve flag presence for noexec checks via empty value.
    for f in flags:
        opts.setdefault(f, "")
    return path.strip(), opts


def modules_tmpfs_for_service(
    compose: dict, service: str, modules_path: str
) -> dict[str, str] | None:
    """Options dict for the tmpfs mounted at modules_path, or None if missing."""
    for spec in service_tmpfs_specs(compose, service):
        path, opts = parse_tmpfs_spec(spec)
        if path.rstrip("/") == modules_path.rstrip("/"):
            return opts
    return None


def tmpfs_contract_ok(opts: dict[str, str], *, uid: int, gid: int | None = None) -> bool:
    """noexec + mode=0700 + uid(/gid) parity with the image runtime user."""
    if "noexec" not in opts:
        return False
    if opts.get("mode") != "0700":
        return False
    if opts.get("uid") != str(uid):
        return False
    expected_gid = str(gid if gid is not None else uid)
    if opts.get("gid") != expected_gid:
        return False
    return True


# ---- positive: live tree -------------------------------------------------


def test_dockerfile_declares_hf_modules_cache_as_env() -> None:
    """HARM-A-02: HF_MODULES_CACHE must be image ENV (not ARG / RUN export)."""
    # Effective body of the default runtime inherits runtime-base ENV.
    body = effective_stage_body(DOCKERFILE, DEFAULT_RUNTIME_STAGE)
    assert env_is_declared(body, "HF_MODULES_CACHE"), (
        "Dockerfile must declare ENV HF_MODULES_CACHE=… so transformers sees it "
        "at import time (RUN export / ARG alone are invisible to the runtime process)"
    )
    # Own-body of runtime-base is the declaration site (not a sibling stage only).
    base = dockerfile_stages(DOCKERFILE)[RUNTIME_BASE_STAGE]
    assert env_is_declared(base, "HF_MODULES_CACHE"), (
        "ENV HF_MODULES_CACHE must live on runtime-base so both runtime images inherit it"
    )
    value = env_assignments(body)["HF_MODULES_CACHE"]
    assert value.startswith("/"), f"HF_MODULES_CACHE must be an absolute path, got {value!r}"


def test_hf_modules_cache_not_nested_under_hf_home() -> None:
    """Module scratch must stay off the :ro weight mount under HF_HOME."""
    body = effective_stage_body(DOCKERFILE, DEFAULT_RUNTIME_STAGE)
    assert hf_modules_cache_outside_hf_home(body), (
        "HF_MODULES_CACHE must not equal or nest under HF_HOME "
        f"(got {env_assignments(body)!r})"
    )


def _live_hf_modules_cache_path() -> str:
    """HF_MODULES_CACHE from the live Dockerfile effective runtime body."""
    body = effective_stage_body(DOCKERFILE, DEFAULT_RUNTIME_STAGE)
    envs = env_assignments(body)
    assert "HF_MODULES_CACHE" in envs, (
        "Dockerfile must declare ENV HF_MODULES_CACHE before compose tmpfs can "
        "be checked against it"
    )
    return envs["HF_MODULES_CACHE"]


def test_compose_api_and_worker_mount_modules_tmpfs() -> None:
    """Both api and worker must tmpfs-mount the exact HF_MODULES_CACHE path.

    Covers env + prod compose (HARM-A-02 live half: prod was previously ungated).
    """
    modules_path = _live_hf_modules_cache_path()
    for label, path in _COMPOSE_FILES:
        compose = _load_compose(path)
        for service in _APP_SERVICES:
            opts = modules_tmpfs_for_service(compose, service, modules_path)
            assert opts is not None, (
                f"{label} service {service!r} must mount tmpfs at "
                f"{modules_path} (HF_MODULES_CACHE)"
            )


def test_modules_tmpfs_noexec_mode_and_uid_parity() -> None:
    """tmpfs: noexec + mode=0700 + uid/gid == Dockerfile useradd -u (derived).

    Asserted on every compose file that runs the recognition image (env + prod).
    """
    stages = dockerfile_stages(DOCKERFILE)
    base = stages[RUNTIME_BASE_STAGE]
    uid = useradd_uid(base)
    assert uid is not None, "runtime-base must create acx via useradd -u <uid>"
    modules_path = _live_hf_modules_cache_path()
    for label, path in _COMPOSE_FILES:
        compose = _load_compose(path)
        for service in _APP_SERVICES:
            opts = modules_tmpfs_for_service(compose, service, modules_path)
            assert opts is not None, (
                f"{label} {service}: missing modules tmpfs at {modules_path}"
            )
            assert tmpfs_contract_ok(opts, uid=uid), (
                f"{label} {service}: tmpfs at {modules_path} must carry noexec, "
                f"mode=0700, uid={uid}, gid={uid} (derived from Dockerfile "
                f"useradd); got {opts}"
            )


def _compose_has_blob_ownership_repair(compose_text: str) -> bool:
    """True when compose defines a root one-shot chown repair for acx_blobs."""
    if not re.search(r"^\s*fix-blob-ownership\s*:", compose_text, re.MULTILINE):
        return False
    if not re.search(r'user:\s*["\']?0:0["\']?', compose_text):
        return False
    if "chown" not in compose_text or "/var/lib/acx-blobs" not in compose_text:
        return False
    if not re.search(r'profiles:\s*\[\s*["\']repair["\']\s*\]', compose_text):
        return False
    if not re.search(r"acx_blobs:/var/lib/acx-blobs", compose_text):
        return False
    return True


def test_compose_env_and_prod_blob_ownership_repair_profile() -> None:
    """Both compose files ship fix-blob-ownership (S1-A-02 prod half was open)."""
    for label, path in _COMPOSE_FILES:
        text = path.read_text(encoding="utf-8")
        assert _compose_has_blob_ownership_repair(text), (
            f"{label} must ship profiles:[repair] fix-blob-ownership that chowns "
            f"acx_blobs as root (Docker never re-chowns existing named volumes)"
        )


def _fn_body(script_text: str, name: str) -> str:
    start = script_text.index(f"{name}()")
    end = script_text.index("\n}\n", start)
    return script_text[start:end]


def test_boot_smoke_mounts_modules_tmpfs_matching_dockerfile() -> None:
    """HARM-A-02: Gate 2 run_args must tmpfs-mount HF_MODULES_CACHE with parity.

    Behavioural contract: the live Dockerfile ENV path + useradd uid appear in
    do_boot_smoke's --tmpfs flag with noexec (not a synthetic re-implementation
    of the smoke itself).
    """
    modules_path = _live_hf_modules_cache_path()
    stages = dockerfile_stages(DOCKERFILE)
    uid = useradd_uid(stages[RUNTIME_BASE_STAGE])
    assert uid is not None
    body = _fn_body(DEPLOY_SCRIPT.read_text(encoding="utf-8"), "do_boot_smoke")
    # --tmpfs /path:mode=0700,uid=N,gid=N,...,noexec
    tmpfs_flags = re.findall(r"--tmpfs\s+(\S+)", body)
    assert tmpfs_flags, (
        "do_boot_smoke must pass --tmpfs for HF_MODULES_CACHE so smoke exercises "
        "the deployed mount topology (not the image-layer seed dir)"
    )
    matched = False
    for flag in tmpfs_flags:
        path, opts = parse_tmpfs_spec(flag)
        if path.rstrip("/") != modules_path.rstrip("/"):
            continue
        assert tmpfs_contract_ok(opts, uid=uid), (
            f"do_boot_smoke --tmpfs {flag!r} must match Dockerfile "
            f"HF_MODULES_CACHE={modules_path} uid={uid} noexec mode=0700"
        )
        matched = True
    assert matched, (
        f"do_boot_smoke --tmpfs must include path {modules_path} "
        f"(from Dockerfile ENV HF_MODULES_CACHE); got {tmpfs_flags}"
    )


def test_deploy_restart_runs_blob_ownership_repair() -> None:
    """S1-A-02: do_restart must invoke repair_blob_volume_ownership before unit restart."""
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "repair_blob_volume_ownership()" in script, (
        "recognition-service.sh must define repair_blob_volume_ownership"
    )
    repair_body = _fn_body(script, "repair_blob_volume_ownership")
    assert "--profile repair" in repair_body
    assert "fix-blob-ownership" in repair_body
    restart_body = _fn_body(script, "do_restart")
    assert "repair_blob_volume_ownership" in restart_body, (
        "do_restart must call repair_blob_volume_ownership so existing root:root "
        "acx_blobs volumes are chowned before USER acx serves traffic"
    )
    # Repair must run before systemctl restart (order is load-bearing).
    assert restart_body.index("repair_blob_volume_ownership") < restart_body.index(
        "systemctl restart"
    )


def test_every_runtime_stage_bakes_stage_identity_image_variant() -> None:
    """HARM-A-03: each runtime stage bakes /app/.image-variant for its own identity.

    Expected label is derived from the stage name (runtime → recognition,
    *-vlm → vlm). ENV ACX_IMAGE_VARIANT alone is non-authoritative and remains
    gated separately in test_dockerfile_stage_topology.py.
    """
    stages = dockerfile_stages(DOCKERFILE)
    for stage in _RUNTIME_STAGES:
        assert stage in stages, f"missing runtime stage {stage!r}"
        expected = expected_image_variant_for_stage(stage)
        own = stages[stage]
        assert stage_bakes_image_variant(own, expected), (
            f"{stage} must `printf '{expected}\\n' > /app/.image-variant && chmod 0444` "
            f"(stage-derived identity; ENV alone fails open under compose env_file)"
        )
        # Cross-wire protection: must not bake the sibling identity.
        sibling = "vlm" if expected == "recognition" else "recognition"
        assert not stage_bakes_image_variant(own, sibling), (
            f"{stage} must not bake sibling identity {sibling!r}"
        )


# ---- discriminators / TEST-15 --------------------------------------------


def test_discriminator_env_not_arg_or_run_export() -> None:
    """ENV form passes; ARG / RUN export do not satisfy env_is_declared."""
    assert env_is_declared("ENV HF_MODULES_CACHE=/var/cache/acx/hf_modules\n", "HF_MODULES_CACHE")
    assert not env_is_declared("ARG HF_MODULES_CACHE=/var/cache/acx/hf_modules\n", "HF_MODULES_CACHE")
    assert not env_is_declared(
        "RUN export HF_MODULES_CACHE=/var/cache/acx/hf_modules\n", "HF_MODULES_CACHE"
    )
    assert not env_is_declared("# ENV HF_MODULES_CACHE=/var/cache/acx/hf_modules\n", "HF_MODULES_CACHE")


def test_discriminator_nested_under_hf_home_fails() -> None:
    good = (
        "ENV HF_MODULES_CACHE=/var/cache/acx/hf_modules\n"
        "ENV HF_HOME=/data/cache/huggingface_cache\n"
    )
    nested = (
        "ENV HF_HOME=/data/cache/huggingface_cache\n"
        "ENV HF_MODULES_CACHE=/data/cache/huggingface_cache/modules\n"
    )
    equal = (
        "ENV HF_HOME=/data/cache/huggingface_cache\n"
        "ENV HF_MODULES_CACHE=/data/cache/huggingface_cache\n"
    )
    assert hf_modules_cache_outside_hf_home(good)
    assert not hf_modules_cache_outside_hf_home(nested)
    assert not hf_modules_cache_outside_hf_home(equal)


def test_discriminator_tmpfs_missing_noexec_or_mode_or_uid() -> None:
    uid = 10001
    good = {"mode": "0700", "uid": "10001", "gid": "10001", "noexec": "", "size": "32m"}
    assert tmpfs_contract_ok(good, uid=uid)
    assert not tmpfs_contract_ok({**good, "mode": "0755"}, uid=uid)
    assert not tmpfs_contract_ok({k: v for k, v in good.items() if k != "noexec"}, uid=uid)
    assert not tmpfs_contract_ok({**good, "uid": "10002"}, uid=uid)
    assert not tmpfs_contract_ok({**good, "gid": "10002"}, uid=uid)


def test_discriminator_stage_derived_variant_labels() -> None:
    assert expected_image_variant_for_stage("runtime") == "recognition"
    assert expected_image_variant_for_stage(DEFAULT_RUNTIME_STAGE) == "recognition"
    assert expected_image_variant_for_stage("runtime-vlm") == "vlm"
    assert expected_image_variant_for_stage(RUNTIME_VLM_STAGE) == "vlm"
    with pytest.raises(ValueError):
        expected_image_variant_for_stage("builder")


def test_discriminator_image_variant_bake_mutations() -> None:
    """Deleting bake, cross-wiring label, or dropping chmod must go red."""
    good = "RUN printf 'recognition\\n' > /app/.image-variant && chmod 0444 /app/.image-variant\n"
    assert stage_bakes_image_variant(good, "recognition")
    assert not stage_bakes_image_variant("ENV ACX_IMAGE_VARIANT=recognition\n", "recognition")
    cross = "RUN printf 'vlm\\n' > /app/.image-variant && chmod 0444 /app/.image-variant\n"
    assert not stage_bakes_image_variant(cross, "recognition")
    no_chmod = "RUN printf 'recognition\\n' > /app/.image-variant\n"
    assert not stage_bakes_image_variant(no_chmod, "recognition")


def test_discriminator_compose_tmpfs_path_and_service_scope(tmp_path: Path) -> None:
    """Missing service tmpfs or wrong path fails modules_tmpfs_for_service."""
    good = {
        "services": {
            "api": {
                "tmpfs": [
                    "/var/cache/acx/hf_modules:mode=0700,uid=10001,gid=10001,size=32m,noexec"
                ]
            },
            "worker": {
                "tmpfs": [
                    "/var/cache/acx/hf_modules:mode=0700,uid=10001,gid=10001,size=32m,noexec"
                ]
            },
        }
    }
    path = "/var/cache/acx/hf_modules"
    assert modules_tmpfs_for_service(good, "api", path) is not None
    assert modules_tmpfs_for_service(good, "worker", path) is not None
    # Wrong path
    assert modules_tmpfs_for_service(good, "api", "/tmp/other") is None
    # Missing service
    no_worker = {"services": {"api": good["services"]["api"]}}
    assert modules_tmpfs_for_service(no_worker, "worker", path) is None
    # Deleted tmpfs block
    bare = {"services": {"api": {"image": "x"}, "worker": {"image": "x"}}}
    assert modules_tmpfs_for_service(bare, "api", path) is None

    # Write/read path used by live compose loader (sanity for yaml shape).
    yml = tmp_path / "docker-compose.env.yml"
    yml.write_text(yaml.safe_dump(good), encoding="utf-8")
    loaded = _load_compose(yml)
    assert modules_tmpfs_for_service(loaded, "api", path) is not None


def test_discriminator_blob_repair_profile_mutations() -> None:
    """Deleting fix-blob service / profile / root user must fail the guard."""
    good = """
services:
  fix-blob-ownership:
    image: example
    user: "0:0"
    volumes:
      - acx_blobs:/var/lib/acx-blobs
    entrypoint: ["chown", "-R", "acx:acx", "/var/lib/acx-blobs"]
    profiles: ["repair"]
volumes:
  acx_blobs:
"""
    assert _compose_has_blob_ownership_repair(good)
    assert not _compose_has_blob_ownership_repair(good.replace("fix-blob-ownership", "other"))
    assert not _compose_has_blob_ownership_repair(good.replace('user: "0:0"', 'user: "10001:10001"'))
    assert not _compose_has_blob_ownership_repair(good.replace('profiles: ["repair"]', "profiles: []"))
    assert not _compose_has_blob_ownership_repair(good.replace("chown", "true"))
