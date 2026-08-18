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
        {"real_name": "Al Bo", "alias": "Pewter Zyrelle", "tokens": 2},  # <8: letter-anchored, not dropped
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
    # "Zyrelle" is the operator's real given name for one subject and the
    # adjective half of another subject's minted alias. Neither the re-run
    # guard nor the residue scan can tell the two apart, so every downstream
    # check reports clean over a live ambiguity.
    with pytest.raises(SystemExit) as excinfo:
        pz._assert_map_vocab_disjoint(
            _map(("Zyrelle Ashgrove", "Marbled Quarry"), ("Wyn Kett", "Zyrelle Ridgeway"))
        )
    assert "zyrelle (1 alias, 1 real name)" in str(excinfo.value)


def test_map_vocab_guard_is_silent_on_a_disjoint_map():
    pz._assert_map_vocab_disjoint(
        _map(("Zyrelle Ashgrove", "Marbled Quarry"), ("Wyn Kett", "Burnished Ridgeway"))
    )


def test_map_vocab_guard_counts_every_colliding_entry():
    # One offending word carried by two entries is two separate live
    # ambiguities, not one. A guard that reported the word once would
    # understate the repair needed.
    with pytest.raises(SystemExit) as excinfo:
        pz._assert_map_vocab_disjoint(
            _map(
                ("Zyrelle Ashgrove", "Marbled Quarry"),
                ("Wyn Kett", "Zyrelle Ridgeway"),
                ("Ryanne Wistmoor", "Zyrelle Hollow"),
            )
        )
    # Two aliases carry the word but only one real name does. The guard must
    # not collapse them: the repair is two re-mints, not one.
    assert "zyrelle (2 aliases, 1 real name)" in str(excinfo.value)


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
        pz._assert_map_vocab_disjoint(_map(("Wyn Kett", "Zyrelle Ridgeway"), ("Zyrelle Ashgrove", "Marbled Quarry")))
    assert "zyrelle (1 alias, 1 real name)" in str(excinfo.value)


def test_map_vocab_guard_matches_whole_tokens_not_substrings():
    # "Coralline" is not "Zyrelle". A substring test would raise on ordinary
    # words and train the operator to bypass the guard.
    pz._assert_map_vocab_disjoint(_map(("Coralline Ashgrove", "Marbled Quarry"), ("Wyn Kett", "Zyrelle Ridgeway")))


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


def test_ambiguous_dictionary_stem_is_rewritten_with_a_family_word(monkeypatch, tmp_path):
    # BR-15 measured this leak as residue and asserted rewrite is a no-op.
    # Those assertions *are* the finding: there was no repair path. BR-29
    # is the repair. The no-op / media_ambiguous assertions cannot survive
    # it; the residue measurement moves to a stem that still has no
    # replacement (test_unresolved_keeps_its_meaning_when_no_family_word).
    # `brook` stays in the wordlist so given-name cannot steal this.
    wl = tmp_path / "words"
    wl.write_text("brook\n", encoding="utf-8")
    monkeypatch.setenv("PRIV1_WORDLIST", str(wl))
    _reset_wordlist()
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "photos/brook-pool-04.jpg"
    expected = pz._family_words({"brook": {"Falcon", "Harbor"}})["brook"]
    out, counts, unresolved = passes.rewrite(text, ".md")
    assert "brook" not in out.lower()
    assert expected in out.lower()
    assert counts["media"] == 1
    assert "brook" not in unresolved
    assert passes.residue(text, ".md").get("media") == 1
    assert "media_ambiguous" not in passes.residue(text, ".md")
    assert passes.residue(out, ".md") == {}


def test_ambiguous_stem_line_is_count_and_reason_never_the_token():
    # CARD-07: a loud guard is worth nothing if the loud path names the
    # token. Zero is a measurement too.
    assert pz._ambiguous_stem_line(0) == (
        "ambiguous media stems: 0 left unresolved (token maps to >1 identity)"
    )
    one = pz._ambiguous_stem_line(1)
    assert one == "ambiguous media stems: 1 left unresolved (token maps to >1 identity)"
    assert "brook" not in one


# --- family-word backstop for ambiguous stems, PRIV-1-BR-29 --------------
#
# Invented names only. `brook` is in the autouse wordlist so the given-name
# pass cannot steal a stem fixture. The family word is whatever
# `_family_words` mints for that token under the pinned test key.


def _family_word_for_brook() -> str:
    return pz._family_words({"brook": {"Falcon", "Harbor"}})["brook"]


