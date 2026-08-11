"""FIR3-BR-01 / FIR4-BR-01 + FINALB release-gate contracts (RED-first).

Static/behavior guards for:
1. Docker image deps resolve from ``uv.lock`` via frozen lock consumption
   (not unlocked ``pip install .[bench]``).
2. A dedicated CI workflow runs real YuNet/SFace ORT-vs-OpenCV parity with
   fail-closed missing-model semantics.
3. Test infrastructure distinguishes ordinary modelless skips from the
   required parity gate (covered here + face_pipeline_support helpers).
4. FINALB-03 — parity workflow machine-enforces zero skips (JUnit + gate).
5. FINALB-05 — Docker project install must not resolve build reqs outside lock.
6. FINALB-07 — accepted FIR-4 plan must not retain stale claims vs HEAD.

No Dockerfile/workflow/plan edits in the RED pass — new FINALB tests fail until
GREEN production surfaces land.

Heuristics: RLSE-01/02/05/07, SERVE-07, EVAL-01/04, PROV-01/08, TEST-06/08,
DEP-01/02, CFG-02, rg-006.
"""

from __future__ import annotations

import importlib.util
import re
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from recognition.tests.dockerfile_stages import (
    DEFAULT_BUILDER_STAGE,
    DEFAULT_RUNTIME_STAGE,
    RUNTIME_VLM_STAGE,
    _PROJECT_EXTRAS_RE,
    default_build_target,
    dockerfile_stages,
    effective_stage_body,
    has_vlm_extra,
    join_continued_lines,
    unlocked_project_extra_installs,
)
from recognition.tests.unit import face_pipeline_support as fps
from recognition.tests.unit.face_pipeline_support import (
    FACE_PIPELINE_PARITY_REQUIRED_ENV,
    parity_required,
)

# recognition/tests/unit/this_file.py → parents[3] = service root, [5] = monorepo
_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DOCKERFILE = _SERVICE_ROOT / "Dockerfile"
_UV_LOCK = _SERVICE_ROOT / "uv.lock"
_FIR4_PLAN = _REPO_ROOT / "docs" / "tasks" / "fir" / "FIR-4-runtime-integration-task-plan.md"
# FINALB-03: checked-in JUnit zero-skip gate (GREEN implements; RED asserts).
_JUNIT_SKIP_GATE = _SERVICE_ROOT / "scripts" / "check_junit_no_skips.py"
_JUNIT_SKIP_GATE_MODULE = "check_junit_no_skips"
_PARITY_WORKFLOW_CANDIDATES = (
    _REPO_ROOT / ".github" / "workflows" / "face-pipeline-ort-parity.yml",
    _REPO_ROOT / ".github" / "workflows" / "face-pipeline-parity.yml",
    _REPO_ROOT / ".github" / "workflows" / "face_pipeline_ort_parity.yml",
)

# Every stage that contributes to a shippable image (recognition + VLM).
# ACX_BUILD_TARGET=runtime-vlm publishes acx-backend-vlm; lock-integrity and
# unlocked-install gates must cover both image paths (REV-r08112960-B-10).
_BUILDER_VLM_STAGE = "builder-vlm"
_SHIPPABLE_IMAGE_STAGES = (
    DEFAULT_BUILDER_STAGE,
    _BUILDER_VLM_STAGE,
    DEFAULT_RUNTIME_STAGE,
    RUNTIME_VLM_STAGE,
)
# Back-compat alias used by tests that mean "all publishable stage bodies".
_DEFAULT_IMAGE_STAGES = _SHIPPABLE_IMAGE_STAGES


def _dockerfile_stages() -> dict[str, str]:
    assert _DOCKERFILE.is_file(), f"missing Dockerfile at {_DOCKERFILE}"
    return dockerfile_stages(_DOCKERFILE)


def _builder_body() -> str:
    stages = _dockerfile_stages()
    assert DEFAULT_BUILDER_STAGE in stages, (
        f"Dockerfile missing {DEFAULT_BUILDER_STAGE!r} stage; have {list(stages)}"
    )
    return stages[DEFAULT_BUILDER_STAGE]


def _runtime_body() -> str:
    """Effective runtime body (built-image claims; follows FROM inheritance)."""
    stages = _dockerfile_stages()
    assert DEFAULT_RUNTIME_STAGE in stages, (
        f"Dockerfile missing {DEFAULT_RUNTIME_STAGE!r} stage; have {list(stages)}"
    )
    return effective_stage_body(_DOCKERFILE, DEFAULT_RUNTIME_STAGE)


def _default_image_stage_text() -> str:
    """Effective bodies for every shippable image stage (recognition + VLM)."""
    stages = _dockerfile_stages()
    parts: list[str] = []
    for name in _SHIPPABLE_IMAGE_STAGES:
        if name not in stages:
            continue
        parts.append(effective_stage_body(_DOCKERFILE, name))
    return "\n".join(parts)


def _parity_workflow_path() -> Path:
    for path in _PARITY_WORKFLOW_CANDIDATES:
        if path.is_file():
            return path
    # Prefer the canonical name in the failure message.
    return _PARITY_WORKFLOW_CANDIDATES[0]


