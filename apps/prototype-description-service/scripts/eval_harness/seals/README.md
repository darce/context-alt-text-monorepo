# Eval seals (post-split, 8b93c473)

Do not overwrite historical freeze hashes in place. A re-seal is a new named
anchor next to the old one (EVAL-10 / PROV-09).

## S1 eval split

| Anchor | Path | Source corpus | Status |
| --- | --- | --- | --- |
| `S1-sealed-eval-split-20260818` | `docs/tasks/vlm/bakeoff-results/S1-sealed-eval-split-20260818.json` | 37-entry `golden.json` (source SHA `93fc86b2…`) | **historical / superseded** by `8b93c473`. Held-out media_ids are the live reported 20. |
| `S1-sealed-eval-split-reported-20-20260822` | `scripts/eval_harness/seals/S1-sealed-eval-split-reported-20-20260822.json` | post-split reported `golden.json` (20 entries, source SHA `40270ff3…`) | **live**. Same seed / fraction / assignment rule. Train is empty because those 20 SHAs are the held-out half of the 20260818 draw. |

## S2A caption determinism freeze

| Anchor | Path | Corpus | Status |
| --- | --- | --- | --- |
| VLM6-DELTA-09 hashes `14e5e2e1…` / `bca65e31…` / `1d5c35bf…` | (test constant `_FROZEN_DIGESTS_PRE_SPLIT_37`) | 37-entry golden + traps 39/40 | **historical**. File bytes later moved (PRIV-1 scrub `231a39d6`) without a named re-pin. |
| On-disk 37+2 freeze | `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-*` | still 39 entries | **committed historical corpus**. Digests `_FROZEN_DIGESTS_37_CORPUS_ON_DISK`. Live `score --check-determinism` does not match this pair (stale vs live scorer). |
| reported-20 freeze | `scripts/eval_harness/seals/caption-freeze-reported-20/` | 20 reported + traps 39/40 | **live generator/scorer anchor**. Digests `_FROZEN_DIGESTS_REPORTED_20`. |
