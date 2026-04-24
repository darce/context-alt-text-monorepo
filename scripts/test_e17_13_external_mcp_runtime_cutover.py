from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MCP_CONFIG_PATH = REPO_ROOT / ".vscode" / "mcp.json"
TASK_START_PATH = REPO_ROOT / "scripts" / "task-start.sh"
TASK_FINISH_PATH = REPO_ROOT / "scripts" / "task-finish.sh"
SCRIPTS_README_PATH = REPO_ROOT / "scripts" / "README.md"
MAKEFILE_PATH = REPO_ROOT / "Makefile"
MCP_SHIM_PATH = REPO_ROOT / "scripts" / "mcp" / "mcp-server.sh"

LOCAL_PACKAGE_PYTHONPATH = (
    'PYTHONPATH="${REPO_ROOT}/packages/agent-handoff-mcp/src:'
    '${REPO_ROOT}/packages/agent-orchestrator-mcp/src"'
)


def test_external_mcp_runtime_cutover_uses_installed_commands() -> None:
    config = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    servers = config["servers"]

    assert servers["altcontext-mcp"]["command"] == "agent-handoff-mcp"
    assert servers["altcontext-orchestrator-mcp"]["command"] == "agent-orchestrator-mcp"

    for server_name in ("altcontext-mcp", "altcontext-orchestrator-mcp"):
        args = servers[server_name]["args"]
        joined_args = " ".join(args)
        assert "scripts/mcp/mcp-server.sh" not in joined_args
        assert "packages/agent-handoff-mcp" not in joined_args
        assert "packages/agent-orchestrator-mcp" not in joined_args


def test_task_lifecycle_scripts_do_not_boot_from_local_mcp_package_source() -> None:
    task_start = TASK_START_PATH.read_text(encoding="utf-8")
    task_finish = TASK_FINISH_PATH.read_text(encoding="utf-8")
    scripts_readme = SCRIPTS_README_PATH.read_text(encoding="utf-8")

    assert LOCAL_PACKAGE_PYTHONPATH not in task_start
    assert LOCAL_PACKAGE_PYTHONPATH not in task_finish

    assert "launch shim used by `.vscode/mcp.json`" not in scripts_readme
    assert "VS Code now calls the installed console scripts directly via `.vscode/mcp.json`." in scripts_readme
    assert "mcp-server.sh" not in scripts_readme
    assert not MCP_SHIM_PATH.exists()


def test_manual_mcp_makefile_targets_use_installed_entrypoint() -> None:
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")

    assert "./scripts/mcp/mcp-server.sh run" not in makefile
    assert "scripts/mcp/mcp-server.sh\" run" not in makefile
    assert 'agent-handoff-mcp --workspace-root "$(PWD)" serve-stdio' in makefile
    assert 'gemini mcp add context-alt-text-handoff "agent-handoff-mcp" -- --workspace-root "$(PWD)" serve-stdio' in makefile


def test_installed_mcp_console_scripts_smoke() -> None:
    doctor = subprocess.run(
        [
            "agent-handoff-mcp",
            "--workspace-root",
            str(REPO_ROOT),
            "doctor",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stderr or doctor.stdout
    assert "workspace_root" in doctor.stdout

    orchestrator_help = subprocess.run(
        [
            "agent-orchestrator-mcp",
            "--workspace-root",
            str(REPO_ROOT),
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert orchestrator_help.returncode == 0, orchestrator_help.stderr or orchestrator_help.stdout
    assert "usage:" in orchestrator_help.stdout.lower()