#!/usr/bin/env python3
"""Replace curated real names with their roster pseudonyms across the tracked tree.

`benchmarks/manifests/corpus-manifest-v3.json` declares
``consent.personal = "subjects are named by pseudonym throughout"`` and stamps
every ``bucket == "personal"`` identity with ``naming = "pseudonym"``. Both
claims are false on the tip: those identity records carry the operator's real
curated names, byte-identical to the ones in
``curated-identities-20260716.json``. This makes the artifact match its own
declared contract (MLDATA-13: a name bound to a face box is its own data class;
rg-015: never let an artifact assert metadata it does not honour).

Every alias is freshly minted. The roster's own ``slug`` field looks like a
pseudonym vocabulary but is in fact the real name slugified for all 90 personal
identities, so it leaks too and cannot seed an alias. Minting is deterministic
under a **secret key** held only in ``ACX_CORPUS_PRIVATE_DIR`` -- with a
committed salt the map is reconstructible by anyone who can guess a name, which
makes the pseudonyms confirmable rather than confidential (MLDATA-17).

Celebrity identities (``bucket == "celebs"``, ``naming == "real_name"``) are
left alone: they are third-party editorial fixtures the consent block already
discloses as such, and their real names are the functional ground truth for the
recognition leg of the bake-off.

The reverse map and the mint key are written to ``benchmarks/private/`` --
durable, but behind the ``/benchmarks/`` ignore fence, never tracked.

Rewrites are confined to ``SCAN_ALLOW`` (this project's own source, docs, and
manifests). Third-party text under ``literature/`` is scanned and *reported*
but never edited: a surname that collides with a cited author is a false
positive, and rewriting it corrupts a quoted source (CARD-07 -- fail loudly
rather than silently mangling somebody else's bytes).

Usage:
    python scripts/privacy/priv1_pseudonymize.py plan     # mint key + alias map
    python scripts/privacy/priv1_pseudonymize.py apply    # rewrite tracked files
    python scripts/privacy/priv1_pseudonymize.py verify   # re-scan for residue
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROSTER = REPO / "benchmarks" / "manifests" / "corpus-manifest-v3.json"
PRIVATE = Path(os.environ.get("ACX_CORPUS_PRIVATE_DIR") or REPO / "benchmarks" / "private")
ALIAS_MAP = PRIVATE / "priv1-alias-map.json"
MINT_KEY = PRIVATE / "priv1-mint-key"

# Rewrite scope. Everything tracked outside this list is still scanned, but only
# reported -- see the module docstring.
SCAN_ALLOW = (
    "apps/",
    "benchmarks/",
    "config/",
    "docs/",
    "infra/",
    "local/",
    "mk/",
    "packages/",
    "reviews/",
    "scripts/",
    "workbay-overrides/",
)

# In-scope files that cannot be decoded as text, each with the sha256 of the
# bytes a human actually inspected and the reason those bytes are nonetheless
# not a leak. Nothing may be skipped silently: an undecodable in-scope file that
# is NOT declared here fails `verify`, because "we could not read it" and "it is
# clean" are not the same sentence (CARD-07).
#
# The waiver is pinned to content, not to the path. An OOXML container fails to
# decode no matter what is inside it, so a path-keyed waiver would go on
# excusing that path through every future edit -- including one that introduces
# a name nobody has reviewed. Pinning the digest keeps the waiver's scope equal
# to the evidence behind it (CARD-06); re-inspect and re-pin when it moves.
DECLARED_UNSCANNABLE = {
    "docs/assessments/current/AltContext_Local_AI_Strategy_Session_Brief.docx": (
        "27f343d84e4795669d82985c892bef3b840050c6326ce0d011055367320e2a35",
        "OOXML container. Inspected part-by-part: the single roster-token hit in "
        "word/document.xml is a cited author surname inside a bibliography entry "
        "of the form `<author> & <author> (2023).pdf`, not a corpus subject. "
        "Rewriting it would corrupt somebody else's citation -- the same reason "
        "literature/ is scanned but never edited.",
    ),
}

SKIP_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".pdf",
    ".zip",
    ".gz",
    ".bz2",
    ".woff",
    ".woff2",
    ".ico",
    ".ttf",
    ".otf",
    ".mp4",
    ".mov",
    ".npy",
    ".bin",
)

# Slug vocabulary for minting replacements for name-derived slugs. Drawn from
# the shape already present in the roster (adjective_noun), so a minted alias is
# indistinguishable from an inherited one.
_ADJ = (
    "amber",
    "cobalt",
    "quiet",
    "linen",
    "hollow",
    "candid",
    "marbled",
    "russet",
    "tidal",
    "vellum",
    "sable",
    "opaline",
    "citrine",
    "muted",
    "brisk",
    "verdant",
    "auburn",
    "slate",
    "wicker",
    "pewter",
    "saffron",
    "umber",
    "flaxen",
    "dappled",
    "burnished",
    "indigo",
    "ochre",
    "sylvan",
    "gilded",
    "hazel",
    "onyx",
    "plumb",
)
_NOUN = (
    "falcon",
    "harbor",
    "lantern",
    "meadow",
    "quarry",
    "thistle",
    "beacon",
    "cypress",
    "current",
    "ridgeway",
    "willow",
    "compass",
    "ferry",
    "orchard",
    "bramble",
    "kestrel",
    "hollow",
    "fathom",
    "juniper",
    "lockwood",
    "marsh",
    "pennant",
    "rookery",
    "sable",
    "tanner",
    "verity",
    "warren",
    "yarrow",
)


# Single-token identity names that must never be matched in free text live
# on the alias map as `free_text_deny`: lowercase tokens that are
# overwhelmingly an ordinary word rather than the person. The block is
# optional at schema and required at load — an absent list is not an
# empty list (CARD-07). An empty list is valid and means every
# single-token identity is eligible in data/prose. Denied tokens are
# still scrubbed where they appear as a whole JSON string.

# A bare single-token name is also a perfectly good variable name: `bea =
# _identity_item(...)` in a test is an identifier, not a person, and rewriting
# it to a two-word alias is a SyntaxError. Single-token names are therefore
# matched in free text only inside data and prose files, never in source.
SINGLE_TOKEN_FREE_TEXT_SUFFIXES = {".json", ".md", ".html", ".htm", ".txt", ".csv", ".tsv"}

# `\b` treats `_` as a word character, so it never fires at a letter->underscore
# transition. That is exactly the boundary a snake_case filename or a
# `_first_last` identifier presents, and it is why the first pass left
# `candid_brisk_failure_analysis.md` and `_pewter_coral` untouched. Bound on
# letters only.
#
# A JSON string body encodes a newline as the two characters backslash + n.
# A name at the start of a line inside that string is therefore preceded by
# the letter `n` of the escape, and a letters-only lookbehind refuses. Treat
# those escapes as a left boundary -- each lookbehind is fixed-width, which
# Python requires. Right side is already fine: a name followed by an escape
# has a backslash on its right, which is non-alphanumeric.
NBL = r"(?:(?<![A-Za-z0-9])|(?<=\\n)|(?<=\\t)|(?<=\\r))"
NBR = r"(?![A-Za-z0-9])"

# ...and a digit-adjacent boundary is not enough on its own. A sha256 pin is a
# 64-character alnum run whose *first* characters can spell a short name
# (`4beca0...` starts at a quote, so the left boundary holds). Rewriting inside
# one produces `4quiet0a04...`, which the manifest validator rejects -- silent
# corruption of the exact artifact this scrub exists to protect. Any match
# sitting inside a long hex run is refused.
_HEX = set("0123456789abcdefABCDEF")
_HEX_RUN_MIN = 16

# Concatenated-name tiers. A joined form of this length and above is
# matched unanchored (BR-22): that many letters of a real full name
# cannot plausibly collide with an ordinary word. Shorter multi-token
# joins are still admitted, but under a letter-only anchor — the floor
# was protecting an in-word collision, not a digit/`@`/`/` neighbour,
# and dropping them silently made `verify` report 0 over live names
# (BR-25). Single-token names have no concatenation; those are the
# remaining exclusion, and they are counted, not swallowed.
CONCAT_UNANCHORED_MIN = 8
_CONCAT_LETTER_NBL = r"(?<![A-Za-z])"
_CONCAT_LETTER_NBR = r"(?![A-Za-z])"


def _inside_hex_run(text: str, start: int, end: int) -> bool:
    i = start
    while i > 0 and text[i - 1] in _HEX:
        i -= 1
    j = end
    while j < len(text) and text[j] in _HEX:
        j += 1
    return all(c in _HEX for c in text[start:end]) and (j - i) >= _HEX_RUN_MIN


_KEY: str | None = None


def _hash(text: str) -> str:
    if _KEY is None:  # pragma: no cover - guarded by every caller path
        raise SystemExit("mint key not loaded; call _load_key() first")
    return hmac.new(_KEY.encode("utf-8"), text.encode("utf-8"), hashlib.sha256).hexdigest()


def _key_fingerprint() -> str:
    return hashlib.sha256(("fp\x00" + (_KEY or "")).encode("utf-8")).hexdigest()[:16]


def _load_key(create: bool = False) -> str:
    """Read (or first-time mint) the secret key.

    Never committed and never echoed. Without it the alias map cannot be
    reproduced from the tracked tree, which is the whole point: a salt that
    ships in the repo turns every pseudonym into a confirmable guess.
    """
    global _KEY
    if MINT_KEY.is_file():
        key = MINT_KEY.read_text(encoding="utf-8").strip()
        if len(key) < 32:
            raise SystemExit(f"mint key at {MINT_KEY} is too short ({len(key)} chars); refusing to use it")
        _KEY = key
        return key
    if not create:
        raise SystemExit(
            f"mint key not found: {MINT_KEY}\n"
            "It is untracked by design. Restore it from the private corpus store, "
            "or point ACX_CORPUS_PRIVATE_DIR at the directory that holds it."
        )
    PRIVATE.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    MINT_KEY.write_text(key + "\n", encoding="utf-8")
    MINT_KEY.chmod(0o600)
    _KEY = key
    return key


def _read(path: Path) -> str:
    """Newline-preserving read. `Path.read_text` translates CRLF to LF, so a
    round-trip through it silently reformats every DOS-line-ending file the
    scrub touches -- a diff the scrub was never asked to make."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _read_or_reason(path: Path) -> tuple[str | None, str]:
    """Read `path`, or return why it could not be read.

    An unreadable in-scope file is not an absent one: a `.docx`/`.epub`/unknown
    container carries names in bytes the scrub never inspected. Swallowing the
    decode error makes `verify` green on a file it never opened, so the reason is
    returned for the caller to surface instead of being dropped.

    A tracked symlink is read as its own target string rather than followed. That
    string is the whole of what git stores for the path (mode 120000), so it is
    the only content the scrub can be responsible for -- and following the link
    instead would make coverage depend on whether an overlay happens to be
    materialized in this worktree, which is how the git hook links read as
    `FileNotFoundError` and looked like a scan gap.
    """
    if path.is_symlink():
        return os.readlink(path), ""
    try:
        return _read(path), ""
    except UnicodeDecodeError:
        return None, "not utf-8 (binary or non-utf8 container)"
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc.strerror or exc}"


