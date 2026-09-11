from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
ADMIN_SOURCE_ROOT_ENV = "ACX_ADMIN_SOURCE_ROOT"
ADMIN_DIST_ROOT_ENV = "ACX_ADMIN_DIST_ROOT"
PACKAGE_DIST_ROOT_ENV = "ACX_PACKAGE_DIST_ROOT"
LIVE_FRESHNESS_NODE = "test_built_bundle_is_not_older_than_admin_sources"
LIVE_ZIP_NODE = "test_packaged_zip_does_not_ship_retired_apply_copy"
DEPLOY_ZIP_GLOB = "alt-context-*.zip"


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw) if raw else default


def _source_root() -> Path:
    return _path_from_env(ADMIN_SOURCE_ROOT_ENV, SOURCE_ROOT)


def _dist_root() -> Path:
    return _path_from_env(ADMIN_DIST_ROOT_ENV, DIST_ROOT)


def _package_roots() -> tuple[Path, ...]:
    raw = os.environ.get(PACKAGE_DIST_ROOT_ENV)
    if raw:
        return (Path(raw),)
    return (PACKAGE_DIST_ROOT,)


def _using_override_roots() -> bool:
    return any(
        name in os.environ
        for name in (ADMIN_SOURCE_ROOT_ENV, ADMIN_DIST_ROOT_ENV, PACKAGE_DIST_ROOT_ENV)
    )


def _source_mtime(source_root: Path | None = None) -> float:
    root = source_root or _source_root()
    source_files = [
        path for path in root.rglob("*") if path.suffix in {".ts", ".tsx", ".scss", ".js"} and path.is_file()
    ]
    assert source_files, f"no admin source files found under {root}"
    return max(path.stat().st_mtime for path in source_files)


def _package_zips() -> list[Path]:
    """Zips package-plugin.sh writes (repo-root dist/), never the tracked legacy copy."""
    return sorted(
        path
        for root in _package_roots()
        if root.is_dir()
        for path in root.glob(DEPLOY_ZIP_GLOB)
        if path.is_file()
    )


def _deploy_zip() -> Path | None:
    zips = _package_zips()
    if not zips:
        return None
    return max(zips, key=lambda path: path.stat().st_mtime)


def _admin_dist_present(dist_root: Path | None = None) -> bool:
    root = dist_root if dist_root is not None else _dist_root()
    return root.is_dir() and any(path.is_file() for path in root.rglob("*"))


def _bundle_optional() -> bool:
    return os.environ.get(BUNDLE_OPTIONAL_ENV) == "1"


def _require_admin_dist(dist_root: Path | None = None) -> None:
    """Fail closed when the built admin bundle is missing unless explicitly optional."""
    root = dist_root if dist_root is not None else _dist_root()
    if _admin_dist_present(root):
        return
    if _bundle_optional():
        pytest.skip(f"admin bundle {root} is absent and {BUNDLE_OPTIONAL_ENV}=1")
    raise AssertionError(
        f"missing admin bundle {root}; set {BUNDLE_OPTIONAL_ENV}=1 if the bundle is not expected"
    )


def _manifest_path(dist_root: Path) -> Path:
    primary = dist_root / ".vite" / "manifest.json"
    fallback = dist_root / "manifest.json"
    return primary if primary.is_file() else fallback


def _expected_generated_files(dist_root: Path) -> list[Path]:
    manifest_path = _manifest_path(dist_root)
    if not manifest_path.is_file():
        raise AssertionError(f"missing vite manifest under {dist_root} (.vite/manifest.json or manifest.json)")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise AssertionError(f"vite manifest is empty: {manifest_path}")
    expected = [manifest_path]
    for chunk in payload.values():
        if not isinstance(chunk, dict):
            continue
        file = chunk.get("file")
        if isinstance(file, str) and file:
            expected.append(dist_root / file)
        for css in chunk.get("css") or []:
            if isinstance(css, str) and css:
                expected.append(dist_root / css)
    return expected


def _bundle_artifacts() -> list[Path]:
    dist_root = _dist_root()
    _require_admin_dist(dist_root)
    expected = _expected_generated_files(dist_root)
    missing = [str(path) for path in expected if not path.is_file()]
    assert missing == [], f"missing expected generated files: {missing}"
    dist_files = [path for path in dist_root.rglob("*") if path.is_file()]
    assert dist_files, f"admin bundle directory is empty: {dist_root}"
    deploy_zip = _deploy_zip()
    if deploy_zip is None:
        raise AssertionError(
            f"missing packaged plugin zip {DEPLOY_ZIP_GLOB} under {', '.join(str(root) for root in _package_roots())}"
        )
    return [*dist_files, deploy_zip]


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


