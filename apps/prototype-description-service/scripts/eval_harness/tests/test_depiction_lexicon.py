"""VLM6-LEX: canon depiction-lexicon loader contract.

The lexicon-on leg of the bake-off is only interpretable if the injected block
is a faithful projection of the canon rows. Every failure mode here is one that
would otherwise produce a *quiet* wrong measurement: an empty rule set read as
"the lexicon made no difference", a silently dropped family read as a full
run, or a stale sha that cannot be traced back to a canon revision.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from scripts.eval_harness.depiction_lexicon import (
    KNOWN_FAMILIES,
    LexiconError,
    load_depiction_lexicon,
    resolve_lexicon_path,
)

_HEADER = """# Depiction & Description Heuristics Lexicon

| Column | What it holds |
|---|---|
| ID | stable citation key |

"""

_ATTRIB_ROW = (
    '| ATTRIB-01<a name="attrib-01"></a> | Depicted person is grammatical subject | '
    "**Bearer, not the depicted**: pose invites will inference -> state visible cues only -> "
    "blocks false psychology ↔ ux [[HAI-01]](interaction-ux.md#hai-01) | "
    "Is the person grammatical owner of a trait no pixel can confirm? | B·d | "
    "[berger-ways-of-seeing](../SOURCES.md#src-berger-ways-of-seeing) |"
)
_ATTRIB_ROW_2 = (
    '| ATTRIB-05<a name="attrib-05"></a> | Source already decides a name | '
    "**Honor source identity decisions**: record name present -> emit the name and prefer "
    "*enslaved* as the person-noun -> blocks logo-person prose | "
    "Did we rewrite a decision the source made (reordering is [[ATTRIB-09]](depiction.md#attrib-09), not this)? "
    "| S·v | [anti-racist-description-resources](../SOURCES.md#src-anti-racist-description-resources) |"
)
_BOUND_ROW = (
    '| BOUND-04<a name="bound-04"></a> | Degrading undress | '
    "**Refuse restage, refuse erasure**: photograph shows forced pose -> address the injury "
    "without restaging -> neither magnifies nor abandons | "
    "Does this description reenact the humiliation? | J·d | "
    "[azoulay-civil-contract-of-photography](../SOURCES.md#src-azoulay-civil-contract-of-photography) |"
)

_ATTRIB_HEADING = '## 1. ATTRIB: Attribution & identity claims<a name="fam-attrib"></a>\n\n'
_BOUND_HEADING = '## 2. BOUND: Descriptive boundaries<a name="fam-bound"></a>\n\n'


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "depiction.md"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def canon_file(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        _HEADER + _ATTRIB_HEADING + _ATTRIB_ROW + "\n" + _ATTRIB_ROW_2 + "\n\n" + _BOUND_HEADING + _BOUND_ROW + "\n",
    )


def test_parses_every_row_with_family_tier_and_phase(canon_file: Path) -> None:
    lex = load_depiction_lexicon(canon_file, version="test")
    assert [r.rule_id for r in lex.rules] == ["ATTRIB-01", "ATTRIB-05", "BOUND-04"]
    assert [r.family for r in lex.rules] == ["ATTRIB", "ATTRIB", "BOUND"]
    assert [r.tier for r in lex.rules] == ["B", "S", "J"]
    assert [r.phases for r in lex.rules] == [("d",), ("v",), ("d",)]


def test_splits_the_canon_condition_action_consequence_contract(canon_file: Path) -> None:
    rule = load_depiction_lexicon(canon_file, version="test").rules[0]
    assert rule.name == "Bearer, not the depicted"
    assert rule.when == "pose invites will inference"
    assert rule.do == "state visible cues only"
    assert rule.why == "blocks false psychology"
    assert rule.check.startswith("Is the person grammatical owner")


def test_drops_cross_lexicon_tail_but_keeps_in_lexicon_reference(canon_file: Path) -> None:
    lex = load_depiction_lexicon(canon_file, version="test")
    # HAI-01 lives in a lexicon this block does not carry: a model told to honour
    # it would be citing a rule it cannot read.
    assert "HAI-01" not in lex.render()
    # ATTRIB-09 is a row of this same family, so the bare id survives.
    assert "ATTRIB-09" in lex.rules[1].check


def test_render_carries_no_markdown_scaffolding(canon_file: Path) -> None:
    rendered = load_depiction_lexicon(canon_file, version="test").render()
    for scaffold in ("<a name=", "](", "**", "↔", "[["):
        assert scaffold not in rendered, scaffold


def test_brief_detail_drops_the_consequence_clause(canon_file: Path) -> None:
    full = load_depiction_lexicon(canon_file, version="test", detail="full").render()
    brief = load_depiction_lexicon(canon_file, version="test", detail="brief").render()
    assert "blocks false psychology" in full
    assert "blocks false psychology" not in brief
    assert "state visible cues only" in brief
    assert len(brief) < len(full)


def test_family_filter_narrows_the_injected_rules(canon_file: Path) -> None:
    lex = load_depiction_lexicon(canon_file, version="test", families=["bound"])
    assert [r.rule_id for r in lex.rules] == ["BOUND-04"]
    assert lex.families == ("BOUND",)
    assert lex.provenance()["rule_ids"] == ["BOUND-04"]


def test_tier_filter_narrows_the_injected_rules(canon_file: Path) -> None:
    lex = load_depiction_lexicon(canon_file, version="test", tiers=["B", "S"])
    assert [r.rule_id for r in lex.rules] == ["ATTRIB-01", "ATTRIB-05"]
    assert lex.tiers == ("B", "S")


def test_filter_that_selects_nothing_is_an_error_not_an_empty_prompt(canon_file: Path) -> None:
    # An empty addendum would make the lexicon-on leg a duplicate of the
    # baseline and report a delta of zero as though it were a measurement.
    with pytest.raises(LexiconError, match="no rules"):
        load_depiction_lexicon(canon_file, version="test", families=["BOUND"], tiers=["B"])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"families": ["ATTRIB", "WRIT"]}, "unknown lexicon family"),
        ({"tiers": ["B", "X"]}, "unknown lexicon tier"),
        ({"detail": "terse"}, "unknown lexicon detail"),
    ],
)
def test_unknown_selectors_are_rejected(canon_file: Path, kwargs: dict, match: str) -> None:
    with pytest.raises(LexiconError, match=match):
        load_depiction_lexicon(canon_file, version="test", **kwargs)


def test_table_without_rule_rows_refuses_to_inject_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEADER + _ATTRIB_HEADING + "| not | a | rule | row |\n")
    with pytest.raises(LexiconError, match="no rule rows found"):
        load_depiction_lexicon(path, version="test")


def test_row_with_wrong_column_count_is_rejected(tmp_path: Path) -> None:
    truncated = _ATTRIB_ROW.rsplit("|", 2)[0] + "|"
    path = _write(tmp_path, _HEADER + _ATTRIB_HEADING + truncated + "\n")
    with pytest.raises(LexiconError, match="expected 6 columns"):
        load_depiction_lexicon(path, version="test")


def test_row_before_any_family_heading_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _HEADER + _ATTRIB_ROW + "\n")
    with pytest.raises(LexiconError, match="before any family heading"):
        load_depiction_lexicon(path, version="test")


def test_rule_cell_without_the_arrow_contract_is_rejected(tmp_path: Path) -> None:
    broken = _ATTRIB_ROW.replace(
        "pose invites will inference -> state visible cues only -> blocks false psychology",
        "pose invites will inference",
    )
    path = _write(tmp_path, _HEADER + _ATTRIB_HEADING + broken + "\n")
    with pytest.raises(LexiconError, match="condition -> action contract"):
        load_depiction_lexicon(path, version="test")


def test_rule_cell_without_a_bold_name_is_rejected(tmp_path: Path) -> None:
    broken = _ATTRIB_ROW.replace("**Bearer, not the depicted**:", "Bearer, not the depicted:")
    path = _write(tmp_path, _HEADER + _ATTRIB_HEADING + broken + "\n")
    with pytest.raises(LexiconError, match="no ..bold name"):
        load_depiction_lexicon(path, version="test")


def test_unknown_tier_letter_in_the_table_is_rejected(tmp_path: Path) -> None:
    broken = _ATTRIB_ROW.replace("| B·d |", "| Z·d |")
    path = _write(tmp_path, _HEADER + _ATTRIB_HEADING + broken + "\n")
    with pytest.raises(LexiconError, match="unknown tier"):
        load_depiction_lexicon(path, version="test")


def test_provenance_pins_the_exact_file_bytes(canon_file: Path) -> None:
    lex = load_depiction_lexicon(canon_file, version="test")
    prov = lex.provenance()
    assert prov["sha256"] == hashlib.sha256(canon_file.read_bytes()).hexdigest()
    assert prov["rule_count"] == 3
    assert prov["rendered_chars"] == len(lex.render())
    assert prov["version"] == "test"


def test_provenance_sha_moves_when_the_canon_row_changes(canon_file: Path) -> None:
    before = load_depiction_lexicon(canon_file, version="test").provenance()["sha256"]
    canon_file.write_text(canon_file.read_text().replace("blocks false psychology", "blocks bad reads"))
    after = load_depiction_lexicon(canon_file, version="test").provenance()["sha256"]
    assert before != after


def test_directory_argument_resolves_to_the_canon_relpath(tmp_path: Path) -> None:
    (tmp_path / "lexicons").mkdir()
    target = _write(tmp_path / "lexicons", _HEADER + _ATTRIB_HEADING + _ATTRIB_ROW + "\n")
    assert resolve_lexicon_path(tmp_path) == target
    assert load_depiction_lexicon(tmp_path, version="test").rules[0].rule_id == "ATTRIB-01"


def test_missing_lexicon_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(LexiconError, match="not found"):
        load_depiction_lexicon(tmp_path / "absent")


@pytest.mark.skipif(
    not os.environ.get("ACX_HEURISTICS_CANON"),
    reason="ACX_HEURISTICS_CANON not set (canon is a separate private checkout)",
)
def test_real_canon_checkout_parses_both_families() -> None:
    lex = load_depiction_lexicon(os.environ["ACX_HEURISTICS_CANON"])
    assert lex.families == KNOWN_FAMILIES
    assert len(lex.rules) >= 15
    assert lex.version.startswith("canon ")
    assert all(r.when and r.do and r.check for r in lex.rules)