def _split_declared(
    unscannable: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Partition unscannable in-scope files into declared and undeclared.

    Only the undeclared half fails the gate. A waiver that no longer names a
    file the scan actually hit is worse than no waiver -- it reads as coverage
    while excusing nothing -- so a stale entry is a hard error, not a shrug.

    A waiver whose file has changed since it was written is the same failure in
    slower motion, so the pinned digest is checked too: the rationale describes
    bytes, and once the bytes move it describes nothing (CARD-06).
    """
    hit = {rel for rel, _ in unscannable}
    if stale := sorted(set(DECLARED_UNSCANNABLE) - hit):
        raise SystemExit(
            "DECLARED_UNSCANNABLE names files the scan did not report as unscannable: "
            f"{stale}. They were renamed, deleted, or became readable -- re-check each "
            "one and drop or update its entry."
        )
    drifted = [
        (rel, DECLARED_UNSCANNABLE[rel][0], _sha_file(REPO / rel))
        for rel in sorted(hit & set(DECLARED_UNSCANNABLE))
        if _sha_file(REPO / rel) != DECLARED_UNSCANNABLE[rel][0]
    ]
    if drifted:
        detail = "; ".join(f"{rel}: pinned {old[:12]}, found {new[:12]}" for rel, old, new in drifted)
        raise SystemExit(
            f"DECLARED_UNSCANNABLE waivers no longer match the files they excuse: {detail}. "
            "The rationale was written against specific bytes and those bytes have changed. "
            "Re-inspect the current content and re-pin the digest, or drop the waiver."
        )
    declared = [(rel, why) for rel, why in unscannable if rel in DECLARED_UNSCANNABLE]
    return declared, [(rel, why) for rel, why in unscannable if rel not in DECLARED_UNSCANNABLE]


def _norm(text: str) -> str:
    """Separator-insensitive normal form. The roster mixes `_` and `-` slugs, and
    comparing against only one of them under-reports name-derived slugs (it
    reported 4 of 90 when the true figure is nearly all of them)."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _slug_is_name_derived(name: str, slug: str) -> bool:
    return _norm(name) == _norm(slug)


def _mint_slug(name: str, taken: set[str]) -> str:
    """Deterministic adjective_noun slug. On collision, re-hash rather than
    appending a counter -- a digit suffix leaks into user-facing demo evidence
    (`Opaline Ridgeway39`) and reads as a machine artefact instead of a name."""
    for attempt in range(512):
        h = int(_hash(f"{name}#{attempt}")[:12], 16)
        candidate = f"{_ADJ[h % len(_ADJ)]}_{_NOUN[(h // len(_ADJ)) % len(_NOUN)]}"
        if candidate not in taken:
            return candidate
    raise SystemExit("could not mint a free slug after 512 attempts")


def _alias_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[_\-]+", slug) if part)


_ALIAS_VOCAB = {w.capitalize() for w in _ADJ} | {w.capitalize() for w in _NOUN}


def _looks_pseudonymized(personal: list[dict]) -> bool:
    """True when the roster's personal names are already drawn from the alias
    vocabulary. Re-running `plan` against a scrubbed roster would mint aliases
    *for the aliases* and destroy the only surviving real->alias mapping."""
    if not personal:
        return False
    hits = sum(1 for i in personal if i["name"].split() and all(t in _ALIAS_VOCAB for t in i["name"].split()))
    return hits * 2 > len(personal)


def _assert_vocab_disjoint_from_roster(identities: list[dict]) -> None:
    """Refuse to mint from a vocabulary any real roster name already uses.

    A shared token breaks two things at once. `_looks_pseudonymized` counts
    alias-vocabulary tokens, so real names built from them read as already
    scrubbed and `plan` silently declines to protect them; and the residue scan
    cannot distinguish a leftover real token from a minted one, so `verify` goes
    green over the leak. The offending vocabulary word is named -- it is a
    literal in this file, not corpus data -- while the colliding names are not.
    """
    tokens: dict[str, int] = {}
    for ident in identities:
        parts = [t for t in re.split(r"[^A-Za-z]+", ident.get("name", "")) if t]
        if not parts or all(t.capitalize() in _ALIAS_VOCAB for t in parts):
            # Wholly alias-shaped: an already-minted alias, not a real name.
            # `_looks_pseudonymized` owns that case and reports it better.
            continue
        for token in parts:
            if token.capitalize() in _ALIAS_VOCAB:
                tokens[token.lower()] = tokens.get(token.lower(), 0) + 1
    if tokens:
        detail = ", ".join(f"{w} (x{n})" for w, n in sorted(tokens.items()))
        raise SystemExit(
            f"alias vocabulary collides with real roster names: {detail}. "
            "Remove those words from _ADJ/_NOUN -- a minted alias sharing a token with a "
            "real name defeats both the re-run guard and the residue scan."
        )


def _split_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^A-Za-z]+", text) if t]


def _assert_map_vocab_disjoint(mapping: dict) -> None:
    """Re-check the disjointness invariant against the map that actually shipped.

    `_assert_vocab_disjoint_from_roster` only runs inside `plan`. It landed one
    commit after the map had already been minted and applied, so it has never
    seen the state on disk -- and it never will, because it reads the roster,
    which `apply` has since pseudonymized. The map is the only artifact that
    still holds the real names, so it is the only place the invariant can be
    re-tested after the fact.

    A collision here is invisible to every other check: a minted alias is by
    construction not residue, so `verify` reports clean, and `plan` refuses to
    re-run against a roster that now looks pseudonymized (CARD-08 -- the blind
    spot was the mint step, which nothing re-validated post-apply).

    The comparison is real-name tokens against *live alias* tokens, not against
    `_ALIAS_VOCAB`. Keying it off the vocabulary would make the check answer a
    question about the current source rather than about the shipped artifact:
    editing the offending word out of `_ADJ` would silence it while the minted
    alias carrying that word stayed on disk. The measurement must not be
    derived from the thing being changed.
    """
    alias_tokens: set[str] = set()
    for entry in mapping.get("entries", ()):
        alias_tokens.update(t.lower() for t in _split_tokens(entry.get("alias", "")))
    # Both sides are counted, because they are different quantities and the
    # smaller one is not the repair scope. One real name carrying the word can
    # collide with several minted aliases, and it is the *aliases* that have to
    # be re-minted. Collapsing to a single number would understate the work
    # whenever the two differ.
    real_hits: dict[str, int] = {}
    alias_hits: dict[str, int] = {}
    for entry in mapping.get("entries", ()):
        for token in (t for t in _split_tokens(entry.get("real_name", "")) if t.lower() in alias_tokens):
            real_hits[token.lower()] = real_hits.get(token.lower(), 0) + 1
    real_tokens = {t.lower() for e in mapping.get("entries", ()) for t in _split_tokens(e.get("real_name", ""))}
    for entry in mapping.get("entries", ()):
        for token in (t for t in _split_tokens(entry.get("alias", "")) if t.lower() in real_tokens):
            alias_hits[token.lower()] = alias_hits.get(token.lower(), 0) + 1
    tokens = real_hits
    if tokens:
        detail = ", ".join(
            f"{w} ({alias_hits.get(w, 0)} alias{'es' if alias_hits.get(w, 0) != 1 else ''}, "
            f"{n} real name{'s' if n != 1 else ''})"
            for w, n in sorted(tokens.items())
        )
        raise SystemExit(
            f"shipped alias map reuses real name tokens as pseudonym tokens: {detail}. "
            "Each of those words is a real name token AND half of a live pseudonym, so neither "
            "the re-run guard nor the residue scan can tell the two apart. Replace the word in "
            "_ADJ/_NOUN keeping the list length -- so every other alias is unchanged -- then "
            "re-mint the affected entries and migrate the tree old-alias->new-alias through "
            "_Passes rather than a literal sweep."
        )


def build_map() -> dict:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    identities = roster["identities"]
    personal = [i for i in identities if i.get("bucket") == "personal"]
    celeb_names = {i["name"] for i in identities if i.get("bucket") != "personal"}

    if _looks_pseudonymized(personal):
        raise SystemExit(
            "roster personal identities are already drawn from the alias vocabulary.\n"
            "`plan` refuses to mint a second generation of aliases: it would overwrite "
            f"{ALIAS_MAP.name} with an alias->alias map and lose the real names for good.\n"
            "If this is intentional, move the existing map aside first and say so in the task plan."
        )

    _assert_vocab_disjoint_from_roster(identities)

    taken_slugs = {i["slug"] for i in identities}
    entries: list[dict] = []
    aliases: set[str] = set()

    for ident in sorted(personal, key=lambda i: i["name"]):
        name = ident["name"]
        # Always mint. The roster's own `slug` is the real name slugified for
        # nearly every personal identity, so deriving an alias from it would
        # re-emit the very string being scrubbed.
        was_derived = _slug_is_name_derived(name, ident["slug"])
        slug = _mint_slug(name, taken_slugs)
        taken_slugs.add(slug)
        alias = _alias_from_slug(slug)
        # An alias must never collide with a real person still in the tree.
        while alias in celeb_names or alias in aliases:
            slug = _mint_slug(name + "#" + slug, taken_slugs)
            taken_slugs.add(slug)
            alias = _alias_from_slug(slug)
        aliases.add(alias)
        entries.append(
            {
                "real_name": name,
                "alias": alias,
                "alias_slug": slug,
                "original_slug": ident["slug"],
                "slug_was_name_derived": was_derived,
                "tokens": len(name.split()),
            }
        )

    return {
        "schema": "priv1-alias-map/2",
        "key_fingerprint": _key_fingerprint(),
        "roster_source": str(ROSTER.relative_to(REPO)),
        "personal_identities": len(entries),
        "celeb_identities_left_intact": len(celeb_names),
        "entries": entries,
        "wordlist": _wordlist_record(),
        "free_text_deny": [],
    }


def load_map() -> dict:
    if not ALIAS_MAP.is_file():
        raise SystemExit(
            f"alias map not found: {ALIAS_MAP}\n"
            "Run `plan` first. The map is name-bearing and therefore untracked; "
            "point ACX_CORPUS_PRIVATE_DIR at it if it lives elsewhere."
        )
    try:
        mapping = json.loads(ALIAS_MAP.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{ALIAS_MAP}: malformed JSON ({exc}). "
            "Restore the alias map from the private corpus store, or re-run `plan` "
            "from a clean tree if the file is unrecoverable."
        ) from exc
    _validate_map(mapping)
    return mapping


def _validate_map(mapping: dict) -> None:
    """Structural validation at load time (rg-008). An empty or half-written map
    would otherwise make `apply` a silent no-op and `verify` report a clean tree."""
    if mapping.get("schema") != "priv1-alias-map/2":
        raise SystemExit(f"{ALIAS_MAP}: unsupported schema {mapping.get('schema')!r}; expected priv1-alias-map/2")
    entries = mapping.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"{ALIAS_MAP}: `entries` missing or empty; re-run `plan`")
    required = {"real_name", "alias", "alias_slug", "original_slug", "tokens"}
    for i, entry in enumerate(entries):
        missing = required - set(entry)
        if missing:
            raise SystemExit(f"{ALIAS_MAP}: entry {i} missing {sorted(missing)}")
        if not entry["real_name"] or not entry["alias"]:
            raise SystemExit(f"{ALIAS_MAP}: entry {i} has an empty name or alias")
    if "free_text_deny" not in mapping:
        raise SystemExit(
            f"{ALIAS_MAP}: add a `free_text_deny` list to the alias map — an empty list is valid. "
            "An absent list is not an empty list: on a real corpus an empty deny set rewrites "
            "every ordinary-word occurrence of a single-token identity."
        )
    deny = mapping["free_text_deny"]
    if not isinstance(deny, list) or not all(isinstance(t, str) for t in deny):
        raise SystemExit(
            f"{ALIAS_MAP}: `free_text_deny` must be a list of lowercase tokens "
            "(an empty list is valid)"
        )
    if mapping.get("key_fingerprint") != _key_fingerprint():
        raise SystemExit(
            f"{ALIAS_MAP} was minted under a different key than {MINT_KEY}.\n"
            "Applying it would produce aliases the map cannot reverse. Restore the "
            "matching key, or move both aside and re-run `plan` from a clean tree."
        )


