# PRIV-1 — corpus pseudonymization

`priv1_pseudonymize.py` replaces the operator's curated real subject names with
minted pseudonyms across the tracked tree, so that
`benchmarks/manifests/corpus-manifest-v3.json` actually honours the contract it
declares (`consent.personal = "subjects are named by pseudonym throughout"`,
`naming = "pseudonym"` on every `bucket == "personal"` identity).

## What is and is not scrubbed

| Surface | Treatment |
| --- | --- |
| `bucket == "personal"` identities (90 people, 681 records) | name, slug, media path, and free-text mentions replaced with a minted alias |
| `bucket == "celebs"` identities | **kept** — third-party editorial fixtures the consent block already discloses, and the ground truth for the recognition leg |
| `literature/**` (35 files) | scanned and **reported**, never rewritten — a surname colliding with a cited author is a false positive, and editing it corrupts somebody else's bytes (CARD-07) |
| Image pixels / embedded XMP | **out of reach.** The scrub rewrites tracked text only. Names inside LocalWP image metadata are untouched; tests that read them assert structure, not the name |

## Running it

The mint key and the reverse map live outside the tree, in the private corpus
store. Point `ACX_CORPUS_PRIVATE_DIR` at it:

```bash
export ACX_CORPUS_PRIVATE_DIR=/path/to/private-corpus-store

python scripts/privacy/priv1_pseudonymize.py plan     # mint key + alias map (first run only)
python scripts/privacy/priv1_pseudonymize.py apply    # rewrite tracked files
python scripts/privacy/priv1_pseudonymize.py verify   # re-scan for residue
```

`apply` also supports `--dry-run`, `--top N`, and `--no-reorder`; `verify`
supports `--show-out-of-scope`.

## The key

Aliases are minted deterministically as `HMAC-SHA256(secret_key, name)` →
`adjective_noun` → Title-Cased display alias. The key is 32 random bytes written
once to `$ACX_CORPUS_PRIVATE_DIR/priv1-mint-key` (mode 600) and never committed.
The alias map records only a `key_fingerprint`, and `plan` refuses to run
against a map minted under a different key.

A *committed* salt would make every pseudonym a confirmable guess: anyone who
suspects a name can hash it and check. That is not de-identification, so the key
is the one artifact that must stay out of the repo (MLDATA-17).

**Consequence: CI cannot gate `verify`.** Without the key and the map, the
residue scan has nothing to scan for. `verify` is an operator-run check on a
machine that holds the private store, not a pipeline step. Do not add it to
`make check-all` — a green run there would only mean "the key is missing."

## Measured residue (2026-08-18, after `apply`)

Two checkers, run to agreement. The first is this script's own `verify`. The
second is an oracle that does **not** import it: the oracle re-derives the token
set from the pre-scrub roster blob (`git show main:…corpus-manifest-v3.json`),
rebuilds both the separated and the concatenated surface forms from scratch, and
rescans the working tree (MLDATA-17 — a de-identification claim needs a measured
re-identification attempt, not an assertion).

The two are quoted together on purpose, and this section has now been wrong
twice for the same reason. An early revision claimed "0 tokens remain" on
`verify` alone; that was false by 379 occurrences. A later revision published
the numbers below with the concatenated row reading "≥8 chars"; that floor was a
silent `continue` in `_concatenated_regex`, which `residue()` builds from too,
so `verify` printed `0 files / 0 occ` while **17 occurrences of 2 identities
across 3 tracked in-scope files** sat on disk in cleartext (PRIV-1-BR-25). Both
were caught only by the independent oracle. A checker that shares the rewriter's
blind spot is not evidence, and an exclusion applied while *building* a pattern
is an exclusion applied to the *measurement* (CARD-08).

The concatenated pass is now two-tiered rather than floored: joined forms of
≥8 letters match unanchored, and shorter multi-token joins match under a
letter-only anchor `(?<![A-Za-z])…(?![A-Za-z])`, which still refuses an in-word
collision — the floor's actual purpose — while admitting the digit, `@` and `/`
neighbours both live leak shapes needed. Whatever the builder still refuses is
counted and printed by `apply` and `verify` rather than dropped.

```
$ python scripts/privacy/priv1_pseudonymize.py verify
  bare tokens left alone (also carried by a non-personal identity): ['liam']
  concat exclusions: 4 dropped (4× single-token name; no concatenation exists)
in-scope residue: 0 files / 0 occ; paths: 0; free-text: 0;
unscannable in-scope: 0 (+1 declared); out-of-scope (reported only): 35 files
exit 0
```

