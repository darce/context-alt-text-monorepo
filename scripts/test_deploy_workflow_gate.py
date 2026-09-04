from __future__ import annotations

import os
import re
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


def test_gpu_lifecycle_dispatch_is_explicit_and_flag_gated() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True, {}))
    gpu_input = triggers["workflow_dispatch"]["inputs"]["gpu_lifecycle"]

    assert gpu_input["type"] == "boolean"
    assert gpu_input["default"] is False

    steps = workflow["jobs"]["deploy"]["steps"]
    lifecycle_step = next(step for step in steps if step.get("name") == "Install GPU lifecycle timers")
    deploy_index = next(index for index, step in enumerate(steps) if str(step.get("name", "")).startswith("Deploy "))
    lifecycle_index = steps.index(lifecycle_step)

    assert lifecycle_index > deploy_index
    assert "gpu_lifecycle == 'true'" in lifecycle_step["if"]
    assert lifecycle_step["env"]["ACX_DEPLOY_GPU_LIFECYCLE"] == "1"
    assert lifecycle_step["env"]["ACX_GPU_READY_URL"] == "${{ vars.ACX_GPU_READY_URL }}"
    assert lifecycle_step["env"]["GPU_INSTANCE_ID"] == "${{ vars.ACX_GPU_INSTANCE_ID }}"
    assert "recognition-service.sh gpu-lifecycle" in lifecycle_step["run"]


def test_every_run_step_uses_pipefail_shell_default() -> None:
    workflow = _workflow()
    expected_shell = "bash --noprofile --norc -eo pipefail {0}"

    assert workflow["defaults"]["run"]["shell"] == expected_shell
    for job_name, job in workflow["jobs"].items():
        job_shell = job.get("defaults", {}).get("run", {}).get("shell", expected_shell)
        for step in job.get("steps", []):
            if "run" not in step:
                continue
            assert step.get("shell", job_shell) == expected_shell, (
                f"{job_name}/{step.get('name', '<unnamed>')} does not use pipefail"
            )


def test_gpu_lifecycle_dry_run_does_not_mask_gh_variable_failures() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert 'export ACX_GPU_READY_URL="$(gh variable get' not in runbook
    assert 'export GPU_INSTANCE_ID="$(gh variable get' not in runbook
    assert 'ACX_GPU_READY_URL="$(gh variable get ACX_GPU_READY_URL)" || exit 1' in runbook
    assert 'GPU_INSTANCE_ID="$(gh variable get ACX_GPU_INSTANCE_ID)" || exit 1' in runbook
    assert "`pinned`" in runbook
    assert "`resolved-by-name`" in runbook


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


def test_gpu_lifecycle_rollback_is_fail_fast_and_shell_parseable() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")
    marked = runbook.split("<!-- gpu-lifecycle-rollback:start -->", 1)[1].split(
        "<!-- gpu-lifecycle-rollback:end -->", 1
    )[0]
    block = re.search(r"```bash\n(.*?)```", marked, flags=re.DOTALL)
    assert block is not None
    commands = block.group(1)

    parsed = subprocess.run(
        ["bash", "-n"], input=commands, text=True, capture_output=True, check=False
    )
    assert parsed.returncode == 0, parsed.stderr
    assert "set -euo pipefail" in commands
    assert commands.index("disable --now acx-gpu-start.timer") < commands.index(
        "previous_release=$(readlink -f"
    )
    assert "systemctl start acx-gpu-reap.service" in commands
    assert "--property=FragmentPath" in commands
    assert "--property=DropInPaths" in commands
    assert "cmp -s" in commands
    assert commands.index("systemctl start acx-gpu-reap.service") < commands.index(
        "enable --now acx-gpu-start.timer"
    )