def _uncovered_roster_identities(mapping: dict) -> list[str]:
    """Personal identities in the CURRENT roster that the alias map does not cover.

    Every other check in this file reasons from the map. The map is a snapshot
    taken at `plan` time, and `plan` refuses to re-run without `--force` (which
    would re-mint and orphan every existing alias), so the map is expected to
    outlive many roster edits. Nothing else compares the two: a subject added to
    the roster after the last `plan` is absent from `entries`, so no pass is ever
    built for them, `apply` rewrites nothing, and `residue` looks for nothing --
    both commands exit 0 over a tree carrying that person's name in cleartext.
    That is a false green produced by the sampling frame, not by any pass
    (CARD-11): the thing being measured has grown and the measurement has not.

    A covered identity is one the map accounts for in either direction: still a
    real name awaiting rewrite (pre-`apply`), or already the minted alias
    (post-`apply`). Anything else is new since the last `plan`.

    Returns slugs, never names -- a caller may print the result.
    """
    roster = json.loads(_read(ROSTER))
    known = {e["real_name"] for e in mapping["entries"]} | {e["alias"] for e in mapping["entries"]}
    return sorted(
        i.get("slug", "<no-slug>")
        for i in roster["identities"]
        if i.get("bucket") == "personal" and i.get("name") not in known
    )


def _assert_roster_is_covered(mapping: dict) -> None:
    """Fail closed when the roster has grown past the alias map."""
    if uncovered := _uncovered_roster_identities(mapping):
        raise SystemExit(
            f"{len(uncovered)} personal identities in {ROSTER.name} are absent from {ALIAS_MAP.name}: "
            f"{uncovered}. They were added after the last `plan`, so no pass covers them and both "
            "`apply` and `verify` would report clean while their names sit in the tree in cleartext. "
            "Extend the map for the new subjects (minting under the existing key) before continuing."
        )


def _in_scope(rel: str) -> bool:
    return rel.startswith(SCAN_ALLOW) or "/" not in rel


def _tracked_files() -> list[tuple[Path, bool]]:
    """(path, in_scope) for every tracked text file. Out-of-scope files are
    returned too so `apply` can report name hits it deliberately did not fix."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    files = []
    for rel in out.split("\0"):
        if not rel or rel.lower().endswith(SKIP_SUFFIXES):
            continue
        files.append((REPO / rel, _in_scope(rel)))
    return files


def _map_free_text_deny(mapping: dict) -> set[str]:
    """Lowercased deny tokens from the map. Absent means empty (unit fixtures)."""
    raw = mapping.get("free_text_deny")
    if raw is None:
        return set()
    return {t.lower() for t in raw}


def _multi_token_regex(mapping: dict, singles: bool = False) -> tuple[re.Pattern, dict]:
    """One alternation over multi-token names, longest-first.

    With ``singles=True`` the alternation also carries single-token names
    whose token is not in the map's ``free_text_deny`` list. Callers pass
    that only for data and prose files. A map that never went through
    ``load_map`` and omits the block is treated as an empty deny so
    unit-constructed fixtures keep exercising the rewrite passes.
    """
    deny = _map_free_text_deny(mapping)
    multi = [
        e for e in mapping["entries"] if e["tokens"] > 1 or (singles and e["real_name"].lower() not in deny)
    ]
    by_key = {}
    parts = []
    for e in sorted(multi, key=lambda e: -len(e["real_name"])):
        # `%20` is a URL-encoded space. `%2520` is a double-encoded
        # percent sequence — a different string, not a case of `%20` —
        # and is out of scope.
        parts.append(re.escape(e["real_name"]).replace(r"\ ", r"(?:[\s_\-]|%20)+"))
        by_key[_name_key(e["real_name"])] = e
    if not parts:
        raise SystemExit("alias map contains no multi-token names")
    return re.compile(NBL + r"(?:" + "|".join(parts) + r")" + NBR, re.IGNORECASE), by_key


def _name_key(text: str) -> str:
    """Normalise a matched name so separators, including `%20`, collapse.

    `%2520` is left intact: it is a different encoding, not a case of `%20`.
    Collapsing `%20` first keeps `first%20last` keyed as `first last`;
    without that the `%` and the digits become their own tokens and the
    lookup misses, so rewrite would leave a match residue cannot ignore.
    """
    collapsed = re.sub(r"%20", " ", text, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", collapsed.lower()).strip()


def _render(alias: str, matched: str) -> str:
    """Mirror the matched token's separator and case so paths/slugs stay valid."""
    # `%20` is a separator, not a bare token. Prefer it so `first%20last`
    # keeps the encoded space rather than collapsing to the alias's first word.
    sep_match = re.search(r"%20|[\s_\-]", matched, flags=re.IGNORECASE)
    words = alias.split()
    if sep_match is None:
        # A bare token must stay a bare token. Expanding a single-token name into
        # the two-word display alias inserts a space into whatever slot it sat in:
        # `ccqw-linen.jpg` became `ccqw-cobalt orchard.jpg`, a path that resolves
        # to nothing. Map positionally instead -- token i of the name to word i of
        # the alias -- which for a single-token name is the alias's first word.
        words = words[:1]
    sep = sep_match.group(0) if sep_match else " "
    if matched.isupper():
        return sep.join(w.upper() for w in words)
    if matched.islower():
        return sep.join(w.lower() for w in words)
    return sep.join(words)


def _preserve_case(word: str, source: str) -> str:
    """Mirror Title / UPPER / lower of the source token onto a replacement.

    Family-word nouns are stored lowercase; positional aliases are stored
    Title-cased. Without this, a sentence-initial family-word hit becomes
    a lowercase alias (`Velmoth` → `harbor`) while a positional hit of
    the same shape stays Title (REV-D-09).
    """
    if source.isupper():
        return word.upper()
    if source.islower():
        return word.lower()
    if source.istitle():
        return word[:1].upper() + word[1:].lower()
    return word


def _substitute(text: str, rx: re.Pattern, by_key: dict) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        if _inside_hex_run(m.string, m.start(), m.end()):
            return m.group(0)
        key = _name_key(m.group(0))
        entry = by_key.get(key)
        if entry is None:
            return m.group(0)
        count += 1
        return _render(entry["alias"], m.group(0))

    return rx.sub(repl, text), count


def _quoted_exact_regex(mapping: dict) -> tuple[re.Pattern | None, dict]:
    """Whole-string JSON tokens (`"Name"`) for the four single-token names.

    Matching both quotes means only a complete string value or key can match, so
    a 3-4 character common word embedded in a caption is never touched. Applied
    to .json files only -- in Python/TS a bare `"Mark"` literal is far more
    likely to be unrelated. Preserves byte formatting; no reserialisation.
    """
    singles: dict[str, dict] = {}
    for e in mapping["entries"]:
        if e["tokens"] == 1:
            singles[e["real_name"]] = {"replacement": e["alias"]}
        if not re.search(r"[_\-]", e["original_slug"]):
            singles[e["original_slug"]] = {"replacement": e["alias_slug"]}
    if not singles:
        return None, {}
    alt = "|".join(re.escape(n) for n in sorted(singles, key=len, reverse=True))
    return re.compile(r'"(' + alt + r')"'), singles


def _slug_regex(mapping: dict) -> tuple[re.Pattern | None, dict]:
    """Retire every superseded slug. Nearly all of them are the real name
    slugified, and the roster's `slug` field must stay in step with `name`."""
    leaky = {
        e["original_slug"].lower(): e
        for e in mapping["entries"]
        # Single-token slugs are 3-4 character common words; matching them in
        # free text rewrites unrelated prose and identifiers. They go through
        # the quoted-JSON pass instead.
        if e["original_slug"] != e["alias_slug"] and re.search(r"[_\-]", e["original_slug"])
    }
    if not leaky:
        return None, {}
    alt = "|".join(re.escape(s) for s in sorted(leaky, key=len, reverse=True))
    return re.compile(NBL + r"(?:" + alt + r")" + NBR, re.IGNORECASE), leaky


def _concatenated_regex(mapping: dict) -> tuple[re.Pattern | None, dict, tuple[dict, ...]]:
    """Multi-token names written with no separator at all (`firstnamelastname`).

    Social-media exports name their files `<first><last>-<ts>_<id>.jpg`, and
    they also glue that form *inside* a longer alphanumeric run -- a handle
    like `<prefix><first><last>_<id>`. Every other pass is anchored on
    NBL/NBR, which require a non-alphanumeric character on each side, so an
    embedded occurrence is structurally unreachable.

    Two tiers, one alternation, longest-first so a shorter joined form
    cannot win inside a longer one. `_inside_hex_run()` is applied to
    both tiers by the rewrite/residue callers:

    * ``len(joined) >= CONCAT_UNANCHORED_MIN`` (8) — fully unanchored
      (BR-22). That many letters of a real full name cannot plausibly
      collide with an ordinary word.
    * ``2 <= tokens`` and ``len(joined) < 8`` — letter-only anchors
      ``(?<![A-Za-z])`` / ``(?![A-Za-z])``. The floor's purpose was an
      in-word collision, not a digit, ``@``, or ``/`` neighbour; those
      are the live leak shapes a silent ``continue`` made `verify` miss
      (BR-25).

    Whatever is still not admitted — after the tier, only names with
    fewer than two tokens — is returned as ``dropped``, each with a
    reason. Callers print that list. A floor that ``continue``s is a
    measurement the checker inherits.
    """
    long_forms: dict[str, str] = {}
    short_forms: dict[str, str] = {}
    excluded: list[dict] = []
    no_alias: list[int] = []
    for entry in mapping["entries"]:
        real = [t for t in re.split(r"[^A-Za-z0-9]+", entry["real_name"]) if t]
        alias = [t for t in re.split(r"[^A-Za-z0-9]+", entry["alias"]) if t]
        joined = "".join(real)
        if len(real) < 2:
            excluded.append(
                {
                    "reason": (
                        "single-token name; no concatenation exists"
                        if len(real) == 1
                        else "empty name; no concatenation exists"
                    ),
                    "tokens": len(real),
                    "joined_length": len(joined),
                }
            )
            continue
        if not alias:
            # No alias to substitute is a map defect, not a name to skip.
            no_alias.append(len(joined))
            continue
        # Token counts need not match. A concatenation has no internal
        # boundaries, so the whole joined name maps to the whole joined alias --
        # requiring len(alias) >= len(real) silently dropped four 3-token names
        # that carry 2-token aliases, and an independent oracle then found 8
        # occurrences of them that `verify` was reporting as zero.
        dest = long_forms if len(joined) >= CONCAT_UNANCHORED_MIN else short_forms
        dest[joined.lower()] = "".join(alias)
    if no_alias:
        raise SystemExit(
            f"{len(no_alias)} multi-token entries (name lengths {sorted(no_alias)}) have no alias "
            "tokens, so their concatenated form cannot be rewritten. Fix the alias map; "
            "skipping them would make `verify` blind to exactly those names."
        )
    forms = {**long_forms, **short_forms}
    dropped = tuple(excluded)
    if not forms:
        return None, {}, dropped
    # Longest-first across both tiers. Short alternatives carry the
    # letter-only lookaround; long ones stay fully unanchored.
    alts: list[str] = []
    for form in sorted(forms, key=len, reverse=True):
        escaped = re.escape(form)
        if len(form) >= CONCAT_UNANCHORED_MIN:
            alts.append(escaped)
        else:
            alts.append(_CONCAT_LETTER_NBL + escaped + _CONCAT_LETTER_NBR)
    return re.compile(r"(?:" + "|".join(alts) + r")", re.IGNORECASE), forms, dropped


def _concat_exclusion_line(dropped: tuple[dict, ...] | list[dict]) -> str:
    """One printed measurement of what the concat builder refused.

    Always a complete sentence, including the zero case: a `0` that
    cannot say what it excluded is not a measurement. Names are not
    included — the caller may print this on `apply` and `verify`.
    """
    n = len(dropped)
    if n == 0:
        return "concat exclusions: 0 dropped"
    by_reason: dict[str, int] = {}
    for item in dropped:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    detail = "; ".join(f"{count}× {reason}" for reason, count in sorted(by_reason.items()))
    return f"concat exclusions: {n} dropped ({detail})"


_MEDIA_PATH_RX = re.compile(r"[\w./\-]*[\w\-]+\.(?:jpg|jpeg|png|webp)", re.IGNORECASE)


