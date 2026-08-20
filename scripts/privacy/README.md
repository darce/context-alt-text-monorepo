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

`verify` will not run without a pin record. If the private store has a map
and a key but no `$ACX_CORPUS_PRIVATE_DIR/priv1-digest-pins.json`, it exits
immediately:

```
pin record not found: <path>/priv1-digest-pins.json. Run `apply` (not --dry-run) to publish one. An absent record cannot be treated as 'all pins fine'.
```

That is a hard dependency, not a skip. An operator who has been running
`verify` for weeks and has not yet re-run a wet `apply` will hit it. The
fix is to run `apply` once (not `--dry-run`) so it publishes the record;
`verify` will then load it.

The record is deliberately untracked. Putting it in the tree would put it
in the pin graph: it is a JSON file of 64-hex literals, persist writes it
*after* the re-pin fixpoint, and a pin of the record file would go stale
on every write. It lives next to the alias map, behind the same ignore
fence, so `_tracked_files` never sees it.

All three commands need a word list, used to decide which roster tokens are
ordinary English and must be left alone. It defaults to `/usr/share/dict/words`
and is overridden with `$PRIV1_WORDLIST`. A missing, unreadable or empty list is
a hard failure, never a silent empty exclusion set (rg-008) — an empty set makes
every dictionary-word given name eligible for rewriting, which on this corpus
would have rewritten 10,662 occurrences of one ordinary 4-letter word across 689
files, `Makefile` and `pyproject.toml` among them. `plan` records the list's
path, sha256 and word count in the alias map, and `apply` and `verify` both
refuse to run against a list whose digest has moved since. Both print the
measurement on every run. A map with no `wordlist` block at all is the same
hard failure, not a warning. The fix is `plan --pin-wordlist`: it adds only
that block and does not re-mint. `--force` is not the fix — it re-mints every
alias and orphans applied rewrites.

The alias map also needs a `free_text_deny` list block. An absent block is a
hard failure (add the block; an empty list is valid).

## The key

Aliases are minted deterministically as `HMAC-SHA256(secret_key, f"{name}#{attempt}")`
→ `adjective_noun` → Title-Cased display alias (`attempt` starts at 0; a
collision re-hashes with the next integer rather than hashing `name` alone).
The key is 32 random bytes written
once to `$ACX_CORPUS_PRIVATE_DIR/priv1-mint-key` (mode 600) and never committed.
The alias map records only a `key_fingerprint`. `apply` and `verify` refuse a
map minted under a different key (`load_map` → `_validate_map`). `plan` does
not: if a map already exists it says so and asks for `--force`, and `--force`
re-mints every alias, orphaning any rewrite already applied. A key mismatch is
not a reason to pass `--force` — restore the matching key, or move both the map
and the key aside and re-run `plan` from a clean tree.

A *committed* salt would make every pseudonym a confirmable guess: anyone who
suspects a name can hash it and check. That is not de-identification, so the key
is the one artifact that must stay out of the repo (MLDATA-17).

**Consequence: CI cannot gate `verify`.** Without the key and the map, the
residue scan has nothing to scan for. `verify` is an operator-run check on a
machine that holds the private store, not a pipeline step. Do not add it to
`make check-all` — CI has no store, so the command can only ever be red
(`mint key not found`, exit 1). Do not wrap that exit as a skip: the same
code covers every other hard failure.

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
  bare tokens left alone (also carried by a non-personal identity): ['<given-name-token>']
  concat exclusions: 4 dropped (4× single-token name; no concatenation exists)
  adjacent exclusions: 6 dropped (4× no positional alias token; 2× pair maps to >1 identity)
  ambiguous family exclusions: <N> dropped
  wordlist: <N> words (sha256 ..)
  ambiguous media stems: 0 left unresolved (token maps to >1 identity)
  digest pins: <N> published; <S> stale; <M> missing
