# L11-br2526 — verification of FIR-ORCH-BR-25 and BR-26

Lane: `L11-br2526` (verification-only). Worktree `/Users/daniel/Development/context-alt-text-monorepo-l11`, detached HEAD `f2ff25484` (`int/round9`).
No tracked production file was modified. No frozen artifact, anchor, run-record, manifest, or golden corpus was regenerated. All scratch under `/tmp/l11/`.

---

## FIR-ORCH-BR-25 — VERDICT: **CONFIRMED**

**Claim:** the reported `mean_tag_coverage` improvement `0.6068 -> 0.6838` on the 39-image split is not attributable to L2's roster-token-exclusion change.

### 1. Where the literals live

```
git grep -n '0.6068' / '0.6838'   (worktree)
```

- `0.6068` — **exactly one hit in the whole worktree**, and it is prose: `.lane/REPORT-L2-roster.md:266`. It is in **no** committed report, no test, no fixture, no code on this branch.
- `0.6838` — `.lane/REPORT-L2-roster.md` (prose) **and** the committed artifact
  `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json:1778` → `"mean_tag_coverage": 0.6838`.

### 2. Provenance of `0.6068` (git archaeology)

```
git log --all --oneline -S'0.6068' -- <report.json>
git show <c>:<report.json> | jq .quality.mean_tag_coverage
git merge-base --is-ancestor e93c41d17 HEAD
```

| commit | `mean_tag_coverage` |
|---|---|
| `e93c41d17` "re-freeze S2A caption determinism anchor after PRIV-1" | **0.6068** |
| `231a39d65` merge main into feature/vlm-6 | 0.6838 |
| `5a7d30209` regen anchor to FIR-11 v3 | 0.6838 |
| `898a90ea7` **L2's roster-exclusion commit** | 0.6838 |
| `HEAD` (`f2ff25484`) | 0.6838 |

`git merge-base --is-ancestor e93c41d17 HEAD` → **NO**.

`0.6068` is the value of the artifact on the **`main`/PRIV-1 lineage**, which is *not an ancestor of this branch*. `0.6838` was already the value on the `feature/vlm-6` lineage **before** L2's commit (`5a7d30209`, and back to `246dec928`). The "delta" is a **cross-branch artifact difference**, not a scorer change.

### 3. Controlled A/B re-run of the scorer (the decisive evidence)

`_caption_scores_without_identity_spelling` (added by `898a90ea7`) is L2's exclusion path; it is called from `score_run_record` for both `alt_text_draft` and `alt_text_long`. I ran `score_run_record` on the **same** frozen inputs twice — once as committed, once with that function monkeypatched to the identity function (pre-L2 behaviour). Read-only; nothing written back.

```
cd apps/prototype-description-service && ./.venv/bin/python /tmp/l11/ab2.py
```

| arm | mean_fkre | mean_repetition_ratio | **mean_tag_coverage** |
|---|---|---|---|
| A: roster-exclusion **ACTIVE** (as committed) | 65.12 | 0.0567 | **0.6838** |
| B: roster-exclusion **BYPASSED** (pre-L2) | 65.12 | 0.0567 | **0.6838** |

- Full `quality` dict comparison: `IDENTICAL? True`.
- Per-image `tag_coverage` across all 39 images: **zero differences**.
- media `2 / 24 / 25` tag_coverage: `1.0 / 1.0 / 1.0` in **both** arms (L2 reported `0.0 -> 1.0`; measured delta is `0.0`).
- advisory images: `0` in both arms.

**Neither arm produces 0.6068.** The patch's true delta on this corpus is exactly **0.0000**.

### 4. TEST-15 — proof the bypass lever can actually move the number

A "no difference" result is worthless if the lever is inert. I injected a roster name into one caption **in memory only** (`"Slate Willow sits at a table with Slate Willow's plate of food."`) and re-ran both arms:

```
cd apps/prototype-description-service && ./.venv/bin/python /tmp/l11/lever.py
```

| arm (mutated corpus) | mean_fkre | mean_repetition_ratio |
|---|---|---|
| ACTIVE | 64.60 | 0.0558 |
| BYPASS | 65.02 | 0.0556 |

`DIVERGE? True`. The lever is real; the null result on the true corpus is a property of the corpus, not a broken harness.

### 5. Conclusion

