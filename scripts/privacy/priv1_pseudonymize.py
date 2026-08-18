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

# In-scope files that cannot be decoded as text, each with the reason it is
# nonetheless not a leak. Nothing may be skipped silently: an undecodable
# in-scope file that is NOT declared here fails `verify`, because "we could not
# read it" and "it is clean" are not the same sentence (CARD-07).
DECLARED_UNSCANNABLE = {
    "docs/assessments/current/AltContext_Local_AI_Strategy_Session_Brief.docx": (
        "OOXML container. Inspected part-by-part: the single roster-token hit in "
        "word/document.xml is a cited author surname inside a bibliography entry "
        "of the form `<author> & <author> (2023).pdf`, not a corpus subject. "
        "Rewriting it would corrupt somebody else's citation -- the same reason "
        "literature/ is scanned but never edited."
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
    "coral",
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


# Single-token identity names that must never be matched in free text, because
# the token is overwhelmingly an ordinary word rather than the person. `self`
# alone accounts for 283 in-tree occurrences, essentially all of them the Python
# parameter. These are still scrubbed where they appear as a whole JSON string,
# which is the only position that unambiguously denotes the identity.
FREE_TEXT_DENY = {"self"}

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
NBL = r"(?<![A-Za-z0-9])"
NBR = r"(?![A-Za-z0-9])"

# ...and a digit-adjacent boundary is not enough on its own. A sha256 pin is a
# 64-character alnum run whose *first* characters can spell a short name
# (`4beca0...` starts at a quote, so the left boundary holds). Rewriting inside
# one produces `4quiet0a04...`, which the manifest validator rejects -- silent
# corruption of the exact artifact this scrub exists to protect. Any match
# sitting inside a long hex run is refused.
_HEX = set("0123456789abcdefABCDEF")
_HEX_RUN_MIN = 16


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
    """
    hit = {rel for rel, _ in unscannable}
    if stale := sorted(set(DECLARED_UNSCANNABLE) - hit):
        raise SystemExit(
            "DECLARED_UNSCANNABLE names files the scan did not report as unscannable: "
            f"{stale}. They were renamed, deleted, or became readable -- re-check each "
            "one and drop or update its entry."
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
    }


def load_map() -> dict:
    if not ALIAS_MAP.is_file():
        raise SystemExit(
            f"alias map not found: {ALIAS_MAP}\n"
            "Run `plan` first. The map is name-bearing and therefore untracked; "
            "point ACX_CORPUS_PRIVATE_DIR at it if it lives elsewhere."
        )
    mapping = json.loads(ALIAS_MAP.read_text(encoding="utf-8"))
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
    if mapping.get("key_fingerprint") != _key_fingerprint():
        raise SystemExit(
            f"{ALIAS_MAP} was minted under a different key than {MINT_KEY}.\n"
            "Applying it would produce aliases the map cannot reverse. Restore the "
            "matching key, or move both aside and re-run `plan` from a clean tree."
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


def _multi_token_regex(mapping: dict, singles: bool = False) -> tuple[re.Pattern, dict]:
    """One alternation over multi-token names, longest-first.

    With ``singles=True`` the alternation also carries single-token names whose
    token is not an ordinary word (see FREE_TEXT_DENY). Callers pass that only
    for data and prose files.
    """
    multi = [
        e for e in mapping["entries"] if e["tokens"] > 1 or (singles and e["real_name"].lower() not in FREE_TEXT_DENY)
    ]
    by_key = {}
    parts = []
    for e in sorted(multi, key=lambda e: -len(e["real_name"])):
        parts.append(re.escape(e["real_name"]).replace(r"\ ", r"[\s_\-]+"))
        by_key[re.sub(r"[^a-z0-9]+", " ", e["real_name"].lower()).strip()] = e
    if not parts:
        raise SystemExit("alias map contains no multi-token names")
    return re.compile(NBL + r"(?:" + "|".join(parts) + r")" + NBR, re.IGNORECASE), by_key


def _render(alias: str, matched: str) -> str:
    """Mirror the matched token's separator and case so paths/slugs stay valid."""
    sep_match = re.search(r"[\s_\-]", matched)
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


def _substitute(text: str, rx: re.Pattern, by_key: dict) -> tuple[str, int]:
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        if _inside_hex_run(m.string, m.start(), m.end()):
            return m.group(0)
        key = re.sub(r"[^a-z0-9]+", " ", m.group(0).lower()).strip()
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


def _concatenated_regex(mapping: dict) -> tuple[re.Pattern | None, dict]:
    """Multi-token names written with no separator at all (`firstnamelastname`).

    Social-media exports name their files `<first><last>-<ts>_<id>.jpg`. Every
    other pass is anchored on NBL/NBR, which require a non-alphanumeric
    character between the tokens, and `_media_stem_pass` splits the stem on
    `[^A-Za-z0-9]+` -- so this shape is not under-matched, it is structurally
    unreachable. It survived the first scrub in 379 places across 38 tracked
    files, exposing 14 identities in full cleartext, including a rendered HTML
    evidence report. Matched only at >=8 characters so a concatenation cannot
    collide with an ordinary word.
    """
    forms: dict[str, str] = {}
    dropped: list[int] = []
    for entry in mapping["entries"]:
        real = [t for t in re.split(r"[^A-Za-z0-9]+", entry["real_name"]) if t]
        alias = [t for t in re.split(r"[^A-Za-z0-9]+", entry["alias"]) if t]
        joined = "".join(real)
        if len(real) < 2 or len(joined) < 8:
            continue
        if not alias:
            # No alias to substitute is a map defect, not a name to skip.
            dropped.append(len(joined))
            continue
        # Token counts need not match. A concatenation has no internal
        # boundaries, so the whole joined name maps to the whole joined alias --
        # requiring len(alias) >= len(real) silently dropped four 3-token names
        # that carry 2-token aliases, and an independent oracle then found 8
        # occurrences of them that `verify` was reporting as zero.
        forms[joined.lower()] = "".join(alias)
    if dropped:
        raise SystemExit(
            f"{len(dropped)} multi-token entries (name lengths {sorted(dropped)}) have no alias "
            "tokens, so their concatenated form cannot be rewritten. Fix the alias map; "
            "skipping them would make `verify` blind to exactly those names."
        )
    if not forms:
        return None, {}
    alt = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(NBL + r"(?:" + alt + r")" + NBR, re.IGNORECASE), forms


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


def _media_stem_pass(text: str, index: dict) -> tuple[str, int, set[str]]:
    """Rewrite name tokens inside image filenames only.

    Scoped to the filename stem so ordinary prose is untouched: `coral` is a
    dress in a caption and a surname in a roster, and only the filename context
    is safe to decide. Each stem votes for the identity it shares the most
    tokens with; a lone token that maps to more than one identity is left alone
    and reported rather than guessed at.
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
                unresolved.add(part.lower())
                rebuilt.append(part)
                continue
            word = words.pop()
            rebuilt.append(word.upper() if part.isupper() else word.lower() if part.islower() else word)
            changed = True
        if not changed:
            return whole
        count += 1
        return (head + "/" if head else "") + "".join(rebuilt) + dot + ext

    return _MEDIA_PATH_RX.sub(repl, text), count, unresolved


_DICT = Path("/usr/share/dict/words")


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


def _given_name_regex(mapping: dict) -> tuple[re.Pattern | None, dict]:
    """Bare name tokens that can only be one person and are not ordinary words.

    The full-name pass cannot see `Candid relax by a lake` or `Weavers'`; the
    residue is a real given name in readable prose. The filter is deliberately
    one-sided: a token that is also a dictionary word (`rose`, `faith`, `ivy`)
    or that more than one identity shares is left alone, so this under-scrubs
    rather than rewriting an ordinary caption word into somebody's pseudonym.
    """
    words = set()
    if _DICT.is_file():
        words = {w.strip().lower() for w in _DICT.read_text(errors="ignore").splitlines()}
    by_token: dict[str, set[str]] = {}
    for entry in mapping["entries"]:
        real, alias = entry["real_name"].split(), entry["alias"].split()
        for i, token in enumerate(real):
            if len(token) < 4 or i >= len(alias) or token.lower() in words:
                continue
            by_token.setdefault(token.lower(), set()).add(alias[i])
    resolved = {t: next(iter(a)) for t, a in by_token.items() if len(a) == 1}
    resolved.update(_family_words(by_token))
    if not resolved:
        return None, {}
    alt = "|".join(re.escape(t) for t in sorted(resolved, key=len, reverse=True))
    return re.compile(NBL + r"(" + alt + r")" + NBR, re.IGNORECASE), resolved


class _Passes:
    """Every substitution pass, built once and reused by apply *and* verify.

    v1 built four of the six passes in `verify` and none of the token-level
    ones, so `verify: 0 residue` was structurally incapable of seeing the two
    leak classes the reviewers reproduced by hand. A single shared object makes
    the checker and the rewriter provably the same code (CARD-08).
    """

    def __init__(self, mapping: dict) -> None:
        self.name_rx, self.by_key = _multi_token_regex(mapping)
        self.data_rx, self.data_key = _multi_token_regex(mapping, singles=True)
        self.quoted_rx, self.singles = _quoted_exact_regex(mapping)
        self.slug_rx, self.leaky = _slug_regex(mapping)
        self.token_index = _token_index(mapping)
        self.given_rx, self.given = _given_name_regex(mapping)
        self.concat_rx, self.concat = _concatenated_regex(mapping)

    def rewrite(self, text: str, suffix: str) -> tuple[str, dict[str, int], set[str]]:
        counts = {"name": 0, "single": 0, "slug": 0, "media": 0, "given": 0, "concat": 0}

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

        text, n_media, unresolved = _media_stem_pass(text, self.token_index)
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
                tok = m.group(1)
                return word.upper() if tok.isupper() else word.lower() if tok.islower() else word

            text = self.given_rx.sub(_given_repl, text)

        return text, counts, unresolved

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
        `rewrite`, so a pass cannot exist in one and be missing in the other."""
        found = {}
        rx = self.data_rx if suffix.lower() in SINGLE_TOKEN_FREE_TEXT_SUFFIXES else self.name_rx
        if n := len(rx.findall(text)):
            found["name"] = n
        if self.slug_rx is not None and (n := len(self.slug_rx.findall(text))):
            found["slug"] = n
        if self.quoted_rx is not None and suffix == ".json" and (n := len(self.quoted_rx.findall(text))):
            found["single"] = n
        _out, n_media, _unresolved = _media_stem_pass(text, self.token_index)
        if n_media:
            found["media"] = n_media
        if self.given_rx is not None and (n := len(self.given_rx.findall(text))):
            found["given"] = n
        if self.concat_rx is not None and (n := len(self.concat_rx.findall(text))):
            found["concat"] = n
        return found


def cmd_plan(args) -> int:
    if ALIAS_MAP.is_file() and not args.force:
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
FREE_TEXT_REDACTIONS = (
    (
        "benchmarks/manifests/golden150-draft-20260723.sidecar.json",
        re.compile(r'("parsed_name":\s*)"(?:[^"\\]|\\.)*"'),
        r'\1"<redacted-filename-parse>"',
    ),
)


def _redact_free_text(dry_run: bool) -> list[tuple[str, int]]:
    out = []
    for rel, rx, repl in FREE_TEXT_REDACTIONS:
        path = REPO / rel
        if not path.is_file():
            raise SystemExit(f"redaction target missing: {rel}. Update FREE_TEXT_REDACTIONS or restore the file.")
        text = _read(path)
        new_text, n = rx.subn(repl, text)
        if n:
            out.append((rel, n))
            if not dry_run:
                _write(path, new_text)
    return out


def _reorder_roster(passes: _Passes) -> bool:
    """Re-sort the identity array on the post-scrub slug.

    The array was sorted by real name, so its order is an alphabetical ordering
    of the names it no longer contains -- an attacker holding a candidate name
    set can align the two and re-identify by position (MLDATA-17). Sorting on
    the minted slug destroys that channel; the slug order is a function of the
    secret key alone.
    """
    text = _read(ROSTER)
    data = json.loads(text)
    before = [i.get("slug") for i in data["identities"]]
    data["identities"] = sorted(data["identities"], key=lambda i: (i.get("bucket", ""), i.get("slug", "")))
    if [i.get("slug") for i in data["identities"]] == before:
        return False
    # Re-serialize at the file's own indent. Hard-coding indent=2 against a
    # 1-space roster reformats all ~105K lines, so the reorder -- the only change
    # that matters here -- becomes unreviewable inside a 210K-line diff.
    dumped = json.dumps(data, indent=_json_indent(text), ensure_ascii=False)
    _write(ROSTER, dumped + "\n" if text.endswith("\n") else dumped)
    return True


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

    Doing it by hand missed one of five pins on the first attempt. Any 64-hex
    literal equal to a file's previously-published digest is a pin by
    construction, so this is exhaustive where a manual sweep is not.

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
        rx = re.compile("|".join(re.escape(o) for o in moved))
        hits: dict[str, int] = {}

        def _repl(m: re.Match, moved=moved, hits=hits) -> str:
            hits[m.group(0)] = hits.get(m.group(0), 0) + 1
            return moved[m.group(0)][0]

        for path in scoped:
            text, _reason = _read_or_reason(path)
            if text is None:
                continue
            new_text = rx.sub(_repl, text)
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


def cmd_apply(args) -> int:
    _load_key()
    mapping = load_map()
    passes = _Passes(mapping)
    files = _tracked_files()

    pre_sha = {str(p.relative_to(REPO)): _sha_file(p) for p, in_scope in files if in_scope and p.is_file()}

    changed: list[tuple[str, dict[str, int]]] = []
    out_of_scope: list[tuple[str, dict[str, int]]] = []
    unscannable: list[tuple[str, str]] = []
    symlink_residue: list[tuple[str, dict[str, int]]] = []
    totals = {"name": 0, "single": 0, "slug": 0, "media": 0, "given": 0, "concat": 0}
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
                (REPO / new_rel).parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "mv", rel, new_rel], cwd=REPO, check=True)
                pre_sha[new_rel] = pre_sha.pop(rel, "")

    redactions = _redact_free_text(args.dry_run)

    reordered = False
    if not args.dry_run and args.reorder:
        reordered = _reorder_roster(passes)

    files_after = _tracked_files() if renames and not args.dry_run else files
    repins = _repin_digests(pre_sha, files_after, args.dry_run)

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
    if all_unresolved:
        print(f"  media stems left alone (token maps to >1 identity): {sorted(all_unresolved)}")
    if out_of_scope:
        print(f"  OUT OF SCOPE -- scanned, deliberately not rewritten ({len(out_of_scope)} files):")
        for rel, hits in sorted(out_of_scope, key=lambda r: -sum(r[1].values()))[:20]:
            print(f"    {rel:<84} {hits}")
    for rel, counts in sorted(symlink_residue):
        print(f"  SYMLINK  {rel} -- target string carries {counts}; retarget by hand")
    declared, undeclared = _split_declared(unscannable)
    for rel, reason in sorted(declared):
        print(f"  DECLARED-UNSCANNABLE {rel} -- {DECLARED_UNSCANNABLE[rel].split('.')[0]}. ({reason})")
    if undeclared:
        print(f"  UNSCANNABLE -- in scope but never opened ({len(undeclared)} files); coverage is NOT complete:")
        for rel, reason in sorted(undeclared):
            print(f"    {rel:<84} {reason}")
    return 1 if (undeclared or symlink_residue) else 0


def cmd_verify(args) -> int:
    _load_key()
    mapping = load_map()
    passes = _Passes(mapping)

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
        print(f"  DECLARED-UNSCANNABLE {rel} -- {DECLARED_UNSCANNABLE[rel]} ({reason})")
    for rel, reason in sorted(undeclared):
        print(f"  UNSCANNABLE {rel} -- {reason}")
    print(
        f"in-scope residue: {len(residue)} files / {sum(sum(h.values()) for h in (x[1] for x in residue))} occ; "
        f"paths: {len(path_residue)}; unscannable in-scope: {len(undeclared)} "
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
    return 1 if (residue or path_residue or undeclared) else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--force", action="store_true", help="overwrite an existing alias map (re-mints every alias)")
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
