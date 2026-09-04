from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(os.environ.get("DEPLOY_GATE_REPO_ROOT", Path(__file__).resolve().parents[1]))
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-recognition.yml"
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbooks" / "deploy-recognition-cicd.md"


def _workflow() -> dict:
    with WORKFLOW_PATH.open(encoding="utf-8") as workflow_file:
        return yaml.safe_load(workflow_file)


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
    assert "scripts/deploy/tests" in output


def test_prod_rollback_commands_set_confirmation_in_the_environment() -> None:
    runbook = RUNBOOK_PATH.read_text()
    assert "CONFIRM=PROMOTE scripts/deploy/recognition-service.sh promote staging prod" in runbook
    assert (
        'CONFIRM=PROMOTE GIT_REF="$GOOD_SHA" REMOTE_BUILD=1 scripts/deploy/recognition-service.sh deploy prod'
    ) in runbook
    assert "GIT_REF=<good-sha>" not in runbook