# Two identities, three-token winner so the leftover token is not a
# full-name match. `nyl` is three letters (given-name floor is 4) and
# belongs to only one identity, so the family builder will not mint
# for it. Media-stem votes Zyllora (2) over Calderre (1) and then has
# no replacement for `nyl`. That is a genuine unresolved — not the
# dictionary-word leak BR-29 closes.
_UNRESOLVED_STEM_MAPPING = {
    "entries": [
        {
            "real_name": "Zyllora Wistmoor Extra",
            "alias": "Amber Falcon Lantern",
            "alias_slug": "amber_falcon_lantern",
            "original_slug": "zyllora-wistmoor-extra",
            "slug_was_name_derived": True,
            "tokens": 3,
        },
        {
            "real_name": "Calderre Nyl",
            "alias": "Cobalt Harbor",
            "alias_slug": "cobalt_harbor",
            "original_slug": "calderre-nyl",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
    ]
}


# Shared token, same positional alias word. Media-stem already has one
# replacement; the family builder must not mint a second one, and must
# count the refusal.
_ONE_ALIAS_STEM_MAPPING = {
    "entries": [
        {
            "real_name": "Zyllora Brook",
            "alias": "Amber Harbor",
            "alias_slug": "amber_harbor",
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


# Shared surname that is NOT a dictionary word. Both `_family_words`
# (via given-name) and `_ambiguous_family_words` must mint the same noun.
_RARE_SHARED_MAPPING = {
    "entries": [
        {
            "real_name": "Zyllora Kettwood",
            "alias": "Amber Falcon",
            "alias_slug": "amber_falcon",
            "original_slug": "zyllora-kettwood",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
        {
            "real_name": "Calderre Kettwood",
            "alias": "Cobalt Harbor",
            "alias_slug": "cobalt_harbor",
            "original_slug": "calderre-kettwood",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
    ]
}


def test_ambiguous_stem_family_word_matches_family_words_mint():
    # Same token, same mint (`family#` + token → `_NOUN`). Two different
    # words for one token would be a new inconsistency.
    index = pz._token_index(_AMBIGUOUS_STEM_MAPPING)
    family, _dropped = pz._ambiguous_family_words(index)
    assert family["brook"] == _family_word_for_brook()


def test_ambiguous_family_words_is_built_on_passes():
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    assert passes.ambiguous_family["brook"] == _family_word_for_brook()
    assert isinstance(passes.ambiguous_family_dropped, tuple)


def test_rewrite_and_residue_share_the_passes_family_map():
    # CARD-08: mutating the object both methods read must move both.
    # A pass that re-derives the map inside `_media_stem_pass` would
    # ignore this and the two could drift.
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    passes.ambiguous_family = {"brook": "thistle"}
    text = "photos/brook-pool-04.jpg"
    out, counts, unresolved = passes.rewrite(text, ".md")
    assert "thistle" in out.lower()
    assert "brook" not in out.lower()
    assert counts["media"] == 1
    assert "brook" not in unresolved
    hits = passes.residue(text, ".md")
    assert hits.get("media") == 1
    assert "media_ambiguous" not in hits


def test_ambiguous_stem_preserves_case_shape():
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    word = _family_word_for_brook()
    upper, _c, _u = passes.rewrite("photos/BROOK-pool-04.jpg", ".md")
    lower, _c, _u = passes.rewrite("photos/brook-pool-04.jpg", ".md")
    mixed, _c, _u = passes.rewrite("photos/Brook-pool-04.jpg", ".md")
    assert word.upper() in upper
    assert word.lower() in lower
    # `_family_words` stores the noun lowercase; mixed falls through
    # to that stored form, matching `_media_stem_pass`'s existing else.
    assert word in mixed
    assert "BROOK" not in upper
    assert "brook" not in lower
    assert "Brook" not in mixed


def test_family_backstop_does_not_touch_prose():
    # The scoping is the finding. Feeding this token into given_rx
    # would rewrite ordinary English. The family word may only fire
    # inside a filename stem.
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    prose = "the brook by the mill is cold"
    out, counts, _u = passes.rewrite(prose, ".md")
    assert out == prose
    assert counts["media"] == 0
    assert counts["given"] == 0
    mixed = "see photos/brook-pool-04.jpg by the brook"
    out_m, counts_m, _u = passes.rewrite(mixed, ".md")
    assert "photos/" + _family_word_for_brook() + "-pool-04.jpg" in out_m
    assert out_m.endswith("by the brook")
    assert counts_m["media"] == 1
    assert counts_m["given"] == 0


def test_given_name_still_leaves_dictionary_word_brook_alone():
    # The wordlist exclusion in `_given_name_regex` is protecting prose
    # and must not be widened. `brook` is in the unit wordlist.
    _rx, resolved, _deferred = pz._given_name_regex(
        _AMBIGUOUS_STEM_MAPPING, protected_tokens=set()
    )
    assert "brook" not in resolved
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    assert "brook" not in passes.given


def test_unambiguous_stem_still_uses_identity_word_not_family():
    # Voting can still pick a winner. The family word is only the
    # backstop for `len(words) != 1`, not a replacement for the vote.
    # Surname-first so the full-name pass cannot steal the fixture:
    # `zyllora-brook` is a name-pass match; `brook-zyllora` is not.
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    family = _family_word_for_brook()
    text = "photos/brook-zyllora-04.jpg"
    out, counts, unresolved = passes.rewrite(text, ".md")
    assert out.lower() == "photos/falcon-amber-04.jpg"
    assert counts["media"] == 1
    assert "brook" not in unresolved
    if family != "falcon":
        assert family not in out.lower()


def test_unresolved_keeps_its_meaning_when_no_family_word():
    # Do not empty `unresolved` by definition. A leftover token that
    # belongs to a non-winner and is not a shared family token still
    # has no replacement; residue must still name that class (BR-15).
    passes = pz._Passes(_UNRESOLVED_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "photos/zyllora-wistmoor-nyl.jpg"
    out, _counts, unresolved = passes.rewrite(text, ".md")
    assert "nyl" in unresolved
    assert "nyl" in out.lower()
    assert passes.residue(text, ".md").get("media_ambiguous", 0) == 1


def test_shared_token_with_one_alias_word_is_counted_not_minted():
    # Two identities, one positional alias word: media-stem already
    # has a unique replacement. Minting a second word would be a new
    # inconsistency. The builder declines and counts the reason.
    index = pz._token_index(_ONE_ALIAS_STEM_MAPPING)
    family, dropped = pz._ambiguous_family_words(index)
    assert "brook" not in family
    assert any(d["reason"] == "shared token already has one alias word" for d in dropped)
    assert all("brook" not in str(d).lower() for d in dropped), (
        "a dropped record that names the token publishes what the scrub removes"
    )
    passes = pz._Passes(_ONE_ALIAS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    out, counts, unresolved = passes.rewrite("photos/brook-pool-04.jpg", ".md")
    assert "brook" not in out.lower()
    assert "harbor" in out.lower()
    assert counts["media"] == 1
    assert "brook" not in unresolved


def test_rare_shared_surname_gets_the_same_word_in_both_builders():
    # Non-dictionary shared token: given-name's `_family_words` *does*
    # see it. The stem backstop must mint the same noun.
    _rx, resolved, _deferred = pz._given_name_regex(
        _RARE_SHARED_MAPPING, protected_tokens=set()
    )
    index = pz._token_index(_RARE_SHARED_MAPPING)
    family, _dropped = pz._ambiguous_family_words(index)
    assert "kettwood" in resolved
    assert family["kettwood"] == resolved["kettwood"]
    assert family["kettwood"] == pz._family_words({"kettwood": {"Falcon", "Harbor"}})["kettwood"]


def test_ambiguous_family_builder_does_not_read_the_wordlist(monkeypatch):
    # CARD-08 / BR-19: a builder that reads the exclusion list can be
    # silenced by editing the exclusion list. The stem backstop exists
    # *because* the wordlist dropped the token.
    def _boom(*_a, **_k):
        raise AssertionError("ambiguous family builder read the wordlist")

    monkeypatch.setattr(pz, "_load_wordlist", _boom)
    family, dropped = pz._ambiguous_family_words(pz._token_index(_AMBIGUOUS_STEM_MAPPING))
    assert family["brook"] == _family_word_for_brook()
    assert dropped == ()


def test_family_exclusion_line_reports_zero_as_a_measurement():
    empty = pz._ambiguous_family_exclusion_line(())
    assert empty == "ambiguous family exclusions: 0 dropped"
    one = pz._ambiguous_family_exclusion_line(
        ({"reason": "shared token already has one alias word", "identities": 2},)
    )
    assert one == (
        "ambiguous family exclusions: 1 dropped "
        "(1× shared token already has one alias word)"
    )
    assert "brook" not in one.lower()


def test_family_exclusion_line_never_names_the_token():
    line = pz._ambiguous_family_exclusion_line(
        (
            {"reason": "shared token already has one alias word", "identities": 2},
            {"reason": "shared token already has one alias word", "identities": 3},
        )
    )
    assert "brook" not in line.lower()
    assert "kettwood" not in line.lower()
    assert "ambiguous family exclusions:" in line


def test_apply_and_verify_both_emit_family_exclusions():
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    verify_src = src[src.index("def cmd_verify") : src.index("def main")]
    assert "_ambiguous_family_exclusion_line" in apply_src
    assert "_ambiguous_family_exclusion_line" in verify_src


def test_same_stem_gets_the_same_replacement_in_json_and_html():
    # A manifest, an HTML report and a filename all carry the same
    # stem. One `_Passes` object, one family map, one apply. The
    # replacement is a property of the token, not of the file.
    passes = pz._Passes(_AMBIGUOUS_STEM_MAPPING, identities=_UNIT_NONPERSONAL)
    word = _family_word_for_brook()
    manifest = '{"path": "personal/brook-pool-04.jpg"}'
    html = '<img src="reports/brook-pool-04.jpg">'
    run = '{"file": "brook-pool-04.jpg"}'
    out_j, _c, _u = passes.rewrite(manifest, ".json")
    out_h, _c, _u = passes.rewrite(html, ".html")
    out_r, _c, _u = passes.rewrite(run, ".json")
    path = passes.rewrite_path("personal/brook-pool-04.jpg")
    assert f"{word}-pool-04.jpg" in out_j
    assert f"{word}-pool-04.jpg" in out_h
    assert f"{word}-pool-04.jpg" in out_r
    assert path.endswith(f"{word}-pool-04.jpg")
    assert "brook" not in out_j.lower()
    assert "brook" not in out_h.lower()
    assert "brook" not in out_r.lower()
    assert "brook" not in path.lower()


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



# --- dictionary given name beside a minted surname, PRIV-1-BR-27 ----------
#
# `Rose` is in the autouse wordlist, so the given-name pass refuses it on
# purpose. `quarry` is this identity's minted surname, not a real-name
# token. The pair is therefore unreachable to every existing pass: the
# full-name alternation wants `Rose Kettwood`, and a bare `Rose` is an
# ordinary English word. Invented name; not a real person.


_ADJACENT_MAPPING = {
    "entries": [
        {
            "real_name": "Rose Kettwood",
            "alias": "Cobalt Quarry",
            "alias_slug": "cobalt_quarry",
            "original_slug": "rose-kettwood",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
        {
            "real_name": "Wyn Vensley",
            "alias": "Amber Harbor",
            "alias_slug": "amber_harbor",
            "original_slug": "wyn-vensley",
            "slug_was_name_derived": True,
            "tokens": 2,
        },
    ]
}


_SHORT_ADJACENT_MAPPING = {
    "entries": [
        {
            "real_name": "Al Vensley",
            "alias": "Cobalt Quarry",
            "alias_slug": "cobalt_quarry",
            "original_slug": "al-vensley",
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

def test_dictionary_given_name_next_to_minted_surname_is_rewritten():
    # The finding. `Rose` stays in the wordlist so the given-name pass
    # cannot steal this; `quarry` is the minted surname so the full-name
    # pass cannot steal it either. Only an identity-match against the
    # alias map can see the pair.
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "Rose K. quarry sat down"
    out, counts, _u = passes.rewrite(text, ".md")
    assert "Rose" not in out
    assert "Cobalt K. quarry" in out
    assert counts["adjacent"] == 1
    assert passes.residue(text, ".md").get("adjacent") == 1
    assert passes.residue(out, ".md") == {}


def test_dictionary_given_name_next_to_minted_surname_without_period_is_rewritten():
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "Rose K quarry sat down"
    out, counts, _u = passes.rewrite(text, ".md")
    assert "Rose" not in out
    assert "Cobalt K quarry" in out
    assert counts["adjacent"] == 1


def test_dictionary_given_name_directly_beside_minted_surname_is_rewritten():
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "Rose quarry sat down"
    out, counts, _u = passes.rewrite(text, ".md")
    assert "Rose" not in out
    assert "Cobalt quarry" in out
    assert counts["adjacent"] == 1
    assert passes.residue(text, ".md").get("adjacent") == 1
    assert passes.residue(out, ".md") == {}


def test_adjacent_pass_preserves_case_shape():
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    upper, c_u, _u = passes.rewrite("ROSE quarry", ".md")
    lower, c_l, _u = passes.rewrite("rose quarry", ".md")
    assert upper == "COBALT quarry"
    assert lower == "cobalt quarry"
    assert c_u["adjacent"] == 1 and c_l["adjacent"] == 1


def test_one_rewrite_closes_dictionary_given_then_adjacent():
    # Fresh text still has the real surname. given-name rewrites
    # `Kettwood` (unique, not a dictionary word); the new pass must
    # then see `Rose` sitting next to the just-minted surname in the
    # same rewrite() call. If adjacent ran first it would miss.
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "Rose K. Kettwood sat down"
    out, counts, _u = passes.rewrite(text, ".md")
    assert "Rose" not in out
    assert "Kettwood" not in out
    assert "Cobalt K. Quarry" in out
    assert counts["given"] == 1
    assert counts["adjacent"] == 1
    assert passes.residue(out, ".md") == {}


def test_middle_initial_survives_the_adjacent_rewrite():
    # The identity match names the leading token. The initial is not in
    # the alias map and has no replacement, so stripping it would be a
    # mutation the map cannot justify.
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    dotted, _c, _u = passes.rewrite("Rose K. quarry", ".md")
    bare, _c, _u = passes.rewrite("Rose K quarry", ".md")
    assert dotted == "Cobalt K. quarry"
    assert bare == "Cobalt K quarry"


def test_ordinary_english_with_a_non_alias_neighbour_is_left_alone():
    # Not a heuristic: `bush` is not an alias token of the identity
    # that carries `Rose`. The unfixed tree also leaves this alone;
    # a mutant that pairs any real token with any alias-vocab word
    # is what this must still fail.
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "the rose bush sat by the quarry face"
    # `rose bush` must not fire. The trailing `quarry` is a noun in
    # isolation, not adjacent to the given name.
    out, counts, _u = passes.rewrite(text, ".md")
    assert out == text
    assert counts.get("adjacent", 0) == 0
    assert passes.residue(text, ".md") == {}


def test_wrong_identity_alias_does_not_fire():
    # Rose's minted surname is quarry; Wyn's is harbor. Crossing them
    # is not an identity match.
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    crossed = "Rose harbor and Wyn quarry"
    out, counts, _u = passes.rewrite(crossed, ".md")
    assert out == crossed
    assert counts.get("adjacent", 0) == 0
    assert passes.residue(crossed, ".md") == {}


def test_bare_dictionary_given_name_is_still_left_alone():
    # The given-name exclusion is still correct in isolation. Adjacent
    # must not become "rewrite every dictionary given name".
    passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "the rose sat there"
    out, counts, _u = passes.rewrite(text, ".md")
    assert out == text
    assert counts["given"] == 0
    assert counts.get("adjacent", 0) == 0


def test_short_real_token_beside_minted_surname_is_rewritten():
    # No length floor via continue. `Al` is two letters, so the
    # given-name pass cannot steal this (its own floor is 4). An
    # adjacent builder that `continue`s on short tokens leaves `Al`
    # in the clear next to a surname the scrub minted.
    passes = pz._Passes(_SHORT_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    text = "Al quarry sat down"
    out, counts, _u = passes.rewrite(text, ".md")
    assert "Al " not in out
    assert "Cobalt quarry" in out
    assert counts["adjacent"] == 1
    assert passes.residue(text, ".md").get("adjacent") == 1


def test_short_adjacent_pair_is_letter_anchored_not_unanchored():
    # Mutant guard: an unanchored compile of the pair hits the in-word
    # fixture the live pass must refuse. If this search is None, the
    # fixture is not a collision and the negative half cannot go red.
    fixture = "superAl quarryx"
    unanchored = re.compile(r"Al[ \t]+quarry", re.IGNORECASE)
    assert unanchored.search(fixture) is not None
    passes = pz._Passes(_SHORT_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
    out, counts, _u = passes.rewrite(fixture, ".md")
    assert out == fixture
    assert counts.get("adjacent", 0) == 0
    assert passes.residue(fixture, ".md") == {}


def test_adjacent_pairs_are_built_from_the_map_not_the_wordlist(monkeypatch, tmp_path):
    # CARD-08 / BR-19 shape: if the override listed only tokens the
    # wordlist currently excludes, editing `rose` out of the list
    # would drop the pair while `Rose quarry` stayed on disk. Both
    # wordlists are non-empty so the given-name builder still loads.
    for body in ("the\na\nof\nrose\nfaith\n", "the\na\nof\nfaith\n"):
        wl = tmp_path / "adj-words"
        wl.write_text(body, encoding="utf-8")
        monkeypatch.setenv("PRIV1_WORDLIST", str(wl))
        _reset_wordlist()
        passes = pz._Passes(_ADJACENT_MAPPING, identities=_UNIT_NONPERSONAL)
        assert ("rose", "quarry") in passes.adjacent


def test_adjacent_builder_does_not_read_the_wordlist(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("adjacent builder read the wordlist")

    monkeypatch.setattr(pz, "_load_wordlist", _boom)
    rx, pairs, _dropped = pz._adjacent_alias_regex(_ADJACENT_MAPPING)
    assert rx is not None
    assert ("rose", "quarry") in pairs


def test_adjacent_builder_refuses_an_entry_with_no_alias():
    with pytest.raises(SystemExit, match="no alias"):
        pz._adjacent_alias_regex(
            {"entries": [{"real_name": "Rose Kettwood", "alias": "", "tokens": 2}]}
        )


def test_no_positional_alias_is_counted_not_silenced():
    _rx, pairs, dropped = pz._adjacent_alias_regex(
        {
            "entries": [
                {
                    "real_name": "Rose Della Kettwood",
                    "alias": "Cobalt Quarry",
                    "tokens": 3,
                }
            ]
        }
    )
    assert ("rose", "quarry") in pairs
    assert any(d["reason"] == "no positional alias token" for d in dropped)
    # Della has a positional alias (Quarry) so it may pair with Cobalt;
    # Kettwood is the one with nothing to emit.
    assert ("kettwood", "quarry") not in pairs
    assert ("kettwood", "cobalt") not in pairs


def test_single_letter_token_is_counted_not_emitted():
    # `A quarry` is ordinary English if any identity carries a
    # one-letter token. Letter anchors cannot save that — both halves
    # are already whole words. Refuse and count; do not `continue`.
    _rx, pairs, dropped = pz._adjacent_alias_regex(
        {
            "entries": [
                {
                    "real_name": "Rose A Kettwood",
                    "alias": "Cobalt Quarry",
                    "tokens": 3,
                }
            ]
        }
    )
    assert ("a", "quarry") not in pairs
    assert ("a", "cobalt") not in pairs
    assert any(d["reason"].startswith("single-letter token") for d in dropped)
    assert ("rose", "quarry") in pairs


def test_ambiguous_adjacent_pair_is_left_alone_and_counted():
    # Two identities share the given name and the minted noun; the
    # replacements differ. Guessing one is a misattribution.
    _rx, pairs, dropped = pz._adjacent_alias_regex(
        {
            "entries": [
                {"real_name": "Rose Kettwood", "alias": "Cobalt Quarry", "tokens": 2},
                {"real_name": "Rose Vensley", "alias": "Amber Quarry", "tokens": 2},
            ]
        }
    )
    assert ("rose", "quarry") not in pairs
    assert any(d["reason"] == "pair maps to >1 identity" for d in dropped)
    passes = pz._Passes(
        {
            "entries": [
                {
                    "real_name": "Rose Kettwood",
                    "alias": "Cobalt Quarry",
                    "alias_slug": "cobalt_quarry",
                    "original_slug": "rose-kettwood",
                    "tokens": 2,
                },
                {
                    "real_name": "Rose Vensley",
                    "alias": "Amber Quarry",
                    "alias_slug": "amber_quarry",
                    "original_slug": "rose-vensley",
                    "tokens": 2,
                },
            ]
        },
        identities=_UNIT_NONPERSONAL,
    )
    text = "Rose quarry sat down"
    out, counts, _u = passes.rewrite(text, ".md")
    assert out == text
    assert counts.get("adjacent", 0) == 0


def test_adjacent_exclusion_line_reports_zero_as_a_measurement():
    empty = pz._adjacent_exclusion_line(())
    assert empty == "adjacent exclusions: 0 dropped"
    one = pz._adjacent_exclusion_line(
        ({"reason": "no positional alias token", "tokens": 3},)
    )
    assert one == "adjacent exclusions: 1 dropped (1× no positional alias token)"
    assert "rose" not in one.lower()
    assert "kettwood" not in one.lower()


def test_adjacent_exclusion_line_never_names_the_token():
    line = pz._adjacent_exclusion_line(
        (
            {"reason": "single-letter token; letter-anchor cannot separate it from the English article", "tokens": 3},
            {"reason": "pair maps to >1 identity", "tokens": 2},
        )
    )
    assert "rose" not in line.lower()
    assert "quarry" not in line.lower()
    assert "adjacent exclusions:" in line


def test_apply_and_verify_both_emit_adjacent_exclusions():
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    verify_src = src[src.index("def cmd_verify") : src.index("def main")]
    assert "_adjacent_exclusion_line" in apply_src
    assert "_adjacent_exclusion_line" in verify_src


# --- PRIV-1-BR-30: the re-parse must share the match pattern's flags ------
#
# The adjacent pattern is compiled with `re.IGNORECASE`. Under that flag
# `[A-Za-z]` also matches the characters that case-fold into ASCII letters:
# U+017F LATIN SMALL LETTER LONG S folds to `s`, U+212A KELVIN SIGN folds to
# `k`. `_ADJACENT_PARSE` re-parses the text the pattern matched, so if it
# does not carry the same flag the two disagree about what a letter is.
# The consequence is not a missed rewrite, it is a divergence: `rewrite()`
# declines the span while `residue()` still counts it, so `verify` reports
# residue that `apply` can never clear and no counter says why.


def test_adjacent_parse_shares_the_match_pattern_flags():
    assert pz._ADJACENT_PARSE.flags & re.IGNORECASE, (
        "_ADJACENT_PARSE re-parses text matched by an IGNORECASE pattern; "
        "without the flag it rejects case-folding non-ASCII letters the "
        "match accepted."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Roſe quarry sat down",       # long s inside the leading token
        "Rose K. quarry sat down",    # Kelvin sign as the middle initial
    ],
)
def test_case_folding_letters_do_not_split_rewrite_from_residue(text):
    """Whatever `residue()` counts, `rewrite()` must be able to clear."""
    passes = pz._Passes(_ADJACENT_MAPPING, identities=())
    out, counts, _unresolved = passes.rewrite(text, ".md")
    assert counts["adjacent"] == 1, out
    assert passes.residue(out, ".md") == {}


def test_unparseable_adjacent_span_raises_instead_of_passing_through(monkeypatch):
    """A span the replacer cannot resolve is a broken invariant, not a skip.

    Returning `m.group(0)` here would be the silent-`continue` shape this
    file exists to refuse: indistinguishable, at the output, from a name
    that was never there -- except that `residue()` would still count it,
    leaving `verify` permanently non-zero with nothing naming the cause.
    """
    passes = pz._Passes(_ADJACENT_MAPPING, identities=())
    monkeypatch.setattr(pz, "_ADJACENT_PARSE", re.compile(r"^(?!x)x$"))
    with pytest.raises(SystemExit) as excinfo:
        passes.rewrite("Rose K. quarry sat down", ".md")
    message = str(excinfo.value)
    assert "drifted" in message
    # The message must never echo what it refused (one roster token is a
    # media stem; a diagnostic that quotes it publishes what the scrub removed).
    assert "Rose" not in message and "quarry" not in message


def test_unparseable_adjacent_span_reports_non_ascii_codepoints(monkeypatch):
    passes = pz._Passes(_ADJACENT_MAPPING, identities=())
    monkeypatch.setattr(pz, "_ADJACENT_PARSE", re.compile(r"^(?!x)x$"))
    with pytest.raises(SystemExit) as excinfo:
        passes.rewrite("Roſe quarry sat down", ".md")
    assert "U+017F" in str(excinfo.value)


# --- digest pin record, PRIV-1-BR-32 --------------------------------------
#
# `_repin_digests` only runs inside `apply` and its baseline is computed
# in-run. `verify` never looked at pins. An out-of-band rewrite left every
# pin of that file stale, with nothing to detect it against. Invented
# paths only (`nylphra`, `qorvex`, `veldrun`) — not plausible English
# names, and not a roster token paired with a minted alias.


_PIN_SCHEMA = "priv1-digest-pins/1"
_PIN_REL = "apps/nylphra/emitter.py"
_PIN_NOTE = "docs/qorvex-note.md"


def _pin_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pin_record(*pairs: tuple[str, str]) -> dict:
    return {
        "schema": _PIN_SCHEMA,
        "pins": [{"path": rel, "sha256": digest} for rel, digest in pairs],
    }


def _prepare_verify_env(tmp_path, monkeypatch, *, files: dict[str, str], record: dict | None):
    """Minimal private store + roster so `cmd_verify` can run.

    `DECLARED_UNSCANNABLE` and `FREE_TEXT_REDACTIONS` are emptied: both
    fail closed against files this fixture does not own.
    """
    repo = tmp_path / "repo"
    private = tmp_path / "private"
    repo.mkdir()
    private.mkdir()
    roster = repo / "roster.json"
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
    monkeypatch.setattr(pz, "REPO", repo)
    monkeypatch.setattr(pz, "ROSTER", roster)
    monkeypatch.setattr(pz, "PRIVATE", private)
    monkeypatch.setattr(pz, "ALIAS_MAP", private / "priv1-alias-map.json")
    monkeypatch.setattr(pz, "MINT_KEY", private / "priv1-mint-key")
    monkeypatch.setattr(pz, "DECLARED_UNSCANNABLE", {})
    monkeypatch.setattr(pz, "FREE_TEXT_REDACTIONS", ())
    pz.MINT_KEY.write_text(("t" * 64) + "\n", encoding="utf-8")
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
        "wordlist": pz._wordlist_record(),
    }
    pz.ALIAS_MAP.write_text(json.dumps(mapping) + "\n", encoding="utf-8")
    tracked = []
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        tracked.append((path, True))
    monkeypatch.setattr(pz, "_tracked_files", lambda: tracked)
    if record is not None:
        (private / "priv1-digest-pins.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
    pz._nonpersonal_identities.cache_clear()
    return repo, private


def test_out_of_band_rewrite_of_a_recorded_path_is_stale(tmp_path, monkeypatch):
    # The finding, at the helper. Rewrite the pinned file without
    # `_repin_digests`. The record still holds the published digest.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    path = tmp_path / _PIN_REL
    path.parent.mkdir(parents=True)
    path.write_text("payload-one\n", encoding="utf-8")
    pinned = pz._sha_file(path)
    path.write_text("payload-two-out-of-band\n", encoding="utf-8")
    live = pz._sha_file(path)
    assert live != pinned
    stale, missing = pz._check_published_pins(_pin_record((_PIN_REL, pinned)))
    assert missing == []
    assert stale == [(_PIN_REL, pinned, live)]


def test_matching_recorded_digest_is_not_stale(tmp_path, monkeypatch):
    # Pair for the finding test: a checker that always returns stale
    # would satisfy that one alone.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    path = tmp_path / _PIN_REL
    path.parent.mkdir(parents=True)
    path.write_text("payload-one\n", encoding="utf-8")
    pinned = pz._sha_file(path)
    stale, missing = pz._check_published_pins(_pin_record((_PIN_REL, pinned)))
    assert stale == [] and missing == []


def test_recorded_path_that_is_gone_is_missing_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "REPO", tmp_path)
    pinned = "ab" * 32
    stale, missing = pz._check_published_pins(_pin_record(("docs/veldrun-gone.md", pinned)))
    assert stale == []
    assert missing == [("docs/veldrun-gone.md", pinned)]


def test_pin_check_line_reports_zero_as_a_measurement():
    empty = pz._pin_check_line(0, 0, 0)
    assert empty == "digest pins: 0 published; 0 stale; 0 missing"
    one = pz._pin_check_line(4, 1, 2)
    assert one == "digest pins: 4 published; 1 stale; 2 missing"
    assert "nylphra" not in one and "Zyllora" not in one


def test_stale_and_missing_pin_lines_are_path_and_digest_only():
    pinned = "aa" * 32
    live = "bb" * 32
    stale = pz._stale_pin_line(_PIN_REL, pinned, live)
    missing = pz._missing_pin_line("docs/veldrun-gone.md", pinned)
    assert stale == f"STALE-PIN {_PIN_REL} pinned {pinned[:12]}.. found {live[:12]}.."
    assert missing == f"MISSING-PIN docs/veldrun-gone.md pinned {pinned[:12]}.. (path gone)"
    assert "Zyllora" not in stale and "Zyllora" not in missing
    assert "Amber" not in stale and "Falcon" not in missing


def test_pin_record_absent_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "PRIVATE", tmp_path)
    with pytest.raises(SystemExit, match="not found") as exc:
        pz._load_pin_record()
    assert "all pins fine" in str(exc.value) or "publish" in str(exc.value).lower()


def test_pin_record_missing_pins_key_is_refused():
    # Vacuous-pass mutant: defaulting a missing `pins` to [] then
    # reporting 0 stale. An empty list is a measured zero; a missing
    # key is not an empty list (rg-008).
    with pytest.raises(SystemExit, match="pins"):
        pz._validate_pin_record({"schema": _PIN_SCHEMA})
    with pytest.raises(SystemExit, match="pins"):
        pz._check_published_pins({"schema": _PIN_SCHEMA})


def test_pin_record_wrong_schema_is_refused():
    with pytest.raises(SystemExit, match="schema"):
        pz._validate_pin_record({"schema": "priv1-digest-pins/0", "pins": []})


def test_pin_record_entry_missing_required_key_is_refused():
    with pytest.raises(SystemExit, match="sha256"):
        pz._validate_pin_record(
            {"schema": _PIN_SCHEMA, "pins": [{"path": _PIN_REL}]}
        )
    with pytest.raises(SystemExit, match="path"):
        pz._validate_pin_record(
            {"schema": _PIN_SCHEMA, "pins": [{"sha256": "ab" * 32}]}
        )


def test_pin_record_rejects_a_non_digest_and_a_duplicate_path():
    with pytest.raises(SystemExit, match="sha256"):
        pz._validate_pin_record(
            {"schema": _PIN_SCHEMA, "pins": [{"path": _PIN_REL, "sha256": "nope"}]}
        )
    with pytest.raises(SystemExit, match="duplicate"):
        pz._validate_pin_record(
            {
                "schema": _PIN_SCHEMA,
                "pins": [
                    {"path": _PIN_REL, "sha256": "ab" * 32},
                    {"path": _PIN_REL, "sha256": "cd" * 32},
                ],
            }
        )


def test_empty_pin_record_is_a_measured_zero():
    # Empty `pins` is valid only as a written record of "nothing
    # published". It must still produce the zero line, not skip the
    # measurement.
    stale, missing = pz._check_published_pins(_pin_record())
    assert stale == [] and missing == []
    assert pz._pin_check_line(0, 0, 0) == "digest pins: 0 published; 0 stale; 0 missing"


def test_live_pin_targets_finds_a_current_digest_literal(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(f"sha256: {digest}\n", encoding="utf-8")
    published = {
        _PIN_REL: digest,
        _PIN_NOTE: pz._sha_file(note),
    }
    found = pz._live_pin_targets(published, [(data, True), (note, True)])
    assert found == {_PIN_REL: digest}


def test_live_pin_targets_does_not_guess_an_unmatched_digest(tmp_path, monkeypatch):
    # A 64-hex literal that is not any published file's current digest
    # is not a pin we know. Recording it would be the always-on alarm
    # the brief refused.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(f"sha256: {'cd' * 32}\n", encoding="utf-8")
    published = {_PIN_REL: pz._sha_file(data), _PIN_NOTE: pz._sha_file(note)}
    found = pz._live_pin_targets(published, [(data, True), (note, True)])
    assert found == {}


def test_live_pin_targets_skips_out_of_scope_and_empty_published(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    note = tmp_path / "literature" / "qorvex.md"
    note.parent.mkdir(parents=True)
    note.write_text(digest, encoding="utf-8")
    published = {_PIN_REL: digest}
    found = pz._live_pin_targets(published, [(data, True), (note, False)])
    assert found == {}
    assert pz._live_pin_targets({}, [(data, True)]) == {}


def test_live_pin_targets_hashes_current_bytes_not_published_values(tmp_path, monkeypatch):
    # `published` is the apply-time `pre_sha` map. Its values are pre-run
    # digests unless `_repin_digests` has mutated them. Persist must still
    # record the file's *current* digest when the pin literal already
    # matches current bytes — otherwise the record is correct only as a
    # side effect of that mutation.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    old = pz._sha_file(data)
    data.write_text("payload-two-moved\n", encoding="utf-8")
    new = pz._sha_file(data)
    assert old != new
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(f"sha256: {new}\n", encoding="utf-8")
    published = {_PIN_REL: old, _PIN_NOTE: pz._sha_file(note)}
    found = pz._live_pin_targets(published, [(data, True), (note, True)])
    assert found == {_PIN_REL: new}
    assert found[_PIN_REL] != old


def test_live_pin_targets_does_not_record_a_stale_digest_literal(tmp_path, monkeypatch):
    # Persist-before-repin: the text still carries the pre-run digest
    # and `published` still holds it. Hashing current bytes means no
    # literal matches a current digest, so the file is omitted rather
    # than recorded under the stale value.
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    old = pz._sha_file(data)
    data.write_text("payload-two-moved\n", encoding="utf-8")
    new = pz._sha_file(data)
    assert old != new
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(f"sha256: {old}\n", encoding="utf-8")
    published = {_PIN_REL: old, _PIN_NOTE: pz._sha_file(note)}
    found = pz._live_pin_targets(published, [(data, True), (note, True)])
    assert found == {}
    assert new not in found.values() and old not in found.values()


def test_live_pin_targets_hit_set_on_a_mixed_hex_fixture(tmp_path, monkeypatch):
    """Hit-set lock for PRIV-1-BR-34.

    The scan used to alternate every published digest. The replacement
    is a generic 64-hex pass plus a dict probe. Those two strategies
    must agree here: an exact 64-char current digest is a pin, a
    65+ char hex run that is not any published digest is not, and an
    unmatched exact 64-hex is not. The assertion is the hit set, not
    the pattern string.

    A membership filter that is missing KeyErrors on the long run
    once the scan is generic. Alternation still agrees with the
    oracle, so this test stays green on the unfixed body.
    """
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    unmatched = "cd" * 32
    # 70 hex chars. No 64-char window equals a published current digest.
    long_run = "f" * 70
    assert digest not in long_run
    assert unmatched not in long_run
    assert all(long_run[i : i + 64] != digest for i in range(len(long_run) - 63))
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note_text = f"sha256: {digest}\nnoise: {long_run}\nunmatched: {unmatched}\n"
    note.write_text(note_text, encoding="utf-8")
    note_digest = pz._sha_file(note)
    published = {_PIN_REL: digest, _PIN_NOTE: note_digest}
    found = pz._live_pin_targets(published, [(data, True), (note, True)])

    # Oracle: which current published digests appear as a literal
    # substring. Same candidate set as the unanchored alternation.
    current = {digest, note_digest}
    oracle = {d for d in current if d in note_text}
    assert oracle == {digest}
    assert found == {_PIN_REL: digest}
    assert set(found.values()) == oracle
    assert unmatched not in found.values()
    assert note_digest not in found.values()
    windows = {long_run[i : i + 64] for i in range(len(long_run) - 63)}
    assert windows.isdisjoint(found.values())

    # In-test copy of both strategies over the same bytes. They must
    # agree with each other and with `_live_pin_targets`. This is the
    # "if you add hex-run guards, prove the hit set did not move" lock
    # the brief asked for.
    alt = re.compile("|".join(re.escape(d) for d in current))
    generic = re.compile(r"[0-9a-f]{64}")
    alt_hits = set(alt.findall(note_text))
    gen_hits = {d for d in generic.findall(note_text) if d in current}
    assert alt_hits == gen_hits == {digest}
    # The generic pass must still *see* the first 64 of the long run
    # (and drop it in the filter). A hex-run guard that never produces
    # that candidate would skip the membership probe this finding is
    # about. This assertion is on the in-test generic, not on
    # production's pattern string.
    raw_generic = generic.findall(note_text)
    assert long_run[:64] in raw_generic
    assert digest in raw_generic
    assert unmatched in raw_generic


def test_persist_published_pins_is_a_noop_on_dry_run(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(pz, "PRIVATE", private)
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(digest, encoding="utf-8")
    published = {_PIN_REL: digest, _PIN_NOTE: pz._sha_file(note)}
    files = [(data, True), (note, True)]
    assert pz._persist_published_pins(published, files, dry_run=True) is None
    assert not (private / "priv1-digest-pins.json").exists()


def test_persist_published_pins_writes_on_wet_run(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir()
    monkeypatch.setattr(pz, "PRIVATE", private)
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(digest, encoding="utf-8")
    published = {_PIN_REL: digest, _PIN_NOTE: pz._sha_file(note)}
    files = [(data, True), (note, True)]
    record = pz._persist_published_pins(published, files, dry_run=False)
    assert record["schema"] == _PIN_SCHEMA
    assert record["pins"] == [{"path": _PIN_REL, "sha256": digest}]
    loaded = pz._load_pin_record()
    assert loaded == record


def test_merge_keeps_a_recorded_path_that_is_no_longer_live(tmp_path, monkeypatch):
    monkeypatch.setattr(pz, "PRIVATE", tmp_path)
    previous = _pin_record((_PIN_REL, "aa" * 32))
    (tmp_path / "priv1-digest-pins.json").write_text(json.dumps(previous) + "\n")
    merged = pz._merge_pin_record({_PIN_NOTE: "bb" * 32})
    by_path = {e["path"]: e["sha256"] for e in merged["pins"]}
    assert by_path[_PIN_REL] == "aa" * 32
    assert by_path[_PIN_NOTE] == "bb" * 32


def test_verify_stays_green_when_recorded_digest_matches(tmp_path, monkeypatch, capsys):
    # Fixture lock: cmd_verify must be able to return 0 on a clean
    # tree with a matching pin. A stale-pin test that always-raises
    # would pass without this.
    body = "payload-one\n"
    pinned = _pin_digest(body)
    _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={_PIN_REL: body, _PIN_NOTE: f"sha256: {pinned}\n"},
        record=_pin_record((_PIN_REL, pinned)),
    )
    try:
        rc = pz.cmd_verify(type("Args", (), {"show_out_of_scope": False})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    out = capsys.readouterr().out
    assert rc == 0
    assert "digest pins: 1 published; 0 stale; 0 missing" in out
    assert "STALE-PIN" not in out
    assert "Zyllora" not in out


def test_verify_exits_nonzero_on_a_stale_pin(tmp_path, monkeypatch, capsys):
    # The finding, at `verify`. Same tree as the lock above, then the
    # pinned file is rewritten out of band. Unfixed verify does not
    # look at the record and returns 0.
    body = "payload-one\n"
    pinned = _pin_digest(body)
    repo, _private = _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={_PIN_REL: body, _PIN_NOTE: f"sha256: {pinned}\n"},
        record=_pin_record((_PIN_REL, pinned)),
    )
    (repo / _PIN_REL).write_text("payload-two-out-of-band\n", encoding="utf-8")
    live = pz._sha_file(repo / _PIN_REL)
    try:
        rc = pz.cmd_verify(type("Args", (), {"show_out_of_scope": False})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    out = capsys.readouterr().out
    assert rc == 1
    assert f"STALE-PIN {_PIN_REL} pinned {pinned[:12]}.. found {live[:12]}.." in out
    assert "digest pins: 1 published; 1 stale; 0 missing" in out
    assert "Zyllora" not in out


def test_verify_exits_nonzero_on_a_missing_recorded_path(tmp_path, monkeypatch, capsys):
    body = "payload-one\n"
    pinned = _pin_digest(body)
    _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={_PIN_NOTE: "no pin here\n"},
        record=_pin_record(("docs/veldrun-gone.md", pinned)),
    )
    try:
        rc = pz.cmd_verify(type("Args", (), {"show_out_of_scope": False})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    out = capsys.readouterr().out
    assert rc == 1
    assert "MISSING-PIN docs/veldrun-gone.md pinned " + pinned[:12] in out
    assert "digest pins: 1 published; 0 stale; 1 missing" in out


def test_verify_refuses_a_missing_pin_record(tmp_path, monkeypatch):
    _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={_PIN_REL: "payload-one\n"},
        record=None,
    )
    try:
        with pytest.raises(SystemExit, match="not found"):
            pz.cmd_verify(type("Args", (), {"show_out_of_scope": False})())
    finally:
        pz._nonpersonal_identities.cache_clear()


def test_apply_and_verify_both_emit_digest_pin_measurements():
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    verify_src = src[src.index("def cmd_verify") : src.index("def main")]
    assert "_persist_published_pins" in apply_src
    assert "_pin_check_line" in apply_src
    assert "_load_pin_record" in verify_src
    assert "_check_published_pins" in verify_src
    assert "_pin_check_line" in verify_src
    # Exit must include the pin findings. A printed note with a zero
    # exit is the BR-15 shape.
    assert "stale_pins" in verify_src or "missing_pins" in verify_src
    ret_line = [ln for ln in verify_src.splitlines() if ln.strip().startswith("return ")][-1]
    assert "stale_pins" in ret_line or "missing_pins" in ret_line


def test_plan_does_not_write_a_pin_record():
    src = _SCRIPT.read_text(encoding="utf-8")
    plan_src = src[src.index("def cmd_plan(") : src.index("FREE_TEXT_REDACTIONS")]
    assert "_persist_published_pins" not in plan_src
    assert "_merge_pin_record" not in plan_src
    assert "_write_pin_record" not in plan_src


def test_apply_does_not_persist_under_the_dry_run_name():
    # The persist call must pass the dry-run flag through. A wet-only
    # call that ignored dry-run would write a record claiming pins
    # were published when nothing was.
    src = _SCRIPT.read_text(encoding="utf-8")
    apply_src = src[src.index("def cmd_apply") : src.index("def cmd_verify")]
    assert "_persist_published_pins(" in apply_src
    assert "args.dry_run" in apply_src[apply_src.index("_persist_published_pins(") :]


def test_apply_records_the_post_apply_digest_of_a_moved_pin(tmp_path, monkeypatch):
    # Integration lock for PRIV-1-BR-33. A pinned file's digest moves
    # because apply rewrites it; `_repin_digests` then rewrites the pin
    # literal. The on-disk record must hold the *post-apply* digest.
    # Source inspection of the call order would lock the text, not the
    # behaviour. Swapping the two calls in `cmd_apply` must turn this
    # assertion red — verified by actually swapping, not by predicting.
    body = "Zyllora Elm\n"
    pre = _pin_digest(body)
    repo, _private = _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={_PIN_REL: body, _PIN_NOTE: f"sha256: {pre}\n"},
        record=None,
    )
    try:
        rc = pz.cmd_apply(type("Args", (), {"dry_run": False, "reorder": False, "top": 25})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    assert rc == 0
    post = pz._sha_file(repo / _PIN_REL)
    assert post != pre
    assert post in (repo / _PIN_NOTE).read_text(encoding="utf-8")
    record = pz._load_pin_record()
    by_path = {e["path"]: e["sha256"] for e in record["pins"]}
    assert by_path[_PIN_REL] == post


# ---- wave 7a: pin-scanner unification ----
#
# One window rule for `_repin_digests` and `_live_pin_targets`. Invented
# paths only (`nylphra` / `qorvex` / `veldrun`). Predictions for the
# table below were written in REPORT.md before this test first ran
# against unfixed production (TEST-06).


def _wave7a_publisher_records(tmp_path, monkeypatch, make_body) -> bool:
    """True iff `_live_pin_targets` records a path whose digest sits in `make_body`."""
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(make_body(digest), encoding="utf-8")
    published = {_PIN_REL: digest, _PIN_NOTE: pz._sha_file(note)}
    found = pz._live_pin_targets(published, [(data, True), (note, True)])
    return found.get(_PIN_REL) == digest


def _wave7a_rewriter_rewrites(tmp_path, monkeypatch, make_body) -> bool:
    """True iff `_repin_digests` rewrites a note that embeds the moved digest."""
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text("payload-one\n", encoding="utf-8")
    old = pz._sha_file(data)
    data.write_text("payload-two-moved\n", encoding="utf-8")
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True, exist_ok=True)
    before = make_body(old)
    note.write_text(before, encoding="utf-8")
    published = {_PIN_REL: old, _PIN_NOTE: pz._sha_file(note)}
    pz._repin_digests(published, [(data, True), (note, True)], dry_run=False)
    after = note.read_text(encoding="utf-8")
    return after != before


_WINDOW_ROWS = (
    ("isolated literal", lambda d: d, True),
    ("sha256: <d>", lambda d: f"sha256: {d}\n", True),
    ("aligned prefix <d>+f*64", lambda d: d + "f" * 64, True),
    ("aligned suffix f*64+<d>", lambda d: "f" * 64 + d, True),
    ("non-aligned f*16+<d>+f*16", lambda d: "f" * 16 + d + "f" * 16, False),
    ("70-run <d>+f*6", lambda d: d + "f" * 6, True),
    ("pin not first window", lambda d: "cd" * 32 + "\n" + d, True),
    ("<d> split by a newline", lambda d: d[:32] + "\n" + d[32:], False),
)


@pytest.mark.parametrize(
    "label, make_body, expected",
    _WINDOW_ROWS,
    ids=[
        "isolated",
        "sha256",
        "aligned_prefix",
        "aligned_suffix",
        "non_aligned",
        "seventy_run",
        "not_first_window",
        "split_by_newline",
    ],
)
def test_repin_and_live_targets_share_one_window_rule(
    tmp_path, monkeypatch, label, make_body, expected
):
    """CARD-11: rewriter and publisher agree on what a pin literal is.

    TEST-06 predictions (written before the first run against unfixed
    `_repin_digests`, which still alternates the moved digests):

    isolated literal          both pin
    sha256: <d>               both pin
    <d>+f*64 aligned prefix   both pin
    f*64+<d> aligned suffix   both pin
    f*16+<d>+f*16 non-aligned rewriter pins, publisher does not  ← red
    <d>+f*6 70-run            both pin
    cd*32 \\n <d> not first   both pin
    <d> split by a newline    neither pin

    After unification both walks use `_HEX64_RX` windows, so the
    non-aligned row becomes neither-pin and this test goes green.
    The expected column is load-bearing for M1 / M10 (shared regex)
    and M2 / M7 / the BR-34 alternation (publisher-only swap).
    """
    publisher = _wave7a_publisher_records(tmp_path, monkeypatch, make_body)
    rewriter = _wave7a_rewriter_rewrites(tmp_path, monkeypatch, make_body)
    assert rewriter == publisher, (
        f"{label}: rewriter would rewrite={rewriter} publisher records={publisher}"
    )
    assert publisher is expected, (
        f"{label}: publisher records={publisher} expected={expected}"
    )
    assert rewriter is expected, (
        f"{label}: rewriter would rewrite={rewriter} expected={expected}"
    )


def test_live_pin_targets_does_not_record_a_non_aligned_embed(tmp_path, monkeypatch):
    """REV-A-10 / BR-34: the mixed-hex fixture never held this shape.

    A published digest at offset 16 of a longer hex run is a substring
    hit for the old alternation (`if digest in text` / `"|".join`) and
    not a left-aligned window. Reintroducing either old scan in
    `_live_pin_targets` must turn this red (TEST-15).
    """
    monkeypatch.setattr(pz, "REPO", tmp_path)
    data = tmp_path / _PIN_REL
    data.parent.mkdir(parents=True)
    data.write_text("payload-one\n", encoding="utf-8")
    digest = pz._sha_file(data)
    body = ("f" * 16) + digest + ("f" * 16)
    assert digest in body
    assert body[0:64] != digest
    note = tmp_path / _PIN_NOTE
    note.parent.mkdir(parents=True)
    note.write_text(body, encoding="utf-8")
    published = {_PIN_REL: digest, _PIN_NOTE: pz._sha_file(note)}
    found = pz._live_pin_targets(published, [(data, True), (note, True)])
    assert found == {}


def test_merge_overwrites_a_recorded_digest_for_the_same_path(tmp_path, monkeypatch):
    """REV-A-03 / M3: updates win. Existing-wins leaves the old digest."""
    monkeypatch.setattr(pz, "PRIVATE", tmp_path)
    old, new = "aa" * 32, "bb" * 32
    (tmp_path / "priv1-digest-pins.json").write_text(
        json.dumps(_pin_record((_PIN_REL, old))) + "\n"
    )
    merged = pz._merge_pin_record({_PIN_REL: new})
    by_path = {e["path"]: e["sha256"] for e in merged["pins"]}
    assert by_path[_PIN_REL] == new
    loaded = pz._load_pin_record()
    assert {e["path"]: e["sha256"] for e in loaded["pins"]}[_PIN_REL] == new


def test_second_wet_apply_refreshes_the_recorded_digest(tmp_path, monkeypatch):
    """Same overwrite, through two wet `apply` runs whose pin digest moves."""
    body1 = "Zyllora Elm\npayload-one\n"
    pre1 = _pin_digest(body1)
    repo, _private = _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={_PIN_REL: body1, _PIN_NOTE: f"sha256: {pre1}\n"},
        record=None,
    )
    try:
        rc1 = pz.cmd_apply(type("Args", (), {"dry_run": False, "reorder": False, "top": 25})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    assert rc1 == 0
    digest1 = pz._sha_file(repo / _PIN_REL)
    assert digest1 != pre1
    by_path = {e["path"]: e["sha256"] for e in pz._load_pin_record()["pins"]}
    assert by_path[_PIN_REL] == digest1

    body2 = "Zyllora Elm\npayload-two\n"
    pre2 = _pin_digest(body2)
    assert pre2 != digest1
    (repo / _PIN_REL).write_text(body2, encoding="utf-8")
    (repo / _PIN_NOTE).write_text(f"sha256: {pre2}\n", encoding="utf-8")
    try:
        rc2 = pz.cmd_apply(type("Args", (), {"dry_run": False, "reorder": False, "top": 25})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    assert rc2 == 0
    digest2 = pz._sha_file(repo / _PIN_REL)
    assert digest2 != digest1
    assert digest2 != pre2
    assert digest2 in (repo / _PIN_NOTE).read_text(encoding="utf-8")
    by_path = {e["path"]: e["sha256"] for e in pz._load_pin_record()["pins"]}
    assert by_path[_PIN_REL] == digest2


def test_apply_records_the_post_rename_path_of_a_live_pin(tmp_path, monkeypatch):
    """REV-A-08 / M11: persist must walk `files_after`, not the pre-rename list.

    The pinned file's path is rewritten by the run. The live pin travels
    with the bytes; the record must name the new path. Walking `files`
    sees a gone path and records nothing.
    """
    old_rel = "apps/nylphra/zyllora-elm.py"
    new_rel = "apps/nylphra/amber_falcon.py"
    body = "payload-one\n"
    digest = _pin_digest(body)
    repo, _private = _prepare_verify_env(
        tmp_path,
        monkeypatch,
        files={old_rel: body, _PIN_NOTE: f"sha256: {digest}\n"},
        record=None,
    )

    def tracked():
        out = []
        for rel in (old_rel, new_rel, _PIN_NOTE):
            path = repo / rel
            if path.is_file():
                out.append((path, True))
        return out

    monkeypatch.setattr(pz, "_tracked_files", tracked)

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and len(cmd) >= 4 and cmd[0] == "git" and cmd[1] == "mv":
            cwd = Path(kwargs.get("cwd") or ".")
            src = cwd / cmd[2]
            dst = cwd / cmd[3]
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.replace(dst)
            return pz.subprocess.CompletedProcess(list(cmd), 0, "", "")
        raise AssertionError(f"unexpected subprocess.run: {cmd!r}")

    monkeypatch.setattr(pz.subprocess, "run", fake_run)
    try:
        rc = pz.cmd_apply(type("Args", (), {"dry_run": False, "reorder": False, "top": 25})())
    finally:
        pz._nonpersonal_identities.cache_clear()
    assert rc == 0
    assert (repo / new_rel).is_file()
    assert not (repo / old_rel).exists()
    assert pz._sha_file(repo / new_rel) == digest
    record = pz._load_pin_record()
    by_path = {e["path"]: e["sha256"] for e in record["pins"]}
    assert by_path.get(new_rel) == digest
    assert old_rel not in by_path
