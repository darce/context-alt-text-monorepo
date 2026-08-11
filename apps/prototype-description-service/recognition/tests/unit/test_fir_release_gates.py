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
import sys
from pathlib import Path
from types import ModuleType

import pytest

from recognition.tests.dockerfile_stages import (
    DEFAULT_BUILDER_STAGE,
    DEFAULT_RUNTIME_STAGE,
    _PROJECT_EXTRAS_RE,
    dockerfile_stages,
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

# Default image path only (builder + runtime). Do not assert internals of
# builder-vlm / runtime-vlm — a concurrent lane owns those stages.
_DEFAULT_IMAGE_STAGES = (DEFAULT_BUILDER_STAGE, DEFAULT_RUNTIME_STAGE)


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
    stages = _dockerfile_stages()
    assert DEFAULT_RUNTIME_STAGE in stages, (
        f"Dockerfile missing {DEFAULT_RUNTIME_STAGE!r} stage; have {list(stages)}"
    )
    return stages[DEFAULT_RUNTIME_STAGE]


def _default_image_stage_text() -> str:
    stages = _dockerfile_stages()
    return "\n".join(stages[name] for name in _DEFAULT_IMAGE_STAGES if name in stages)


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
        body = stages.get(stage, "")
        for hit in unlocked_project_extra_installs(body):
            offenders.append(f"{stage}: {hit}")
    assert not offenders, (
        "default image stages must not use unlocked project+extras pip/uv install "
        "for dependency resolution; switch to COPY uv.lock + "
        "`uv sync --frozen --extra bench`. Found:\n  - " + "\n  - ".join(offenders)
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
    Scoped to the default image stages (builder + runtime).
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
        "Dockerfile default image stages must not hard-code a second ORT version "
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
