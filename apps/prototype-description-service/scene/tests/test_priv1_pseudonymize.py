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
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "privacy" / "priv1_pseudonymize.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("priv1_pseudonymize", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pz = _load_module()


@pytest.fixture(autouse=True)
def _mint_key():
    # Several builders hash through the mint key. Pin a fixed one so alias words
    # are stable across runs without touching the real (untracked) key.
    previous = pz._KEY
    pz._KEY = "t" * 64
    yield
    pz._KEY = previous


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
    passes = pz._Passes(mapping)
    text = "2026/07/ryannewistmoor-1721_9988776655.jpg"
    out, counts, _unresolved = passes.rewrite(text, ".json")
    assert "ryannewistmoor" not in out.lower()
    assert "amberfalcon" in out.lower()
    assert counts["concat"] == 1


def test_concatenated_name_is_reported_as_residue(mapping):
    # verify and apply must agree: a class the rewriter fixes but the checker
    # cannot see is how "0 residue" was reported over 379 live occurrences.
    passes = pz._Passes(mapping)
    assert passes.residue("2026/07/ryannewistmoor-1721_9988.jpg", ".json").get("concat") == 1


def test_concatenated_pass_preserves_case_shape(mapping):
    passes = pz._Passes(mapping)
    out, _counts, _u = passes.rewrite("RYANNEWISTMOOR and Ryannewistmoor", ".md")
    assert "AMBERFALCON" in out
    assert "AmberFalcon" in out, "mixed case must fall back to the alias's own casing"


def test_concatenated_pass_respects_alphanumeric_boundaries(mapping):
    # NBL/NBR, not the hex guard, are what keep this pass out of a sha256 pin:
    # a match embedded in a longer alnum run cannot fire at all. Asserting the
    # boundary directly is the only reachable protection to pin here.
    passes = pz._Passes(mapping)
    out, counts, _u = passes.rewrite("xryannewistmoorx and ryannewistmoor9", ".json")
    assert counts["concat"] == 0
    assert out == "xryannewistmoorx and ryannewistmoor9"


def test_concatenated_form_is_built_when_the_alias_has_fewer_tokens():
    # A 3-token real name mapped to a 2-token alias. Requiring token-count parity
    # dropped four such identities from the pattern, and an independent oracle
    # then found 8 live occurrences of them that `verify` reported as zero.
    rx, forms = pz._concatenated_regex(
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
        {"real_name": "Al Bo", "alias": "Pewter Coral", "tokens": 2},  # too short to join
        {"real_name": "Solo", "alias": "Brisk Ember", "tokens": 1},  # single token
    ]
    _rx, forms = pz._concatenated_regex({"entries": entries})
    eligible = {
        "".join(e["real_name"].split()).lower()
        for e in entries
        if len(e["real_name"].split()) >= 2 and len("".join(e["real_name"].split())) >= 8
    }
    assert set(forms) == eligible, "an eligible entry was dropped from the pattern"


def test_concatenated_pass_ignores_short_joins():
    # An 8-character floor keeps a two-token join from colliding with an
    # ordinary word. Below it, no pattern is built at all.
    rx, forms = pz._concatenated_regex({"entries": [{"real_name": "Al Bo", "alias": "Amber Falcon", "tokens": 2}]})
    assert rx is None and forms == {}


# --- rewrite idempotence ---------------------------------------------------


def test_rewrite_is_idempotent(mapping):
    passes = pz._Passes(mapping)
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
    passes = pz._Passes(mapping)
    assert passes.residue("../shared/ryannewistmoor/hook", ".sh").get("concat") == 1


def test_declared_waiver_does_not_excuse_an_undeclared_file(monkeypatch):
    monkeypatch.setattr(pz, "DECLARED_UNSCANNABLE", {"a.docx": "inspected; cited author"})
    declared, undeclared = pz._split_declared([("a.docx", "not utf-8"), ("b.docx", "not utf-8")])
    assert declared == [("a.docx", "not utf-8")]
    assert undeclared == [("b.docx", "not utf-8")], "an undeclared container must still fail the gate"


def test_stale_waiver_is_refused(monkeypatch):
    # The file was renamed or became readable. Leaving the waiver in place reads
    # as coverage while excusing nothing.
    monkeypatch.setattr(pz, "DECLARED_UNSCANNABLE", {"gone.docx": "inspected"})
    with pytest.raises(SystemExit, match="did not report as unscannable"):
        pz._split_declared([])


def test_every_shipped_waiver_carries_a_rationale():
    for rel, why in pz.DECLARED_UNSCANNABLE.items():
        assert len(why) > 60, f"{rel} is waived without a reviewable reason"


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
    monkeypatch.setattr(pz, "REPO", tmp_path)
    a = tmp_path / "a.txt"
    a.write_text("changed", encoding="utf-8")
    assert pz._repin_digests({"a.txt": _sha("original")}, [(a, True)], dry_run=True) == []


# --- alias vocabulary hygiene, PRIV-1-BR-04 -------------------------------


def test_vocab_collision_with_a_real_name_is_refused():
    stolen = pz._ADJ[0].capitalize()
    with pytest.raises(SystemExit, match="alias vocabulary collides"):
        pz._assert_vocab_disjoint_from_roster([{"name": f"{stolen} Vensk", "bucket": "personal"}])


def test_disjoint_vocabulary_is_accepted():
    pz._assert_vocab_disjoint_from_roster([{"name": "Ryanne Wistmoor", "bucket": "personal"}])


def test_already_minted_aliases_are_not_treated_as_collisions():
    # A wholly alias-shaped name is a previous run's output; `_looks_pseudonymized`
    # owns that case and reports it with the right remedy.
    alias = f"{pz._ADJ[0].capitalize()} {pz._NOUN[0].capitalize()}"
    pz._assert_vocab_disjoint_from_roster([{"name": alias, "bucket": "personal"}])