in-scope residue: 0 files / 0 occ; paths: 0; free-text: 0; unscannable in-scope: 0 (+1 declared); out-of-scope (reported only): 35 files
exit 0
```

The `bare tokens left alone …` line echoes leftover tokens. It belongs on
the operator's terminal only — never paste a live token list into a tracked
document.

**`verify` currently exits 0.** The three media stems that used to keep it
at 1 were shared tokens that also happen to be ordinary English. The
filename pass still leaves an ambiguous stem alone when no replacement
exists, but `_ambiguous_family_words` now mints one shared family noun for
a token two or more identities carry (PRIV-1-BR-29). Previously
`_ambiguous_stem_line` printed them as a note while the exit code stayed 0
— a measurement with no consequence attached, which is the shape a reader
mistakes for a clean run (PRIV-1-BR-15). A non-zero `verify` here is new
residue, not those three.

`verify` also prints `digest pins: N published; S stale; M missing` on
every run, including the zero case. That count is live and is not pinned
here. A missing record is not a zero on that line — it is the hard
failure above. `apply` now exits non-zero when its own pin check reports
stale or missing pins — the same finding `verify` already failed on. A
dry run does not check pins and prints `digest pins: not checked (dry run …)`
rather than a measured `0 published; 0 stale; 0 missing`.

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

exit 0. The oracle scans for *pre-scrub roster forms*. The two
checkers now agree on the exit code as well as the bytes: the
ambiguous stems the script used to count are rewritten by the family
backstop (PRIV-1-BR-29), and they were never among the oracle's
needles.

Three classes are deliberately left in place, and none is a residue claim:

- 73 roster tokens are ordinary dictionary words that happen to also be given
  names (15,555 occurrences, overwhelmingly prose in `literature/` and synthetic
  test fixtures). Rewriting them corrupts unrelated English, so they are out of
  scope by design rather than missed. *Bare* is the operative word: since
  PRIV-1-BR-27 one of these tokens standing next to an alias token of the same
  identity is rewritten, because the adjacency identifies it. The exclusion
  covers the lone word, not the phrase.
- 3 of the 4 single-token identities fall in that same class: each is a
  dictionary word, and one is a 4-letter token with 10,662 in-scope occurrences
  across 689 files (`Makefile`, `Dockerfile`, `pyproject.toml`, module names).
  Those occurrences are the ordinary word, not references to a subject. The
  fourth single-token identity is covered by the given-name pass and was
  rewritten. This row is reproducible: the word list behind it is pinned by
  sha256 in the alias map and both commands fail closed when it drifts. It was
  not always so — the loader used to degrade to an empty set on a host without
  `/usr/share/dict/words`, which is most CI images and containers, making the
  number an accident of the machine that ran it (PRIV-1-BR-26).
- 1 in-scope file is undecodable and declared, not skipped: an OOXML strategy
  brief whose single roster-token hit is a cited author surname in a
  bibliography entry. It is listed in `DECLARED_UNSCANNABLE` with that
  rationale; any *undeclared* undecodable in-scope file fails `verify` with a
  non-zero exit.

Media stems that map to more than one identity used to be left alone by the
filename pass; `_ambiguous_family_words` now mints a shared family noun for
those tokens (PRIV-1-BR-29). The stems are not listed here — one of them is
a roster given name, and a document explaining the scrub must not be the
thing that publishes it. `apply` and `verify` print the count
(`ambiguous media stems: N left unresolved (token maps to >1 identity)`),
re-derived from the roster on every run rather than pinned here where it
would rot. They never print the token.

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
  exercises the same seven passes as `apply` (CARD-08) — `name`, `single`,
  `slug`, `media`, `given`, `concat`, `adjacent`. The family backstop
  (`_ambiguous_family_words`) is a map the media pass consults; it is not an
  eighth counts key. Sharing the object is
  necessary but not sufficient: both are built from the same builders, so a
  builder that drops an entry blinds the checker and the rewriter together.
  That has now happened three times — the concatenated form as a whole; four
  3-token names whose 2-token aliases tripped a token-count guard; and two
  7-letter joined names dropped by an `>= 8` length floor. Every one was caught
  only by the independent oracle, never by `verify`. The floor is the clearest
  case: it was a *defensible* guard, correctly reasoned in its own docstring,
  and still wrong — because it was enforced by `continue` instead of by
  anchoring. Guard by narrowing the match, not by removing the entry.
- A guard that only runs at mint time has never seen the artifact that shipped.
  `_assert_vocab_disjoint_from_roster` refuses to mint a pseudonym word that is
  also a real name token — but it landed one commit *after* the map had been
  minted and applied, so it never ran against the state on disk, and it never
  could: it reads the roster, which `apply` has since pseudonymized. One
  collision was already live, invisible to everything. `verify` could not see it
  (a minted alias is by construction not residue) and `plan` refused to re-run
  (the roster now looks pseudonymized). `_assert_map_vocab_disjoint` re-tests the
  invariant against the shipped map, from `apply` and `verify`, and compares real
  name tokens against *live alias tokens* rather than against the vocabulary — so
  that editing the offending word out of `_ADJ` cannot silence it while the
  minted alias carrying that word stays on disk. The first draft of that guard
  did key off the vocabulary and reported clean over a still-colliding map.
  Retiring a vocabulary word is a *replacement* at a fixed index, never a
  deletion: the minter hashes into the list, so a length change re-mints
  everybody. Replacing in place left the other 89 aliases byte-identical.
- A correct exclusion can still leak, because it only looks at one word. The
  given-name pass refuses ordinary dictionary words on purpose — rewriting them
  corrupts unrelated English — and that judgement is right about the word and
  wrong about the phrase. A dictionary-word given name sitting next to a surname
  this scrub itself minted is not ordinary English; the neighbour is the
  evidence. `verify` reported 0 because `residue()` was built from the same
  builder that declined to look (CARD-08, third instance). The adjacent pass
  fires only when both halves are provable from the alias map — the leading
  token is a real-name token of identity X with a positional alias, and the
  neighbour is a *different-index* alias token of the same X — so ordinary
  English is safe by construction rather than by a length floor. Same-index
  pairing would have rewritten `<given> <own-alias-noun>` to
  `<alias-noun> <alias-noun>`. Built from the map, never the wordlist: a builder
  that reads the exclusion list can be silenced by editing the exclusion list
  while the exposed surface stays on disk (PRIV-1-BR-27).
- Widening a character class is not a free change. Adding `%20` to the separator
  as `(?:[\s_\-]+|%20)+` put a `+` inside an alternation under another `+`. For
  a run of N separator characters that ultimately fails to match, the engine can
  partition them into `[\s_\-]+` groups in 2^(N-1) ways and tries all of them:
  0.8 ms at 14 characters, 249 ms at 22, a clean 4× per two added characters. A
  JSON manifest indents far past 22, so `verify` stopped terminating on a corpus
  it had finished in two minutes the day before. The de-nested
  `(?:[\s_\-]|%20)+` accepts the same language with a unique parse, so matching
  is linear. The 65-test unit suite passed throughout — no fixture held a long
  separator run — and it was caught only by running `verify` end-to-end
  (PRIV-1-BR-28). Note for whoever tests the next one: a wall-clock assertion
  cannot catch this. `re.search` runs in C and never yields to the interpreter,
  so a timing check placed after the call never executes and `SIGALRM` never
  fires. Bound it structurally, by asserting on `regex.pattern`, and
  out-of-process with `subprocess.run(timeout=...)`.
- `re.IGNORECASE` changes what `[A-Za-z]` means. Under the flag it also matches
  the characters that case-fold into ASCII letters — U+017F LATIN SMALL LETTER
  LONG S folds to `s`, U+212A KELVIN SIGN folds to `k`. The adjacent pass
  compiles with the flag and then re-parses the matched span with a second
  pattern; that second pattern was compiled without it, so it rejected spans the
  first had accepted and the replacer returned them unchanged. The damage is not
  a missed rewrite, it is a *divergence*: `residue()` counts the span through the
  same pattern that matched it, so `verify` would have reported residue `apply`
  could never clear, permanently non-zero with no counter naming the cause. Any
  time one regex re-reads what another matched, the flags are part of the
  contract. Document-side lookups use `.casefold()`, not `.lower()`
  (PRIV-1-BR-30).
- A test fixture can spell a real leak. Minted aliases are ordinary English
  adjectives and nouns, and 73 roster tokens are ordinary dictionary words, so an
  author inventing plausible names draws from the same vocabulary the real map
  uses. One fixture here paired a genuine roster name token with a genuine minted
  alias token, and the moment the adjacent pass landed, `verify` counted this
  repo's own test file as residue — correctly, because at the byte level a
  fixture that spells a real pair and a real leak are the same string. The
  collision is invisible from inside an offload lane, which never receives the
  map. The repair is to rename the fixture, never to exclude the test file from
  the scan: excluding it would be an exclusion applied to the measurement, which
  is the one mistake this file has now made three times (PRIV-1-BR-31).
- An entry that cannot be rewritten raises instead of being skipped. A `continue`
  in a builder is indistinguishable, at the output, from a name that was never
  there.
- A map with no `wordlist` block used to warn and continue. `apply` and
  `verify` now refuse. `plan --pin-wordlist` is the non-destructive repair
  (it adds only that block); `--force` re-mints and is not the fix.
- An alias map without a `free_text_deny` list block is refused. Add the
  block; an empty list is valid.
- A tracked symlink is read as its own target string, not followed. Following it
  makes coverage depend on whether an overlay happens to be materialized in the
  current worktree — seven git-hook links read as `FileNotFoundError` and looked
  like a scan gap.
- A rewrite that goes around `apply` leaves every pin of that file stale.
  `_repin_digests` only runs inside `apply` and its baseline is the in-run
  map, so a one-shot migration that calls the passes and the writer directly
  has nothing to detect against. `verify` now re-hashes the pin record
  (PRIV-1-BR-32).
- A shared surname that is also an ordinary English word had no repair path
  in a filename stem. The given-name pass drops dictionary words before
  `_family_words` runs, and the filename pass leaves an ambiguous stem
  alone. `_ambiguous_family_words` is the third path (PRIV-1-BR-29).

## Known limits

- **Digest re-pinning still only repairs drift this script caused.**
  `_repin_digests` diffs digests captured at the top of an `apply` run
  against post-rewrite digests, so a digest that moves out-of-band — a
  hand edit, a rebase, a re-serialization by another tool — is invisible
  to the rewriter. `verify` now re-hashes every path in the pin record
  and exits 1 on stale or missing (PRIV-1-BR-11, PRIV-1-BR-32). `apply`
  now also exits non-zero when its own pin check reports those findings.
  Repair of an out-of-band move is still a manual old→new sweep iterated
  to a fixpoint; the next `apply` will not do it.
- **CI cannot gate any of this** (see *The key*). `verify` is an operator check.
