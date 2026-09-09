from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "apps/prototype-wp-alt-context"
SOURCE_ROOT = APP / "js"
DIST_ROOT = APP / "public/assets/dist"
GUIDED_COPY = "Apply and undo"
RETIRED_COPY = "Apply it yourself"


def _source_mtime() -> float:
    newest = 0.0
    for path in SOURCE_ROOT.rglob("*"):
        if path.suffix in {".ts", ".tsx", ".scss", ".js"} and path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return newest


def test_built_bundle_is_not_older_than_admin_sources() -> None:
    if not DIST_ROOT.exists():
        return
    dist_files = [path for path in DIST_ROOT.rglob("*") if path.is_file()]
    if not dist_files:
        return
    newest_dist = max(path.stat().st_mtime for path in dist_files)
    newest_source = _source_mtime()
    assert newest_dist >= newest_source - 1, "admin bundle in public/assets/dist is stale relative to js/ sources"


def test_gitignore_does_not_hide_php_lockfile() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!apps/prototype-wp-alt-context/composer.lock" in gitignore


def test_packaged_zip_does_not_ship_retired_apply_copy() -> None:
    zips = list((APP / "dist").glob("*.zip"))
    if not zips:
        return
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