def _clean_subprocess_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != BUNDLE_OPTIONAL_ENV}
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _run_pytest(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = _clean_subprocess_env()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-p", "no:cacheprovider", "-q"],
        cwd=str(cwd),
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_zip(path: Path, *, payload: str, mtime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("alt-context/assets/admin.js", payload)
    os.utime(path, (mtime, mtime))
    return path


def _write_bundle_tree(
    root: Path,
    *,
    source_mtime: float,
    artifact_mtimes: dict[str, float],
    zip_mtime: float | None = None,
    write_zip: bool = True,
    write_manifest: bool = True,
    zip_payload: str = GUIDED_COPY,
) -> tuple[Path, Path, Path]:
    source_root = root / "js"
    dist_root = root / "public-dist"
    package_root = root / "packages"
    source_root.mkdir(parents=True)
    dist_root.mkdir(parents=True)
    package_root.mkdir(parents=True)
    source = source_root / "admin.ts"
    source.write_text("export {}\n", encoding="utf-8")
    os.utime(source, (source_mtime, source_mtime))
    for name, mtime in artifact_mtimes.items():
        path = dist_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("bundle\n", encoding="utf-8")
        os.utime(path, (mtime, mtime))
    newest_artifact = max(artifact_mtimes.values()) if artifact_mtimes else source_mtime
    if write_manifest:
        js_files = [name for name in artifact_mtimes if name.endswith(".js")]
        css_files = [name for name in artifact_mtimes if name.endswith(".css")]
        manifest = dist_root / ".vite" / "manifest.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            json.dumps(
                {
                    "js/admin/main.tsx": {
                        "file": js_files[0] if js_files else "admin.js",
                        "css": css_files,
                    }
                }
            ),
            encoding="utf-8",
        )
        os.utime(manifest, (newest_artifact, newest_artifact))
    if write_zip:
        _write_zip(
            package_root / "alt-context-0.0.0.zip",
            payload=zip_payload,
            mtime=newest_artifact if zip_mtime is None else zip_mtime,
        )
    return source_root, dist_root, package_root


def _freshness_override_env(source_root: Path, dist_root: Path, package_root: Path) -> dict[str, str]:
    return {
        ADMIN_SOURCE_ROOT_ENV: str(source_root),
        ADMIN_DIST_ROOT_ENV: str(dist_root),
        PACKAGE_DIST_ROOT_ENV: str(package_root),
    }


