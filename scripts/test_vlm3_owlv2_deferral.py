from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFERRAL = REPO_ROOT / "docs" / "tasks" / "vlm" / "VLM-3-owlv2-tier-b-deferral.md"

# Installing optional extras (e.g. [vlm] → transformers) must not false-fail
# this guard via vendored owlv2 modules under .venv / node_modules.
_SKIP_DIR_NAMES = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        "site-packages",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".tox",
    }
)
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".pyc", ".so", ".dylib"}


def _iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        yield path


def test_owlv2_tier_b_is_explicitly_gated_on_context_pack_brands() -> None:
    text = DEFERRAL.read_text()

    assert "ContextPack.brands" in text
    assert "E20-BRAND-A" in text
    assert "deferred" in text.lower()
    assert "No production OWLv2 route or worker is enabled" in text
    assert "Slice 6" in text


def test_no_production_owlv2_code_exists_while_deferred() -> None:
    searched_roots = [REPO_ROOT / "apps", REPO_ROOT / "packages"]
    offenders = []
    for root in searched_roots:
        if not root.is_dir():
            continue
        for path in _iter_source_files(root):
            rel = path.relative_to(REPO_ROOT)
            text = path.read_text(errors="ignore").lower()
            if "owlv2" in text or "owl_v2" in text:
                offenders.append(str(rel))

    assert offenders == []