def _token_index(mapping: dict) -> dict[str, list[tuple[str, str, int]]]:
    """token -> [(identity key, positional alias word, name width)].

    Corpus filenames carry name tokens in orders the full-name pass cannot see:
    surname-first (`harbor-current-*.jpg`), given-name-only (`kestrel-pool.jpg`), and
    two-of-three-token subsets. A forward-order alternation misses all of them,
    which is why 13k name occurrences survived the first pass in filenames alone.
    """
    index: dict[str, list[tuple[str, str, int]]] = {}
    for entry in mapping["entries"]:
        real, alias = entry["real_name"].split(), entry["alias"].split()
        for i, token in enumerate(real):
            if len(token) < 3 or i >= len(alias):
                continue
            index.setdefault(token.lower(), []).append((entry["real_name"], alias[i], len(real)))
    return index


def _media_stem_pass(
    text: str, index: dict, family: dict[str, str]
) -> tuple[str, int, set[str]]:
    """Rewrite name tokens inside image filenames only.

    Scoped to the filename stem so ordinary prose is untouched: `coral` is a
    dress in a caption and a surname in a roster, and only the filename context
    is safe to decide. Each stem votes for the identity it shares the most
    tokens with. A lone token that maps to more than one identity is rewritten
    with the shared family word when one exists (BR-29); otherwise it is left
    alone and reported rather than guessed at.
    """
    count = 0
    unresolved: set[str] = set()

    def repl(match: re.Match) -> str:
        nonlocal count
        whole = match.group(0)
        head, _, filename = whole.rpartition("/")
        stem, dot, ext = filename.rpartition(".")
        parts = re.split(r"([^A-Za-z0-9]+)", stem)
        votes: dict[str, int] = {}
        width: dict[str, int] = {}
        for part in parts:
            for identity, _word, size in index.get(part.lower(), ()):
                votes[identity] = votes.get(identity, 0) + 1
                width[identity] = size
        if not votes:
            return whole
        # Rank by tokens matched, then by coverage: a stem token that is somebody's
        # entire name identifies them outright, while the same token as one part of
        # a three-token name is weak evidence. Without the tie-break the two read as
        # equal and the stem is skipped in source files while the sibling JSON --
        # which reached it through the single-token pass -- rewrites it, leaving a
        # test literal pointing at a path the manifest no longer contains.
        best = max((v, v == width[k]) for k, v in votes.items())
        winners = [k for k, v in votes.items() if (v, v == width[k]) == best]
        rebuilt, changed = [], False
        for part in parts:
            options = index.get(part.lower())
            if not options:
                rebuilt.append(part)
                continue
            words = {w for ident, w, _s in options if ident in winners}
            if len(words) != 1:
                shared = family.get(part.lower())
                if shared is None:
                    # Genuinely no replacement: not a shared family token,
                    # or the builder declined it. Keep unresolved's meaning
                    # rather than emptying it by definition (CARD-08).
                    unresolved.add(part.lower())
                    rebuilt.append(part)
                    continue
                word = shared
            else:
                word = words.pop()
            rebuilt.append(word.upper() if part.isupper() else word.lower() if part.islower() else word)
            changed = True
        if not changed:
            return whole
        count += 1
        return (head + "/" if head else "") + "".join(rebuilt) + dot + ext

    return _MEDIA_PATH_RX.sub(repl, text), count, unresolved


_WORDLIST_ENV = "PRIV1_WORDLIST"
_DEFAULT_WORDLIST = Path("/usr/share/dict/words")


def _resolved_wordlist_path() -> Path:
    override = os.environ.get(_WORDLIST_ENV)
    if override:
        return Path(override)
    return _DEFAULT_WORDLIST


