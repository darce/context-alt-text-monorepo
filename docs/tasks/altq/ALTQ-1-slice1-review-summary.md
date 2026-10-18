# ALTQ-1 Slice 1 — Parallel Review Summary (round r07140ddf, 2026-07-14)

Durable record of the `/review-parallel` pass over the Slice-1 eval-harness
implementation (`feature/altq-1` @ `0ddf1d99`). **Finding bodies live in the
handoff DB** (`review_findings(review={"operation":"list","task_ref":"ALTQ-1"})`),
per the Review Findings Placement rule — this document records the round's
shape, themes, and verdict, and references findings by ID only.

## Round shape

- Mode: whole-branch fallback (`branch_diff` scope — no slice packets existed;
  stated in verdict decision `claude_review_parallel_verdict_altq1`).
- Reviewers: 2 adversarial record-only reviewers, in-process fan-out
  (Claude Code `Agent` primitive per the harness routing table), scoped refs
  `ALTQ-1-REV-r07140ddf-A` / `-B`, single-probe preflight (commit+date round token).
- Merge: 18 findings merged under `ALTQ-1` with `merged_from` provenance;
  source rows retired `superseded`.
- Review run: `altq1-review-parallel-r07140ddf` (branch mode, id 389).
- Verdict: **pass_with_findings** (decision `claude_review_parallel_verdict_altq1`, 2227).

## Severity distribution

1 high · 7 medium · 10 low (18 total: A-01..A-10, B-01..B-08 under `ALTQ-1`).

## Themes (findings by ID)

1. **Name-matching granularity** — ALTQ-1-REV-B-01 (high): full-name
   word-boundary matching is blind to first-name-only mentions, weakening the
   wrong-name trap, name_precision, and distractor_taken simultaneously.
2. **Eval-mode transform/score consistency (rg-015 class)** — A-02, A-03, B-03,
   B-04, A-09: fetch-time transforms (ablation/distractor) are narrower than
   score-time assumptions (present-names-only, top-level-str-only ablation;
   stamps recorded but never consumed; fetch/score manifest drift unenforced).
3. **Denominator coherence on ineligible rows** — A-06, B-02: wrong-name
   counts vs rates use different eligibility filters; markdown implies one
   denominator.
4. **Roster completeness** — A-01, B-07: manifest top-level `roster` ignored by
   `_corpus_roster`; unreferenced roster names escape the hallucination gate.
5. **Ablation gate edge** — A-04: policy-disabled rows exit before the leak
   check in ablation mode.
6. **Signal-quality lows** — A-05, A-08, A-10, B-05, B-06, B-08, A-07:
   trap-set validation, 125-char boundary, NFC normalization, abbreviation
   sentence-splitting, duplication-metric confounds, long-surface distractor
   blind spot, EVAL_MODES constant duplication.

## Verified-clean (both reviewers)

mean_gated_score refactor equivalent to the old inline computation in standard
mode; old run-records (no eval_mode / stamps / long surface) score unchanged;
regex metacharacters escaped; `_render_context` renders the injected
`also_pictured` field; `_fmt` None-handling; empty-caption handling. Reviewer B
verified the latent findings (3/7) are not live against the current golden.json.

## Gate consequence

Fix the high finding plus the eval-mode-integrity mediums **before any live
bench uses the eval modes** — VLM-4's measure-gate (Easy-Wrong reduction)
consumes exactly these metrics, so their validity is on VLM-4's critical path.
Heuristics anchor: [GRPH-18] (a borderline match that names an entity is
B-tier), [GRPH-14] (assert against recorded lineage — the stamps — not
assumptions).
