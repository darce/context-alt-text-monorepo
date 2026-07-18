"""FIR3-BR-01 / FIR4-BR-01 release-gate contracts (RED-first).

Static/behavior guards for:
1. Docker image deps resolve from ``uv.lock`` via frozen lock consumption
   (not unlocked ``pip install .[bench]``).
2. A dedicated CI workflow runs real YuNet/SFace ORT-vs-OpenCV parity with
   fail-closed missing-model semantics.
3. Test infrastructure distinguishes ordinary modelless skips from the
   required parity gate (covered here + face_pipeline_support helpers).

No Dockerfile/workflow edits in the RED pass — these tests must fail until
GREEN production surfaces land.

Heuristics: RLSE-01/02/05/07, SERVE-07, EVAL-01/04, PROV-01/08, TEST-06,
DEP-01, CFG-02.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

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
_PARITY_WORKFLOW_CANDIDATES = (
    _REPO_ROOT / ".github" / "workflows" / "face-pipeline-ort-parity.yml",
    _REPO_ROOT / ".github" / "workflows" / "face-pipeline-parity.yml",
    _REPO_ROOT / ".github" / "workflows" / "face_pipeline_ort_parity.yml",
)


def _dockerfile_text() -> str:
    assert _DOCKERFILE.is_file(), f"missing Dockerfile at {_DOCKERFILE}"
    return _DOCKERFILE.read_text(encoding="utf-8")


def _parity_workflow_path() -> Path:
    for path in _PARITY_WORKFLOW_CANDIDATES:
        if path.is_file():
            return path
    # Prefer the canonical name in the failure message.
    return _PARITY_WORKFLOW_CANDIDATES[0]


# ---------------------------------------------------------------------------
# 1. Docker frozen-lock install (FIR4-BR-01)
# ---------------------------------------------------------------------------


def test_service_uv_lock_exists() -> None:
    assert _UV_LOCK.is_file(), (
        f"expected checked-in lock at {_UV_LOCK.relative_to(_REPO_ROOT)} "
        "(Docker must consume this file, not resolve unlocked)"
    )


def test_dockerfile_copies_uv_lock() -> None:
    """Builder must COPY uv.lock so frozen sync can consume exact pins."""
    text = _dockerfile_text()
    # Accept COPY of lock alone or alongside pyproject on one line.
    assert re.search(r"^COPY\s+[^\n]*\buv\.lock\b", text, re.MULTILINE), (
        "Dockerfile must COPY uv.lock into the build context "
        "(FIR4-BR-01: lock is system of record for image deps)"
    )


def test_dockerfile_installs_deps_via_uv_sync_frozen() -> None:
    """Dependency install must use uv sync with a frozen/locked resolution."""
    text = _dockerfile_text()
    assert "uv sync" in text, (
        "Dockerfile must install runtime deps with `uv sync` (not unlocked pip resolve)"
    )
    assert "--frozen" in text or "--locked" in text, (
        "Dockerfile `uv sync` must pass --frozen (or --locked) for exact lock consumption"
    )


def test_dockerfile_frozen_sync_enables_bench_extra() -> None:
    """runtime+[bench]: insightface stays available for the dark default until FIR-6."""
    text = _dockerfile_text()
    # Prefer explicit --extra bench on a uv sync line; allow multi-line RUN.
    sync_blocks = re.findall(r"uv sync[^\n]*(?:\\\n[^\n]*)*", text)
    joined = "\n".join(sync_blocks) if sync_blocks else text
    assert re.search(r"--extra\s+bench\b", joined) or "extras=bench" in joined, (
        "Dockerfile frozen install must enable the bench extra "
        "(`uv sync --frozen --extra bench` or equivalent)"
    )


def test_dockerfile_rejects_unlocked_pip_bench_dependency_install() -> None:
    """Unlocked ``pip install .[bench]`` (without --no-deps) must not resolve deps."""
    text = _dockerfile_text()
    offenders = [
        ln.strip()
        for ln in text.splitlines()
        if "pip install" in ln and ".[bench]" in ln.replace(" ", "") and "--no-deps" not in ln
    ]
    # Also catch spaced forms: pip install ".[bench]"
    if not offenders:
        offenders = [
            ln.strip()
            for ln in text.splitlines()
            if "pip install" in ln and ".[bench]" in ln and "--no-deps" not in ln
        ]
    assert not offenders, (
        "Dockerfile must not use unlocked `pip install .[bench]` for dependency "
        "resolution; switch to COPY uv.lock + `uv sync --frozen --extra bench`. "
        "Found:\n  - " + "\n  - ".join(offenders)
    )


def test_dockerfile_runtime_editable_install_may_remain_no_deps() -> None:
    """App package install may stay `pip install -e . --no-deps` after lock-based deps."""
    text = _dockerfile_text()
    # Not a hard requirement that editable install exists — only that if pip
    # installs the app package without the bench extra, --no-deps is used.
    app_pip = [
        ln
        for ln in text.splitlines()
        if "pip install" in ln and re.search(r"\s-e\s+\.|\spip install[^\n]*\s\.\s", ln)
    ]
    for ln in app_pip:
        if ".[bench]" in ln or ".[dev]" in ln:
            continue
        if re.search(r"pip install[^\n]*\s\.(?:\s|$)", ln) or " -e ." in ln or " -e ." in ln.replace(
            "  ", " "
        ):
            assert "--no-deps" in ln, (
                "Runtime app `pip install` of `.` must use --no-deps when deps "
                f"come from the lock. Offending line: {ln.strip()}"
            )


def test_dockerfile_no_hardcoded_ort_version_independent_of_lock() -> None:
    """Do not pin a second onnxruntime version window outside uv.lock.

    A post-install smoke may still import onnxruntime, but hard-coded version
    tuples (e.g. ``(1, 22) <= p < (2, 0)``) reintroduce dual writers vs the lock.
    """
    text = _dockerfile_text()
    # Only flag executable/version-check forms — not prose mentioning 1.22.
    patterns = (
        r"\(1\s*,\s*22\)\s*<=",  # tuple lower bound
        r"<=\s*p\s*<\s*\(2\s*,\s*0\)",  # tuple upper bound pair
        r"sys\.exit\(0 if \(1\s*,\s*22\)",
        r"__version__.*1\.22|1\.22.*__version__",
    )
    hits = [m.group(0) for pat in patterns if (m := re.search(pat, text))]
    assert not hits, (
        "Dockerfile must not hard-code a second ORT version bound independent of "
        "uv.lock (remove the pip-resolved [1.22, 2.0) smoke; lock pins ORT). "
        f"Matched: {hits!r}"
    )


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
