"""Guard: non-demo backend docs must not point at stale secrets/.env paths.

Every non-demo backend stack (prod, staging, dev, dev-fir) reads exactly one
env file, `/opt/acx-backend/<env>/.env` (regular file, 0600). Deploy rewrites
that path with os.replace, so a `.env -> secrets/.env` symlink does not
survive and `/opt/acx-backend/<env>/secrets/.env` is a stale copy nothing
reads [REF-09]. Operator docs that still name the stale path send people to
a dead file [CARD-07]. Demo is the exception and stays as
`/opt/acx-backend/demo/secrets/.env`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

STALE = re.compile(
    r"/opt/acx-backend/(?:(?:prod|staging|dev|dev-fir|<env>)/)?secrets/\.env"
)

SCAN_ROOTS = (
    "docs/runbooks",
    "infra",
    "apps/prototype-description-service",
    "docs/tasks/15.0/E15-29-public-demo-go-live-task-plan.md",
    ".gitignore",
)

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".example",
    ".sh",
    ".py",
    ".toml",
    ".conf",
    ".service",
    ".ini",
    ".cfg",
}
TEXT_NAMES = {"Makefile", "Caddyfile", "Dockerfile", ".gitignore"}
MAX_BYTES = 1_000_000
SKIP_PARTS = {
    ".git",
    "node_modules",
    "vendor",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}
# Guarded by scripts/test_secrets_inventory_doc.py (sibling lane).
EXCLUDED = frozenset({"apps/prototype-description-service/docs/secrets-inventory.md"})


def _is_text_file(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES


def _relposix(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _git_ls_files() -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--", *SCAN_ROOTS],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [p for p in proc.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _skip_rglob_part(part: str) -> bool:
    return part in SKIP_PARTS or part.startswith(".venv")


def _rglob_fallback() -> list[str]:
    found: list[str] = []
    for root in SCAN_ROOTS:
        candidate = REPO_ROOT / root
        if candidate.is_file():
            found.append(root)
            continue
        if not candidate.is_dir():
            continue
        for path in candidate.rglob("*"):
            if not path.is_file():
                continue
            if any(_skip_rglob_part(part) for part in path.parts):
                continue
            found.append(_relposix(path))
    return found


def _candidate_relpaths() -> list[str]:
    paths = _git_ls_files()
    if not paths:
        paths = _rglob_fallback()
    return paths


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for rel in _candidate_relpaths():
        if rel in EXCLUDED:
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        if not _is_text_file(path):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size >= MAX_BYTES:
            continue
        files.append(path)
    return files


def test_no_stale_backend_secrets_env_refs() -> None:
    hits: list[str] = []
    for path in _iter_scan_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = _relposix(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if STALE.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    assert hits == [], "stale secrets/.env refs:\n" + "\n".join(hits)


@pytest.mark.parametrize(
    ("sample", "should_match"),
    [
        ("/opt/acx-backend/prod/secrets/.env", True),
        ("/opt/acx-backend/staging/secrets/.env", True),
        ("/opt/acx-backend/dev/secrets/.env", True),
        ("/opt/acx-backend/dev-fir/secrets/.env", True),
        ("/opt/acx-backend/<env>/secrets/.env", True),
        ("/opt/acx-backend/secrets/.env", True),
        ("/opt/acx-backend/demo/secrets/.env", False),
        ("/opt/acx-backend/prod/.env", False),
        ("legacy `<env>/secrets/.env`", False),
    ],
)
def test_stale_pattern_catches_each_backend_env(sample: str, should_match: bool) -> None:
    # TEST-15: prove the green can go red — the scanner pattern must catch
    # every non-demo backend env and the bare secrets/.env path, and must
    # leave demo plus live <env>/.env plus prose "legacy <env>/secrets/.env"
    # alone.
    matched = STALE.search(sample) is not None
    assert matched is should_match, (sample, matched, should_match)


def test_scan_scope_is_not_vacuous() -> None:
    files = _iter_scan_files()
    rels = {_relposix(path) for path in files}
    assert len(files) > 50, f"scan returned {len(files)} files; empty scan must fail loudly [CARD-07]"
    assert "docs/runbooks/key-management.md" in rels


def test_prod_admin_token_docs_point_at_vault() -> None:
    key_mgmt = (REPO_ROOT / "docs/runbooks/key-management.md").read_text(
        encoding="utf-8", errors="replace"
    )
    admin_keys = (REPO_ROOT / "docs/runbooks/admin-tenant-keys.md").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "oci_vault" in key_mgmt
    assert "oci_vault" in admin_keys
