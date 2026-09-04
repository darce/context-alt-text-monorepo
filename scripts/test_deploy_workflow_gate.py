from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(os.environ.get("DEPLOY_GATE_REPO_ROOT", Path(__file__).resolve().parents[1]))
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-recognition.yml"
REQUIRED_RUN_SHELL = "bash --noprofile --norc -eo pipefail {0}"
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbooks" / "deploy-recognition-cicd.md"


def _workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as workflow_file:
        return yaml.safe_load(workflow_file)


def _deploy_workflow_paths() -> list[Path]:
    """Discover workflows that can reach a deploy job."""
    paths = []
    for workflow_path in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        with workflow_path.open(encoding="utf-8") as workflow_file:
            workflow = yaml.safe_load(workflow_file)
        if "deploy" in workflow.get("jobs", {}):
            paths.append(workflow_path)
    return paths


def _workflow_cases() -> list[object]:
    cases: list[object] = []
    for workflow_path in _deploy_workflow_paths():
        if workflow_path.name == "deploy-recognition.yml":
            cases.append(
                pytest.param(
                    workflow_path,
                    marks=pytest.mark.xfail(
                        strict=True,
                        reason="owned by demoland-1-g3",
                    ),
                )
            )
        else:
            cases.append(workflow_path)
    return cases


@pytest.mark.parametrize("workflow_path", _workflow_cases(), ids=lambda path: path.name)
def test_every_deploy_workflow_run_step_uses_fail_closed_bash(workflow_path: Path) -> None:
    with workflow_path.open(encoding="utf-8") as workflow_file:
        workflow = yaml.safe_load(workflow_file)

    unsafe_steps = []
    for job_name, job in workflow.get("jobs", {}).items():
        if not isinstance(job, dict):
            continue
        job_shell = job.get("defaults", {}).get("run", {}).get("shell")
        for step in job.get("steps", []):
            if not isinstance(step, dict) or "run" not in step:
                continue
            effective_shell = step.get("shell", job_shell)
            if effective_shell != REQUIRED_RUN_SHELL:
                unsafe_steps.append(f"{job_name}: {step.get('name', '<unnamed>')}")

    assert unsafe_steps == [], (
        f"{workflow_path.relative_to(REPO_ROOT)} has run steps without "
        f"shell: {REQUIRED_RUN_SHELL!r}: {unsafe_steps}"
    )


def _contract_gate(workflow: dict) -> tuple[str, dict]:
    matching_jobs = [
        (job_name, job)
        for job_name, job in workflow["jobs"].items()
        if any(
            "make test-deploy-contract" in step.get("run", "")
            for step in job.get("steps", [])
            if isinstance(step, dict)
        )
    ]
    assert matching_jobs, "workflow must run make test-deploy-contract before deploying"
    assert len(matching_jobs) == 1, "workflow must have exactly one deploy-contract gate"
    return matching_jobs[0]


def test_deploy_needs_contract_gate() -> None:
    workflow = _workflow()
    gate_name, _ = _contract_gate(workflow)

    needs = workflow["jobs"]["deploy"].get("needs", [])
    if isinstance(needs, str):
        needs = [needs]
    assert gate_name in needs, "deploy must depend on the deploy-contract gate"


def test_contract_gate_is_isolated_and_bounded() -> None:
    workflow = _workflow()
    _, gate = _contract_gate(workflow)
    gate_text = str(gate).lower()

    assert "environment" not in gate, "gate must not consume a deployment environment"
    assert gate.get("timeout-minutes") == 10, "gate must have its own 10-minute timeout"
    assert "tailscale" not in gate_text, "gate must not join the tailnet"
    assert "secrets." not in gate_text, "gate must not consume GitHub secrets"
    assert "docker" not in gate_text, "gate must not depend on Docker"


def test_push_paths_cover_the_gate_inputs() -> None:
    workflow = _workflow()
    # PyYAML 1.1 resolves an unquoted `on` key as boolean True.
    triggers = workflow.get("on", workflow.get(True, {}))
    paths = triggers["push"]["paths"]

    assert "scripts/test_deploy_workflow_gate.py" in paths
    assert "scripts/test_ocirv1_vault_readiness.py" in paths
    assert "scripts/deploy/tests/**" in paths
    assert "Makefile" in paths


def test_make_target_keeps_credential_suites() -> None:
    result = subprocess.run(
        ["make", "-n", "test-deploy-contract"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "test_ocirv1_vault_readiness.py" in output
    assert "test-ocir-auth.sh" in output


def _rollback_prose() -> str:
    """The Rollback section with fenced code blocks stripped.

    Prose only: a variable named inside the command it appears in does not tell
    the operator to set it beforehand.
    """
    text = RUNBOOK_PATH.read_text(encoding="utf-8")
    start = text.index("## Rollback")
    section = text[start : text.index("\n## ", start + 1)]
    return re.sub(r"```.*?```", "", section, flags=re.DOTALL)


def test_prod_rollback_commands_are_copy_pasteable() -> None:
    """A rollback command is executed at 2am, not designed there (rg-006).

    ``GIT_REF=<good-sha>`` is a literal angle-bracket placeholder: pasted
    verbatim under incident pressure it hands ``git rev-parse`` the text
    ``<good-sha>`` and fails. The shell-variable form runs as written.
    """
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
    assert "CONFIRM=PROMOTE scripts/deploy/recognition-service.sh promote staging prod" in runbook
    assert (
        'CONFIRM=PROMOTE GIT_REF="$GOOD_SHA" REMOTE_BUILD=1 scripts/deploy/recognition-service.sh deploy prod'
        in runbook
    ), "the prod redeploy command is not copy-pasteable as written"
    assert "GIT_REF=<good-sha>" not in runbook, (
        "the runbook still documents a literal angle-bracket placeholder for GIT_REF"
    )
    assert "GOOD_SHA" in _rollback_prose(), (
        "the rollback section's prose never tells the operator to set GOOD_SHA "
        "before running the redeploy command"
    )