Independent oracle (`str.find` over needles built from the alias map, sharing no
code with the script) across 2,994 tracked files:

| measure                                     | value |
| ------------------------------------------- | ----- |
| personal identities in the pre-scrub roster | 90    |
| multi-token identities (concat-eligible)    | 86    |
| single-token identities (see below)         | 4     |
| separated-form occurrences remaining        | **0** |
| concatenated-form occurrences remaining     | **0** |
| slug / snake / dot-form occurrences remaining | **0** |
| offending files                             | **0** |

exit 0.

Three classes are deliberately left in place, and none is a residue claim:

- 73 roster tokens are ordinary dictionary words that happen to also be given
  names (15,555 occurrences, overwhelmingly prose in `literature/` and synthetic
  test fixtures). Rewriting them corrupts unrelated English, so they are out of
  scope by design rather than missed.
- 3 of the 4 single-token identities fall in that same class: each is a
  dictionary word, and one is a 4-letter token with 10,662 in-scope occurrences
  across 689 files (`Makefile`, `Dockerfile`, `pyproject.toml`, module names).
  Those occurrences are the ordinary word, not references to a subject. The
  fourth single-token identity is covered by the given-name pass and was
  rewritten. **Caveat:** the dictionary is `/usr/share/dict/words`, an untracked
  host file that the builder degrades to an empty set when absent — so this row
  is host-dependent and not reproducible from the repo alone (PRIV-1-BR-26,
  open).
- 1 in-scope file is undecodable and declared, not skipped: an OOXML strategy
  brief whose single roster-token hit is a cited author surname in a
  bibliography entry. It is listed in `DECLARED_UNSCANNABLE` with that
  rationale; any *undeclared* undecodable in-scope file fails `verify` with a
  non-zero exit.

Media stems that map to more than one identity are left alone by the filename
pass; the family-word pass covers those identities' surnames. The stems are not
listed here — one of them is a roster given name, and a document explaining the
scrub must not be the thing that publishes it. `apply` prints the live list
(`media stems left alone (token maps to >1 identity)`), re-derived from the
roster on every run rather than pinned here where it would rot.

## Traps this script exists to avoid

- `\b` treats `_` as a word character, so it never fires at a letter→underscore
  transition. Snake_case filenames and `_first_last` identifiers leaked in the
  first attempt. Boundaries are `(?<![A-Za-z0-9])` / `(?![A-Za-z0-9])`.
- Widening the boundary to digits is not enough on its own: a sha256 pin is a
  64-char run whose leading characters can spell a short name, and rewriting
  inside one silently corrupts the exact artifact this scrub protects.
  `_inside_hex_run()` refuses any match sitting inside a ≥16-char hex run.
- Digest re-pinning must run to a fixpoint — writing a corrected pin into a file
  changes that file's own digest (3 second-order pins measured). Non-convergence
  raises rather than passing quietly.
- `rewrite()` and `residue()` share one `_Passes` object, so `verify` provably
  exercises the same six passes as `apply` (CARD-08). Sharing the object is
  necessary but not sufficient: both are built from the same builders, so a
  builder that drops an entry blinds the checker and the rewriter together.
  That has now happened three times — the concatenated form as a whole; four
  3-token names whose 2-token aliases tripped a token-count guard; and two
  7-letter joined names dropped by an `>= 8` length floor. Every one was caught
  only by the independent oracle, never by `verify`. The floor is the clearest
  case: it was a *defensible* guard, correctly reasoned in its own docstring,
  and still wrong — because it was enforced by `continue` instead of by
  anchoring. Guard by narrowing the match, not by removing the entry.
- An entry that cannot be rewritten raises instead of being skipped. A `continue`
  in a builder is indistinguishable, at the output, from a name that was never
  there.
- A tracked symlink is read as its own target string, not followed. Following it
  makes coverage depend on whether an overlay happens to be materialized in the
  current worktree — seven git-hook links read as `FileNotFoundError` and looked
  like a scan gap.

## Known limits

- **Digest pins only track drift this script caused.** `_repin_digests` diffs
  digests captured at the top of an `apply` run against post-rewrite digests, so
  a digest that moves out-of-band — a hand edit, a rebase, a re-serialization by
  another tool — is invisible to it, and `verify` does not check pins at all.
  Both commands will report clean over a stale pin. Repair is a manual old→new
  sweep iterated to a fixpoint. Tracked as PRIV-1-BR-11.
- **CI cannot gate any of this** (see *The key*). `verify` is an operator check.