def _write_dockerfile(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "Dockerfile"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. Docker frozen-lock install (FIR4-BR-01) — stage-scoped (RC-02/RC-03)
# ---------------------------------------------------------------------------


_ENTRYPOINT = _SERVICE_ROOT / "scripts" / "docker-entrypoint.sh"


def test_entrypoint_exports_baked_image_variant() -> None:
    """S1-A-08: bake must be exported so children see ACX_IMAGE_VARIANT without image ENV."""
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(r"(?m)^export\s+ACX_IMAGE_VARIANT=", text), (
        "docker-entrypoint.sh must `export ACX_IMAGE_VARIANT=...` from the bake "
        "(plain assignment is not visible to children if image ENV is stripped)"
    )


def test_entrypoint_traps_term_during_pre_uvicorn() -> None:
    """A-13: PID 1 must handle SIGTERM during migrate/schema/verify window."""
    text = _ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(r"""trap\s+['"]_on_term['"]\s+TERM\b""", text), (
        "entrypoint must install trap _on_term TERM before long boot steps"
    )
    # alembic backgrounded so the trap can kill it (not a forever-foreground child).
    assert re.search(r"(?m)^alembic\b.+\s&\s*$", text), (
        "alembic must run under &+wait so SIGTERM can interrupt the migrate step"
    )


def test_entrypoint_export_reaches_child_process() -> None:
    """Behavioural: export (not bare assign) propagates bake into a child shell."""
    # Mirrors the entrypoint's prefer-bake export without running the full boot chain.
    probe = (
        "#!/bin/sh\n"
        "set -eu\n"
        "BAKED_IMAGE_VARIANT=vlm\n"
        "export ACX_IMAGE_VARIANT=\"${BAKED_IMAGE_VARIANT}\"\n"
        # Child without inherited env would still see exported names from parent.
        "sh -c 'printf %s \"$ACX_IMAGE_VARIANT\"'\n"
    )
    proc = subprocess.run(
        ["sh", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "vlm"
    # Control: bare assign without export does not reach an env-cleared child.
    bare = (
        "#!/bin/sh\n"
        "set -eu\n"
        "ACX_IMAGE_VARIANT=vlm\n"
        "env -i PATH=\"$PATH\" sh -c 'printf %s \"${ACX_IMAGE_VARIANT:-missing}\"'\n"
    )
    bare_proc = subprocess.run(
        ["sh", "-c", bare],
        check=False,
        capture_output=True,
        text=True,
    )
    assert bare_proc.returncode == 0
    assert bare_proc.stdout == "missing"


def _stub_bin(dir_path: Path, name: str, body: str = "#!/bin/sh\nexit 0\n") -> None:
    path = dir_path / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_entrypoint_unreadable_data_cache_fails_closed(tmp_path: Path) -> None:
    """A-08: VLM boot must refuse an unreadable /data/cache host bind with ownership hint.

    Image-layer chown is masked by the host bind; without this gate, uid 10001
    hits a bare library PermissionError. Behavioural: run the real entrypoint
    under path rewrites (do not only grep source for the FATAL string).
    """
    root = tmp_path / "root"
    app = root / "app"
    blobs = root / "var" / "lib" / "acx-blobs"
    cache = root / "data" / "cache"
    bin_dir = root / "bin"
    app.mkdir(parents=True)
    blobs.mkdir(parents=True)
    cache.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    (app / ".image-variant").write_text("vlm\n", encoding="utf-8")
    # Mode 000: exists but not readable by the executing uid (non-root).
    cache.chmod(0o000)

    for name in ("alembic", "python", "uvicorn"):
        _stub_bin(bin_dir, name)
    _stub_bin(
        bin_dir,
        "id",
        textwrap.dedent(
            """\
            #!/bin/sh
            if [ "$1" = "-u" ]; then echo 10001; else echo acx; fi
            """
        ),
    )

    src = _ENTRYPOINT.read_text(encoding="utf-8")
    rewritten = (
        src.replace("/app", str(app))
        .replace("/var/lib/acx-blobs", str(blobs))
        .replace("/data/cache", str(cache))
    )
    script = root / "docker-entrypoint.sh"
    script.write_text(rewritten, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(root),
        "RECOGNITION_BLOB_ROOT": str(blobs),
        "ACX_IMAGE_VARIANT": "vlm",
    }
    result = subprocess.run(
        ["/bin/sh", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(root),
    )
    # Restore cache perms so tmp cleanup cannot fail on some hosts.
    cache.chmod(0o755)

    assert result.returncode == 1, result.stdout + result.stderr
    err = result.stderr
    assert "not readable" in err, err
    assert "10001" in err or "ACX_MODELS_PATH" in err, err

    # Control: readable cache proceeds past the ownership gate (stubs exit 0).
    cache.chmod(0o755)
    result_ok = subprocess.run(
        ["/bin/sh", str(script)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(root),
    )
    assert result_ok.returncode == 0, result_ok.stdout + result_ok.stderr
    assert "not readable" not in result_ok.stderr


def test_service_uv_lock_exists() -> None:
    assert _UV_LOCK.is_file(), (
        f"expected checked-in lock at {_UV_LOCK.relative_to(_REPO_ROOT)} "
        "(Docker must consume this file, not resolve unlocked)"
    )


def test_dockerfile_copies_uv_lock() -> None:
    """Builder must COPY uv.lock so frozen sync can consume exact pins."""
    text = _builder_body()
    # Accept COPY of lock alone or alongside pyproject on one line.
    assert re.search(r"^COPY\s+[^\n]*\buv\.lock\b", text, re.MULTILINE), (
        "builder stage must COPY uv.lock into the build context "
        "(FIR4-BR-01: lock is system of record for image deps)"
    )


def test_dockerfile_installs_deps_via_uv_sync_frozen() -> None:
    """Dependency install must use uv sync with a frozen/locked resolution."""
    text = _builder_body()
    assert "uv sync" in text, (
        "builder stage must install runtime deps with `uv sync` "
        "(not unlocked pip resolve)"
    )
    assert "--frozen" in text or "--locked" in text, (
        "builder stage `uv sync` must pass --frozen (or --locked) for exact lock consumption"
    )


def test_dockerfile_frozen_sync_enables_bench_extra() -> None:
    """runtime+[bench]: insightface stays available for the dark default until FIR-6."""
    text = _builder_body()
    # Prefer explicit --extra bench on a uv sync line; allow multi-line RUN.
    sync_blocks = re.findall(r"uv sync[^\n]*(?:\\\n[^\n]*)*", text)
    joined = "\n".join(sync_blocks) if sync_blocks else text
    assert re.search(r"--extra\s+bench\b", joined) or "extras=bench" in joined, (
        "builder frozen install must enable the bench extra "
        "(`uv sync --frozen --extra bench` or equivalent)"
    )


def test_dockerfile_rejects_unlocked_pip_bench_dependency_install() -> None:
    """Unlocked project-with-extras install must not resolve deps outside the lock.

    Structural (RC-03): catch ``.[bench]``, ``".[bench,vlm]"``, any extra name,
    quoting, spacing, and line continuations — not just the literal ``.[bench]``
    token the old gate matched.
    """
    offenders: list[str] = []
    stages = _dockerfile_stages()
    for stage in _DEFAULT_IMAGE_STAGES:
        if stage not in stages:
            continue
        # Effective body: an unlocked install inherited from a parent stage is
        # indistinguishable in the built image from one declared directly.
        body = effective_stage_body(_DOCKERFILE, stage)
        for hit in unlocked_project_extra_installs(body):
            offenders.append(f"{stage}: {hit}")
    assert not offenders, (
        "shippable image stages (builder, builder-vlm, runtime, runtime-vlm) must "
        "not use unlocked project+extras pip/uv install for dependency resolution; "
        "switch to COPY uv.lock + `uv sync --frozen --extra bench`. Found:\n  - "
        + "\n  - ".join(offenders)
    )


def test_default_builder_stage_has_no_vlm_extra() -> None:
    """RC-02: default builder dependency set must not pull the vlm extra.

    Whole-file greps stay green when ``--extra vlm`` lives only on builder-vlm
    *or* when it is smuggled into the default builder — stage scope is the only
    way to enforce the comment that the default builder/runtime set is unchanged.
    """
    stages = _dockerfile_stages()
    builder = stages[DEFAULT_BUILDER_STAGE]
    assert not has_vlm_extra(builder), (
        "default builder stage must not resolve --extra vlm / .[vlm] / --all-extras "
        "(torch belongs to builder-vlm only; RC-02 stage scope)"
    )
    # Active (non-comment) lines must not mention torch in the default builder.
    active = "\n".join(
        ln
        for ln in join_continued_lines(builder)
        if ln.strip() and not ln.strip().startswith("#")
    )
    assert "torch" not in active.lower(), (
        "default builder active body must not mention torch (VLM path only)"
    )


def test_dockerfile_stage_topology_keeps_default_torch_free() -> None:
    """S1-RC-06: default target stays torch-free; VLM path is explicit + offline.

    Stage-aware: last stage must be runtime; builder has no --extra vlm; VLM
    builder/stage exist with offline fail-closed env on runtime-vlm.
    """
    stages = _dockerfile_stages()
    assert stages, "expected named Dockerfile stages"
    last = default_build_target(_DOCKERFILE)
    assert last == DEFAULT_RUNTIME_STAGE, (
        f"last Dockerfile stage is {last!r}; bare docker build would ship it. "
        f"{DEFAULT_RUNTIME_STAGE!r} must stay last (S1-RC-06 / RA-05)."
    )
    assert not has_vlm_extra(stages[DEFAULT_BUILDER_STAGE]), (
        "default builder must not pull --extra vlm"
    )
    assert _BUILDER_VLM_STAGE in stages and RUNTIME_VLM_STAGE in stages, (
        "builder-vlm and runtime-vlm must remain reachable via --target"
    )
    assert has_vlm_extra(stages[_BUILDER_VLM_STAGE]), (
        "builder-vlm must resolve --extra vlm"
    )
    vlm_eff = effective_stage_body(_DOCKERFILE, RUNTIME_VLM_STAGE)
    # Offline second line of defense (HF hub / transformers only — not insightface).
    active_vlm = "\n".join(
        ln
        for ln in join_continued_lines(vlm_eff)
        if ln.strip() and not ln.strip().startswith("#")
    )
    assert re.search(r"(?m)^ENV\s+HF_HUB_OFFLINE=1\s*$", active_vlm), (
        "runtime-vlm must set ENV HF_HUB_OFFLINE=1 (fail closed if weights missing)"
    )
    assert re.search(r"(?m)^ENV\s+TRANSFORMERS_OFFLINE=1\s*$", active_vlm), (
        "runtime-vlm must set ENV TRANSFORMERS_OFFLINE=1"
    )


def test_guard_bites_when_runtime_vlm_drops_offline_env(tmp_path: Path) -> None:
    """TEST-15: removing HF_HUB_OFFLINE from a synthetic runtime-vlm fails the gate."""
    text = (
        "FROM python:3.12-slim AS builder\n"
        "RUN uv sync --frozen --extra bench\n"
        "\n"
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --frozen --extra bench --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime-base\n"
        "RUN true\n"
        "\n"
        "FROM runtime-base AS runtime-vlm\n"
        "COPY --from=builder-vlm /opt/venv /opt/venv\n"
        "ENV TRANSFORMERS_OFFLINE=1\n"
        "\n"
        "FROM runtime-base AS runtime\n"
        "COPY --from=builder /opt/venv /opt/venv\n"
    )
    path = _write_dockerfile(tmp_path, text)
    vlm_eff = effective_stage_body(path, RUNTIME_VLM_STAGE)
    active = "\n".join(
        ln
        for ln in join_continued_lines(vlm_eff)
        if ln.strip() and not ln.strip().startswith("#")
    )
    assert not re.search(r"(?m)^ENV\s+HF_HUB_OFFLINE=1\s*$", active)
    # Control: both offline ENVs present would pass the same predicate.
    with_both = active + "\nENV HF_HUB_OFFLINE=1\n"
    assert re.search(r"(?m)^ENV\s+HF_HUB_OFFLINE=1\s*$", with_both)
    assert re.search(r"(?m)^ENV\s+TRANSFORMERS_OFFLINE=1\s*$", with_both)


def test_no_stage_installs_deps_outside_uv_lock() -> None:
    """RC-03: every stage that creates ``/opt/venv`` must use locked ``uv sync``.

    Creating a venv then ``pip install ".[bench,vlm]"`` abandons frozen-lock
    resolution while still producing ``/opt/venv`` — the headline supply-chain
    invariant. Detect create-site stages and require ``uv sync --frozen|--locked``.
    """
    stages = _dockerfile_stages()
    create_markers = (
        re.compile(r"\buv\s+venv\b.*/opt/venv"),
        re.compile(r"\bpython(?:3)?\s+-m\s+venv\s+/opt/venv"),
        re.compile(r"\bvirtualenv\s+/opt/venv"),
    )
    offenders: list[str] = []
    for name, body in stages.items():
        joined = "\n".join(join_continued_lines(body))
        creates = any(
            m.search(ln)
            for ln in join_continued_lines(body)
            if not ln.strip().startswith("#")
            for m in create_markers
        ) or bool(re.search(r"UV_PROJECT_ENVIRONMENT=/opt/venv", joined))
        if not creates:
            # Also treat an own-body ``uv sync`` that writes /opt/venv as a create site.
            has_sync = any(
                re.search(r"\buv\s+sync\b", ln)
                for ln in join_continued_lines(body)
                if not ln.strip().startswith("#")
            )
            if not has_sync:
                continue
            # Sync without create in this stage is fine only if it is a re-sync
            # of an inherited venv (builder-vlm FROM builder). Still require lock flags.
            creates = True
        sync_cmds = [
            ln.strip()
            for ln in join_continued_lines(body)
            if re.search(r"\buv\s+sync\b", ln) and not ln.strip().startswith("#")
        ]
        if not sync_cmds:
            offenders.append(f"{name}: creates/uses /opt/venv but has no `uv sync`")
            continue
        for cmd in sync_cmds:
            if "--frozen" not in cmd and "--locked" not in cmd:
                offenders.append(f"{name}: uv sync without --frozen/--locked: {cmd}")
    assert not offenders, (
        "stages that materialise /opt/venv must install via `uv sync --frozen` "
        "(or --locked). Found:\n  - " + "\n  - ".join(offenders)
    )


def test_dockerfile_runtime_editable_install_may_remain_no_deps() -> None:
    """App package install may stay `pip install -e . --no-deps` after lock-based deps."""
    text = _runtime_body()
    # Not a hard requirement that editable install exists — only that if pip
    # installs the app package without extras, --no-deps is used.
    app_pip = [
        ln
        for ln in text.splitlines()
        if "pip install" in ln and re.search(r"\s-e\s+\.|\spip install[^\n]*\s\.\s", ln)
    ]
    for ln in app_pip:
        if _PROJECT_EXTRAS_RE.search(ln):
            continue
        if re.search(r"pip install[^\n]*\s\.(?:\s|$)", ln) or " -e ." in ln or " -e ." in ln.replace(
            "  ", " "
        ):
            assert "--no-deps" in ln, (
                "runtime stage app `pip install` of `.` must use --no-deps when deps "
                f"come from the lock. Offending line: {ln.strip()}"
            )


def _project_install_lines(text: str) -> list[str]:
    """Lines that install the local project package into the image venv."""
    lines: list[str] = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "pip install" not in stripped and "uv pip install" not in stripped:
            continue
        # Project package: `-e .` or bare `.` without extras; skip deps-only paths.
        if _PROJECT_EXTRAS_RE.search(stripped):
            continue
        if re.search(r"(?:^|\s)-e\s+\.(?:\s|$)", stripped) or re.search(
            r"pip install[^\n]*\s\.(?:\s|$)", stripped
        ):
            lines.append(stripped)
    return lines


def test_dockerfile_project_install_disables_build_isolation() -> None:
    """FINALB-05 [DEP-01/02]: project install must not resolve build reqs outside lock.

    Frozen ``uv sync`` puts runtime deps in ``/opt/venv``, but a plain
    ``pip install -e . --no-deps`` still runs a PEP 517 isolated build that can
    pull ``setuptools>=68`` (etc.) from the network, unbound by ``uv.lock``.
    GREEN must disable build isolation (and keep install inside ``/opt/venv``).
    """
    builder = _builder_body()
    runtime = _runtime_body()
    # Preserve frozen lock consumption for deps (builder stage).
    assert "uv sync" in builder and ("--frozen" in builder or "--locked" in builder), (
        "FINALB-05: builder stage must keep frozen uv sync for dependency install"
    )
    assert re.search(r"--extra\s+bench\b", builder) or "extras=bench" in builder, (
        "FINALB-05: builder frozen sync must still enable the bench extra"
    )

    project_lines = _project_install_lines(runtime)
    assert project_lines, (
        "FINALB-05: expected a project install step in the runtime stage "
        "(`pip install -e .` / `uv pip install -e .`) after frozen dep sync"
    )
    for ln in project_lines:
        assert "--no-deps" in ln, (
            "FINALB-05: project install must keep --no-deps so runtime deps "
            f"come only from the lock. Offending: {ln}"
        )
        assert "--no-build-isolation" in ln, (
            "FINALB-05: project install must pass --no-build-isolation so PEP 517 "
            "cannot resolve setuptools/build-system deps outside uv.lock. "
            f"Offending: {ln}"
        )
        # Install executes with /opt/venv on PATH (builder/runtime copy pattern).
        assert "/opt/venv" in runtime or "/opt/venv" in builder, (
            "FINALB-05: image must install into /opt/venv (relocatable locked venv)"
        )

    # Structural unlocked-extras rejection on the default image path (RC-03).
    offenders: list[str] = []
    for stage_name, body in (
        (DEFAULT_BUILDER_STAGE, builder),
        (DEFAULT_RUNTIME_STAGE, runtime),
    ):
        for hit in unlocked_project_extra_installs(body):
            offenders.append(f"{stage_name}: {hit}")
    assert not offenders, (
        "FINALB-05: unlocked project+extras pip/uv install must not resolve deps. Found:\n  - "
        + "\n  - ".join(offenders)
    )


def test_dockerfile_no_hardcoded_ort_version_independent_of_lock() -> None:
    """Do not pin a second onnxruntime version window outside uv.lock.

    A post-install smoke may still import onnxruntime, but hard-coded version
    tuples (e.g. ``(1, 22) <= p < (2, 0)``) reintroduce dual writers vs the lock.
    Scoped to every shippable image stage (builder, builder-vlm, runtime,
    runtime-vlm) so the VLM publish path is not ungated (B-10).
    """
    text = _default_image_stage_text()
    # Only flag executable/version-check forms — not prose mentioning 1.22.
    patterns = (
        r"\(1\s*,\s*22\)\s*<=",  # tuple lower bound
        r"<=\s*p\s*<\s*\(2\s*,\s*0\)",  # tuple upper bound pair
        r"sys\.exit\(0 if \(1\s*,\s*22\)",
        r"__version__.*1\.22|1\.22.*__version__",
    )
    hits = [m.group(0) for pat in patterns if (m := re.search(pat, text))]
    assert not hits, (
        "Dockerfile shippable stages must not hard-code a second ORT version "
        "bound independent of uv.lock (remove the pip-resolved [1.22, 2.0) smoke; "
        f"lock pins ORT). Matched: {hits!r}"
    )


# ---------------------------------------------------------------------------
# 1b. Negative guards — prove stage scope + structural install bite (TEST-15)
# ---------------------------------------------------------------------------

def test_guard_bites_when_uv_lock_copy_only_in_non_builder_stage(tmp_path: Path) -> None:
    """RC-02: uv.lock present only outside builder must not satisfy the gate."""
    text = (
        "FROM python:3.12-slim AS builder\n"
        "RUN uv sync --frozen --extra bench\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "COPY pyproject.toml uv.lock ./\n"
    )
    path = _write_dockerfile(tmp_path, text)
    stages = dockerfile_stages(path)
    # Whole-file would still see the lock COPY.
    assert re.search(r"^COPY\s+[^\n]*\buv\.lock\b", path.read_text(), re.MULTILINE)
    assert not re.search(
        r"^COPY\s+[^\n]*\buv\.lock\b", stages[DEFAULT_BUILDER_STAGE], re.MULTILINE
    ), "stage-scoped builder body must not claim a lock COPY that lives in runtime"


def test_guard_bites_on_python_m_pip_unlocked_extra_install() -> None:
    """Wave-3 M3b/RC4: ``python -m pip install ".[bench]"`` must be caught."""
    for form in (
        'RUN python -m pip install ".[bench]"',
        'RUN python3 -m pip install ".[bench]"',
        'RUN /opt/venv/bin/python -m pip install ".[bench]"',
        'RUN /app/.venv/bin/python -m pip install ".[dev]"',
    ):
        offenders = unlocked_project_extra_installs(form)
        assert offenders, f"must catch interpreter form: {form}"


def test_guard_bites_on_semicolon_sibling_no_deps_whitelist() -> None:
    """Wave-3 M4/RC4: --no-deps on a sibling fragment must not whitelist extras install."""
    line = 'RUN pip install --no-deps wheel ; pip install ".[bench]"'
    offenders = unlocked_project_extra_installs(line)
    assert offenders, (
        "per-fragment --no-deps: harmless `pip install --no-deps wheel` must not "
        "whitelist sibling `pip install \".[bench]\"`"
    )
    assert all("--no-deps" not in o for o in offenders)


def test_guard_bites_on_quoted_multi_extra_unlocked_install(tmp_path: Path) -> None:
    """RC-03 mutation (c): ``pip install ".[bench,vlm]"`` must be rejected."""
    text = (
        "FROM python:3.12-slim AS builder\n"
        "COPY pyproject.toml uv.lock ./\n"
        "RUN uv sync --frozen --no-dev --extra bench --no-install-project\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        'RUN pip install ".[bench,vlm]"\n'
    )
    path = _write_dockerfile(tmp_path, text)
    offenders = unlocked_project_extra_installs(
        dockerfile_stages(path)[DEFAULT_RUNTIME_STAGE]
    )
    assert offenders, (
        "structural gate must reject quoted multi-extra unlocked project install"
    )
    assert any("bench" in o and "vlm" in o for o in offenders)


def test_guard_bites_on_continued_line_unlocked_extra_install(tmp_path: Path) -> None:
    """RC-03: line-continued pip install of project extras must still be caught."""
    text = (
        "FROM python:3.12-slim AS builder\n"
        "RUN true\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN pip install \\\n"
        "    --no-cache-dir \\\n"
        "    '.[dev]'\n"
    )
    path = _write_dockerfile(tmp_path, text)
    offenders = unlocked_project_extra_installs(
        dockerfile_stages(path)[DEFAULT_RUNTIME_STAGE]
    )
    assert offenders, "line-continued unlocked project+extras install must be caught"


def test_guard_bites_when_uv_sync_only_in_vlm_builder(tmp_path: Path) -> None:
    """RC-02: frozen uv sync only in builder-vlm must not satisfy the default builder."""
    text = (
        "FROM python:3.12-slim AS builder\n"
        "RUN echo no-sync-here\n"
        "\n"
        "FROM python:3.12-slim AS builder-vlm\n"
        "RUN uv sync --frozen --extra bench --extra vlm\n"
        "\n"
        "FROM python:3.12-slim AS runtime\n"
        "RUN true\n"
    )
    path = _write_dockerfile(tmp_path, text)
    stages = dockerfile_stages(path)
    whole = path.read_text()
    assert "uv sync" in whole and "--frozen" in whole  # whole-file would stay green
    assert "uv sync" not in stages[DEFAULT_BUILDER_STAGE]
    assert "--frozen" not in stages[DEFAULT_BUILDER_STAGE]


def test_literal_bench_token_gate_is_evadable_control(tmp_path: Path) -> None:
    """Control: the old literal ``.[bench]`` match misses quoted multi-extra forms.

    Documents why RC-03 replaced the token check with a structural parser.
    """
    line = 'RUN pip install ".[bench,vlm]"'
    # Old gate (simplified): look for the exact ``.[bench]`` token.
    old_hit = ".[bench]" in line.replace(" ", "") and "--no-deps" not in line
    # ``.[bench,vlm]`` does not contain the exact ``.[bench]`` token after
    # space-stripping either — the comma breaks the literal.
    assert ".[bench]" not in line.replace(" ", "")
    assert old_hit is False
    assert unlocked_project_extra_installs(line), "structural parser must still catch it"


# ---------------------------------------------------------------------------
# 2. Dedicated parity CI workflow (FIR3-BR-01)
# ---------------------------------------------------------------------------


def test_face_pipeline_parity_workflow_exists() -> None:
    path = _parity_workflow_path()
    assert path.is_file(), (
        "Missing dedicated face-pipeline ORT parity CI workflow. "
        f"Expected one of: {[p.relative_to(_REPO_ROOT).as_posix() for p in _PARITY_WORKFLOW_CANDIDATES]}. "
        "Gate must run real YuNet/SFace ORT-vs-OpenCV parity (not modelless skips)."
    )


def _workflow_text() -> str:
    path = _parity_workflow_path()
    assert path.is_file(), f"parity workflow missing: {path}"
    return path.read_text(encoding="utf-8")


def test_parity_workflow_installs_frozen_dev_and_bench() -> None:
    text = _workflow_text()
    assert "uv sync" in text, "parity workflow must install with uv sync"
    assert "--frozen" in text or "--locked" in text, (
        "parity workflow uv sync must be frozen/locked"
    )
    assert re.search(r"--extra\s+dev\b", text) or "extra dev" in text, (
        "parity workflow must install the dev extra"
    )
    assert re.search(r"--extra\s+bench\b", text) or "extra bench" in text, (
        "parity workflow must install the bench extra"
    )


def test_parity_workflow_fetches_and_verifies_pinned_models() -> None:
    text = _workflow_text()
    assert "fetch_face_pipeline_models.py" in text, (
        "parity workflow must use scripts/fetch_face_pipeline_models.py "
        "(hash-verified pinned fetch)"
    )
    assert "--verify-only" in text, (
        "parity workflow must run fetch_face_pipeline_models.py --verify-only "
        "after cache/download"
    )


def test_parity_workflow_sets_fail_closed_parity_env() -> None:
    text = _workflow_text()
    assert FACE_PIPELINE_PARITY_REQUIRED_ENV in text, (
        f"parity workflow must set {FACE_PIPELINE_PARITY_REQUIRED_ENV} "
        "so missing models fail instead of skipping"
    )
    assert re.search(
        rf"{re.escape(FACE_PIPELINE_PARITY_REQUIRED_ENV)}\s*[:=]\s*['\"]?1",
        text,
    ), (
        f"parity workflow must set {FACE_PIPELINE_PARITY_REQUIRED_ENV}=1 "
        "(fail-closed)"
    )


def test_parity_workflow_runs_ort_parity_module() -> None:
    text = _workflow_text()
    assert "test_face_pipeline_ort_parity.py" in text, (
        "parity workflow must execute recognition/tests/unit/test_face_pipeline_ort_parity.py"
    )


def test_parity_workflow_uses_service_cwd_and_npm_free_python() -> None:
    text = _workflow_text()
    assert "apps/prototype-description-service" in text, (
        "parity workflow commands must run from apps/prototype-description-service "
        "(working-directory or explicit cd)"
    )
    # npm-free: no Node package manager steps for this Python gate.
    assert not re.search(r"\bnpm\s+(ci|install|run)\b", text), (
        "parity workflow must use npm-free Python/uv conventions (no npm ci/install/run)"
    )
    assert "package-lock.json" not in text, (
        "parity workflow must not depend on Node package-lock.json"
    )


def test_parity_workflow_triggers_on_relevant_paths() -> None:
    text = _workflow_text()
    # Path filters should cover source, lock, and the workflow itself.
    required_fragments = (
        "prototype-description-service",
        "uv.lock",
    )
    for frag in required_fragments:
        assert frag in text, (
            f"parity workflow path triggers should include {frag!r} "
            "(source/lock/workflow relevance)"
        )


# ---------------------------------------------------------------------------
# 3. Fail-closed switch behavior (no network)
# ---------------------------------------------------------------------------


def test_parity_required_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, raising=False)
    assert parity_required() is False
    monkeypatch.setenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, "1")
    assert parity_required() is True
    monkeypatch.setenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, "true")
    assert parity_required() is True
    monkeypatch.setenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, "0")
    assert parity_required() is False


def test_ensure_models_skips_when_optional_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, raising=False)
    monkeypatch.setattr(fps, "MODELS_PRESENT", False)
    with pytest.raises(pytest.skip.Exception) as excinfo:
        fps.ensure_face_pipeline_models()
    assert "fetch_face_pipeline_models.py" in str(excinfo.value)


