from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "apps/prototype-wp-alt-context"
SOURCE_ROOT = APP / "js"
DIST_ROOT = APP / "public/assets/dist"
PACKAGE_DIST_ROOT = REPO_ROOT / "dist"
LEGACY_PACKAGE_DIST_ROOT = APP / "dist"
GUIDED_COPY = "Apply and undo"
RETIRED_COPY = "Apply it yourself"
FRESHNESS_TOLERANCE_SECONDS = 1
BUNDLE_OPTIONAL_ENV = "ACX_BUNDLE_OPTIONAL"


def _source_mtime() -> float:
    source_files = [
        path for path in SOURCE_ROOT.rglob("*") if path.suffix in {".ts", ".tsx", ".scss", ".js"} and path.is_file()
    ]
    assert source_files, f"no admin source files found under {SOURCE_ROOT}"
    return max(path.stat().st_mtime for path in source_files)


def _package_zips() -> list[Path]:
    roots = (PACKAGE_DIST_ROOT, LEGACY_PACKAGE_DIST_ROOT)
    return sorted(path for root in roots if root.is_dir() for path in root.glob("*.zip"))


def _admin_dist_present(dist_root: Path = DIST_ROOT) -> bool:
    return dist_root.is_dir() and any(path.is_file() for path in dist_root.rglob("*"))


def _bundle_optional() -> bool:
    return os.environ.get(BUNDLE_OPTIONAL_ENV) == "1"


def _require_admin_dist(dist_root: Path = DIST_ROOT) -> None:
    """Fail closed when the built admin bundle is missing unless explicitly optional."""
    if _admin_dist_present(dist_root):
        return
    if _bundle_optional():
        pytest.skip(
            f"admin bundle {dist_root} is absent and {BUNDLE_OPTIONAL_ENV}=1"
        )
    raise AssertionError(
        f"missing admin bundle {dist_root}; set {BUNDLE_OPTIONAL_ENV}=1 if the bundle is not expected"
    )


def _bundle_artifacts() -> list[Path]:
    _require_admin_dist()
    artifacts: list[Path] = []
    dist_files = [path for path in DIST_ROOT.rglob("*") if path.is_file()]
    assert dist_files, f"admin bundle directory is empty: {DIST_ROOT}"
    artifacts.extend(dist_files)
    artifacts.extend(_package_zips())
    return artifacts


def _stale_artifacts(artifacts: list[Path], newest_source: float) -> list[Path]:
    cutoff = newest_source - FRESHNESS_TOLERANCE_SECONDS
    return [path for path in artifacts if path.stat().st_mtime < cutoff]


def _retired_copy_members(archive: Path) -> list[str]:
    retired: list[str] = []
    with zipfile.ZipFile(archive) as handle:
        for name in handle.namelist():
            if not name.endswith((".js", ".css", ".html")):
                continue
            data = handle.read(name).decode("utf-8", errors="ignore")
            if RETIRED_COPY in data:
                retired.append(name)
    return retired


def test_require_admin_dist_accepts_a_present_bundle(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "admin.js").write_text("ok", encoding="utf-8")
    _require_admin_dist(dist)


def test_missing_admin_dist_fails_unless_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BUNDLE_OPTIONAL_ENV, raising=False)
    with pytest.raises(AssertionError, match="missing admin bundle"):
        _require_admin_dist(tmp_path / "missing-dist")


def test_missing_admin_dist_skips_when_optional(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(BUNDLE_OPTIONAL_ENV, "1")
    with pytest.raises(pytest.skip.Exception, match=f"{BUNDLE_OPTIONAL_ENV}=1"):
        _require_admin_dist(tmp_path / "missing-dist")


def test_built_bundle_is_not_older_than_admin_sources() -> None:
    artifacts = _bundle_artifacts()
    newest_source = _source_mtime()
    stale = [str(path.relative_to(REPO_ROOT)) for path in _stale_artifacts(artifacts, newest_source)]
    assert stale == [], f"admin bundle/package artifacts are stale relative to js/ sources: {stale}"


def test_one_stale_bundle_member_is_not_hidden_by_a_fresh_member(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.js"
    stale = tmp_path / "stale.css"
    fresh.write_text("fresh", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    os.utime(fresh, (200, 200))
    os.utime(stale, (100, 100))

    assert _stale_artifacts([fresh, stale], 200) == [stale]


def test_packaged_zip_does_not_ship_retired_apply_copy() -> None:
    zips = _package_zips()
    assert zips, f"missing packaged plugin artifact under {PACKAGE_DIST_ROOT} or {LEGACY_PACKAGE_DIST_ROOT}"
    retired = []
    for archive in zips:
        retired.extend(f"{archive.name}:{name}" for name in _retired_copy_members(archive))
    assert retired == [], f"packaged zip still ships retired guided-UI copy: {retired}"


def test_retired_copy_is_rejected_when_guided_copy_is_also_present(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("assets/admin.js", f"{GUIDED_COPY}; {RETIRED_COPY}")

    assert _retired_copy_members(archive) == ["assets/admin.js"]
