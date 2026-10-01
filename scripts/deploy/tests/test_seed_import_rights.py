"""Regression tests for the demo seed rights gate in import.sh."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPO_ROOT / "infra" / "oci" / "demo" / "seed" / "import.sh"
RIGHTS_HEADER = "file\tsubject\tbasis\tsource\tnotice\tadded"


def _run_import(
    tmp_path: Path,
    media_files: Sequence[str],
    rights_rows: Sequence[tuple[str, str, str]],
    *,
    wrong_header: str | None = None,
    missing_ledger: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    demo_dir = tmp_path / "demo"
    (demo_dir / "secrets").mkdir(parents=True)
    (demo_dir / "secrets" / ".env").write_text("DEMO_TEST=1\n", encoding="utf-8")

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    for filename in media_files:
        (media_dir / filename).touch()

    rights_dir = tmp_path / "rights"
    rights_dir.mkdir()
    rows = [
        f"{filename}\tTest subject\t{basis}\t{source}\t{notice}\t2026-09-01"
        for filename, basis, source in rights_rows
        for notice in ["attribution_required"]
    ]
    for ledger_name in ("clustering-rights.tsv", "guided-rights.tsv"):
        if ledger_name == missing_ledger:
            continue
        header = "bad\theader" if ledger_name == wrong_header else RIGHTS_HEADER
        ledger_rows = rows if ledger_name == "clustering-rights.tsv" else []
        (rights_dir / ledger_name).write_text("\n".join([header, *ledger_rows]) + "\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    docker_count = tmp_path / "docker-count"
    docker_stub = bin_dir / "docker"
    docker_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_LOG\"\n"
        "if [[ \" $* \" == *\" wp media import \"* ]]; then\n"
        "  count=0\n"
        "  if [[ -f \"$DOCKER_COUNT\" ]]; then read -r count < \"$DOCKER_COUNT\"; fi\n"
        "  count=$((count + 1))\n"
        "  printf '%s\\n' \"$count\" > \"$DOCKER_COUNT\"\n"
        "  printf '%s\\n' \"$((7000 + count))\"\n"
        "fi\n",
        encoding="utf-8",
    )
    docker_stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "DEMO_DIR": str(demo_dir),
            "SEED_MEDIA_DIR": str(media_dir),
            "SEED_RIGHTS_DIR": str(rights_dir),
            "DOCKER_LOG": str(docker_log),
            "DOCKER_COUNT": str(docker_count),
            "PATH": f"{bin_dir}:{env['PATH']}",
        }
    )
    result = subprocess.run(
        ["bash", str(IMPORT_SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    commands = docker_log.read_text(encoding="utf-8").splitlines() if docker_log.exists() else []
    return result, commands


def _media_imports(commands: Sequence[str]) -> list[str]:
    return [command for command in commands if " wp media import " in f" {command} "]


def _meta_updates(commands: Sequence[str]) -> list[str]:
    return [command for command in commands if " wp post meta update " in f" {command} "]


def test_recognised_rights_import_every_file_and_write_both_meta_values(tmp_path: Path) -> None:
    rows = [
        ("alpha.jpg", "cc_by", "Wikimedia source alpha"),
        ("beta.webp", "public_domain", "Wikimedia source beta"),
    ]
    result, commands = _run_import(tmp_path, ["alpha.jpg", "beta.webp"], rows)

    assert result.returncode == 0, result.stdout + result.stderr
    imports = _media_imports(commands)
    assert len(imports) == 2
    assert any("wp media import /seed/alpha.jpg --porcelain" in command for command in imports)
    assert any("wp media import /seed/beta.webp --porcelain" in command for command in imports)

    updates = _meta_updates(commands)
    assert len(updates) == 4
    expected_meta = (
        "wpcli wp post meta update 7001 acx_seed_rights_basis cc_by",
        "wpcli wp post meta update 7001 acx_seed_rights_source Wikimedia source alpha",
        "wpcli wp post meta update 7002 acx_seed_rights_basis public_domain",
        "wpcli wp post meta update 7002 acx_seed_rights_source Wikimedia source beta",
    )
    for expected in expected_meta:
        assert any(expected in command for command in updates)
    assert "imported=2 refused=0" in result.stdout


def test_unrecorded_basis_is_named_and_refused_while_other_media_imports(tmp_path: Path) -> None:
    rows = [
        ("alpha.jpg", "unrecorded", "Basis not known"),
        ("beta.webp", "cc_by_sa", "Wikimedia source beta"),
    ]
    result, commands = _run_import(tmp_path, ["alpha.jpg", "beta.webp"], rows)

    assert result.returncode == 0, result.stdout + result.stderr
    imports = _media_imports(commands)
    assert len(imports) == 1
    assert "wp media import /seed/beta.webp --porcelain" in imports[0]
    assert "alpha.jpg" in result.stderr
    assert "unrecognised rights basis 'unrecorded'" in result.stderr
    assert len(_meta_updates(commands)) == 2
    assert "imported=1 refused=1" in result.stdout


def test_empty_basis_is_refused(tmp_path: Path) -> None:
    result, commands = _run_import(
        tmp_path,
        ["alpha.jpg"],
        [("alpha.jpg", "", "Wikimedia source alpha")],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not _media_imports(commands)
    assert "alpha.jpg" in result.stderr
    assert "unrecognised rights basis ''" in result.stderr
    assert "imported=0 refused=1" in result.stdout


def test_missing_media_row_exits_before_importing_any_file(tmp_path: Path) -> None:
    result, commands = _run_import(
        tmp_path,
        ["alpha.jpg", "missing.webp"],
        [("alpha.jpg", "generated", "Generated test image")],
    )

    assert result.returncode == 2
    assert "missing.webp" in result.stderr
    assert not _media_imports(commands)


def test_wrong_ledger_header_exits_before_importing_any_file(tmp_path: Path) -> None:
    result, commands = _run_import(
        tmp_path,
        ["alpha.jpg"],
        [("alpha.jpg", "cc_by", "Wikimedia source alpha")],
        wrong_header="clustering-rights.tsv",
    )

    assert result.returncode == 2
    assert "clustering-rights.tsv" in result.stderr
    assert "wrong header" in result.stderr
    assert not _media_imports(commands)


def test_missing_ledger_exits_before_importing_any_file(tmp_path: Path) -> None:
    result, commands = _run_import(
        tmp_path,
        ["alpha.jpg"],
        [("alpha.jpg", "cc_by", "Wikimedia source alpha")],
        missing_ledger="guided-rights.tsv",
    )

    assert result.returncode == 2
    assert "guided-rights.tsv" in result.stderr
    assert "missing" in result.stderr
    assert not _media_imports(commands)
