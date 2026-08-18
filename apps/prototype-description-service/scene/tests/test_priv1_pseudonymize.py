"""PRIV-1: unit coverage for the pseudonymization scrub.

The script lives at the repo root (``scripts/privacy/``), outside any package,
so it is loaded by path. It had no tests at all: every claim about it rested on
one operator run of `apply`/`verify` against a tree nobody can reconstruct
without the secret mint key, which is exactly the shape of evidence that cannot
be re-checked (CARD-08).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "privacy" / "priv1_pseudonymize.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("priv1_pseudonymize", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pz = _load_module()


def _reset_wordlist():
    loader = getattr(pz, "_load_wordlist", None)
    if loader is not None and hasattr(loader, "cache_clear"):
        loader.cache_clear()


@pytest.fixture(autouse=True)
def _mint_key():
    # Several builders hash through the mint key. Pin a fixed one so alias words
    # are stable across runs without touching the real (untracked) key.
    previous = pz._KEY
    pz._KEY = "t" * 64
    yield
    pz._KEY = previous


@pytest.fixture(autouse=True)
def _test_wordlist(tmp_path, monkeypatch):
    # Tests must not inherit the host wordlist (BR-20/26). An empty or missing
    # /usr/share/dict/words would make every `_Passes` construct raise after
    # the fail-fast, and a full host list would make residue a property of the
    # machine. Invented fixture names are not in this list.
    path = tmp_path / "priv1-unit-wordlist"
    path.write_text("the\na\nof\nrose\nfaith\nivy\nself\nbrook\n", encoding="utf-8")
    monkeypatch.setenv("PRIV1_WORDLIST", str(path))
    _reset_wordlist()
    yield path
    _reset_wordlist()


@pytest.fixture
def mapping() -> dict:
    return {
        "entries": [
            {
                "real_name": "Ryanne Wistmoor",
                "alias": "Amber Falcon",
                "alias_slug": "amber_falcon",
                "original_slug": "ryanne-wistmoor",
                "slug_was_name_derived": True,
                "tokens": 2,
            },
            {
                "real_name": "Calderre Vensk",
                "alias": "Cobalt Harbor",
                "alias_slug": "cobalt_harbor",
                "original_slug": "calderre-vensk",
                "slug_was_name_derived": True,
                "tokens": 2,
            },
        ]
    }


# --- non-personal identities are off limits, PRIV-1-BR-17 -----------------


@pytest.fixture
def shared_token_mapping() -> dict:
    # The personal subject's surname is also the celebrity's surname. This is
    # the shape that silently renamed three real people in the shipped run: the
    # token index is built from personal entries only and cannot tell whose
    # surname it is looking at.
    return {
        "entries": [
            {
                "real_name": "Calderre Vensk",
                "alias": "Cobalt Harbor",
                "alias_slug": "cobalt_harbor",
                "original_slug": "calderre-vensk",
                "slug_was_name_derived": True,
                "tokens": 2,
            }
        ]
    }


_CELEB = [
    {
        "bucket": "celebs",
        "naming": "real_name",
        "name": "Marlow Vensk",
        "slug": "marlow_vensk",
        "primary_of": ["celebs/marlow_vensk_25.webp"],
        "appears_in": ["celebs/marlow_vensk_25.webp"],
    }
]

# Stated empty rather than omitted: `_Passes` otherwise reads the roster
# off disk, and a unit test must not inherit a sampling frame it does not
# own (CARD-11).
_UNIT_NONPERSONAL: list[dict] = []


def test_celebrity_record_survives_a_shared_surname(shared_token_mapping):
    passes = pz._Passes(shared_token_mapping, identities=_CELEB)
    record = '{"name": "Marlow Vensk", "slug": "marlow_vensk", "primary_of": ["celebs/marlow_vensk_25.webp"]}'
    out, _counts, _unresolved = passes.rewrite(record, ".json")
    assert out == record, "a non-personal identity's own name, slug and media path must come back byte-identical"
    assert passes.residue(record, ".json") == {}, "and must not be counted as residue either"


def test_the_personal_subject_sharing_that_surname_is_still_scrubbed(shared_token_mapping):
    # The other half of the pair. Protecting the celebrity by blacklisting the
    # shared token would make this pass -- and leak the subject the scrub exists
    # for -- so both directions have to be asserted together.
    passes = pz._Passes(shared_token_mapping, identities=_CELEB)
    text = '{"name": "Calderre Vensk", "path": "personal/calderre-vensk-04.jpg"}'
    out, _counts, _unresolved = passes.rewrite(text, ".json")
    assert "Calderre" not in out and "calderre" not in out
    assert "Cobalt Harbor" in out and "cobalt_harbor" in out
    assert passes.residue(text, ".json"), "and the checker must see the same thing the rewriter did"


def test_masking_is_load_bearing(shared_token_mapping):
    # Prove the guard can go red: with no protected identities the same input
    # is corrupted, which is exactly what shipped.
    passes = pz._Passes(shared_token_mapping, identities=[])
    record = '{"name": "Marlow Vensk", "slug": "marlow_vensk"}'
    out, _counts, _unresolved = passes.rewrite(record, ".json")
    assert out != record


def test_omitting_identities_reads_the_roster_and_fails_if_absent(mapping, tmp_path, monkeypatch):
    # Defaulting identities to [] would keep every test green with the
    # roster gone, while silently protecting nobody (CARD-11). Production
    # must still read the file and fail loudly when it cannot.
    monkeypatch.setattr(pz, "ROSTER", tmp_path / "no-such-roster.json")
    pz._nonpersonal_identities.cache_clear()
    try:
        with pytest.raises(FileNotFoundError):
            pz._Passes(mapping)
    finally:
        pz._nonpersonal_identities.cache_clear()


# --- _inside_hex_run -------------------------------------------------------


def test_hex_run_guard_refuses_matches_inside_a_digest():
    digest = "4beca0" + "a" * 58
    assert pz._inside_hex_run(digest, 0, 6) is True


def test_hex_run_guard_allows_a_short_hex_looking_word():
    # `dad` is hex-valid but the surrounding run is far below the threshold, so
    # a name that happens to be spelled in hex letters must still be rewritable.
    text = "the dad stood there"
    assert pz._inside_hex_run(text, 4, 7) is False


def test_hex_run_guard_refuses_only_at_the_documented_threshold():
    # Exactly _HEX_RUN_MIN is inside; one character short is not. Without the
    # boundary being asserted, the constant could drift to any value and every
    # other hex test would still pass.
    at = "a" * pz._HEX_RUN_MIN
    below = "a" * (pz._HEX_RUN_MIN - 1)
    assert pz._inside_hex_run(at, 0, 2) is True
    assert pz._inside_hex_run(below, 0, 2) is False


def test_hex_run_guard_ignores_non_hex_matches():
    text = "z" * 40
    assert pz._inside_hex_run(text, 0, 3) is False


# --- concatenated (separator-free) name forms, PRIV-1-BR-08 ----------------


def test_concatenated_name_is_rewritten(mapping):
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    text = "2026/07/ryannewistmoor-1721_9988776655.jpg"
    out, counts, _unresolved = passes.rewrite(text, ".json")
    assert "ryannewistmoor" not in out.lower()
    assert "amberfalcon" in out.lower()
    assert counts["concat"] == 1


def test_concatenated_name_is_reported_as_residue(mapping):
    # verify and apply must agree: a class the rewriter fixes but the checker
    # cannot see is how "0 residue" was reported over 379 live occurrences.
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    assert passes.residue("2026/07/ryannewistmoor-1721_9988.jpg", ".json").get("concat") == 1


def test_concatenated_pass_preserves_case_shape(mapping):
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    out, _counts, _u = passes.rewrite("RYANNEWISTMOOR and Ryannewistmoor", ".md")
    assert "AMBERFALCON" in out
    assert "AmberFalcon" in out, "mixed case must fall back to the alias's own casing"


def test_concatenated_pass_reaches_embedded_alnum_runs(mapping):
    # BR-22 inverted this test. The previous assertions pinned NBL/NBR around
    # the concatenated form -- which is the bug. A handle like
    # `<prefix><first><last>_<id>` is a longer alnum run, and the joined
    # form (>= 8 letters of a real name) is identifying inside it. An
    # anchored-only compile of the same alternation cannot match this
    # fixture; `_inside_hex_run` is now the sha256 protection, proven
    # separately.
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    out, counts, _u = passes.rewrite("xryannewistmoorx and ryannewistmoor9", ".json")
    assert counts["concat"] == 2
    assert "ryannewistmoor" not in out.lower()
    assert "amberfalcon" in out.lower()


def test_concatenated_form_is_built_when_the_alias_has_fewer_tokens():
    # A 3-token real name mapped to a 2-token alias. Requiring token-count parity
    # dropped four such identities from the pattern, and an independent oracle
    # then found 8 live occurrences of them that `verify` reported as zero.
    rx, forms, _dropped = pz._concatenated_regex(
        {"entries": [{"real_name": "Ryanne Della Wistmoor", "alias": "Amber Falcon", "tokens": 3}]}
    )
    assert forms == {"ryannedellawistmoor": "AmberFalcon"}
    assert rx.search("ryannedellawistmoor-1721.jpg")


def test_concatenated_builder_refuses_an_entry_with_no_alias():
    # Skipping it would make the checker blind to exactly that name (CARD-07).
    with pytest.raises(SystemExit, match="no alias tokens"):
        pz._concatenated_regex({"entries": [{"real_name": "Ryanne Wistmoor", "alias": "", "tokens": 2}]})


def test_every_eligible_entry_yields_a_concatenated_form():
    entries = [
        {"real_name": "Ryanne Wistmoor", "alias": "Amber Falcon", "tokens": 2},
        {"real_name": "Ryanne Della Wistmoor", "alias": "Cobalt Harbor", "tokens": 3},
        {"real_name": "Al Bo", "alias": "Pewter Coral", "tokens": 2},  # <8: letter-anchored, not dropped
        {"real_name": "Solo", "alias": "Brisk Ember", "tokens": 1},  # single token — still excluded
    ]
    _rx, forms, _dropped = pz._concatenated_regex({"entries": entries})
    # BR-25: eligibility is "2+ tokens", not "2+ tokens AND joined >= 8".
    # The length floor is now a tier (letter-anchor), not a drop. Widening
    # this predicate strengthens the assertion: albo must be present.
    eligible = {
        "".join(e["real_name"].split()).lower()
        for e in entries
        if len(e["real_name"].split()) >= 2
    }
    assert set(forms) == eligible, "an eligible entry was dropped from the pattern"


def test_short_concat_is_letter_anchored_not_dropped():
    # BR-25 inverted this test. The previous assertions pinned
    # `rx is None and forms == {}` for any join under 8 letters — which
    # is the bug. A 4-letter two-token join is now admitted under a
    # letter-only anchor so `@albo ` and `albo09` rewrite, while an
    # in-word collision stays refused. An unanchored compile of `albo`
    # matches `xalbox`; that is the mutant this must still fail.
    rx, forms, _dropped = pz._concatenated_regex(
        {"entries": [{"real_name": "Al Bo", "alias": "Amber Falcon", "tokens": 2}]}
    )
    assert forms == {"albo": "AmberFalcon"}
    assert rx is not None
    assert rx.search("albo09_1.jpg")
    assert rx.search("@albo ")
    assert rx.search("xalbox") is None


# --- embedded concatenated forms, PRIV-1-BR-22 -----------------------------


def test_embedded_concatenated_handle_is_rewritten(mapping):
    # Social-media exports glue firstnamelastname inside a longer handle.
    # NBL/NBR make that occurrence structurally unreachable.
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    joined = "ryannewistmoor"
    text = f"theprefix{joined}_25.webp"
    out, counts, _u = passes.rewrite(text, ".json")
    assert "ryannewistmoor" not in out.lower()
    assert "amberfalcon" in out.lower()
    assert counts["concat"] == 1
    assert passes.residue(text, ".json").get("concat") == 1
    assert passes.residue(out, ".json") == {}


def test_anchored_concat_pattern_misses_an_embedded_handle(mapping):
    # Mutant guard: a concat pass that `return text` would still let the
    # rewrite test above pass if we never showed the fixture is unreachable
    # under the old anchors. Compile the same joined form with NBL/NBR
    # restored -- that is the pre-BR-22 builder -- and the handle must not
    # match.
    joined = "ryannewistmoor"
    fixture = f"theprefix{joined}_25.webp"
    anchored = re.compile(
        r"(?<![A-Za-z0-9])(?:" + re.escape(joined) + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    assert anchored.search(fixture) is None
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    _out, counts, _u = passes.rewrite(fixture, ".json")
    assert counts["concat"] == 1, "live pass must still see the handle the anchors miss"


def test_standalone_concatenated_form_is_still_rewritten(mapping):
    # Unanchoring must not be the only way this pass can fire; a
    # firstnamelastname sitting on a real boundary is the original BR-08
    # case and still has to move.
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    text = "ryannewistmoor-1721.jpg"
    out, counts, _u = passes.rewrite(text, ".json")
    assert counts["concat"] == 1
    assert "amberfalcon" in out.lower()


def test_concatenated_form_inside_a_hex_run_is_left_intact():
    # Unanchoring would otherwise rewrite a sha256 pin whose hex happens
    # to spell a joined name. `_inside_hex_run` is the only remaining
    # guard; prove it fires. "Cade Facade" is constructed so the join is
    # hex-valid, not because anyone is named that.
    mapping = {
        "entries": [
            {
                "real_name": "Cade Facade",
                "alias": "Amber Falcon",
                "alias_slug": "amber_falcon",
                "original_slug": "cade-facade",
                "slug_was_name_derived": True,
                "tokens": 2,
            }
        ]
    }
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    joined = "cadefacade"
    assert all(c in pz._HEX for c in joined)
    text = "aa" + joined + "ffff"
    assert len(text) >= pz._HEX_RUN_MIN
    out, counts, _u = passes.rewrite(text, ".json")
    assert out == text
    assert counts["concat"] == 0
    assert passes.residue(text, ".json") == {}


# --- JSON-escape left boundary, PRIV-1-BR-23 -------------------------------


# Surname is three letters so the given-name pass cannot rewrite it on
# its own. With the shared two-token fixture, "Wistmoor" moves and the
# escape test goes green on a surname substitution -- residue is then
# non-empty for the wrong pass, which is not the finding.
_ESCAPE_MAPPING = {
    "entries": [
        {
            "real_name": "Zyllora Elm",
            "alias": "Amber Falcon",
            "alias_slug": "amber_falcon",
            "original_slug": "zyllora-elm",
            "slug_was_name_derived": True,
            "tokens": 2,
        }
    ]
}


def test_name_after_a_json_escape_is_rewritten():
    # A JSON string body encodes a newline as the two characters
    # backslash + n. NBL over raw source then sees the letter `n`, not
    # a boundary, and both rewrite and residue decline -- verify goes
    # green over live cleartext.
    passes = pz._Passes(_ESCAPE_MAPPING, identities=_UNIT_NONPERSONAL)
    text = '{"note": "lined up\\nZyllora Elm sat down"}'
    out, counts, _u = passes.rewrite(text, ".json")
    assert counts["name"] == 1
    assert "Zyllora Elm" not in out
    assert "Amber Falcon" in out
    # residue runs every pass on the original text, so the given-name
    # builder also sees `Zyllora` once NBL lets it. rewrite consumes the
    # full name first, so the counts are not the same shape -- agreement
    # here is that both sides see the name class, and the output is clean.
    assert passes.residue(text, ".json").get("name") == 1
    assert passes.residue(out, ".json") == {}


def test_name_inside_a_longer_word_is_not_rewritten():
    # The left-boundary widening is only for JSON escapes. Dropping NBL
    # entirely would rewrite this too, and would pass the escape test
    # while corrupting ordinary words.
    passes = pz._Passes(_ESCAPE_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "the SuperZyllora Elm portrait"
    out, counts, _u = passes.rewrite(text, ".md")
    assert out == text
    assert counts["name"] == 0
    assert passes.residue(text, ".md") == {}


# --- rewrite idempotence ---------------------------------------------------


def test_rewrite_is_idempotent(mapping):
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    text = json.dumps(
        {
            "name": "Ryanne Wistmoor",
            "slug": "ryanne-wistmoor",
            "file": "2026/07/ryannewistmoor-11_22.jpg",
            "other": "Calderre Vensk",
        }
    )
    once, _c1, _u1 = passes.rewrite(text, ".json")
    twice, counts2, _u2 = passes.rewrite(once, ".json")
    assert twice == once, "a second pass changed the text; the scrub is not a fixpoint"
    assert sum(counts2.values()) == 0
    assert passes.residue(once, ".json") == {}


# --- unreadable files, PRIV-1-BR-01 ---------------------------------------


def test_undecodable_file_returns_a_reason_not_an_exception(tmp_path):
    blob = tmp_path / "doc.docx"
    blob.write_bytes(b"PK\x03\x04\xff\xfe\x00binary")
    text, reason = pz._read_or_reason(blob)
    assert text is None
    assert "utf-8" in reason


def test_missing_file_returns_a_reason(tmp_path):
    text, reason = pz._read_or_reason(tmp_path / "gone.md")
    assert text is None and reason


def test_readable_file_round_trips_with_no_reason(tmp_path):
    src = tmp_path / "a.md"
    src.write_text("plain\r\ntext\n", encoding="utf-8")
    text, reason = pz._read_or_reason(src)
    # CRLF must survive: the reader exists to avoid reformatting DOS files.
    assert text == "plain\r\ntext\n" and reason == ""


def test_symlink_is_read_as_its_own_target_not_followed(tmp_path):
    # git stores a symlink (mode 120000) as the target string; that string is the
    # whole of its tracked content. Following the link would make coverage depend
    # on whether an overlay is materialized in this worktree -- which is how seven
    # git-hook links read as FileNotFoundError and looked like a scan gap.
    link = tmp_path / "hook"
    link.symlink_to("../../hooks/git/pre-commit")
    assert not link.exists(), "fixture must be a dangling link"
    text, reason = pz._read_or_reason(link)
    assert text == "../../hooks/git/pre-commit" and reason == ""


def test_symlink_target_is_scanned_for_residue(mapping):
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    assert passes.residue("../shared/ryannewistmoor/hook", ".sh").get("concat") == 1


def _waive(tmp_path, monkeypatch, rel: str, body: bytes, *, pin: str | None = None):
    """Write an in-scope container and waive it under its own (or a wrong) digest."""
    monkeypatch.setattr(pz, "REPO", tmp_path)
    (tmp_path / rel).write_bytes(body)
    digest = pin if pin is not None else hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(pz, "DECLARED_UNSCANNABLE", {rel: (digest, "inspected; cited author")})


def test_declared_waiver_does_not_excuse_an_undeclared_file(tmp_path, monkeypatch):
    _waive(tmp_path, monkeypatch, "a.docx", b"PK\x03\x04 opaque")
    declared, undeclared = pz._split_declared([("a.docx", "not utf-8"), ("b.docx", "not utf-8")])
    assert declared == [("a.docx", "not utf-8")]
    assert undeclared == [("b.docx", "not utf-8")], "an undeclared container must still fail the gate"


def test_stale_waiver_is_refused(monkeypatch):
    # The file was renamed or became readable. Leaving the waiver in place reads
    # as coverage while excusing nothing.
    monkeypatch.setattr(pz, "DECLARED_UNSCANNABLE", {"gone.docx": ("00" * 32, "inspected")})
    with pytest.raises(SystemExit, match="did not report as unscannable"):
        pz._split_declared([])


def test_waiver_whose_file_changed_since_inspection_is_refused(tmp_path, monkeypatch):
    # The path still fails to decode -- an OOXML container always will -- so a
    # path-keyed waiver would go on excusing it through an edit that introduces
    # a name nobody reviewed. The pin is what bounds the waiver to the bytes the
    # rationale was written against (CARD-06).
    _waive(tmp_path, monkeypatch, "a.docx", b"PK\x03\x04 edited since", pin="11" * 32)
    with pytest.raises(SystemExit, match="no longer match the files they excuse"):
        pz._split_declared([("a.docx", "not utf-8")])


def test_waiver_matching_its_pin_is_accepted(tmp_path, monkeypatch):
    # Paired with the test above on purpose: a drift check that always raised
    # would satisfy that one alone.
    _waive(tmp_path, monkeypatch, "a.docx", b"PK\x03\x04 as inspected")
    declared, undeclared = pz._split_declared([("a.docx", "not utf-8")])
    assert declared == [("a.docx", "not utf-8")] and undeclared == []


def test_every_shipped_waiver_carries_a_pinned_rationale():
    for rel, (digest, why) in pz.DECLARED_UNSCANNABLE.items():
        assert len(why) > 60, f"{rel} is waived without a reviewable reason"
        assert len(digest) == 64 and set(digest) <= set("0123456789abcdef"), f"{rel} waiver is not pinned to bytes"


# --- roster re-serialization, PRIV-1-BR-02 --------------------------------


def test_json_indent_is_read_from_the_document():
    assert pz._json_indent('{\n "a": 1\n}\n') == 1
    assert pz._json_indent('{\n    "a": 1\n}\n') == 4


def test_json_indent_falls_back_when_the_document_is_flat():
    assert pz._json_indent('{"a": 1}') == 2


def test_reorder_rewrites_the_roster_at_its_own_indent(tmp_path, monkeypatch):
    roster = tmp_path / "corpus.json"
    payload = {
        "identities": [
            {"bucket": "personal", "slug": "zulu", "name": "Z"},
            {"bucket": "personal", "slug": "alfa", "name": "A"},
        ]
    }
    roster.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    monkeypatch.setattr(pz, "ROSTER", roster)
    assert pz._reorder_roster(object()) is True
    after = roster.read_text(encoding="utf-8")
    assert json.loads(after)["identities"][0]["slug"] == "alfa"
    assert '\n "identities"' in after, "roster was re-indented; the reorder diff is now unreviewable"


def test_reorder_is_a_noop_when_already_sorted(tmp_path, monkeypatch):
    roster = tmp_path / "corpus.json"
    payload = {"identities": [{"bucket": "personal", "slug": "alfa", "name": "A"}]}
    original = json.dumps(payload, indent=1) + "\n"
    roster.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pz, "ROSTER", roster)
    assert pz._reorder_roster(object()) is False
    assert roster.read_text(encoding="utf-8") == original


# --- digest re-pinning, PRIV-1-BR-03 --------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_repin_reaches_second_order_pins(tmp_path, monkeypatch):
    # a.txt's content changed; b.txt pins a.txt; c.txt pins b.txt. A single
    # pass fixes b and leaves c stale, so the fixpoint loop is what is under
    # test -- not the substitution.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    a, b, c = (tmp_path / n for n in ("a.txt", "b.txt", "c.txt"))
    a.write_text("original", encoding="utf-8")
    b.write_text("pins " + _sha("original") + "\n", encoding="utf-8")
    c.write_text("pins " + _sha("pins " + _sha("original") + "\n") + "\n", encoding="utf-8")
    published = {"a.txt": _sha("original"), "b.txt": pz._sha_file(b), "c.txt": pz._sha_file(c)}
    a.write_text("scrubbed", encoding="utf-8")

    applied = pz._repin_digests(published, [(a, True), (b, True), (c, True)], dry_run=False)

    assert pz._sha_file(a) in b.read_text(encoding="utf-8")
    assert pz._sha_file(b) in c.read_text(encoding="utf-8"), "second-order pin was left stale"
    assert {rel for rel, *_ in applied} == {"a.txt", "b.txt"}


def test_repin_refuses_when_identical_files_diverge(tmp_path, monkeypatch):
    # Two files with identical content share one published digest. If the scrub
    # moves them apart, a pin literal carrying that digest has two correct
    # replacements; guessing one silently mis-pins the other.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    a, b = (tmp_path / n for n in ("a.txt", "b.txt"))
    a.write_text("same", encoding="utf-8")
    b.write_text("same", encoding="utf-8")
    published = {"a.txt": _sha("same"), "b.txt": _sha("same")}
    a.write_text("one", encoding="utf-8")
    b.write_text("two", encoding="utf-8")

    with pytest.raises(SystemExit, match="ambiguous"):
        pz._repin_digests(published, [(a, True), (b, True)], dry_run=False)


def test_repin_tracks_every_file_sharing_a_digest(tmp_path, monkeypatch):
    # Same starting digest, same ending digest: not ambiguous, but both rels
    # must be re-published or the next round re-detects the stale one forever.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    a, b = (tmp_path / n for n in ("a.txt", "b.txt"))
    for path in (a, b):
        path.write_text("same", encoding="utf-8")
    published = {"a.txt": _sha("same"), "b.txt": _sha("same")}
    for path in (a, b):
        path.write_text("moved", encoding="utf-8")

    pz._repin_digests(published, [(a, True), (b, True)], dry_run=False)
    assert published["a.txt"] == published["b.txt"] == _sha("moved")


def test_repin_is_a_noop_on_dry_run(tmp_path, monkeypatch):
    # Asserted against the live call, not against []: a body that always returns
    # [] would satisfy the return value alone, so the same fixture is run twice
    # and the two outcomes must differ. Dry-run must leave both the file and the
    # pin table untouched; the real run must move the pin.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / "data.txt"
    data.write_text("changed", encoding="utf-8")
    pin = tmp_path / "pin.md"
    stale = f"sha256: {_sha('original')}\n"
    pin.write_text(stale, encoding="utf-8")
    files = [(data, True), (pin, True)]

    dry = {"data.txt": _sha("original")}
    assert pz._repin_digests(dry, files, dry_run=True) == []
    assert pin.read_text(encoding="utf-8") == stale, "dry-run must not touch the file"
    assert dry == {"data.txt": _sha("original")}, "dry-run must not touch the pin table"

    wet = {"data.txt": _sha("original")}
    assert pz._repin_digests(wet, files, dry_run=False), "the real run must report the re-pin"
    assert pin.read_text(encoding="utf-8") == f"sha256: {_sha('changed')}\n"
    assert wet["data.txt"] == _sha("changed")


# --- alias vocabulary hygiene, PRIV-1-BR-04 -------------------------------


def test_vocab_disjointness_separates_collisions_from_accepted_names():
    # Both directions in one test on purpose. A bare "this call does not raise"
    # test passes against a body of `return`, and a bare "this call raises" test
    # passes against a body that always raises; only the pair discriminates.
    stolen = pz._ADJ[0].capitalize()
    with pytest.raises(SystemExit, match="alias vocabulary collides"):
        pz._assert_vocab_disjoint_from_roster([{"name": f"{stolen} Vensk", "bucket": "personal"}])

    pz._assert_vocab_disjoint_from_roster([{"name": "Ryanne Wistmoor", "bucket": "personal"}])

    # A wholly alias-shaped name is a previous run's output; `_looks_pseudonymized`
    # owns that case and reports it with the right remedy.
    alias = f"{pz._ADJ[0].capitalize()} {pz._NOUN[0].capitalize()}"
    pz._assert_vocab_disjoint_from_roster([{"name": alias, "bucket": "personal"}])


# --- short concatenated forms, PRIV-1-BR-25 --------------------------------


# Joined length is 7. Neither token is given-name-eligible on its own
# inside the joined run (the 4-letter surname sits after a letter), so
# concat is the only pass that can see these fixtures. Invented name;
# not a real person.
_SHORT_JOINED = "wynkett"
_SHORT_CONCAT_MAPPING = {
    "entries": [
        {
            "real_name": "Wyn Kett",
            "alias": "Amber Falcon",
            "alias_slug": "amber_falcon",
            "original_slug": "wyn-kett",
            "slug_was_name_derived": True,
            "tokens": 2,
        }
    ]
}


def test_seven_char_concat_digit_adjacent_is_rewritten():
    # Leak shape 1: media filename stem. Left neighbour is start-of-string
    # (or `/` / `"`); right neighbour is a digit. NBR rejects the digit,
    # which is why the old anchors could not have caught this either.
    assert len(_SHORT_JOINED) == 7
    passes = pz._Passes(_SHORT_CONCAT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = f"{_SHORT_JOINED}09_123456_1.jpg"
    out, counts, _u = passes.rewrite(text, ".json")
    assert counts["concat"] == 1
    assert _SHORT_JOINED not in out.lower()
    assert "amberfalcon" in out.lower()
    assert passes.residue(out, ".json") == {}


def test_seven_char_concat_at_handle_is_rewritten():
    # Leak shape 2: social handle in caption free-text. Left neighbour
    # is `@`; right neighbour is a space or `"`.
    passes = pz._Passes(_SHORT_CONCAT_MAPPING, identities=_UNIT_NONPERSONAL)
    caption = f"the @{_SHORT_JOINED} watermark anchored"
    quoted = f'"..._text": ["@{_SHORT_JOINED}", "pioneer...]'
    out_c, counts_c, _u = passes.rewrite(caption, ".md")
    out_q, counts_q, _u = passes.rewrite(quoted, ".json")
    assert counts_c["concat"] == 1
    assert counts_q["concat"] == 1
    assert _SHORT_JOINED not in out_c.lower()
    assert _SHORT_JOINED not in out_q.lower()
    assert "amberfalcon" in out_c.lower() and "amberfalcon" in out_q.lower()
    assert passes.residue(out_c, ".md") == {}
    assert passes.residue(out_q, ".json") == {}


def test_seven_char_concat_inside_a_letter_run_is_left_alone():
    # The floor's whole purpose: a short join inside a longer letter
    # run must not be rewritten. Dropping the tier and unanchoring
    # everything would pass both leak-shape tests and fail this one.
    passes = pz._Passes(_SHORT_CONCAT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = f"super{_SHORT_JOINED}portrait"
    out, counts, _u = passes.rewrite(text, ".md")
    assert out == text
    assert counts["concat"] == 0
    assert passes.residue(text, ".md") == {}


def test_unanchored_seven_char_form_hits_an_in_word_collision():
    # Mutant guard: an unanchored compile of the 7-char form matches
    # the letter-run fixture the live pass must refuse. If this search
    # is None, the fixture is not a collision and the negative test
    # above cannot go red.
    fixture = f"super{_SHORT_JOINED}portrait"
    unanchored = re.compile(re.escape(_SHORT_JOINED), re.IGNORECASE)
    assert unanchored.search(fixture) is not None
    passes = pz._Passes(_SHORT_CONCAT_MAPPING, identities=_UNIT_NONPERSONAL)
    _out, counts, _u = passes.rewrite(fixture, ".md")
    assert counts["concat"] == 0, "live pass must still refuse the in-word collision"


def test_seven_char_concat_inside_a_hex_run_is_left_intact():
    # "Abe Deca" is constructed so the 7-char join is hex-valid, not
    # because anyone is named that. Neighbours are *digits*: letter
    # hex padding (`aa`/`ffff`) is itself a letter, so the new
    # letter-only anchor would refuse before `_inside_hex_run` ran
    # and the guard would not be what this test is proving.
    mapping = {
        "entries": [
            {
                "real_name": "Abe Deca",
                "alias": "Amber Falcon",
                "alias_slug": "amber_falcon",
                "original_slug": "abe-deca",
                "slug_was_name_derived": True,
                "tokens": 2,
            }
        ]
    }
    passes = pz._Passes(mapping, identities=_UNIT_NONPERSONAL)
    joined = "abedeca"
    assert len(joined) == 7
    assert all(c in pz._HEX for c in joined)
    text = "0" + joined + "0" * 8
    assert len(text) >= pz._HEX_RUN_MIN
    out, counts, _u = passes.rewrite(text, ".json")
    assert out == text
    assert counts["concat"] == 0
    assert passes.residue(text, ".json") == {}


def test_seven_char_concat_is_visible_to_residue():
    # The finding: verify printed 0 files / 0 occ because residue()
    # built its pattern from the same floor-gated function. This
    # assertion is red on the unfixed builder. If it is green before
    # the two-tier change, the fix is not what closed the gap.
    passes = pz._Passes(_SHORT_CONCAT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = f"{_SHORT_JOINED}09_123456_1.jpg"
    assert passes.residue(text, ".json").get("concat") == 1


def test_concat_exclusions_are_single_token_only():
    entries = [
        {"real_name": "Ryanne Wistmoor", "alias": "Amber Falcon", "tokens": 2},
        {"real_name": "Wyn Kett", "alias": "Cobalt Harbor", "tokens": 2},
        {"real_name": "Solo", "alias": "Brisk Ember", "tokens": 1},
    ]
    _rx, forms, dropped = pz._concatenated_regex({"entries": entries})
    assert set(forms) == {"ryannewistmoor", "wynkett"}
    assert len(dropped) == 1
    assert dropped[0]["reason"] == "single-token name; no concatenation exists"
    assert dropped[0]["tokens"] == 1


def test_concat_exclusion_line_reports_zero_as_a_measurement():
    # A silent 0 is not a measurement. The formatter must name the
    # class even when nothing was dropped.
    empty = pz._concat_exclusion_line(())
    assert empty == "concat exclusions: 0 dropped"
    one = pz._concat_exclusion_line(
        ({"reason": "single-token name; no concatenation exists", "tokens": 1, "joined_length": 4},)
    )
    assert one == (
        "concat exclusions: 1 dropped (1× single-token name; no concatenation exists)"
    )


def test_apply_and_verify_both_emit_concat_exclusions():
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    verify_src = src[src.index("def cmd_verify") : src.index("def main")]
    assert "_concat_exclusion_line" in apply_src
    assert "_concat_exclusion_line" in verify_src


# --- PRIV-1-BR-19: the shipped map must not reuse a real name token as a
# --- pseudonym token ---------------------------------------------------------


def _map(*pairs):
    return {"entries": [{"real_name": r, "alias": a} for r, a in pairs]}


def test_map_vocab_guard_fires_when_an_alias_word_is_also_a_real_name_word():
    # "Coral" is the operator's real given name for one subject and the
    # adjective half of another subject's minted alias. Neither the re-run
    # guard nor the residue scan can tell the two apart, so every downstream
    # check reports clean over a live ambiguity.
    with pytest.raises(SystemExit) as excinfo:
        pz._assert_map_vocab_disjoint(
            _map(("Coral Ashgrove", "Marbled Quarry"), ("Wyn Kett", "Coral Ridgeway"))
        )
    assert "coral (1 alias, 1 real name)" in str(excinfo.value)


def test_map_vocab_guard_is_silent_on_a_disjoint_map():
    pz._assert_map_vocab_disjoint(
        _map(("Coral Ashgrove", "Marbled Quarry"), ("Wyn Kett", "Burnished Ridgeway"))
    )


def test_map_vocab_guard_counts_every_colliding_entry():
    # One offending word carried by two entries is two separate live
    # ambiguities, not one. A guard that reported the word once would
    # understate the repair needed.
    with pytest.raises(SystemExit) as excinfo:
        pz._assert_map_vocab_disjoint(
            _map(
                ("Coral Ashgrove", "Marbled Quarry"),
                ("Wyn Kett", "Coral Ridgeway"),
                ("Ryanne Wistmoor", "Coral Hollow"),
            )
        )
    # Two aliases carry the word but only one real name does. The guard must
    # not collapse them: the repair is two re-mints, not one.
    assert "coral (2 aliases, 1 real name)" in str(excinfo.value)


def test_map_vocab_guard_does_not_read_the_alias_vocabulary(monkeypatch):
    # The measurement must not be derived from the thing being changed.
    # An earlier revision of this guard compared real-name tokens against
    # `_ALIAS_VOCAB`, so editing the offending word out of `_ADJ` silenced it
    # while the minted alias carrying that word stayed on disk -- the same
    # blind-spot shape as the bug it exists to catch (CARD-08). Emptying the
    # vocabulary entirely must not change the verdict: the question is about
    # the shipped artifact, not the current source.
    monkeypatch.setattr(pz, "_ALIAS_VOCAB", set())
    monkeypatch.setattr(pz, "_ADJ", ())
    monkeypatch.setattr(pz, "_NOUN", ())
    with pytest.raises(SystemExit) as excinfo:
        pz._assert_map_vocab_disjoint(_map(("Wyn Kett", "Coral Ridgeway"), ("Coral Ashgrove", "Marbled Quarry")))
    assert "coral (1 alias, 1 real name)" in str(excinfo.value)


def test_map_vocab_guard_matches_whole_tokens_not_substrings():
    # "Coralline" is not "Coral". A substring test would raise on ordinary
    # words and train the operator to bypass the guard.
    pz._assert_map_vocab_disjoint(_map(("Coralline Ashgrove", "Marbled Quarry"), ("Wyn Kett", "Coral Ridgeway")))


def test_apply_and_verify_both_recheck_the_shipped_map_vocabulary():
    # `plan` is the only other caller of a disjointness check, and it cannot
    # run post-apply: it reads the roster, which `apply` has pseudonymized.
    # The two commands that *do* run against a shipped map must carry it.
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    verify_src = src[src.index("def cmd_verify") : src.index("def main")]
    assert "_assert_map_vocab_disjoint" in apply_src
    assert "_assert_map_vocab_disjoint" in verify_src
# --- wordlist fail-fast and pin, PRIV-1-BR-20 + PRIV-1-BR-26 --------------


def test_absent_wordlist_raises_rather_than_widening_given_name(mapping, monkeypatch, tmp_path):
    # The finding: a missing file became an empty exclusion set, so every
    # ordinary-word given name entered the rewrite. Fail closed, and name
    # both the resolved path and the override so an operator can recover.
    missing = tmp_path / "no-such-words"
    monkeypatch.setenv("PRIV1_WORDLIST", str(missing))
    _reset_wordlist()
    with pytest.raises(SystemExit, match="PRIV1_WORDLIST") as exc:
        pz._given_name_regex(mapping)
    assert str(missing) in str(exc.value)


@pytest.mark.parametrize("body", ["", "\n\n  \n"])
def test_empty_wordlist_raises(mapping, monkeypatch, tmp_path, body):
    empty = tmp_path / "empty-words"
    empty.write_text(body, encoding="utf-8")
    monkeypatch.setenv("PRIV1_WORDLIST", str(empty))
    _reset_wordlist()
    with pytest.raises(SystemExit, match="PRIV1_WORDLIST") as exc:
        pz._given_name_regex(mapping)
    assert str(empty) in str(exc.value)


def test_priv1_wordlist_env_is_honoured_and_count_is_printed(mapping, monkeypatch, tmp_path):
    wl = tmp_path / "custom-words"
    wl.write_text("ryanne\ncalderre\n", encoding="utf-8")
    monkeypatch.setenv("PRIV1_WORDLIST", str(wl))
    _reset_wordlist()
    _rx, resolved, _deferred = pz._given_name_regex(mapping)
    assert "ryanne" not in resolved
    assert "calderre" not in resolved
    words, digest, path = pz._load_wordlist()
    assert Path(path) == wl
    assert len(words) == 2
    assert pz._wordlist_line() == f"wordlist: 2 words (sha256 {digest[:12]}..)"


def test_wordlist_sha256_mismatch_fails_verify(monkeypatch, tmp_path):
    wl = tmp_path / "words"
    body = b"alpha\nbeta\n"
    wl.write_bytes(body)
    monkeypatch.setenv("PRIV1_WORDLIST", str(wl))
    _reset_wordlist()
    live = hashlib.sha256(body).hexdigest()
    recorded = "ab" * 32
    with pytest.raises(SystemExit, match="sha256") as exc:
        pz._assert_wordlist_pin({"wordlist": {"path": str(wl), "sha256": recorded, "count": 2}})
    msg = str(exc.value)
    assert live in msg
    assert recorded in msg


def test_map_without_wordlist_block_warns_and_does_not_fail(capsys):
    mapping = {"entries": []}
    pz._assert_wordlist_pin(mapping)
    captured = capsys.readouterr()
    assert "warning" in captured.out.lower()
    assert "wordlist" in captured.out.lower()
    assert "wordlist" not in mapping, "absent means absent (rg-015); do not invent the field"


def test_matching_wordlist_pin_is_silent(monkeypatch, tmp_path, capsys):
    # Pair for the two tests above: a pin check that always raised would
    # satisfy the mismatch test, and one that always warned would satisfy
    # the legacy-map test.
    wl = tmp_path / "words"
    wl.write_text("alpha\n", encoding="utf-8")
    monkeypatch.setenv("PRIV1_WORDLIST", str(wl))
    _reset_wordlist()
    _, digest, path = pz._load_wordlist()
    pz._assert_wordlist_pin({"wordlist": {"path": path, "sha256": digest, "count": 1}})
    assert "warning" not in capsys.readouterr().out.lower()


def test_validate_map_does_not_invent_a_wordlist_block():
    mapping = {
        "schema": "priv1-alias-map/2",
        "key_fingerprint": pz._key_fingerprint(),
        "entries": [
            {
                "real_name": "Zyllora Elm",
                "alias": "Amber Falcon",
                "alias_slug": "amber_falcon",
                "original_slug": "zyllora-elm",
                "tokens": 2,
            }
        ],
    }
    pz._validate_map(mapping)
    assert "wordlist" not in mapping


def test_build_map_records_wordlist_block(tmp_path, monkeypatch):
    roster = tmp_path / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "identities": [
                    {"bucket": "personal", "name": "Zyllora Elm", "slug": "zyllora-elm"},
                    {"bucket": "celebs", "name": "Marlow Vensk", "slug": "marlow_vensk"},
                ]
            }
        ),
        encoding="utf-8",
    )
    # build_map records `roster_source` as a path relative to REPO.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    monkeypatch.setattr(pz, "ROSTER", roster)
    mapping = pz.build_map()
    assert "wordlist" in mapping
    rec = mapping["wordlist"]
    assert set(rec) == {"path", "sha256", "count"}
    assert rec["count"] >= 1
    assert rec["sha256"] == hashlib.sha256(Path(rec["path"]).read_bytes()).hexdigest()


def test_apply_and_verify_emit_wordlist_and_ambiguous_stem_measurements():
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    verify_src = src[src.index("def cmd_verify") : src.index("def main")]
    plan_src = src[src.index("def build_map") : src.index("def load_map")]
    assert "_wordlist_line" in apply_src
    assert "_wordlist_line" in verify_src
    assert "_ambiguous_stem_line" in apply_src
    assert "_ambiguous_stem_line" in verify_src
    # Both commands pin it, not just verify. `apply`'s rewrite decisions read
    # the same wordlist -- the given-name pass excludes dictionary words -- so a
    # list that drifted since `plan` makes apply rewrite a different token set
    # than the map's recorded provenance describes, and nothing downstream can
    # see it: the map still carries the old digest, and verify re-derives its
    # residue pattern from the same drifted list (CARD-08/CARD-11).
    assert "_assert_wordlist_pin" in verify_src
    assert "_assert_wordlist_pin" in apply_src
    assert "wordlist" in plan_src


# --- ambiguous dictionary-word stems, PRIV-1-BR-15 ------------------------


_AMBIGUOUS_STEM_MAPPING = {
    "entries": [
        {
            "real_name": "Zyllora Brook",
            "alias": "Amber Falcon",
            "alias_slug": "amber_falcon",
            "original_slug": "zyllora-brook",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
        {
            "real_name": "Calderre Brook",
            "alias": "Cobalt Harbor",
            "alias_slug": "cobalt_harbor",
            "original_slug": "calderre-brook",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
    ]
}


def test_ambiguous_dictionary_stem_is_reported_as_residue(monkeypatch, tmp_path):
    # One stem token, two identities, and the token is a dictionary word.
    # Media-stem skips it (ambiguous); given-name skips it (wordlist);
    # `_family_words` never sees it. The name stays in the stem and must
    # show up in residue — that is the finding. Rewrite stays a no-op.
    wl = tmp_path / "words"
    wl.write_text("brook\n", encoding="utf-8")
    monkeypatch.setenv("PRIV1_WORDLIST", str(wl))
    _reset_wordlist()
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "photos/brook-pool-04.jpg"
    hits = passes.residue(text, ".md")
    assert hits.get("media_ambiguous", 0) > 0
    assert sum(hits.values()) > 0
    out, counts, unresolved = passes.rewrite(text, ".md")
    assert out == text, "rewrite must still refuse an ambiguous stem"
    assert counts["media"] == 0
    assert "brook" in unresolved


def test_ambiguous_stem_line_is_count_and_reason_never_the_token():
    # CARD-07: a loud guard is worth nothing if the loud path names the
    # token. Zero is a measurement too.
    assert pz._ambiguous_stem_line(0) == (
        "ambiguous media stems: 0 left unresolved (token maps to >1 identity)"
    )
    one = pz._ambiguous_stem_line(1)
    assert one == "ambiguous media stems: 1 left unresolved (token maps to >1 identity)"
    assert "brook" not in one


# --- percent-encoded separators, PRIV-1-BR-21 -----------------------------


# First token is two letters so the given-name pass cannot rewrite it
# on its own. With the shared Ryanne fixture, `ryanne%20wistmoor` is
# rewritten to `amber%20wistmoor` by the bare-token pass — the URL
# separator never fired and the test would go green on the wrong pass.
# `%20` sits against a digit on the surname's left, so NBL also refuses
# `wistmoor` as a bare token. Only the multi-token pass can see this.
_URL_MAPPING = {
    "entries": [
        {
            "real_name": "Al Wistmoor",
            "alias": "Amber Falcon",
            "alias_slug": "amber_falcon",
            "original_slug": "al-wistmoor",
            "slug_was_name_derived": True,
            "tokens": 2,
        }
    ]
}


def test_percent_encoded_space_in_url_is_rewritten():
    passes = pz._Passes(_URL_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "https://example.test/gallery/al%20wistmoor"
    out, counts, _u = passes.rewrite(text, ".md")
    assert "wistmoor" not in out.lower()
    assert "amber%20falcon" in out.lower()
    assert counts["name"] == 1
    assert passes.residue(text, ".md").get("name") == 1
    assert passes.residue(out, ".md") == {}


def test_double_encoded_percent_20_is_left_alone():
    # `%2520` is a different encoding, not a case of `%20`. Out of scope.
    passes = pz._Passes(_URL_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "https://example.test/gallery/al%2520wistmoor"
    out, counts, _u = passes.rewrite(text, ".md")
    assert out == text
    assert counts["name"] == 0
    assert passes.residue(text, ".md") == {}


# --- PRIV-1-BR-28: the %20 separator class must not backtrack exponentially ---


_REDOS_MAPPING = {
    "entries": [
        {
            "real_name": "Ryanne Wistmoor",
            "alias": "Marbled Quarry",
            "alias_slug": "marbled_quarry",
            "original_slug": "ryanne_wistmoor",
            "slug_was_name_derived": True,
            "tokens": 2,
        }
    ]
}


def test_multi_token_separator_has_no_nested_quantifier():
    """A run of ordinary whitespace after a name prefix must not hang the scan.

    The first `%20` fix wrote the separator as `(?:[\\s_\\-]+|%20)+` -- a `+`
    inside an alternation under another `+`. For a run of N separator characters
    that ultimately fails to match, the engine can partition those N characters
    into `[\\s_\\-]+` groups in 2**(N-1) ways and tries all of them. Measured
    growth was 4x per two characters: 0.8ms at 14 spaces, 249ms at 22. A JSON
    manifest indents far past that, which is why `verify` stopped terminating on
    a corpus it had scanned in two minutes the day before.

    Each iteration of the corrected class consumes either exactly one separator
    character or exactly the three characters of `%20`, and no string can be
    split both ways, so the parse is unique and the scan is linear.

    This is asserted on the pattern text rather than on elapsed time. A timing
    assertion cannot fail here: `re.search` runs in C and does not yield to the
    interpreter, so the pathological pattern does not run slowly under a
    deadline -- it never returns, and the test hangs instead of going red. A
    guard that hangs reports nothing (CARD-07). The out-of-process bound below
    is the behavioural half; this is the half that names the defect.
    """
    regex, _by_key = pz._multi_token_regex(_REDOS_MAPPING)
    assert "(?:[\\s_\\-]|%20)+" in regex.pattern
    assert "+|%20)+" not in regex.pattern


def test_multi_token_separator_terminates_on_a_hostile_separator_run():
    # The behavioural half, run out-of-process because the failure mode is
    # non-termination: at 64 separator characters the nested-quantifier form
    # needs on the order of 2**63 steps, so any wall clock a healthy machine can
    # meet separates the two by an astronomical margin and cannot flake.
    import subprocess
    import sys

    probe = (
        "import importlib.util,json,sys\n"
        f"spec=importlib.util.spec_from_file_location('pz', {str(_SCRIPT)!r})\n"
        "m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        f"r,_=m._multi_token_regex(json.loads({json.dumps(json.dumps(_REDOS_MAPPING))}))\n"
        "sys.exit(0 if r.search('Ryanne' + ' '*64 + '!') is None else 3)\n"
    )
    done = subprocess.run([sys.executable, "-c", probe], timeout=60, capture_output=True)
    assert done.returncode == 0, done.stderr.decode()


def test_percent_encoded_separator_still_matches_after_the_redos_fix():
    # The de-nesting must not cost the behaviour BR-21 added.
    regex, _by_key = pz._multi_token_regex(_REDOS_MAPPING)
    for form in ("Ryanne%20Wistmoor", "Ryanne Wistmoor", "Ryanne_Wistmoor", "Ryanne%20 Wistmoor"):
        assert regex.search(form) is not None, form