def test_ensure_models_fails_when_required_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, "1")
    monkeypatch.setattr(fps, "MODELS_PRESENT", False)
    with pytest.raises(pytest.fail.Exception) as excinfo:
        fps.ensure_face_pipeline_models()
    msg = str(excinfo.value)
    assert FACE_PIPELINE_PARITY_REQUIRED_ENV in msg
    assert "missing" in msg.lower()
    assert "fetch_face_pipeline_models.py" in msg


def test_ensure_models_noop_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, "1")
    monkeypatch.setattr(fps, "MODELS_PRESENT", True)
    fps.ensure_face_pipeline_models()  # must not raise


def test_models_absent_allows_skip_false_when_parity_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the gate is required, skipif must not suppress model-gated tests."""
    monkeypatch.setenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, "1")
    monkeypatch.setattr(fps, "MODELS_PRESENT", False)
    assert fps.models_absent_allows_skip() is False


def test_models_absent_allows_skip_true_for_ordinary_modelless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FACE_PIPELINE_PARITY_REQUIRED_ENV, raising=False)
    monkeypatch.setattr(fps, "MODELS_PRESENT", False)
    assert fps.models_absent_allows_skip() is True


def test_parity_required_env_name_is_stable() -> None:
    """Workflow contracts and helpers share one env name (CFG-02)."""
    assert FACE_PIPELINE_PARITY_REQUIRED_ENV == "FACE_PIPELINE_PARITY_REQUIRED"
    assert hasattr(fps, "FACE_PIPELINE_PARITY_REQUIRED_ENV")


# ---------------------------------------------------------------------------
# 4. FINALB-03 — machine-enforced zero skips (JUnit + checked-in gate)
# ---------------------------------------------------------------------------
#
# Comments + FACE_PIPELINE_PARITY_REQUIRED alone are not enough: ordinary
# pytest still exits 0 when tests are skipped. GREEN must emit JUnit XML and
# run scripts/check_junit_no_skips.py (or equivalent) so any <skipped> fails CI.
#
# Gate contract (GREEN implements at scripts/check_junit_no_skips.py):
#   count_skipped(path: Path | str) -> int
#   main(argv: list[str] | None = None) -> int  # 0 iff total skipped == 0
# CLI: python scripts/check_junit_no_skips.py <junit.xml>


_ZERO_SKIP_JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites tests="2" failures="0" errors="0" skipped="0">
  <testsuite name="parity" tests="2" failures="0" errors="0" skipped="0">
    <testcase classname="t" name="a" time="0.01"/>
    <testcase classname="t" name="b" time="0.01"/>
  </testsuite>
</testsuites>
"""

