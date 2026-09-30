from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
IMPORT_SCRIPT = REPO_ROOT / "infra/oci/demo/seed/import.sh"
SYNC_SCRIPT = REPO_ROOT / "scripts/deploy/sync-demo.sh"


def test_import_media_glob_collects_webp_files(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    webp_files = [media_dir / "guided.webp", media_dir / "GUIDED.WEBP"]
    for path in webp_files:
        path.touch()

    import_source = IMPORT_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"(?m)^media_files=(.*)$", import_source)
    assert match is not None, "could not find the seed media glob in import.sh"
    script = (
        'SEED_MEDIA_DIR="$1"; shopt -s nullglob; media_files='
        + match.group(1)
        + '; for path in "${media_files[@]}"; do printf "%s\\n" "$path"; done'
    )
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(media_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # case-insensitive filesystems collapse the two fixture names to one file
    surviving = {str(path) for path in media_dir.iterdir()}
    assert set(result.stdout.splitlines()) == surviving


def test_sync_media_filter_collects_webp_files(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    webp_file = media_dir / "guided.webp"
    webp_file.touch()

    sync_source = SYNC_SCRIPT.read_text(encoding="utf-8")
    line = next((line for line in sync_source.splitlines() if "done < <(find \"$SEED_MEDIA_DIR\"" in line), None)
    assert line is not None, "could not find the seed media find expression in sync-demo.sh"
    find_command = line.partition("<(")[2].rsplit(")", 1)[0]
    result = subprocess.run(
        ["bash", "-c", 'SEED_MEDIA_DIR="$1"; ' + find_command, "bash", str(media_dir)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [str(webp_file)]
