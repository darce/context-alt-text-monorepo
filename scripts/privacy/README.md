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

## Measured residue (2026-08-17, after `apply`)

Measured by an oracle that does **not** import this script: it re-derives the
token set from the pre-scrub roster blob (`git show main:…corpus-manifest-v3.json`)
and rescans the working tree (MLDATA-17 — a de-identification claim needs a
measured re-identification attempt, not an assertion).

- **0** non-dictionary roster tokens remain anywhere in scope (2,837 files).
- **0** real names remain in an identity-bearing JSON key. The oracle's 238 raw
  structural hits resolve to 236 × the `"unlabeled"` sentinel (a `slug` value in
  the roster, not a person), one UI label sentence, and the `Alice`/`Alicia`
  cluster-label test fixture.
- 44 surviving tokens are ordinary dictionary words that are also given names
  (24,262 occurrences) — prose and synthetic test fixtures, sampled and
  confirmed. They are not scrubbed because rewriting them corrupts unrelated
  English.
- 4 media stems (`faith`, `kelly`, `lee`, `sampliner`) are left alone by the
  filename pass because each maps to more than one identity; the family-word
  pass covers those identities' surnames.

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
  exercises the same six passes as `apply` (CARD-08).