_NONZERO_SKIP_JUNIT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites tests="2" failures="0" errors="0" skipped="1">
  <testsuite name="parity" tests="2" failures="0" errors="0" skipped="1">
    <testcase classname="t" name="a" time="0.01"/>
    <testcase classname="t" name="b" time="0.01">
      <skipped message="models missing"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def _load_junit_skip_gate() -> ModuleType:
    """Import the checked-in zero-skip gate (FINALB-03)."""
    path = _JUNIT_SKIP_GATE
    assert path.is_file(), (
        "FINALB-03 [RLSE-05][TEST-08]: missing "
        f"{path.relative_to(_REPO_ROOT).as_posix()}. "
        "Parity CI must machine-check zero skips via a checked-in JUnit parser "
        "that exits nonzero when <skipped> > 0 (comments are not a gate)."
    )
    # Unique module name avoids stale sys.modules across pytest rewrites.
    mod_name = f"{_JUNIT_SKIP_GATE_MODULE}_{path.stat().st_mtime_ns}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None, f"cannot load gate from {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _gate_count_skipped(module: ModuleType, report: Path) -> int:
    for name in ("count_skipped", "count_junit_skipped", "skipped_count"):
        fn = getattr(module, name, None)
        if callable(fn):
            return int(fn(report))
    pytest.fail(
        "FINALB-03: check_junit_no_skips.py must expose count_skipped(path) -> int "
        "(or count_junit_skipped / skipped_count)"
    )


def _gate_main(module: ModuleType, report: Path) -> int:
    main = getattr(module, "main", None)
    assert callable(main), (
        "FINALB-03: check_junit_no_skips.py must expose main(argv=None) -> int "
        "for CLI use from the parity workflow"
    )
    return int(main([str(report)]))


def test_junit_zero_skip_gate_module_exists() -> None:
    """FINALB-03: checked-in gate script is part of the release surface."""
    assert _JUNIT_SKIP_GATE.is_file(), (
        "FINALB-03: expected "
        f"{_JUNIT_SKIP_GATE.relative_to(_REPO_ROOT).as_posix()} "
        "(JUnit XML zero-skip gate; RLSE-05 silent-green is failure)"
    )


def test_junit_gate_passes_synthetic_zero_skip_report(tmp_path: Path) -> None:
    """FINALB-03: zero <skipped> → count 0 and main exits 0."""
    gate = _load_junit_skip_gate()
    report = tmp_path / "zero-skip.xml"
    report.write_text(_ZERO_SKIP_JUNIT, encoding="utf-8")
    assert _gate_count_skipped(gate, report) == 0
    assert _gate_main(gate, report) == 0


def test_junit_gate_fails_synthetic_nonzero_skip_report(tmp_path: Path) -> None:
    """FINALB-03: any <skipped> → count > 0 and main exits nonzero."""
    gate = _load_junit_skip_gate()
    report = tmp_path / "with-skip.xml"
    report.write_text(_NONZERO_SKIP_JUNIT, encoding="utf-8")
    skipped = _gate_count_skipped(gate, report)
    assert skipped > 0, f"expected skipped > 0 from synthetic report, got {skipped}"
    rc = _gate_main(gate, report)
    assert rc != 0, (
        f"FINALB-03: main must exit nonzero when skipped={skipped} (got rc={rc})"
    )


def test_parity_workflow_wires_junit_and_zero_skip_gate() -> None:
    """FINALB-03: workflow must emit JUnit and invoke the zero-skip gate.

    FACE_PIPELINE_PARITY_REQUIRED comments alone leave silent greens when
    pytest reports skips with exit code 0. Wire a deterministic mechanism.
    """
    text = _workflow_text()
    emits_junit = bool(
        re.search(r"--junitxml\b|=junitxml\b|junit-xml|JUnitXML", text, re.IGNORECASE)
    )
    assert emits_junit, (
        "FINALB-03: parity workflow must emit JUnit XML "
        "(e.g. pytest --junitxml=parity-junit.xml) so skips are machine-readable"
    )
    gate_name = _JUNIT_SKIP_GATE.name
    assert gate_name in text or "check_junit_no_skips" in text, (
        "FINALB-03: parity workflow must invoke "
        f"{_JUNIT_SKIP_GATE.relative_to(_REPO_ROOT).as_posix()} "
        "(or check_junit_no_skips) after pytest; exit nonzero on any skip. "
        "Comments claiming 'skips are failures' are not enforcement."
    )


# ---------------------------------------------------------------------------
# 5. FINALB-07 — accepted FIR-4 plan must match HEAD (stale claim sweep)
# ---------------------------------------------------------------------------


def _fir4_plan_text() -> str:
    assert _FIR4_PLAN.is_file(), f"missing FIR-4 plan at {_FIR4_PLAN}"
    return _FIR4_PLAN.read_text(encoding="utf-8")


def test_fir4_plan_exists_for_contract_sweep() -> None:
    assert _FIR4_PLAN.is_file(), (
        "FINALB-07: expected accepted plan at "
        f"{_FIR4_PLAN.relative_to(_REPO_ROOT).as_posix()}"
    )


def test_fir4_plan_no_two_active_dimension_knobs_claim() -> None:
    """FINALB-07: plan must not require two active dimension knobs.

    HEAD uses PGVECTOR_DIM as the single width root; dual-knob prose is stale.
    """
    text = _fir4_plan_text()
    offenders: list[str] = []
    patterns = (
        r"two\s+active\s+dimension\s+knobs",
        r"\*\*two\*\*\s+dimension\s+knobs",
        r"two\s+dimension\s+knobs",
        r"both\s+knobs\s+to\s+128",
        r"set\s+both\s+knobs",
    )
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            # Context line for operators sweeping the plan.
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"L{line_no}: ...{m.group(0)}...")
    assert not offenders, (
        "FINALB-07: FIR-4 plan still claims two (active) dimension knobs. "
        "Rephrase for single-root PGVECTOR_DIM / remove dual-knob requirements. "
        "Hits:\n  - " + "\n  - ".join(offenders)
    )