The figures `0.6068 -> 0.6838 (+0.0770)` and media `2/24/25: 0.0 -> 1.0` in `.lane/REPORT-L2-roster.md` are **not attributable to L2's change**. `0.6838` was the pre-existing checked-out value; `0.6068` originates from a different branch lineage (PRIV-1 re-freeze on `main`) that is not an ancestor of this branch. On the inputs actually scored, the roster-exclusion patch is a bit-identical no-op.

Mitigating note for the coordinator: L2's own prose is partly self-aware — it describes the fix as "returns `mean_tag_coverage` to the existing baseline `0.6838`" and explicitly declines to attribute the advisory-count movement. But it still states the `+0.0770` delta as this patch's metric delta under a "Metric deltas (T3)" heading, which is the mis-attribution BR-25 names.

**Confidence: HIGH.** Directly executed, deterministic, reproducible; lever verified falsifiable.

---

## FIR-ORCH-BR-26 — VERDICT: **CONFIRMED**

**Claim:** the 39-image freeze contains only generic seeded stub captions with no roster names, making the exclusion change a no-op on this corpus.

### Inputs
- Captions: `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json` → `items[*].describe.alt_text_draft` (39 items; `provenance.adapter = "seeded"`, `base_url = "seeded-stub://offline"`, `model_id = "seeded-fixtures"`).
- Roster: reproduced exactly as `report._corpus_roster` builds it — the manifest's top-level `roster` key in `S2A-determinism-anchor-manifest-20260811.json`, unioned with every entry's `present_identities`, `must_right`, and `easy_wrong`.

Resolved roster (10 names): `Auburn Current, Daniel Arce, Gilded Cypress, Hollow Pennant, Linen Kestrel, Muted Current, Muted Yarrow, Russet Fathom, Slate Willow, Tidal Harbor`.

### Matching rule
Two rules, both case-insensitive with word boundaries `(?<!\w)…(?!\w)`:
1. **Full-name** match — the whole roster string.
2. **Per-token** match — every alphabetic token of every roster name (`Slate`, `Willow`, `Auburn`, `Current`, …). This is the *stricter, more generous-to-the-defence* rule, and it is what L2's `_identity_quality_match_patterns` actually uses.

### Results

| measure | count |
|---|---|
| total captions | **39** |
| captions containing ≥1 full roster name | **0** |
| captions containing ≥1 roster **token** | **0** |

Additionally, `tag_coverage` is computed over `visual_facts.objects`. The **complete** distinct object vocabulary across all 39 items is:

`animal, building, chair, document, food, mountain, object, person, plant, plate, sky, table`

Objects containing a roster token: **0**. So the tag-scrubbing half of L2's change (`_quality_objects_without_identity_names`) is also provably inert here.

### 5 sample captions (verbatim)

```
media  1: "A plate of food on a wooden table."
media  2: "A plate of food on a wooden table."
media  3: "Two people seated indoors in conversation."
media  4: "A pet animal resting on a soft surface."
media  5: "A scenic landscape with mountains under a clear sky."
```

The corpus is generic seeded stubs exactly as the reviewer described. Note the manifest's *ground truth* is rich and name-bearing (e.g. entry 1 `base_caption`: "Slate Willow crouches on wet dark rocks inside a blue glacial ice cave…"), which is why the split looks name-laden at a glance — but the **model-side captions being scored** carry no names at all.

Count is **0** ⇒ **CONFIRMED**. This is the mechanistic explanation for BR-25's measured `0.0000` delta: with zero roster tokens in captions and zero in tags, the exclusion path cannot alter any quality metric.

**Confidence: HIGH.** Exhaustive over all 39 captions and the full object vocabulary; two matching rules, both zero.

---

## Cross-finding note

BR-25 and BR-26 are one fact seen from two angles. BR-26 explains *why* BR-25's delta is zero. The reported `+0.0770` is a cross-branch artifact diff mistaken for a scorer delta.

The underlying L2 patch is not thereby shown to be *wrong* — its two-spelling invariance unit test exercises real behaviour, and the TEST-15 mutation above shows the code path does work when roster names are present. What is unsupported is the **corpus-level metric claim**. If a corpus-level claim is wanted, it needs a caption corpus that actually contains roster names.

## HONEST STATUS: COMPLETE
