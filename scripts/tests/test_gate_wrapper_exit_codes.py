from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github/workflows/deploy-demo.yml"


def _workflow_run_shell(workflow: str) -> str:
    """Return the job-wide shell, or GitHub Actions' bash default."""
    match = re.search(
        r"(?ms)^    defaults:\n      run:\n        shell:\s*(?P<shell>.+?)\s*$",
        workflow,
    )
    if match is None:
        return "bash --noprofile --norc -e {0}"
    return match.group("shell")


def test_deploy_workflow_propagates_a_runner_failure_through_output_tail(tmp_path: Path) -> None:
    """A startup failure must stay red when a wrapper trims its diagnostics."""
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    shell = _workflow_run_shell(workflow)
    script = tmp_path / "masked-runner.sh"
    script.write_text(
        "(printf 'vitest STARTUP FAILURE\\n' >&2; exit 23) | tail -n 20\n",
        encoding="utf-8",
    )

    argv = [str(script) if part == "{0}" else part for part in shlex.split(shell)]
    completed = subprocess.run(argv, text=True, capture_output=True, check=False)

    assert completed.returncode == 23, (
        "The deploy gate reported success after its runner exited 23, so a suite that ran zero "
        f"tests can merge green. Configured shell: {shell!r}; stderr: {completed.stderr!r}"
    )


def test_owned_bash_gate_wrappers_enable_pipefail() -> None:
    wrappers = [
        "scripts/localwp-gate-status.sh",
        "scripts/remote_gate.sh",
        "scripts/deploy/sync-demo.sh",
        "scripts/deploy/recognition-service.sh",
        "scripts/deploy/ocir-token-rotate.sh",
        "scripts/vm/reap-lane.sh",
    ]

    missing = []
    for relative_path in wrappers:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        if not re.search(r"(?m)^set -[^\n]*o pipefail\s*$", source):
            missing.append(relative_path)

    assert missing == [], (
        "Gate wrappers without pipefail can turn a failed runner into EXIT=0 when output is piped "
        f"through tail/head: {missing}"
    )


def test_remote_gate_shell_enables_pipefail_before_running_targets() -> None:
    source = (REPO_ROOT / "scripts/remote_gate.sh").read_text(encoding="utf-8")

    assert '"set -uo pipefail\n' in source, (
        "The remote shell must propagate the runner's status through any diagnostic pipeline; "
        "local pipefail does not cross the SSH process boundary."
    )


def test_css_artifact_eviction_scope_is_distinct_per_lane() -> None:
    module = (
        REPO_ROOT
        / "apps/prototype-wp-alt-context/js/admin/styles/components/__tests__/productionCssBundle.ts"
    )
    javascript = f"""
globalThis.__dirname = {json.dumps(str(module.parent))};
const fixture = await import({json.dumps(module.as_uri())});
const roots = [
  fixture.artifactFixtureRootForAppRoot('/worktrees/feature-a/apps/prototype-wp-alt-context'),
  fixture.artifactFixtureRootForAppRoot('/worktrees/feature-b/apps/prototype-wp-alt-context'),
];
console.log(JSON.stringify(roots));
"""

    completed = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", javascript],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    lane_a, lane_b = json.loads(completed.stdout)
    assert lane_a != lane_b, (
        "Concurrent lanes share one CSS artifact LRU, so the fifth lane can evict a sibling's "
        "bundle while that sibling's gate is still running."
    )
