from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "deploy" / "sync-demo.sh"
LEDGERS = ("clustering-rights.tsv", "guided-rights.tsv")


def test_seed_rights_ledgers_are_copied_after_the_import_script() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    import_copy = '$SCP "$SEED_IMPORT_SRC" "${OCI_USER}@${OCI_HOST}:${REMOTE_DEMO_DIR}/seed/import.sh"'
    assert import_copy in source
    import_copy_index = source.index(import_copy)

    for ledger in LEDGERS:
        copy = (
            f'$SCP "$SEED_RIGHTS_DIR/{ledger}" '
            f'"${{OCI_USER}}@${{OCI_HOST}}:${{REMOTE_DEMO_DIR}}/seed/{ledger}"'
        )
        assert copy in source, f"missing copy of {ledger} to the remote seed directory"
        assert source.index(copy) > import_copy_index, f"{ledger} must ship after seed/import.sh"


@pytest.mark.parametrize("missing_ledger", LEDGERS)
def test_missing_seed_rights_ledger_stops_before_remote_copy(
    tmp_path: Path, missing_ledger: str
) -> None:
    rights_dir = tmp_path / "rights"
    rights_dir.mkdir()
    for ledger in LEDGERS:
        if ledger != missing_ledger:
            (rights_dir / ledger).write_text("header\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    remote_log = tmp_path / "remote.log"
    for command in ("ssh", "scp"):
        shim = bin_dir / command
        shim.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\\n" "${0##*/} $*" >> "$REMOTE_COMMAND_LOG"\n'
            "exit 91\n",
            encoding="utf-8",
        )
        shim.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "REMOTE_COMMAND_LOG": str(remote_log),
            "SEED_RIGHTS_DIR": str(rights_dir),
            "PLUGIN_ZIP": "",
            "ACX_DEMO_GPU_PREFLIGHT": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert missing_ledger in result.stderr
    assert not remote_log.exists(), "sync-demo.sh contacted the VM before validating the ledger"
