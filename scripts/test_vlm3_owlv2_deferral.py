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