def test_fir4_plan_no_instruction_to_set_recognition_embedding_dimension() -> None:
    """FINALB-07: do not instruct operators to set RECOGNITION_EMBEDDING_DIMENSION.

    Mentions are allowed only to state the env is ignored/removed/no-op.
    """
    text = _fir4_plan_text()
    env_name = "RECOGNITION_EMBEDDING_DIMENSION"
    allowed_markers = (
        "ignored",
        "ignore",
        "removed",
        "no-op",
        "noop",
        "deprecated",
        "not used",
        "unused",
        "do not set",
        "must not set",
        "no longer",
    )
    offenders: list[str] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if env_name not in line:
            continue
        lower = line.lower()
        if any(marker in lower for marker in allowed_markers):
            continue
        offenders.append(f"L{i}: {line.strip()[:160]}")
    assert not offenders, (
        "FINALB-07: plan still instructs or documents "
        f"{env_name} as an active knob. Rephrase as ignored/removed, or delete. "
        "Hits:\n  - " + "\n  - ".join(offenders)
    )


def test_fir4_plan_no_migration_001_hardcodes_512_claim() -> None:
    """FINALB-07: plan must not claim migration 001 hardcodes 512."""
    text = _fir4_plan_text()
    patterns = (
        r"001_identity_schema\.py\s+hardcodes\s+512",
        r"greenfield\s+`?001_identity_schema\.py`?\s+hardcodes\s+512",
        r"migration\s+001[^\n]{0,40}hardcodes\s+512",
        r"hardcodes\s+512",
    )
    offenders: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            # Keep the hardcodes-512 hit only when migration/001 context is near.
            start = max(0, m.start() - 80)
            window = text[start : m.end() + 40]
            if pat == r"hardcodes\s+512" and not re.search(
                r"001|migration|identity_schema", window, flags=re.IGNORECASE
            ):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"L{line_no}: {m.group(0)}")
    assert not offenders, (
        "FINALB-07: plan still claims migration 001 hardcodes 512. "
        "Update against HEAD schema/defaults. Hits:\n  - " + "\n  - ".join(offenders)
    )


