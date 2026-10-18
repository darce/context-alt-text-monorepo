"""The GPU snapshot gate's own contract, asserted outside the workflow file.

WBUX6-W4-F-02: `.github/workflows/gpu-snapshot-gate.yml` exists because the
strongest cases in `scripts/deploy/tests/test-check-gpu-snapshots.sh` -- the
ones that caught WBUX6-MRG-01 -- need real root plus setpriv(1), and everywhere
else they print SKIP while the suite still reports success. Nothing in the repo
asserted that this workflow exists or that it disarms the skip. Deleting the
file, or dropping `ACX_GPU_TEST_REQUIRE_FULL_COVERAGE=1` from its run step,
restored the silent-skip shape with no signal at all -- the same fail-open class
the workflow was created to close (RLSE-05 silent failure is the worst failure,
~/Development/heuristics-canon-research/lexicons/engineering.md:696; TEST-15
prove the green can go red, engineering.md:396).

Parsed with a real YAML parser and validated key-by-key rather than grepped, so
a structurally broken workflow fails here instead of silently never running
(rg-008).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE_WORKFLOW = REPO_ROOT / ".github/workflows/gpu-snapshot-gate.yml"
DEPLOY_WORKFLOW = REPO_ROOT / ".github/workflows/deploy-recognition.yml"
SHELL_SUITE_REL = "scripts/deploy/tests/test-check-gpu-snapshots.sh"
COVERAGE_FLAG = "ACX_GPU_TEST_REQUIRE_FULL_COVERAGE"


def _load(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} does not exist"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict), f"{path.name} must parse to a mapping, got {type(document).__name__}"
    return document


def _triggers(document: dict[str, Any]) -> dict[str, Any]:
    # PyYAML resolves the bare key `on` to the boolean True (YAML 1.1).
    triggers = document.get("on", document.get(True))
    assert isinstance(triggers, dict), "workflow must declare a mapping of triggers"
    return triggers


def _steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = document.get("jobs")
    assert isinstance(jobs, dict) and jobs, "workflow declares no jobs"
    return [step for job in jobs.values() for step in job.get("steps", []) if isinstance(step, dict)]


def test_gpu_snapshot_gate_workflow_exists_and_parses() -> None:
    document = _load(GATE_WORKFLOW)

    assert document.get("name"), "the gate workflow must be named"
    triggers = _triggers(document)
    assert "pull_request" in triggers, (
        "the gate must run on pull_request; a push-to-main-only gate never blocks the change that breaks it"
    )
    for event in ("pull_request", "push"):
        paths = triggers[event].get("paths")
        assert isinstance(paths, list), f"{event} must filter on an explicit paths list"
        for required in ("scripts/deploy/**", "infra/oci/**", "apps/prototype-description-service/Dockerfile"):
            assert required in paths, f"{event}.paths must cover {required}"


def test_gpu_snapshot_gate_runs_the_shell_suite_with_skips_made_fatal() -> None:
    """Both halves matter: running the suite, and refusing to accept a SKIP."""

    steps = _steps(_load(GATE_WORKFLOW))
    suite_steps = [step for step in steps if SHELL_SUITE_REL in str(step.get("run", ""))]

    assert suite_steps, f"no step runs {SHELL_SUITE_REL}"
    assert any(str(step.get("env", {}).get(COVERAGE_FLAG)) == "1" for step in suite_steps), (
        f"the step that runs {SHELL_SUITE_REL} must set {COVERAGE_FLAG}=1; "
        "without it a runner that loses root or setpriv degrades to a quiet pass"
    )


def test_gpu_snapshot_gate_job_is_privileged_enough_to_run_the_skipped_cases() -> None:
    jobs = _load(GATE_WORKFLOW)["jobs"]
    privileged = [job for job in jobs.values() if job.get("container")]

    assert privileged, (
        "the suite's root-only cases need a container job (GitHub's default runner user is unprivileged), "
        f"otherwise {COVERAGE_FLAG}=1 turns every run red instead of proving coverage"
    )
    assert any("setpriv" in str(step.get("run", "")) for job in privileged for step in job.get("steps", [])), (
        "the privileged job must install/verify setpriv(1); without it the probe cannot drop privilege"
    )


def test_deploy_workflow_gate_watches_the_files_its_contract_tests_read() -> None:
    """WBUX6-W4-F-04: a paths filter that misses the contract's inputs is no gate."""

    triggers = _triggers(_load(DEPLOY_WORKFLOW))
    paths = triggers["push"]["paths"]

    for required in ("infra/oci/**", "scripts/deploy/**", "scripts/deploy/tests/**"):
        assert required in paths, f"deploy-recognition.yml push.paths must cover {required}"
    # The Dockerfile carries the `groupadd -r -g 10001 acx` pin that fixed
    # WBUX6-MRG-01; it is covered by the app glob rather than by name.
    assert "apps/prototype-description-service/**" in paths, (
        "the api Dockerfile's pinned runtime gid must be inside the deploy gate's paths filter"
    )
