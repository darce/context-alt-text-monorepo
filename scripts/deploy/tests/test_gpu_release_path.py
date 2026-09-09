"""ISSUEDAG-1 GPU release-path contracts: effective prod/.env and Green ordering.

Coordinator 10387 / RLSE-03: the producer env file is
REMOTE_BACKEND_DIR/prod/.env, not prod/secrets/.env. Demo stays
REMOTE_DEMO_DIR/secrets/.env. The executable Green bash block must run
prepare-producer prod after gpu-lifecycle and before the first
check-gpu-snapshots-live and deploy prod (TEST-15, DATA-13, AGT-06).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNC_DEMO = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "gpu-demo-env-flip.md"
BACKEND_PROD_ENV = "/opt/acx-backend/prod/.env"
BACKEND_PROD_SECRETS_ENV = "/opt/acx-backend/prod/secrets/.env"
DEMO_SECRETS_ENV = "/opt/acx-backend/demo/secrets/.env"
PREPARE_PRODUCER = (
    "CONFIRM=PROMOTE scripts/deploy/recognition-service.sh prepare-producer prod"
)
GPU_LIFECYCLE = "scripts/deploy/recognition-service.sh gpu-lifecycle"
FIRST_LIVE_CHECK = "GPU_SNAPSHOT_ENV=prod make check-gpu-snapshots-live"
DEPLOY_PROD = "CONFIRM=PROMOTE scripts/deploy/recognition-service.sh deploy prod"


def _bash_blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)


def _runbook() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _deploy_block() -> str:
    """Executable Green-ordering block under producer-then-consumer deploy."""
    section = _runbook().split("## 3. Deploy in producer-then-consumer order", 1)[1]
    return section.split("```bash\n", 1)[1].split("```", 1)[0]


def _run_sync_preflight(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], str]:
    """Bounded mocked SSH/SCP of sync-demo GPU preflight (no real network)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    log_path = shlex.quote(str(log))
    (bin_dir / "ssh").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'ssh %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (bin_dir / "scp").write_text(
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"printf 'scp %q ' \"$@\" >> {log_path}\n"
        f"printf '\\n' >> {log_path}\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for shim in (bin_dir / "ssh", bin_dir / "scp"):
        shim.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["OCI_HOST"] = "test-host.invalid"
    env["OCI_USER"] = "test-user"
    env["PLUGIN_ZIP"] = ""
    env["ACX_DEMO_GPU_PREFLIGHT"] = "1"
    result = subprocess.run(
        ["bash", str(SYNC_DEMO)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    logged = log.read_text(encoding="utf-8") if log.exists() else ""
    return result, logged


def test_sync_demo_preflight_source_uses_backend_prod_env_not_secrets() -> None:
    source = SYNC_DEMO.read_text(encoding="utf-8")
    assert 'REMOTE_BACKEND_DIR="/opt/acx-backend"' in source
    assert 'REMOTE_DEMO_DIR="/opt/acx-backend/demo"' in source
    preflight = source[source.index("run_gpu_env_preflight()") :]
    preflight = preflight.split("\n}\n", 1)[0]
    assert "'${REMOTE_BACKEND_DIR}/prod/.env'" in preflight
    assert "'${REMOTE_BACKEND_DIR}/prod/secrets/.env'" not in preflight
    assert "'${REMOTE_DEMO_DIR}/secrets/.env'" in preflight


def test_sync_demo_preflight_ssh_argv_uses_prod_env(tmp_path: Path) -> None:
    result, logged = _run_sync_preflight(tmp_path)
    combined = result.stdout + result.stderr + logged
    preflight_lines = [line for line in logged.splitlines() if "--check-reaper" in line]
    assert preflight_lines, combined
    argv = "\n".join(preflight_lines)
    assert BACKEND_PROD_ENV in argv, argv
    assert BACKEND_PROD_SECRETS_ENV not in argv
    assert DEMO_SECRETS_ENV in argv


def test_runbook_staged_preflight_already_uses_prod_env() -> None:
    """Textual runbook contract: staged preflight fence (line 80) is the prior-art path."""
    blocks = _bash_blocks(_runbook())
    staged = next(block for block in blocks if "--check-reaper" in block)
    assert BACKEND_PROD_ENV in staged
    assert BACKEND_PROD_SECRETS_ENV not in staged
    assert DEMO_SECRETS_ENV in staged


def test_runbook_backup_edit_restore_use_backend_prod_env() -> None:
    """Textual runbook contract: executable backup/edit/restore blocks, not prose."""
    blocks = _bash_blocks(_runbook())
    backup = next(
        block
        for block in blocks
        if "pre-gpu-flip" in block and "sudo cp -a" in block and "sudoedit" in block
    )
    restore = next(
        block
        for block in blocks
        if ".env.pre-gpu-flip" in block and "systemctl restart" in block
    )
    for block in (backup, restore):
        assert BACKEND_PROD_ENV in block, block
        assert f"{BACKEND_PROD_ENV}.pre-gpu-flip" in block or (
            "/opt/acx-backend/prod/.env.pre-gpu-flip" in block
        ), block
        assert BACKEND_PROD_SECRETS_ENV not in block
        assert DEMO_SECRETS_ENV in block
    assert "sudoedit" in backup
    assert "/opt/acx-backend/prod/.env" in backup.split("sudoedit", 1)[1]
    assert "/opt/acx-backend/prod/secrets/.env" not in backup.split("sudoedit", 1)[1]


def test_green_ordering_block_runs_prepare_producer_before_first_live_check() -> None:
    """Executable Green block, not the prose 'scoped producer-preparation' sentence."""
    block = _deploy_block()
    assert GPU_LIFECYCLE in block
    assert PREPARE_PRODUCER in block, block
    assert FIRST_LIVE_CHECK in block
    assert DEPLOY_PROD in block
    lifecycle = block.index(GPU_LIFECYCLE)
    prepare = block.index(PREPARE_PRODUCER)
    first_check = block.index(FIRST_LIVE_CHECK)
    deploy = block.index(DEPLOY_PROD)
    assert lifecycle < prepare < first_check < deploy, (
        f"order lifecycle={lifecycle} prepare={prepare} "
        f"first_check={first_check} deploy={deploy}"
    )


def test_green_ordering_preserves_repeated_aggregate_checks_before_demo() -> None:
    block = _deploy_block()
    assert block.count(FIRST_LIVE_CHECK) >= 2
    assert block.rindex(FIRST_LIVE_CHECK) < block.index("ACX_DEMO_GPU_PREFLIGHT=1")
    assert DEPLOY_PROD in block
    assert block.index(DEPLOY_PROD) < block.rindex(FIRST_LIVE_CHECK)


def test_green_ordering_does_not_fabricate_zeros_or_delete_registry() -> None:
    block = _deploy_block()
    assert "queue_depth" not in block or "queue_depth\":0" not in block
    assert not re.search(r"queue_depth\s*[:=]\s*0", block)
    assert "gpu-snapshot-deployments.conf" in block
    assert not re.search(r"\brm\b[^\n]*gpu-snapshot-deployments\.conf", block)
    assert "for environment in dev dev-fir staging prod" not in block
    assert "ACX_VERIFY_OPTIONAL" not in block
