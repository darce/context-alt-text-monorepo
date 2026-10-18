from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFIER = REPO_ROOT / "infra/oci/demo/tests/verify-clustering-seed.sh"
SELECTOR = REPO_ROOT / "infra/oci/demo/seed/select-guided-seed.sh"
ASSETS = REPO_ROOT / "apps/prototype-wp-alt-context/js/admin/assets/guided"


def verify(seed: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(VERIFIER)],
        env={**os.environ, "SEED_DIR": str(seed), "PERSONS": "1", "PER_PERSON": "1"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    committed_rights = REPO_ROOT / "infra/oci/demo/seed/guided-rights.tsv"
    committed_rights_before = committed_rights.read_bytes()
    (tmp_path / "README.md").write_text(
        "<!-- GUIDED-PROVENANCE:START -->\n<!-- GUIDED-PROVENANCE:END -->\n"
        "| ordinary_1.webp | Ordinary | source | date |\n"
    )
    result = subprocess.run(
        ["bash", str(SELECTOR)],
        env={
            **os.environ,
            "OUT": str(tmp_path / "media"),
            "MANIFEST": str(tmp_path / "guided-manifest.txt"),
            "README": str(tmp_path / "README.md"),
            "RIGHTS": str(tmp_path / "guided-rights.tsv"),
            "ADDED": "2099-01-01",
            "SRC": str(ASSETS),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert committed_rights.read_bytes() == committed_rights_before
    shutil.copyfile(
        ASSETS / "guided-press-coachella-2026.webp",
        tmp_path / "media/ordinary_1.webp",
    )
    (tmp_path / "clustering-manifest.txt").write_text("ordinary 1\n")
    return tmp_path


@pytest.mark.parametrize("extension", ["webp", "WEBP"])
def test_accepts_real_webp_in_ordinary_and_guided_seed(seed: Path, extension: str) -> None:
    for slug in ("ordinary", "coachella_press"):
        (seed / f"media/{slug}_1.webp").rename(seed / f"media/{slug}_1.{extension}")
    readme = seed / "README.md"
    readme.write_text(readme.read_text().replace(".webp", f".{extension}"))
    result = verify(seed)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "8 images = 1 persons x 1 + 7 guided, 8 provenance rows" in result.stdout


@pytest.mark.parametrize("slug", ["ordinary", "coachella_press"])
@pytest.mark.parametrize("extension", ["webp", "jpg"])
def test_rejects_invalid_content(seed: Path, slug: str, extension: str) -> None:
    path = seed / f"media/{slug}_1.webp"
    path.write_text("not an image\n")
    path.rename(seed / f"media/{slug}_1.{extension}")
    result = verify(seed)
    assert result.returncode != 0
    assert "by content" in result.stderr


@pytest.mark.parametrize("damage", ["missing", "extra", "provenance", "manifest"])
def test_preserves_bundle_rules(seed: Path, damage: str) -> None:
    if damage == "missing":
        (seed / "media/coachella_press_1.webp").rename(seed / "media/unrelated_1.webp")
    elif damage == "extra":
        shutil.copyfile(seed / "media/ordinary_1.webp", seed / "media/extra_1.webp")
    elif damage == "provenance":
        readme = seed / "README.md"
        readme.write_text("\n".join(line for line in readme.read_text().splitlines() if "ordinary_1" not in line))
    else:
        (seed / "clustering-manifest.txt").write_text("ordinary 0\n")
    assert verify(seed).returncode != 0


@pytest.mark.parametrize("slug", ["ordinary", "coachella_press"])
def test_rejects_webp_disguised_as_jpeg(seed: Path, slug: str) -> None:
    (seed / f"media/{slug}_1.webp").rename(seed / f"media/{slug}_1.jpg")
    result = verify(seed)
    assert result.returncode != 0
    assert "by content" in result.stderr
