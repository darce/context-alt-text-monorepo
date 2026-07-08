from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFERRAL = REPO_ROOT / "docs" / "tasks" / "vlm" / "VLM-3-owlv2-tier-b-deferral.md"


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
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            rel = path.relative_to(REPO_ROOT)
            text = path.read_text(errors="ignore").lower()
            if "owlv2" in text or "owl_v2" in text:
                offenders.append(str(rel))

    assert offenders == []