def test_fir4_plan_no_docker_independently_pip_resolved_claim() -> None:
    """FINALB-07: plan must not claim Docker remains independently pip-resolved."""
    text = _fir4_plan_text()
    patterns = (
        r"pip resolves[^\n]{0,40}independently of\s+`?uv\.lock`?",
        r"independently pip-resolved",
        r"pip-vs-repo-uv install duality",
        r"image remains independently pip",
        r"Docker remains independently pip",
    )
    offenders: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"L{line_no}: {m.group(0)}")
    assert not offenders, (
        "FINALB-07: plan still claims Docker/image is independently pip-resolved. "
        "HEAD uses frozen uv.lock sync — rephrase. Hits:\n  - "
        + "\n  - ".join(offenders)
    )


def test_fir4_plan_no_completed_image_ort_smoke_claim() -> None:
    """FINALB-07: no completed checklist claim for an image ORT smoke that is gone."""
    text = _fir4_plan_text()
    patterns = (
        r"\[x\]\s*Image ORT smoke",
        r"Image ORT smoke:\s*image build prints",
        r"image build prints\s+`?onnxruntime\.__version__`?",
    )
    offenders: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            line_no = text.count("\n", 0, m.start()) + 1
            offenders.append(f"L{line_no}: {m.group(0)}")
    assert not offenders, (
        "FINALB-07: plan still marks completed image ORT-smoke work that no longer "
        "exists on HEAD. Remove or rephrase the claim. Hits:\n  - "
        + "\n  - ".join(offenders)
    )


