"""VLM-2B bake-off fixtures: manifest ground-truth invariants (Slice 1).

The bake-off subset manifest must make insertion rate *measurable*: every
recognition-enabled entry with labeled identities carries those names in the
``context_pack`` text the candidate model actually sees. Policy-disabled and
no-context entries are deliberate traps and are asserted separately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.eval_harness.manifest import GoldenEntry, GoldenManifest, load_manifest

BAKEOFF_MANIFEST = Path(__file__).parent / "seed" / "bakeoff_golden.json"
GOLDEN_MANIFEST = Path(__file__).parent / "seed" / "golden.json"


@pytest.fixture(scope="module")
def manifest() -> GoldenManifest:
    return load_manifest(str(BAKEOFF_MANIFEST))


def _context_text(entry: GoldenEntry) -> str:
    pack = entry.context_pack.model_dump(exclude_none=True)
    return " ".join(str(v) for v in pack.values())


def _insertion_cohort(manifest: GoldenManifest) -> list[GoldenEntry]:
    return [e for e in manifest.entries if e.policy.recognition_enabled and e.present_identities]


def test_manifest_loads_and_is_bakeoff_sized(manifest: GoldenManifest) -> None:
    assert 8 <= len(manifest.entries) <= 12


def test_insertion_cohort_context_packs_carry_every_present_identity(manifest: GoldenManifest) -> None:
    cohort = _insertion_cohort(manifest)
    assert cohort, "bake-off manifest has no insertion-rate cohort; insertion rate is unmeasurable"
    for entry in cohort:
        text = _context_text(entry)
        assert text.strip(), f"{entry.path}: insertion-cohort entry has an empty context pack"
        for name in entry.present_identities:
            assert name in text, f"{entry.path}: injected name {name!r} missing from context_pack text"


def test_must_right_names_are_supplied_in_context(manifest: GoldenManifest) -> None:
    for entry in manifest.entries:
        if not entry.policy.recognition_enabled:
            continue
        text = _context_text(entry)
        for name in entry.must_right:
            assert name in text, (
                f"{entry.path}: must_right {name!r} not supplied in context_pack; "
                "the gate would demand a name the model never saw"
            )


def test_policy_disabled_trap_exists_and_leaks_no_names(manifest: GoldenManifest) -> None:
    disabled = [e for e in manifest.entries if not e.policy.recognition_enabled]
    assert disabled, "bake-off manifest needs at least one policy-disabled trap entry"
    for entry in disabled:
        text = _context_text(entry)
        for name in entry.present_identities:
            assert name not in text, f"{entry.path}: policy-disabled entry leaks {name!r} into context"


def test_no_context_degradation_entry_exists(manifest: GoldenManifest) -> None:
    empty = [e for e in manifest.entries if not _context_text(e).strip()]
    assert empty, "bake-off manifest needs a no-context degradation entry"


def test_rubrics_are_not_vacuous(manifest: GoldenManifest) -> None:
    assert any(e.must_right or e.easy_wrong for e in manifest.entries)


# main golden.json has no rubrics until VLM-2C populates it; that warning is its, not ours
@pytest.mark.filterwarnings("ignore::scripts.eval_harness.manifest.RubricEmptyWarning")
def test_entries_reuse_golden_corpus_images(manifest: GoldenManifest) -> None:
    golden = load_manifest(str(GOLDEN_MANIFEST))
    golden_by_path = {e.path: e.sha256 for e in golden.entries}
    for entry in manifest.entries:
        assert entry.path in golden_by_path, f"{entry.path}: not in golden corpus (new image needs README bootstrap)"
        assert entry.sha256 == golden_by_path[entry.path], f"{entry.path}: sha256 drifted from golden corpus"