@lru_cache(maxsize=1)
def _load_wordlist() -> tuple[frozenset[str], str, str]:
    """Load the exclusion wordlist. Fail closed if missing or empty (rg-008).

    Returns ``(words, sha256 hex, resolved path)``. Cached so builders,
    ``plan``, ``apply`` and ``verify`` share one load. Tests that change
    ``$PRIV1_WORDLIST`` must ``cache_clear()``.
    """
    path = _resolved_wordlist_path()
    if not path.is_file():
        raise SystemExit(
            f"wordlist not found: {path}. "
            f"Set {_WORDLIST_ENV} to a readable non-empty word list "
            f"(default {_DEFAULT_WORDLIST})."
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemExit(
            f"wordlist unreadable: {path} ({exc}). "
            f"Set {_WORDLIST_ENV} to a readable non-empty word list "
            f"(default {_DEFAULT_WORDLIST})."
        ) from exc
    words = {w.strip().lower() for w in raw.decode(errors="ignore").splitlines() if w.strip()}
    if not words:
        raise SystemExit(
            f"wordlist is empty: {path}. "
            f"Set {_WORDLIST_ENV} to a readable non-empty word list "
            f"(default {_DEFAULT_WORDLIST})."
        )
    return frozenset(words), hashlib.sha256(raw).hexdigest(), str(path)


def _wordlist_record() -> dict:
    words, digest, path = _load_wordlist()
    return {"path": path, "sha256": digest, "count": len(words)}


def _wordlist_line() -> str:
    words, digest, _path = _load_wordlist()
    return f"wordlist: {len(words)} words (sha256 {digest[:12]}..)"


def _assert_wordlist_pin(mapping: dict) -> None:
    """Fail closed when the map has no wordlist pin, or the live list drifted.

    An absent block is not "any host wordlist is fine" (CARD-07). Re-pin
    with ``plan --pin-wordlist``; do not invent the field here (rg-015).
    """
    recorded = mapping.get("wordlist")
    if recorded is None:
        raise SystemExit(
            "alias map has no wordlist block. "
            "Run `plan --pin-wordlist` to record the live wordlist without reminting. "
            "An absent pin cannot be treated as 'any host wordlist is fine'."
        )
    _words, digest, _path = _load_wordlist()
    expected = recorded.get("sha256")
    if expected != digest:
        raise SystemExit(
            f"wordlist sha256 mismatch: map has {expected}, live wordlist is {digest}. "
            f"Restore the recorded list via {_WORDLIST_ENV}, or re-pin with "
            "`plan --pin-wordlist` after a deliberate wordlist change."
        )


def _ambiguous_stem_line(n: int) -> str:
    """Count and reason only — never the token itself (CARD-07)."""
    return f"ambiguous media stems: {n} left unresolved (token maps to >1 identity)"


def _family_words(by_token: dict[str, set[str]]) -> dict[str, str]:
    """One shared replacement per name token that more than one identity carries.

    A rare surname two roster members share resolves to two different alias
    words positionally, so the unambiguous-token rule skips it -- and a rare
    surname in the clear is identifying on its own. Mint a single family word
    for it instead: the family link survives (it survives in the real data too),
    nobody is misattributed, and the token stops being a name.
    """
    out: dict[str, str] = {}
    for token, aliases in sorted(by_token.items()):
        if len(aliases) <= 1:
            continue
        h = int(_hash("family#" + token)[:12], 16)
        out[token] = _NOUN[h % len(_NOUN)]
    return out


def _ambiguous_family_words(index: dict) -> tuple[dict[str, str], tuple[dict, ...]]:
    """One shared replacement per token carried by two or more identities.

    Built over `_token_index`, not over the given-name `by_token`. The
    given-name builder drops dictionary words before `_family_words` ever
    sees them, which is why a shared surname that is also ordinary English
    had no repair path in a filename stem (BR-29). Reuses `_family_words`
    so a token that is ambiguous in both places gets the same noun.

    A token two identities share but that already has one positional alias
    word is declined, not reminted: media-stem already has a unique
    replacement. Whatever is declined is returned as ``dropped``, each
    with a reason, never the token. Callers print that list, including
    the zero case.
    """
    by_token: dict[str, set[str]] = {}
    dropped: list[dict] = []
    for token, options in sorted(index.items()):
        idents = {ident for ident, _w, _s in options}
        if len(idents) < 2:
            continue
        aliases = {w for _ident, w, _s in options}
        if len(aliases) <= 1:
            dropped.append(
                {
                    "reason": "shared token already has one alias word",
                    "identities": len(idents),
                }
            )
            continue
        by_token[token] = aliases
    return _family_words(by_token), tuple(dropped)


def _ambiguous_family_exclusion_line(dropped: tuple[dict, ...] | list[dict]) -> str:
    """One printed measurement of what the stem-family builder refused.

    Always a complete sentence, including the zero case. Names are not
    included — one roster token is itself a media stem, and a message
    that echoes what it refused would publish the thing the scrub
    removed. The caller may print this on `apply` and `verify`.
    """
    n = len(dropped)
    if n == 0:
        return "ambiguous family exclusions: 0 dropped"
    by_reason: dict[str, int] = {}
    for item in dropped:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    detail = "; ".join(f"{count}× {reason}" for reason, count in sorted(by_reason.items()))
    return f"ambiguous family exclusions: {n} dropped ({detail})"


@lru_cache(maxsize=1)
def _nonpersonal_identities() -> tuple[dict, ...]:
    """Roster identities the scrub promises not to touch (celebs today).

    Read from the roster rather than the alias map: the map contains only the
    personal entries, so nothing built from it can know what must be preserved.
    Cached because `apply` rewrites the roster as it goes, and the set of people
    who are off limits must be the one read before the first byte moved.
    """
    return tuple(i for i in json.loads(_read(ROSTER))["identities"] if i.get("bucket") != "personal")


def _protected_literals(identities=None) -> list[str]:
    """Exact strings belonging to a non-personal identity, masked before any pass.

    The passes below are token-level by necessity -- corpus filenames carry name
    tokens in orders no full-name alternation can see -- and a token index built
    from personal entries alone has no way to know that a surname inside
    `celebs/<first>_<last>_<id>.webp` belongs to somebody the scrub promised to
    leave alone. It did not know, and it rewrote three real celebrities: two had
    their media paths renamed while their `name` field kept saying who they
    really were, desynchronising the name-to-path join the bake-off scores
    against, and one was renamed outright, so a correct recognition of that
    person now scores as a miss against rewritten ground truth.

    Masking exact literals rather than blacklisting tokens keeps the fix from
    creating a leak of its own: a personal subject who shares a surname with a
    celebrity is still scrubbed everywhere except inside that celebrity's own
    name, slug, and media path (MODEL-04 -- the identity key is the record, not
    the name token).
    """
    lits: set[str] = set()
    for i in identities if identities is not None else _nonpersonal_identities():
        lits.add(i.get("name", ""))
        lits.add(i.get("slug", ""))
        for path in set(i.get("primary_of", [])) | set(i.get("appears_in", [])):
            lits.add(path)
            lits.add(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    # Below four characters a "literal" is a fragment that would mask unrelated
    # text; the passes themselves do not fire that short either.
    return sorted((s for s in lits if len(s) >= 4), key=len, reverse=True)


def _nonpersonal_tokens(identities=None) -> set[str]:
    """Name tokens carried by a non-personal identity, for the bare-token pass.

    Masking covers every *whole* protected literal, but `_given_name_regex`
    rewrites a lone token in running prose, where there is no literal to mask:
    a celebrity's bare given name in a caption is not their full name. Nothing
    in the text says which person it is, so the pass declines -- the same
    one-sided rule it already applies to dictionary words.
    """
    src = identities if identities is not None else _nonpersonal_identities()
    return {t.lower() for i in src for t in re.split(r"[^A-Za-z]+", i.get("name", "")) if len(t) >= 4}


def _given_name_regex(mapping: dict, protected_tokens: set[str] | None = None) -> tuple[re.Pattern | None, dict, list[str]]:
    """Bare name tokens that can only be one person and are not ordinary words.

    The full-name pass cannot see `Nylphra relax by a lake` or `Qorvexes'`; the
    residue is a real given name in readable prose. The filter is deliberately
    one-sided: a token that is also a dictionary word (`qorvist`, `brook`, `self`),
    that more than one identity shares, or that a non-personal identity also
    carries is left alone, so this under-scrubs rather than rewriting an
    ordinary caption word -- or a real celebrity -- into somebody's pseudonym.

    The third return value names the tokens dropped for the last reason. A
    silent drop here is the shape of gap that reads as coverage: the pass stops
    looking, so `verify` stops counting, and the tree scans clean because
    nothing is measuring (CARD-11). Callers print it.
    """
    protected = _nonpersonal_tokens() if protected_tokens is None else protected_tokens
    words, _digest, _path = _load_wordlist()
    by_token: dict[str, set[str]] = {}
    deferred: set[str] = set()
    for entry in mapping["entries"]:
        real, alias = entry["real_name"].split(), entry["alias"].split()
        for i, token in enumerate(real):
            if len(token) < 4 or i >= len(alias) or token.lower() in words:
                continue
            if token.lower() in protected:
                deferred.add(token.lower())
                continue
            by_token.setdefault(token.lower(), set()).add(alias[i])
    resolved = {t: next(iter(a)) for t, a in by_token.items() if len(a) == 1}
    resolved.update(_family_words(by_token))
    if not resolved:
        return None, {}, sorted(deferred)
    alt = "|".join(re.escape(t) for t in sorted(resolved, key=len, reverse=True))
    return re.compile(NBL + r"(" + alt + r")" + NBR, re.IGNORECASE), resolved, sorted(deferred)


# Optional middle initial between a real-name token and an alias token of
# the same identity: `Qorvist K. quarry`, `Qorvist K quarry`, or `Qorvist quarry`.
# Letter-only anchors — the same narrowing the short concat tier uses —
# so a digit/`@`/`/` neighbour still matches and an in-word collision
# does not. Built from the alias map, never the wordlist (BR-27).
# IGNORECASE is not cosmetic here: under it `[A-Za-z]` also matches the
# characters that case-fold into ASCII letters -- U+017F LATIN SMALL LETTER
# LONG S and U+212A KELVIN SIGN among them. The match pattern carries the
# flag, so this re-parse of the matched text must carry it too. Without it
# the two disagree, `rewrite()` declines a span that `residue()` counts, and
# `verify` reports residue `apply` can never clear (PRIV-1-BR-30).
_ADJACENT_PARSE = re.compile(
    r"^([A-Za-z]+)((?:[ \t]+[A-Za-z]\.?)?)([ \t]+)([A-Za-z]+)$", re.IGNORECASE
)


def _adjacent_alias_regex(mapping: dict) -> tuple[re.Pattern | None, dict, tuple[dict, ...]]:
    """Real-name token sitting next to an alias token of the same identity.

    The given-name pass excludes dictionary words on purpose — rewriting
    them would corrupt unrelated English. That exclusion is correct in
    isolation. What it ignores is the neighbour: `Qorvist quarry`, where
    `quarry` is a surname this scrub itself minted, is not ordinary
    English. The adjacency is an identity match, not a heuristic.

    Both halves come from the alias map. The builder never reads the
    wordlist: if it did, editing a word out of the exclusion list would
    drop the pair while the exposed surface stayed on disk — measurement
    derived from the thing being changed (CARD-08 / BR-19).

    A pair is emitted only when the leading token is a real-name token
    of identity X with a positional alias, and the adjacent token is a
    *different-index* alias token of the same X — or a family-word
    replacement of a different-index real token of the same X. Shared
    surnames become one minted noun, not either identity's positional
    word, so pairing only against positional aliases leaves
    `Qorvist harbor` and `Qorvist K. harbor` on disk after the
    given-name pass (REV-D-03). Same-index pairing would turn
    `Qorvist cobalt` into `Cobalt cobalt`. A pair that two
    identities resolve to different replacements is refused, not
    guessed. One-letter leading tokens are refused and counted: letter
    anchors cannot separate `a quarry` from the English article.

    Whatever is still not admitted is returned as ``dropped``, each
    with a reason. Callers print that list. A floor that ``continue``s
    is a measurement the checker inherits.
    """
    collected: dict[tuple[str, str], set[str]] = {}
    dropped: list[dict] = []
    no_alias: list[int] = []

    # Family words are minted from the map's own token→alias sets, never
    # the wordlist: the adjacent builder must not become silent because
    # a surname was edited out of the exclusion list (BR-19 / CARD-08).
    by_token: dict[str, set[str]] = {}
    parsed_entries: list[tuple[list[str], list[str]]] = []
    for entry in mapping["entries"]:
        real = [t for t in re.split(r"[^A-Za-z]+", entry.get("real_name", "")) if t]
        alias = [t for t in re.split(r"[^A-Za-z]+", entry.get("alias", "")) if t]
        parsed_entries.append((real, alias))
        for i, token in enumerate(real):
            if i < len(alias):
                by_token.setdefault(token.lower(), set()).add(alias[i])
    family = _family_words(by_token)

    for real, alias in parsed_entries:
        if not real:
            dropped.append({"reason": "empty name; no adjacent pair exists", "tokens": 0})
            continue
        if not alias:
            no_alias.append(len(real))
            continue

        before = len(dropped)
        contributed = False
        for i, token in enumerate(real):
            if len(token) < 2:
                dropped.append(
                    {
                        "reason": (
                            "single-letter token; letter-anchor cannot "
                            "separate it from the English article"
                        ),
                        "tokens": len(real),
                    }
                )
                continue
            if i >= len(alias):
                dropped.append({"reason": "no positional alias token", "tokens": len(real)})
                continue
            replacement = alias[i]
            for j, adj in enumerate(alias):
                if j == i or adj.lower() == token.lower():
                    continue
                # `.lower()`, not `.casefold()`: these come from the map, and
                # `re.split(r"[^A-Za-z]+")` above has already dropped every
                # non-ASCII letter, so the two are identical here and no
                # mutant can tell them apart. The document side is different
                # and does need casefold -- see `_adjacent_repl` (BR-30).
                collected.setdefault((token.lower(), adj.lower()), set()).add(replacement)
                contributed = True
            for k, other in enumerate(real):
                if k == i:
                    continue
                fw = family.get(other.lower())
                if fw is None or fw.lower() == token.lower():
                    continue
                collected.setdefault((token.lower(), fw.lower()), set()).add(replacement)
                contributed = True
        if not contributed and len(dropped) == before:
            dropped.append({"reason": "no distinct alias neighbour", "tokens": len(real)})

    if no_alias:
        raise SystemExit(
            f"{len(no_alias)} entries (name lengths {sorted(no_alias)}) have no alias "
            "tokens, so an adjacent real+alias pair cannot be rewritten. Fix the alias "
            "map; skipping them would make `verify` blind to exactly those names."
        )

    pairs: dict[tuple[str, str], str] = {}
    for key, replacements in collected.items():
        if len(replacements) != 1:
            dropped.append({"reason": "pair maps to >1 identity", "tokens": 2})
            continue
        pairs[key] = next(iter(replacements))

    if not pairs:
        return None, {}, tuple(dropped)

    alts: list[str] = []
    for lead, adj in sorted(pairs, key=lambda k: (len(k[0]) + len(k[1]), len(k[0])), reverse=True):
        alts.append(re.escape(lead) + r"(?:[ \t]+[A-Za-z]\.?)?[ \t]+" + re.escape(adj))
    rx = re.compile(
        _CONCAT_LETTER_NBL + r"(?:" + "|".join(alts) + r")" + _CONCAT_LETTER_NBR,
        re.IGNORECASE,
    )
    return rx, pairs, tuple(dropped)


def _adjacent_exclusion_line(dropped: tuple[dict, ...] | list[dict]) -> str:
    """One printed measurement of what the adjacent-pair builder refused.

    Always a complete sentence, including the zero case. Names are not
    included — one of the ambiguous stems is itself a roster given name,
    and a message that echoes what it refused would publish the thing
    the scrub removed. The caller may print this on `apply` and `verify`.
    """
    n = len(dropped)
    if n == 0:
        return "adjacent exclusions: 0 dropped"
    by_reason: dict[str, int] = {}
    for item in dropped:
        by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
    detail = "; ".join(f"{count}× {reason}" for reason, count in sorted(by_reason.items()))
    return f"adjacent exclusions: {n} dropped ({detail})"


class _Passes:
    """Every substitution pass, built once and reused by apply *and* verify.

    v1 built four of the six passes in `verify` and none of the token-level
    ones, so `verify: 0 residue` was structurally incapable of seeing the two
    leak classes the reviewers reproduced by hand. A single shared object makes
    the checker and the rewriter provably the same code (CARD-08).
    """

    # A digit run between NULs. NUL cannot occur in a decoded source file, and
    # no pass matches bare digits, so a placeholder is inert to every one of
    # them -- which is the whole point: a masked span must come back byte-identical.
    _MASK_RX = re.compile("\x00(\\d+)\x00")

    def __init__(self, mapping: dict, identities=None) -> None:
        # Both protections come from one roster read, so the literal mask and the
        # bare-token filter can never disagree about who is off limits.
        idents = _nonpersonal_identities() if identities is None else identities
        self.name_rx, self.by_key = _multi_token_regex(mapping)
        self.data_rx, self.data_key = _multi_token_regex(mapping, singles=True)
        self.quoted_rx, self.singles = _quoted_exact_regex(mapping)
        self.slug_rx, self.leaky = _slug_regex(mapping)
        self.token_index = _token_index(mapping)
        self.ambiguous_family, self.ambiguous_family_dropped = _ambiguous_family_words(self.token_index)
        self.given_rx, self.given, self.given_deferred = _given_name_regex(mapping, _nonpersonal_tokens(idents))
        self.concat_rx, self.concat, self.concat_dropped = _concatenated_regex(mapping)
        self.adjacent_rx, self.adjacent, self.adjacent_dropped = _adjacent_alias_regex(mapping)
        lits = _protected_literals(idents)
        self.protected = lits
        self.protect_rx = re.compile("|".join(re.escape(s) for s in lits)) if lits else None

    def _mask(self, text: str) -> tuple[str, list[str]]:
        """Hide every non-personal identity's own strings from every rewrite pass."""
        if self.protect_rx is None:
            return text, []
        held: list[str] = []

        def hold(m: re.Match) -> str:
            held.append(m.group(0))
            return f"\x00{len(held) - 1}\x00"

        return self.protect_rx.sub(hold, text), held

    def _unmask(self, text: str, held: list[str]) -> str:
        if not held:
            return text
        out = self._MASK_RX.sub(lambda m: held[int(m.group(1))], text)
        if "\x00" in out:
            # A pass ate or split a placeholder, so a protected span cannot be
            # restored verbatim. Raising is the only honest outcome: the
            # alternative is writing a file with NULs in it (CARD-07).
            raise SystemExit("protected-span mask was corrupted by a rewrite pass -- refusing to write.")
        return out

    def rewrite(self, text: str, suffix: str) -> tuple[str, dict[str, int], set[str]]:
        counts = {"name": 0, "single": 0, "slug": 0, "media": 0, "given": 0, "concat": 0, "adjacent": 0}
        text, held = self._mask(text)

        # Order is load-bearing, most precise pass first. A whole-string JSON
        # token names the identity unambiguously and knows whether it sits in a
        # `name` or a `slug` position; the looser passes below cannot tell, and
        # would rewrite `"linen"` (a slug) into a space-separated display alias.
        if self.quoted_rx is not None and suffix == ".json":

            def _quoted_repl(m: re.Match) -> str:
                counts["single"] += 1
                return '"' + self.singles[m.group(1)]["replacement"] + '"'

            text = self.quoted_rx.sub(_quoted_repl, text)

        # Superseded slugs next: `first_last` would otherwise be caught by the
        # name pass and rendered with the wrong separator, desynchronising it
        # from the roster's `slug` field.
        if self.slug_rx is not None:

            def _slug_repl(m: re.Match) -> str:
                if _inside_hex_run(m.string, m.start(), m.end()):
                    return m.group(0)
                counts["slug"] += 1
                return self.leaky[m.group(0).lower()]["alias_slug"]

            text = self.slug_rx.sub(_slug_repl, text)

        # Separator-free forms. No other pass can reach these -- they are one
        # unbroken alphanumeric run -- so order relative to the rest is free.
        if self.concat_rx is not None:

            def _concat_repl(m: re.Match) -> str:
                if _inside_hex_run(m.string, m.start(), m.end()):
                    return m.group(0)
                counts["concat"] += 1
                matched, alias = m.group(0), self.concat[m.group(0).lower()]
                if matched.isupper():
                    return alias.upper()
                if matched.islower():
                    return alias.lower()
                return alias

            text = self.concat_rx.sub(_concat_repl, text)

        if suffix.lower() in SINGLE_TOKEN_FREE_TEXT_SUFFIXES:
            text, n_name = _substitute(text, self.data_rx, self.data_key)
        else:
            text, n_name = _substitute(text, self.name_rx, self.by_key)
        counts["name"] = n_name

        text, n_media, unresolved = _media_stem_pass(text, self.token_index, self.ambiguous_family)
        counts["media"] = n_media

        # Unlike the single-token pass this one emits exactly one bare word, so it
        # is safe in source too: `tanner = ...` becomes `cobalt = ...`, still a
        # valid identifier, where a two-word display alias would be a SyntaxError.
        if self.given_rx is not None:

            def _given_repl(m: re.Match) -> str:
                if _inside_hex_run(m.string, m.start(), m.end()):
                    return m.group(0)
                counts["given"] += 1
                word = self.given[m.group(1).lower()]
                return _preserve_case(word, m.group(1))

            text = self.given_rx.sub(_given_repl, text)

        # After given-name: a unique real surname has become the minted
        # noun, so a leftover dictionary given name now sits next to an
        # alias token of the same identity. Residue also runs this pass
        # on the mixed form already on disk (BR-27).
        if self.adjacent_rx is not None:

            def _adjacent_repl(m: re.Match) -> str:
                if _inside_hex_run(m.string, m.start(), m.end()):
                    return m.group(0)
                parsed = _ADJACENT_PARSE.match(m.group(0))
                replacement = None
                if parsed is not None:
                    lead, mid, sep, adj = parsed.groups()
                    replacement = self.adjacent.get((lead.casefold(), adj.casefold()))
                if replacement is None:
                    # Unreachable by construction: the pattern is built from
                    # these exact pairs and the re-parse now shares its flags.
                    # Reaching it means the two have drifted apart, and the
                    # failure mode is silent -- `rewrite()` would leave a span
                    # that `residue()` still counts, so `verify` could never
                    # go clean and no counter would say why. Raise instead of
                    # returning the span unchanged. The message reports the
                    # non-ASCII codepoints only, never the token (BR-30).
                    odd = sorted({f"U+{ord(c):04X}" for c in m.group(0) if ord(c) > 127})
                    raise SystemExit(
                        "adjacent pass matched a span it cannot re-parse or look up "
                        f"(length {len(m.group(0))}"
                        + (f", non-ASCII {', '.join(odd)}" if odd else "")
                        + "). The match pattern and _ADJACENT_PARSE have drifted; "
                        "skipping it would leave residue that `verify` counts and "
                        "`apply` can never clear."
                    )
                counts["adjacent"] += 1
                if lead.isupper():
                    word = replacement.upper()
                elif lead.islower():
                    word = replacement.lower()
                else:
                    word = replacement
                return word + mid + sep + adj

            text = self.adjacent_rx.sub(_adjacent_repl, text)

        return self._unmask(text, held), counts, unresolved

    def rewrite_path(self, rel: str) -> str:
        """Same passes against a repo-relative path. A tracked filename that
        embeds a real name leaks it in `git ls-files` no matter how clean the
        file's contents are."""
        head, _, tail = rel.rpartition("/")
        new_tail, _counts, _unresolved = self.rewrite(tail, Path(tail).suffix)
        new_tail = new_tail.replace("/", "-")  # a rendered alias must not invent a directory
        return (head + "/" if head else "") + new_tail

    def residue(self, text: str, suffix: str) -> dict[str, int]:
        """Count what each pass *would still* rewrite. Same builders as
        `rewrite`, so a pass cannot exist in one and be missing in the other.

        Masked identically to `rewrite`. A protected span the rewriter will not
        touch must not be counted as residue either, or `verify` reports a
        permanent non-zero over text it has decided is correct."""
        found = {}
        text, _held = self._mask(text)
        rx = self.data_rx if suffix.lower() in SINGLE_TOKEN_FREE_TEXT_SUFFIXES else self.name_rx

        def visible(pattern: re.Pattern) -> int:
            # Same refusal rewrite applies. findall would count a match sitting
            # inside a sha256 pin that apply will not touch, and after concat
            # is unanchored that is a permanent verify-red on a clean tree.
            return sum(
                1
                for m in pattern.finditer(text)
                if not _inside_hex_run(text, m.start(), m.end())
            )

        if n := visible(rx):
            found["name"] = n
        if self.slug_rx is not None and (n := visible(self.slug_rx)):
            found["slug"] = n
        if self.quoted_rx is not None and suffix == ".json" and (n := len(self.quoted_rx.findall(text))):
            found["single"] = n
        _out, n_media, unresolved = _media_stem_pass(text, self.token_index, self.ambiguous_family)
        if n_media:
            found["media"] = n_media
        if unresolved:
            # Stems the family backstop still cannot rewrite. A skip
            # with no replacement is residue; counting it keeps verify's
            # exit honest rather than emptying unresolved by definition
            # (BR-15, CARD-08).
            found["media_ambiguous"] = len(unresolved)
        if self.given_rx is not None and (n := visible(self.given_rx)):
            found["given"] = n
        if self.concat_rx is not None and (n := visible(self.concat_rx)):
            found["concat"] = n
        if self.adjacent_rx is not None and (n := visible(self.adjacent_rx)):
            found["adjacent"] = n
        return found


def _pin_existing_map_wordlist() -> int:
    """Write only the ``wordlist`` block onto an existing map. No remint."""
    if not ALIAS_MAP.is_file():
        raise SystemExit(
            f"alias map not found: {ALIAS_MAP}\n"
            "`plan --pin-wordlist` records a wordlist pin on an existing map; "
            "it will not mint one. Run `plan` first, or point ACX_CORPUS_PRIVATE_DIR "
            "at the directory that holds the map."
        )
    try:
        mapping = json.loads(ALIAS_MAP.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"{ALIAS_MAP}: malformed JSON ({exc}). "
            "Restore the alias map from the private corpus store, or re-run `plan` "
            "from a clean tree if the file is unrecoverable."
        ) from exc
    if mapping.get("wordlist") is not None:
        _assert_wordlist_pin(mapping)
    mapping["wordlist"] = _wordlist_record()
    ALIAS_MAP.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wordlist pin written: {ALIAS_MAP}")
    print(f"  {_wordlist_line()}")
    return 0


def cmd_plan(args) -> int:
    pin_wordlist = getattr(args, "pin_wordlist", False)
    force = getattr(args, "force", False)
    if pin_wordlist and force:
        raise SystemExit(
            "`--pin-wordlist` and `--force` cannot be combined. "
            "`--pin-wordlist` records the live wordlist on the existing map; "
            "`--force` remints every alias."
        )
    if pin_wordlist:
        return _pin_existing_map_wordlist()
    if ALIAS_MAP.is_file() and not force:
        raise SystemExit(
            f"{ALIAS_MAP} already exists. Re-planning re-mints every alias, which "
            "orphans any rewrite already applied to the tree. Pass --force if that "
            "is what you want."
        )
    _load_key(create=True)
    mapping = build_map()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    ALIAS_MAP.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ALIAS_MAP.chmod(0o600)
    minted = sum(1 for e in mapping["entries"] if e["slug_was_name_derived"])
    single = sum(1 for e in mapping["entries"] if e["tokens"] == 1)
    print(f"alias map written: {ALIAS_MAP}")
    print(f"  mint key                    : {MINT_KEY} (untracked, chmod 600)")
    print(f"  key fingerprint             : {mapping['key_fingerprint']}")
    print(f"  personal identities aliased : {mapping['personal_identities']}")
    print(f"  celeb identities left intact: {mapping['celeb_identities_left_intact']}")
    print(f"  slugs minted (were name-derived): {minted}")
    print(f"  single-token names (structural-only): {single}")
    return 0


# Free-text fields derived from the *original* filenames of personal media. The
# name passes cannot reach them -- a filename fragment need not contain a roster
# name to be identifying -- and nothing reads them (`celeb_provenance_skipped`
# records exist to say the parse was rejected; `media_id`, `path` and `reason`
# carry that on their own). Redact surgically so the file's byte formatting and
# key order survive.
# (path, match pattern, replacement template, literal marker the replacement
# leaves behind). The marker is what lets `verify` check this channel without
# re-running the substitution, and what distinguishes "already redacted" from
# "the pattern stopped matching".
FREE_TEXT_REDACTIONS = (
    (
        "benchmarks/manifests/golden150-draft-20260723.sidecar.json",
        re.compile(r'("parsed_name":\s*)"(?:[^"\\]|\\.)*"'),
        r'\1"<redacted-filename-parse>"',
        '"parsed_name": "<redacted-filename-parse>"',
    ),
)

# Checker floor independent of the rewrite tuple (REV-B-07). Emptying
# FREE_TEXT_REDACTIONS must not make verify greener over a sidecar that
# still carries a live parsed_name.
_FREE_TEXT_SHAPE_RELS = (
    "benchmarks/manifests/golden150-draft-20260723.sidecar.json",
)
_LIVE_PARSED_NAME_RX = re.compile(
    r'"parsed_name"\s*:\s*"(?!<redacted-filename-parse>")(?:[^"\\]|\\.)*"'
)


def _redact_free_text(dry_run: bool) -> list[tuple[str, int]]:
    out = []
    for rel, rx, repl, marker in FREE_TEXT_REDACTIONS:
        path = REPO / rel
        if not path.is_file():
            raise SystemExit(f"redaction target missing: {rel}. Update FREE_TEXT_REDACTIONS or restore the file.")
        text = _read(path)
        new_text, n = rx.subn(repl, text)
        if not n and marker not in text:
            # A declared redaction that matches nothing has either already run or
            # stopped matching -- a renamed key, a changed escaping. Only the
            # first is benign, and the two are distinguishable by whether the
            # replacement is present. Returning quietly on the second would let
            # the one channel `verify` cannot see fail open.
            raise SystemExit(
                f"redaction {rel} matched 0 times and its replacement is absent. The pattern no "
                "longer fits the file -- fix FREE_TEXT_REDACTIONS rather than shipping the field unredacted."
            )
        if n:
            out.append((rel, n))
            if not dry_run:
                _write(path, new_text)
    return out


def _free_text_residue() -> list[str]:
    """Declared free-text targets whose redaction is not present in the file.

    `_redact_free_text` is the one rewrite channel outside `_Passes`, so the
    shared-object argument does not cover it and `verify` would otherwise never
    look at it at all. This is the checker half.

    The scan does not depend on ``FREE_TEXT_REDACTIONS`` being non-empty:
    any known sidecar whose JSON still carries a live ``parsed_name`` is
    residue even if the rewrite tuple was emptied (REV-B-07).
    """
    found: list[str] = []
    checked: set[str] = set()
    for rel, _rx, _repl, marker in FREE_TEXT_REDACTIONS:
        path = REPO / rel
        if not path.is_file():
            raise SystemExit(
                f"free-text target missing: {rel}. "
                "Restore the sidecar or update FREE_TEXT_REDACTIONS; "
                "verify cannot treat an absent file as clean."
            )
        checked.add(rel)
        if marker not in _read(path):
            found.append(rel)
    for rel in _FREE_TEXT_SHAPE_RELS:
        if rel in checked:
            continue
        path = REPO / rel
        if path.is_file() and _LIVE_PARSED_NAME_RX.search(_read(path)):
            found.append(rel)
    return found


def _is_roster_bearing(data: object) -> bool:
    """True when ``data`` is a JSON object with an identities roster."""
    if not isinstance(data, dict):
        return False
    identities = data.get("identities")
    if not isinstance(identities, list) or not identities:
        return False
    return any(isinstance(row, dict) and "bucket" in row and "slug" in row for row in identities)


def _reorder_roster_file(path: Path) -> bool:
    """Re-sort one roster-bearing JSON document on (bucket, slug)."""
    if not path.is_file():
        return False
    text = _read(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not _is_roster_bearing(data):
        return False
    before = [i.get("slug") for i in data["identities"]]
    data["identities"] = sorted(
        data["identities"], key=lambda i: (i.get("bucket", ""), i.get("slug", ""))
    )
    if [i.get("slug") for i in data["identities"]] == before:
        return False
    # Re-serialize at the file's own indent. Hard-coding indent=2 against a
    # 1-space roster reformats all ~105K lines, so the reorder -- the only change
    # that matters here -- becomes unreviewable inside a 210K-line diff.
    dumped = json.dumps(data, indent=_json_indent(text), ensure_ascii=False)
    _write(path, dumped + "\n" if text.endswith("\n") else dumped)
    return True


def _reorder_roster(passes: _Passes, files: list[tuple[Path, bool]] | None = None) -> bool:
    """Re-sort identity arrays on the post-scrub slug.

    The array was sorted by real name, so its order is an alphabetical ordering
    of the names it no longer contains -- an attacker holding a candidate name
    set can align the two and re-identify by position (MLDATA-17). Sorting on
    the minted slug destroys that channel; the slug order is a function of the
    secret key alone.

    Every in-scope roster-bearing manifest the script rewrites gets the same
    treatment — v3, v3r, corpus646 interleave copies, the golden150 draft —
    not just ``ROSTER``. Restricting the sort to v3 left those copies in
    real-name order (REV-D-07).
    """
    changed = False
    seen: set[Path] = set()
    candidates: list[Path] = [ROSTER]
    if files is not None:
        for path, in_scope in files:
            if in_scope:
                candidates.append(path)
    for path in candidates:
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        if path != ROSTER and path.suffix.lower() != ".json":
            continue
        if _reorder_roster_file(path):
            changed = True
    return changed


def _json_indent(text: str, default: int = 2) -> int:
    """Indent width of the first nested key in an already-pretty JSON document."""
    m = re.search(r'\n(\x20+)["\[{]', text)
    return len(m.group(1)) if m else default


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repin_digests(
    published: dict[str, str], files: list[tuple[Path, bool]], dry_run: bool, rounds: int = 8
) -> list[tuple[str, str, str, int]]:
    """Rewrite every tracked occurrence of a digest whose file this run changed.

    Doing it by hand missed one of five pins on the first attempt. Any
    left-aligned non-overlapping 64-hex window equal to a file's
    previously-published digest is a pin by construction (`_HEX64_RX`,
    same window rule as `_live_pin_targets`). A digest at a non-aligned
    offset inside a longer hex run is not a pin.

    Run to a fixpoint: writing a corrected pin *into* a file changes that file's
    own digest, so a single pass leaves the second-order pins stale (three of
    them, measured). Failure to converge is raised, not swallowed (CARD-07).
    """
    if dry_run:
        return []
    scoped = [p for p, in_scope in files if in_scope and p.is_file()]
    applied: list[tuple[str, str, str, int]] = []
    for _round in range(rounds):
        # Keyed by the OLD digest because that is what the pin literals contain,
        # but two byte-identical files share one old digest. If the scrub moves
        # them apart, one old digest has two correct replacements and there is no
        # way to tell from the literal which one a given pin meant -- say so
        # instead of silently picking whichever file was walked last (CARD-07).
        moved: dict[str, tuple[str, list[str]]] = {}
        ambiguous: dict[str, set[str]] = {}
        for path in scoped:
            rel = str(path.relative_to(REPO))
            old = published.get(rel)
            if old is None:
                continue
            if old == "":
                raise SystemExit(
                    f"in-scope path {rel} has an empty pre_sha; refusing to create an empty digest key"
                )
            new = _sha_file(path)
            if new == old:
                continue
            prev = moved.get(old)
            if prev is None:
                moved[old] = (new, [rel])
            else:
                prev[1].append(rel)
                if prev[0] != new:
                    ambiguous.setdefault(old, {prev[0]}).add(new)
        if ambiguous:
            detail = "; ".join(f"{old[:12]}.. -> {sorted(n[:12] for n in news)} in {moved[old][1]}" for old, news in ambiguous.items())
            raise SystemExit(
                "digest re-pinning is ambiguous: previously-identical files now differ, so a pin "
                f"literal has more than one correct replacement -- {detail}. Re-pin these by hand."
            )
        if not moved:
            return applied
        # Same window scan as `_live_pin_targets`: `_HEX64_RX.sub`, not an
        # alternation of the moved digests. Substring semantics would
        # rewrite a non-aligned embed that the publisher then refuses
        # to record (CARD-11).
        replacements = {old: new for old, (new, _rels) in moved.items()}
        hits: dict[str, int] = {}

        def _repl(m: re.Match, replacements=replacements, hits=hits) -> str:
            new = replacements.get(m.group(0))
            if new is None:
                return m.group(0)
            hits[m.group(0)] = hits.get(m.group(0), 0) + 1
            return new

        for path in scoped:
            text, _reason = _read_or_reason(path)
            if text is None:
                continue
            new_text = _HEX64_RX.sub(_repl, text)
            if new_text != text:
                _write(path, new_text)
        for old, (new, rels) in moved.items():
            for rel in rels:
                published[rel] = new
            if old in hits:
                applied.append((rels[0], old, new, hits[old]))
    raise SystemExit(
        f"digest re-pinning did not converge in {rounds} rounds -- the pin graph is cyclic. "
        "Re-pin the remaining digests by hand and record why."
    )


_PIN_RECORD_NAME = "priv1-digest-pins.json"
_PIN_RECORD_SCHEMA = "priv1-digest-pins/1"

# Pin literals are sha256 hexdigest() — lowercase, exactly 64 chars.
# One window rule for every pin walk (`_repin_digests` via sub,
# `_live_pin_targets` via findall): left-aligned, non-overlapping
# 64-hex windows. A digest at a non-aligned offset inside a longer
# hex run is a pin for neither walk. No word boundaries: an aligned
# prefix of a longer run (`<digest>` + more hex) is a window and is
# a pin (BR-34).
_HEX64_RX = re.compile(r"[0-9a-f]{64}")


def _pin_record_path() -> Path:
    # Derived at call time so a test that monkeypatches PRIVATE does not
    # have to also patch a module-level Path that was bound at import.
    return PRIVATE / _PIN_RECORD_NAME


def _validate_pin_record(record: dict) -> None:
    """Structural validation at load time (rg-008).

    A missing ``pins`` key must not become an empty list: that would make
    `verify` report 0 stale over a record that never named a pin, which
    is the wordlist-trap shape (an empty exclusion set meaning "all fine").
    An empty list that *was* written is a measured zero and is allowed.
    """
    path = _pin_record_path()
    if not isinstance(record, dict):
        raise SystemExit(f"{path}: pin record is not an object")
    if record.get("schema") != _PIN_RECORD_SCHEMA:
        raise SystemExit(
            f"{path}: unsupported schema {record.get('schema')!r}; expected {_PIN_RECORD_SCHEMA}"
        )
    if "pins" not in record:
        raise SystemExit(f"{path}: missing required key 'pins'")
    pins = record["pins"]
    if not isinstance(pins, list):
        raise SystemExit(f"{path}: `pins` must be a list")
    required = {"path", "sha256"}
    seen: set[str] = set()
    for i, entry in enumerate(pins):
        if not isinstance(entry, dict):
            raise SystemExit(f"{path}: pins[{i}] is not an object")
        missing = required - set(entry)
        if missing:
            raise SystemExit(f"{path}: pins[{i}] missing {sorted(missing)}")
        rel = entry["path"]
        digest = entry["sha256"]
        if not rel:
            raise SystemExit(f"{path}: pins[{i}] has an empty path")
        if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set("0123456789abcdef"):
            raise SystemExit(f"{path}: pins[{i}] sha256 is not a 64-char lowercase hex digest")
        if rel in seen:
            raise SystemExit(f"{path}: duplicate path {rel}")
        seen.add(rel)


def _load_pin_record() -> dict:
    path = _pin_record_path()
    if not path.is_file():
        raise SystemExit(
            f"pin record not found: {path}. "
            "Run `apply` (not --dry-run) to publish one. "
            "An absent record cannot be treated as 'all pins fine'."
        )
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: malformed JSON ({exc})") from exc
    _validate_pin_record(record)
    return record


def _write_pin_record(record: dict) -> None:
    _validate_pin_record(record)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path = _pin_record_path()
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _merge_pin_record(updates: dict[str, str]) -> dict:
    """Merge newly published path→digest pairs into the on-disk record.

    A missing file starts a new record -- `apply` is creating the baseline.
    `verify` must not take this path; it loads and fails closed.

    Previously recorded paths that are not in ``updates`` are kept, so an
    out-of-band rewrite (no longer a live pin) stays visible to `verify`.
    """
    path = _pin_record_path()
    by_path: dict[str, str] = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        _validate_pin_record(existing)
        by_path = {e["path"]: e["sha256"] for e in existing["pins"]}
    by_path.update(updates)
    record = {
        "schema": _PIN_RECORD_SCHEMA,
        "pins": [{"path": rel, "sha256": by_path[rel]} for rel in sorted(by_path)],
    }
    _write_pin_record(record)
    return record


def _check_published_pins(
    record: dict,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """Re-hash each recorded path. Return ``(stale, missing)``.

    A recorded path that no longer exists is its own state, not dropped
    and not conflated with a matching pin.
    """
    _validate_pin_record(record)
    stale: list[tuple[str, str, str]] = []
    missing: list[tuple[str, str]] = []
    for entry in record["pins"]:
        rel = entry["path"]
        pinned = entry["sha256"]
        path = REPO / rel
        if not path.is_file():
            missing.append((rel, pinned))
            continue
        live = _sha_file(path)
        if live != pinned:
            stale.append((rel, pinned, live))
    return stale, missing


def _pin_check_line(n_published: int, n_stale: int, n_missing: int) -> str:
    """Always a complete sentence, including the zero case.

    Paths and names are not included -- the caller prints those on their
    own lines, truncated the same way REPIN lines are.
    """
    return f"digest pins: {n_published} published; {n_stale} stale; {n_missing} missing"


def _stale_pin_line(rel: str, pinned: str, live: str) -> str:
    return (
        f"STALE-PIN {rel} pinned {pinned[:12]}.. found {live[:12]}.. "
        "Repair: manual old->new sweep of the pin literal in the named file, "
        "then re-run apply; the next apply alone will not repair it"
    )


def _missing_pin_line(rel: str, pinned: str) -> str:
    return f"MISSING-PIN {rel} pinned {pinned[:12]}.. (path gone)"


def _live_pin_targets(published: dict[str, str], files: list[tuple[Path, bool]]) -> dict[str, str]:
    """Paths whose current digest appears as a 64-hex literal in scoped text.

    Inverse of `_repin_digests`: that function rewrites literals that match
    a *previous* digest. This finds literals that match a *current* one.
    Both walks use `_HEX64_RX` (see that comment): left-aligned
    non-overlapping 64-hex windows. A digest at a non-aligned offset
    inside a longer hex run is a pin for neither. Both treat a matching
    window as a pin by construction, so this is not a guess about
    unmatched hex (an upstream release, an untracked artifact).
    The scan is a generic 64-hex pass filtered through ``digest_to_rels``,
    not an alternation of every published digest (BR-34).

    Current digests are hashed from ``files``. ``published`` scopes which
    paths are eligible (files the caller already knew about) but its
    values are not trusted: they may still be the pre-run map (`pre_sha`)
    that `_repin_digests` mutates in place. Hashing here is the same pass
    `_repin_digests` already does.

    This does not remove the ordering requirement. The pin *literal in
    the text* is only the new digest after `_repin_digests` has written
    it. If persist runs first, this pass finds no current-digest literal
    and records nothing for that file, rather than recording the stale
    one. The coupling is not gone.
    """
    if not published:
        return {}
    digest_to_rels: dict[str, list[str]] = {}
    for path, in_scope in files:
        if not in_scope or not path.is_file():
            continue
        rel = str(path.relative_to(REPO))
        if rel not in published:
            continue
        digest = _sha_file(path)
        digest_to_rels.setdefault(digest, []).append(rel)
    if not digest_to_rels:
        return {}
    # One linear [0-9a-f]{64} pass, then a dict probe. Alternating
    # every published digest is O(text × |digests|) in Python's `re`
    # (BR-34). The probe is load-bearing: findall now yields 64-hex
    # strings that are not keys of digest_to_rels.
    found: dict[str, str] = {}
    for path, in_scope in files:
        if not in_scope or not path.is_file():
            continue
        text, _reason = _read_or_reason(path)
        if text is None:
            continue
        for digest in set(_HEX64_RX.findall(text)):
            rels = digest_to_rels.get(digest)
            if rels is None:
                continue
            for rel in rels:
                found[rel] = digest
    return found


def _persist_published_pins(
    published: dict[str, str], files: list[tuple[Path, bool]], dry_run: bool
) -> dict | None:
    """Write the pin record from live targets. Dry-run writes nothing.

    ``published`` is a path scope, not a digest oracle. Live targets
    hash ``files`` themselves; they do not read these values.
    """
    if dry_run:
        return None
    return _merge_pin_record(_live_pin_targets(published, files))


def cmd_apply(args) -> int:
    _load_key()
    mapping = load_map()
    _assert_roster_is_covered(mapping)
    _assert_map_vocab_disjoint(mapping)
    _assert_wordlist_pin(mapping)
    passes = _Passes(mapping)
    files = _tracked_files()

    pre_sha = {str(p.relative_to(REPO)): _sha_file(p) for p, in_scope in files if in_scope and p.is_file()}

    changed: list[tuple[str, dict[str, int]]] = []
    out_of_scope: list[tuple[str, dict[str, int]]] = []
    unscannable: list[tuple[str, str]] = []
    symlink_residue: list[tuple[str, dict[str, int]]] = []
    totals = {"name": 0, "single": 0, "slug": 0, "media": 0, "given": 0, "concat": 0, "adjacent": 0}
    all_unresolved: set[str] = set()

    for path, in_scope in files:
        original, reason = _read_or_reason(path)
        if original is None:
            if in_scope:
                unscannable.append((str(path.relative_to(REPO)), reason))
            continue
        rel = str(path.relative_to(REPO))
        if not in_scope:
            hits = passes.residue(original, path.suffix)
            if hits:
                out_of_scope.append((rel, hits))
            continue
        text, counts, unresolved = passes.rewrite(original, path.suffix)
        all_unresolved |= unresolved
        if text != original:
            for k, v in counts.items():
                totals[k] += v
            changed.append((rel, counts))
            if path.is_symlink():
                # `_write` opens through the link and would replace a mode-120000
                # entry with a regular file holding the rewritten target string.
                # Retargeting a symlink is a manual call, not a text substitution.
                symlink_residue.append((rel, counts))
                changed.pop()
                for k, v in counts.items():
                    totals[k] -= v
            elif not args.dry_run:
                _write(path, text)

    renames: list[tuple[str, str]] = []
    for path, in_scope in files:
        if not in_scope:
            continue
        rel = str(path.relative_to(REPO))
        new_rel = passes.rewrite_path(rel)
        if new_rel != rel:
            renames.append((rel, new_rel))
            if not args.dry_run:
                old_sha = pre_sha.pop(rel, None)
                if not old_sha:
                    raise SystemExit(
                        f"renamed in-scope path {rel} has an empty or absent pre-rewrite "
                        "digest; refusing to create an empty pin key"
                    )
                (REPO / new_rel).parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "mv", rel, new_rel], cwd=REPO, check=True)
                pre_sha[new_rel] = old_sha

    redactions = _redact_free_text(args.dry_run)

    files_after = _tracked_files() if renames and not args.dry_run else files
    reordered = False
    if not args.dry_run and args.reorder:
        reordered = _reorder_roster(passes, files_after)
    # `_repin_digests` must run first: persist hashes current file
    # bytes, but the pin *literals* are only those current digests
    # after the rewrite. Persist does not read the mutated values of
    # `pre_sha`; the coupling is the text, not the dict.
    repins = _repin_digests(pre_sha, files_after, args.dry_run)
    pin_record = _persist_published_pins(pre_sha, files_after, args.dry_run)

    for rel, counts in sorted(changed, key=lambda r: -sum(r[1].values()))[: args.top]:
        detail = " ".join(f"{k}={v}" for k, v in counts.items() if v)
        print(f"  {rel:<86} {detail}")
    verb = "would rewrite" if args.dry_run else "rewrote"
    print(
        f"{verb} {len(changed)} files; "
        + ", ".join(f"{v} {k}" for k, v in totals.items())
        + f"; {len(renames)} renamed; {len(repins)} digests re-pinned; roster reordered={reordered}"
    )
    for rel, n in redactions:
        print(f"  REDACT {rel} x{n} free-text field(s)")
    for old, new in renames:
        print(f"  RENAME {old} -> {new}")
    for rel, old, new, n in repins:
        print(f"  REPIN  {rel} {old[:12]}.. -> {new[:12]}.. (x{n})")
    if passes.given_deferred:
        print(f"  bare tokens left alone (also carried by a non-personal identity): {passes.given_deferred}")
    print(f"  {_concat_exclusion_line(passes.concat_dropped)}")
    print(f"  {_adjacent_exclusion_line(passes.adjacent_dropped)}")
    print(f"  {_ambiguous_family_exclusion_line(passes.ambiguous_family_dropped)}")
    print(f"  {_wordlist_line()}")
    print(f"  {_ambiguous_stem_line(len(all_unresolved))}")
    stale_pins: list = []
    missing_pins: list = []
    if pin_record is None:
        print("  digest pins: not checked (dry run; no record published)")
    else:
        stale_pins, missing_pins = _check_published_pins(pin_record)
        for rel, pinned, live in stale_pins:
            print(f"  {_stale_pin_line(rel, pinned, live)}")
        for rel, pinned in missing_pins:
            print(f"  {_missing_pin_line(rel, pinned)}")
        print(f"  {_pin_check_line(len(pin_record['pins']), len(stale_pins), len(missing_pins))}")
    if out_of_scope:
        print(f"  OUT OF SCOPE -- scanned, deliberately not rewritten ({len(out_of_scope)} files):")
        for rel, hits in sorted(out_of_scope, key=lambda r: -sum(r[1].values()))[:20]:
            print(f"    {rel:<84} {hits}")
    for rel, counts in sorted(symlink_residue):
        print(f"  SYMLINK  {rel} -- target string carries {counts}; retarget by hand")
    declared, undeclared = _split_declared(unscannable)
    for rel, reason in sorted(declared):
        print(f"  DECLARED-UNSCANNABLE {rel} -- {DECLARED_UNSCANNABLE[rel][1].split('.')[0]}. ({reason})")
    if undeclared:
        print(f"  UNSCANNABLE -- in scope but never opened ({len(undeclared)} files); coverage is NOT complete:")
        for rel, reason in sorted(undeclared):
            print(f"    {rel:<84} {reason}")
    return 1 if (undeclared or symlink_residue or stale_pins or missing_pins) else 0


def cmd_verify(args) -> int:
    _load_key()
    mapping = load_map()
    # Before scanning for what the passes can see, establish that the passes
    # cover the roster as it stands now. Otherwise a subject added since the
    # last `plan` produces a clean scan for the reason that nothing is looking
    # for them (CARD-11).
    _assert_roster_is_covered(mapping)
    _assert_map_vocab_disjoint(mapping)
    _assert_wordlist_pin(mapping)
    passes = _Passes(mapping)
    pin_record = _load_pin_record()
    stale_pins, missing_pins = _check_published_pins(pin_record)

    residue: list[tuple[str, dict[str, int]]] = []
    path_residue: list[str] = []
    out_of_scope: list[tuple[str, dict[str, int]]] = []
    unscannable: list[tuple[str, str]] = []
    for path, in_scope in _tracked_files():
        rel = str(path.relative_to(REPO))
        if in_scope and passes.rewrite_path(rel) != rel:
            path_residue.append(rel)
        text, reason = _read_or_reason(path)
        if text is None:
            if in_scope:
                unscannable.append((rel, reason))
            continue
        hits = passes.residue(text, path.suffix)
        if not hits:
            continue
        (residue if in_scope else out_of_scope).append((rel, hits))

    for rel, hits in sorted(residue, key=lambda r: -sum(r[1].values())):
        print(f"  RESIDUE {rel} {hits}")
    for rel in path_residue:
        print(f"  RESIDUE path {rel}")
    # An unopened in-scope file is an unverified one. Counting it as clean turns
    # "no residue found" into "no residue found in the files we could read",
    # which is the same sentence a green gate would print (CARD-07).
    declared, undeclared = _split_declared(unscannable)
    for rel, reason in sorted(declared):
        print(f"  DECLARED-UNSCANNABLE {rel} -- {DECLARED_UNSCANNABLE[rel][1]} ({reason})")
    for rel, reason in sorted(undeclared):
        print(f"  UNSCANNABLE {rel} -- {reason}")
    free_text = _free_text_residue()
    for rel in free_text:
        print(f"  RESIDUE free-text {rel} -- declared redaction marker absent")
    if passes.given_deferred:
        print(f"  bare tokens left alone (also carried by a non-personal identity): {passes.given_deferred}")
    print(f"  {_concat_exclusion_line(passes.concat_dropped)}")
    print(f"  {_adjacent_exclusion_line(passes.adjacent_dropped)}")
    print(f"  {_ambiguous_family_exclusion_line(passes.ambiguous_family_dropped)}")
    print(f"  {_wordlist_line()}")
    print(f"  {_ambiguous_stem_line(sum(h.get('media_ambiguous', 0) for _rel, h in residue))}")
    for rel, pinned, live in stale_pins:
        print(f"  {_stale_pin_line(rel, pinned, live)}")
    for rel, pinned in missing_pins:
        print(f"  {_missing_pin_line(rel, pinned)}")
    print(f"  {_pin_check_line(len(pin_record['pins']), len(stale_pins), len(missing_pins))}")
    print(
        f"in-scope residue: {len(residue)} files / {sum(sum(h.values()) for h in (x[1] for x in residue))} occ; "
        f"paths: {len(path_residue)}; free-text: {len(free_text)}; unscannable in-scope: {len(undeclared)} "
        f"(+{len(declared)} declared); out-of-scope (reported only): {len(out_of_scope)} files"
    )
    if undeclared:
        print(
            "verify is INCOMPLETE: the files above are in rewrite scope but were never decoded. "
            "Either handle them explicitly, declare them in DECLARED_UNSCANNABLE with a recorded "
            "rationale, or add their suffix to SKIP_SUFFIXES."
        )
    if args.show_out_of_scope:
        for rel, hits in sorted(out_of_scope, key=lambda r: -sum(r[1].values())):
            print(f"  OUT-OF-SCOPE {rel} {hits}")
    return 1 if (residue or path_residue or undeclared or free_text or stale_pins or missing_pins) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--force", action="store_true", help="overwrite an existing alias map (re-mints every alias)")
    p.add_argument(
        "--pin-wordlist",
        action="store_true",
        help="record the live wordlist on an existing map without reminting",
    )
    p.set_defaults(fn=cmd_plan)
    a = sub.add_parser("apply")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--top", type=int, default=25)
    a.add_argument("--no-reorder", dest="reorder", action="store_false", help="keep the roster identity order")
    a.set_defaults(fn=cmd_apply, reorder=True)
    v = sub.add_parser("verify")
    v.add_argument("--show-out-of-scope", action="store_true")
    v.set_defaults(fn=cmd_verify)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
