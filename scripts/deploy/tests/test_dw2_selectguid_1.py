from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTOR = REPO_ROOT / "infra/oci/demo/seed/select-guided-seed.sh"
ASSETS = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/assets/guided"


def test_webp_source_keeps_webp_extension_and_manifest_entry(tmp_path: Path) -> None:
    output = tmp_path / "media"
    manifest = tmp_path / "guided-manifest.txt"
    env = os.environ.copy()
    env.update(
        SRC=str(ASSETS),
        OUT=str(output),
        MANIFEST=str(manifest),
        README=str(tmp_path / "README.md"),
    )

    result = subprocess.run(
        ["bash", str(SELECTOR)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (output / "coachella_press_1.webp").read_bytes() == (
        ASSETS / "guided-press-coachella-2026.webp"
    ).read_bytes()
    assert not (output / "coachella_press_1.jpg").exists()
    assert "coachella_press 1" in manifest.read_text().splitlines()
