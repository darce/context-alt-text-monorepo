from __future__ import annotations

import csv
import os
import shutil
import stat
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTOR = REPO_ROOT / "infra/oci/demo/seed/select-clustering-seed.sh"
GUIDED_SELECTOR = REPO_ROOT / "infra/oci/demo/seed/select-guided-seed.sh"
COMMITTED_README = REPO_ROOT / "infra/oci/demo/seed/README.md"
COMMITTED_RIGHTS = REPO_ROOT / "infra/oci/demo/seed/clustering-rights.tsv"
LEGACY_NOTE = "celebs01 — editorial/fair-use demo (takedown on request)"


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def tiny_png() -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00\xff")
    return (
        signature
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", pixels)
        + png_chunk(b"IEND", b"")
    )


@pytest.mark.parametrize(
    ("case", "basis", "notice", "expected_note"),
    [
        ("defaults", None, None, LEGACY_NOTE),
        (
            "cc_by_attribution",
            "cc_by",
            "attribution_required",
            "celebs01 — CC BY 4.0 demo (attribution required)",
        ),
        ("reject_override", None, None, None),
    ],
)
def test_readme_note_matches_rights_ledger(
    tmp_path: Path,
    case: str,
    basis: str | None,
    notice: str | None,
    expected_note: str | None,
) -> None:
    committed_readme_before = COMMITTED_README.read_bytes()
    committed_rights_before = COMMITTED_RIGHTS.read_bytes()

    src = tmp_path / "src"
    src.mkdir()
    for name in ("ada_lovelace_1.png", "grace_hopper_1.png"):
        image = src / name
        image.write_bytes(tiny_png())
        mime = subprocess.run(
            ["file", "--mime-type", str(image)], capture_output=True, text=True, check=False
        )
        assert mime.returncode == 0, mime.stdout + mime.stderr
        assert mime.stdout.rsplit(": ", 1)[-1].strip() == "image/png"

    readme = tmp_path / "README.md"
    shutil.copyfile(COMMITTED_README, readme)
    out = tmp_path / "media"
    manifest = tmp_path / "manifest.txt"
    rights = tmp_path / "rights.tsv"

    env = os.environ.copy()
    for name in (
        "SRC",
        "PERSONS",
        "PER_PERSON",
        "OUT",
        "MANIFEST",
        "README",
        "RIGHTS",
        "BASIS",
        "SOURCE",
        "NOTICE",
        "LICENSE_NOTE",
        "ADDED",
    ):
        env.pop(name, None)
    env.update(
        {
            "SRC": str(src),
            "PERSONS": "2",
            "PER_PERSON": "1",
            "OUT": str(out),
            "MANIFEST": str(manifest),
            "README": str(readme),
            "RIGHTS": str(rights),
        }
    )
    if basis is not None:
        env["BASIS"] = basis
    if notice is not None:
        env["NOTICE"] = notice
    if case == "reject_override":
        env["LICENSE_NOTE"] = "x"

    try:
        result = subprocess.run(
            ["bash", str(SELECTOR)], capture_output=True, text=True, env=env, check=False
        )
    finally:
        assert COMMITTED_README.read_bytes() == committed_readme_before
        assert COMMITTED_RIGHTS.read_bytes() == committed_rights_before

    if case == "reject_override":
        assert result.returncode == 2, result.stdout + result.stderr
        assert "LICENSE_NOTE is derived from BASIS, SOURCE and NOTICE" in result.stderr
        assert not out.exists()
        assert not manifest.exists()
        assert not rights.exists()
        assert readme.read_bytes() == committed_readme_before
        return

    assert result.returncode == 0, result.stdout + result.stderr
    readme_rows = [
        line for line in readme.read_text().splitlines() if line.startswith("| ") and ".png |" in line
    ]
    assert len(readme_rows) == 2
    assert all(row.split("|")[3].strip() == expected_note for row in readme_rows)

    with rights.open(newline="") as handle:
        ledger_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(ledger_rows) == 2
    assert stat.S_IMODE(rights.stat().st_mode) == 0o644
    expected_basis = basis or "editorial_fair_use"
    expected_notice = notice or "takedown_on_request"
    for row in ledger_rows:
        assert row["basis"] == expected_basis
        assert row["source"] == "celebs01"
        assert row["notice"] == expected_notice


@pytest.mark.parametrize("selector_name", ["clustering", "guided"])
def test_invalid_added_date_is_rejected_before_outputs_change(
    tmp_path: Path, selector_name: str
) -> None:
    selector = SELECTOR if selector_name == "clustering" else GUIDED_SELECTOR
    src = tmp_path / "src"
    src.mkdir()
    if selector_name == "clustering":
        for name in ("ada_lovelace_1.png", "grace_hopper_1.png"):
            (src / name).write_bytes(tiny_png())
    else:
        for name in (
            "guided-katy-perry-2026.jpg",
            "guided-katy-perry-2019.jpg",
            "guided-katy-perry-2016.jpg",
            "guided-justin-trudeau-2025.jpg",
            "guided-justin-trudeau-2023.jpg",
            "guided-press-tribeca-2026.jpg",
        ):
            (src / name).write_bytes(bytes((255, 216, 255, 219)))
        (src / "guided-press-coachella-2026.webp").write_bytes(b"RIFF\x04\x00\x00\x00WEBP")

    out = tmp_path / "media"
    out.mkdir()
    sentinel = out / "keep.txt"
    sentinel.write_text("existing media\n")
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("existing manifest\n")
    rights = tmp_path / "rights.tsv"
    rights.write_text("existing rights\n")
    readme = tmp_path / "README.md"
    shutil.copyfile(COMMITTED_README, readme)
    before = {
        path: path.read_bytes() for path in (sentinel, manifest, rights, readme)
    }

    env = os.environ.copy()
    for name in (
        "SRC",
        "PERSONS",
        "PER_PERSON",
        "OUT",
        "MANIFEST",
        "README",
        "RIGHTS",
        "BASIS",
        "SOURCE",
        "NOTICE",
        "LICENSE_NOTE",
        "ADDED",
    ):
        env.pop(name, None)
    env.update(
        {
            "SRC": str(src),
            "OUT": str(out),
            "MANIFEST": str(manifest),
            "README": str(readme),
            "RIGHTS": str(rights),
            "ADDED": "2026-02-31",
        }
    )
    if selector_name == "clustering":
        env.update({"PERSONS": "2", "PER_PERSON": "1"})

    result = subprocess.run(
        ["bash", str(selector)], capture_output=True, text=True, env=env, check=False
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid ADDED date '2026-02-31'" in result.stderr
    assert {path: path.read_bytes() for path in before} == before
    assert list(out.iterdir()) == [sentinel]