def test_fir4_plan_no_stale_dockerfile_pip_install_bench_instruction() -> None:
    """COORD-FINAL-01 / FINALB-07: plan must not instruct Dockerfile pip install .[bench].

    HEAD image deps use frozen ``uv sync --extra bench`` plus project
    ``--no-deps --no-build-isolation``. Stale ``pip install ".[bench]"`` /
    face→bench *rename-as-Dockerfile-install* prose misleads operators.
    """
    text = _fir4_plan_text()
    offenders: list[str] = []
    # Stale Dockerfile install path (not historical package rename alone).
    patterns = (
        r"Dockerfile[^\n]{0,80}pip install[^\n]{0,40}\.?\[bench\]",
        r"pip install\s+[\"']?\.\[bench\][\"']?",
        r"pip install\s+[\"']?\"\.\[bench\]\"[\"']?",
        r"Dockerfile's\s+`?pip install[^\n]{0,60}\.?\[(?:face|bench)\]",
        r"becomes\s+`?\"?\.\[bench\]\"?`?\s*\(rename",
        r"pip install\s+\"\.\[face\]\".*becomes",
    )
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.DOTALL):
            line_no = text.count("\n", 0, m.start()) + 1
            snippet = m.group(0).replace("\n", " ")[:120]
            offenders.append(f"L{line_no}: {snippet}")
    # Dedupe while preserving order.
    seen: set[str] = set()
    unique = []
    for item in offenders:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    assert not unique, (
        "COORD-FINAL-01/FINALB-07: FIR-4 plan still documents Dockerfile "
        '`pip install ".[bench]"` / face→bench rename-as-install. Replace with '
        "frozen `uv sync --extra bench` + project `--no-deps --no-build-isolation`. "
        "Hits:\n  - " + "\n  - ".join(unique)
    )


def test_fir4_plan_documents_frozen_uv_sync_bench_and_no_build_isolation() -> None:
    """COORD-FINAL-01: accepted plan must match HEAD image install surface."""
    text = _fir4_plan_text()
    assert re.search(r"uv sync[^\n]*--extra\s+bench|--extra\s+bench[^\n]*uv sync", text) or (
        "uv sync" in text and "--extra bench" in text
    ), (
        "COORD-FINAL-01: FIR-4 plan must document frozen image deps via "
        "`uv sync ... --extra bench` (not unlocked pip bench resolve)"
    )
    assert "--no-deps" in text and "--no-build-isolation" in text, (
        "COORD-FINAL-01: FIR-4 plan must document project install with "
        "`--no-deps --no-build-isolation` (FINALB-05 / DEP-01/02)"
    )