def _run_live_freshness(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run_pytest(
        [f"{Path(__file__).resolve()}::{LIVE_FRESHNESS_NODE}"],
        cwd=REPO_ROOT,
        env=env,
    )


def _run_live_zip(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run_pytest(
        [f"{Path(__file__).resolve()}::{LIVE_ZIP_NODE}"],
        cwd=REPO_ROOT,
        env=env,
    )


def test_conftest_collection_does_not_set_optional_bundle_bypass(tmp_path: Path) -> None:
    plugin = tmp_path / "conftest_probe_plugin.py"
    plugin.write_text(
        "import os\n"
        "\n"
        "def pytest_collection_finish(session):\n"
        f"    value = os.environ.get({BUNDLE_OPTIONAL_ENV!r})\n"
        "    if value is not None:\n"
        f"        raise SystemExit({BUNDLE_OPTIONAL_ENV!r} + f' was set to {{value!r}} during collection')\n",
        encoding="utf-8",
    )
    env = {"PYTHONPATH": os.pathsep.join([str(tmp_path), os.environ.get("PYTHONPATH", "")])}
    completed = _run_pytest(
        ["--collect-only", str(Path(__file__).resolve()), "-p", "conftest_probe_plugin"],
        cwd=REPO_ROOT,
        env=env,
    )
    assert completed.returncode == 0, (
        "scripts/tests/conftest.py set ACX_BUNDLE_OPTIONAL during collection; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )


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


def test_default_package_root_is_repo_dist_not_tracked_plugin_dist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PACKAGE_DIST_ROOT_ENV, raising=False)
    assert _package_roots() == (PACKAGE_DIST_ROOT,)
    assert LEGACY_PACKAGE_DIST_ROOT not in _package_roots()


def test_package_zips_ignore_tracked_legacy_plugin_zip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PACKAGE_DIST_ROOT_ENV, raising=False)
    legacy = LEGACY_PACKAGE_DIST_ROOT / "alt-context-0.0.4-e15-11-820752cb.zip"
    assert legacy not in _package_zips()
    assert all(path.parent != LEGACY_PACKAGE_DIST_ROOT for path in _package_zips())


@pytest.mark.live_admin_bundle
def test_built_bundle_is_not_older_than_admin_sources() -> None:
    artifacts = _bundle_artifacts()
    newest_source = _source_mtime()
    stale = [str(path) for path in _stale_artifacts(artifacts, newest_source)]
    assert stale == [], f"admin bundle/package artifacts are stale relative to js/ sources: {stale}"


def test_one_stale_bundle_member_is_not_hidden_by_a_fresh_member(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh.js"
    stale = tmp_path / "stale.css"
    fresh.write_text("fresh", encoding="utf-8")
    stale.write_text("stale", encoding="utf-8")
    os.utime(fresh, (200, 200))
    os.utime(stale, (100, 100))

    assert _stale_artifacts([fresh, stale], 200) == [stale]


def test_stale_bundle_pytest_exits_nonzero(tmp_path: Path) -> None:
    source_mtime = 1_700_000_200
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=source_mtime,
        artifact_mtimes={"admin.js": source_mtime, "admin.css": source_mtime - 60},
    )
    completed = _run_live_freshness(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode != 0, (
        "freshness gate stayed green on a stale sibling artifact; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "stale" in combined.lower()


def test_fresh_bundle_pytest_exits_zero(tmp_path: Path) -> None:
    source_mtime = 1_700_000_200
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=source_mtime,
        artifact_mtimes={"admin.js": source_mtime + 60, "admin.css": source_mtime + 60},
    )
    completed = _run_live_freshness(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode == 0, (
        "freshness gate went red on a fully fresh bundle; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )


def test_missing_bundle_pytest_exits_nonzero(tmp_path: Path) -> None:
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=1_700_000_200,
        artifact_mtimes={"admin.js": 1_700_000_200},
    )
    shutil.rmtree(dist_root)
    completed = _run_live_freshness(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode != 0, (
        "freshness gate stayed green on a missing admin bundle; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "missing admin bundle" in combined


def test_missing_manifest_member_pytest_exits_nonzero(tmp_path: Path) -> None:
    source_mtime = 1_700_000_200
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=source_mtime,
        artifact_mtimes={"admin.js": source_mtime + 60, "admin.css": source_mtime + 60},
    )
    (dist_root / "admin.css").unlink()
    completed = _run_live_freshness(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode != 0, (
        "freshness gate stayed green when a manifest member was missing; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "missing expected generated files" in combined


def test_missing_deploy_zip_pytest_exits_nonzero(tmp_path: Path) -> None:
    source_mtime = 1_700_000_200
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=source_mtime,
        artifact_mtimes={"admin.js": source_mtime + 60, "admin.css": source_mtime + 60},
        write_zip=False,
    )
    completed = _run_live_freshness(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode != 0, (
        "freshness gate stayed green when the deploy zip was missing; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "missing packaged plugin zip" in combined


def test_stale_deploy_zip_is_not_hidden_by_fresh_dist(tmp_path: Path) -> None:
    source_mtime = 1_700_000_200
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=source_mtime,
        artifact_mtimes={"admin.js": source_mtime + 60, "admin.css": source_mtime + 60},
        zip_mtime=source_mtime - 60,
    )
    completed = _run_live_freshness(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode != 0, (
        "freshness gate stayed green on a stale deploy zip hidden by fresh dist files; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "stale" in combined.lower()


@pytest.mark.live_admin_bundle
def test_packaged_zip_does_not_ship_retired_apply_copy() -> None:
    zips = _package_zips()
    assert zips, f"missing packaged plugin artifact under {PACKAGE_DIST_ROOT}"
    retired = []
    for archive in zips:
        retired.extend(f"{archive.name}:{name}" for name in _retired_copy_members(archive))
    assert retired == [], f"packaged zip still ships retired guided-UI copy: {retired}"


def test_retired_copy_is_rejected_when_guided_copy_is_also_present(tmp_path: Path) -> None:
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("assets/admin.js", f"{GUIDED_COPY}; {RETIRED_COPY}")

    assert _retired_copy_members(archive) == ["assets/admin.js"]


def test_deploy_zip_with_retired_copy_pytest_exits_nonzero(tmp_path: Path) -> None:
    source_mtime = 1_700_000_200
    source_root, dist_root, package_root = _write_bundle_tree(
        tmp_path,
        source_mtime=source_mtime,
        artifact_mtimes={"admin.js": source_mtime + 60, "admin.css": source_mtime + 60},
        zip_payload=f"{GUIDED_COPY}; {RETIRED_COPY}",
    )
    completed = _run_live_zip(_freshness_override_env(source_root, dist_root, package_root))
    assert completed.returncode != 0, (
        "retired-copy zip gate stayed green; "
        f"stdout={completed.stdout!r}; stderr={completed.stderr!r}"
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "retired" in combined.lower()
