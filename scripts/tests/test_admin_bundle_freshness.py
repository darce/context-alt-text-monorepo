from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "apps/prototype-wp-alt-context"
SOURCE_ROOT = APP / "js"
DIST_ROOT = APP / "public/assets/dist"
PACKAGE_DIST_ROOT = REPO_ROOT / "dist"
LEGACY_PACKAGE_DIST_ROOT = APP / "dist"
GUIDED_COPY = "Apply and undo"
RETIRED_COPY = "Apply it yourself"


def _source_mtime() -> float:
    source_files = [
        path for path in SOURCE_ROOT.rglob("*") if path.suffix in {".ts", ".tsx", ".scss", ".js"} and path.is_file()
    ]
    assert source_files, f"no admin source files found under {SOURCE_ROOT}"
    return max(path.stat().st_mtime for path in source_files)


def _package_zips() -> list[Path]:
    roots = (PACKAGE_DIST_ROOT, LEGACY_PACKAGE_DIST_ROOT)
    return sorted(path for root in roots if root.is_dir() for path in root.glob("*.zip"))


def test_built_bundle_is_not_older_than_admin_sources() -> None:
    if DIST_ROOT.exists():
        dist_files = [path for path in DIST_ROOT.rglob("*") if path.is_file()]
        assert dist_files, f"admin bundle directory is empty: {DIST_ROOT}"
        artifacts = dist_files
    else:
        # The package workflow writes its ZIP at the monorepo root. A checked-in
        # legacy ZIP is accepted for local source snapshots, but no artifact
        # surface may be absent without failing the gate.
        artifacts = _package_zips()
        assert artifacts, (
            f"missing admin bundle {DIST_ROOT} and packaged plugin artifact under "
            f"{PACKAGE_DIST_ROOT} or {LEGACY_PACKAGE_DIST_ROOT}"
        )
    newest_dist = max(path.stat().st_mtime for path in artifacts)
    newest_source = _source_mtime()
    assert newest_dist >= newest_source - 1, "admin bundle/package artifact is stale relative to js/ sources"


def test_packaged_zip_does_not_ship_retired_apply_copy() -> None:
    zips = _package_zips()
    assert zips, f"missing packaged plugin artifact under {PACKAGE_DIST_ROOT} or {LEGACY_PACKAGE_DIST_ROOT}"
    retired = []
    for archive in zips:
        with zipfile.ZipFile(archive) as handle:
            for name in handle.namelist():
                if not name.endswith((".js", ".css", ".html")):
                    continue
                data = handle.read(name).decode("utf-8", errors="ignore")
                if RETIRED_COPY in data and GUIDED_COPY not in data:
                    retired.append(f"{archive.name}:{name}")
    assert retired == [], f"packaged zip still ships retired guided-UI copy: {retired}"
