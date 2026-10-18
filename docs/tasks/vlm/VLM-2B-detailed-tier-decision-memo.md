# VLM-2B — Detailed-Tier Caption Model Decision Memo

> **Metadata**
>
> - **Date**: 2026-07-07 EST
> - **Task**: VLM-2B (`docs/tasks/vlm/VLM-2B-detailed-tier-bakeoff-task-plan.md`)
> - **Corpus**: `scene/tests/seed/bakeoff_golden.json` — 10 golden images, real name-injected context packs, §6b discriminating classes
> - **Protocol**: llama.cpp b9893 on OCI A1 (CPU, aarch64), official Q4_K_M GGUF + mmproj, greedy (temp 0), max 512 tokens, `--image-max-tokens 1536`, concurrency 1, 900 s/request ceiling, unchanged `cli.fetch_run_record` walker; scored by unchanged `report.build_reports` (`--check-determinism` passed on every record)
> - **Artifacts**: `VLM-2B-bakeoff-<model>-{run-record,report}.{json,md}` (this directory) · serving bench: `VLM-2B-a1-serving-notes.md`

## Decision

**Winner: Qwen3-VL-4B-Instruct (Q4_K_M).** It becomes the detailed-tier `DescriptionAdapter` candidate in the follow-on task.

## Comparison table

| Metric | **Qwen3-VL-4B-Instruct** | CapRL-Qwen3VL-4B | MiniCPM-V 4.5 |
| --- | --- | --- | --- |
| Items scored | **10/10** | **10/10** | 6/10 (4 empty captions) |
| Insertion rate (cohort) | **1.000** | **1.000** | 0.800 (of scored only) |
| Must-Right failures | **0/9** | **0/9** | 1/9 (`mcm-planecrash`: dropped supplied name) |
| Policy violations (trap: `maria-pool`) | **0** | **0** | 0 |
| Mean gated score | **0.90**¹ | **0.90**¹ | 0.67 |
| FKRE mean | **60.1** | 57.5 | 51.9 (scored only) |
| Mean words/caption | 51 | 59 | 51 |
| Mean latency/image (A1) | **206 s** | 208 s | ~280 s² |
| Peak RSS | 7.0 GB | 6.9 GB | 11.2 GB |
| Cold load | 27 s | 37 s | 73 s |
| License (HF repo tag) | Apache-2.0 | Apache-2.0 | Apache-2.0³ |
| Wrong-fact signal (manual) | **conservative; flags context-pixel conflict explicitly** | 3–4 unverifiable specifics (see below) | drops supplied names under pressure |

¹ The 0.90 ceiling is structural: the policy-disabled trap (`maria-pool`) scores gated 0.0 by construction when the model correctly does *not* name the unnamed person — both models behaved correctly there.
² MiniCPM latency inflated by thinking-token generation on failed items; successful items ran ~230–330 s. **Latency, peak RSS, and cold-load rows are read from the A1 serve logs / `VLM-2B-a1-serving-notes.md`, not derivable from the committed run-records** (which carry per-item timings only inside MiniCPM's error payloads). They were "equal within noise" and not decisive; every *scored* metric above is reproducible from the committed records.
³ License is read from the HF **repo metadata tag** (`apache-2.0`), not the LICENSE text / model-weight terms; HF has historically paired Apache-2.0 code with separate weight terms, so treat the tag as indicative, not authoritative. Moot for MiniCPM (disqualified on structural failures); the winner's Apache-2.0 (Qwen3-VL-4B-Instruct) is externally well-corroborated. Confirm against the LICENSE file before the adapter-build task ships.

## Why Qwen3-VL-4B-Instruct over CapRL

The deterministic tier ties them (both perfect). The tiebreakers, in order of product risk (§10: wrong-name/wrong-fact insertion is the top risk):

1. **Wrong-fact signal.** CapRL embellishes with unverifiable specifics: float branding `“Abdul’s Blue Boutique x SUNNYLIFE”` (`maria-pool`), poster text `“RASPBERRY OAT MILK”` attributed to a Pink Panther poster (`muted-bar`), and `“likely a Rottweiler”` (`nina-machiavelli`) — three fabricated specifics verified verbatim in the committed run-record, none gate-detectable, all exactly the class of plausible-but-unverified detail the product must not emit. Qwen adds no such specifics. (A fourth CapRL example, `“likely in Iceland … as noted in the album’s description”` on `mcm-planecrash`, is weaker: the crash-site *is* in the description, so the sentence is parseable as attributing the crash-site rather than Iceland — the "album says no such thing" reading holds only for *Iceland*. The three above stand on their own.)
2. **Context-conflicts-pixels behavior** (`mcm-planecrash`): Qwen anchors on pixels and flags the tension with the caption (“contrasting with the caption’s description of a summer garden picnic”). **Caveat on discriminating power:** the manifest `context_pack.description` for this entry *itself* discloses the answer (“the photo itself shows the black-sand plane wreck site”), so both models were told the site is a wreck — Qwen’s flag plausibly echoes the context’s own disclosure rather than proving independent pixel-anchoring. This tiebreaker is therefore softer than tiebreaker 1; the winner does not rest on it.
3. **FKRE** (readability): 60.1 vs 57.5, minor.
4. Latency/RSS/cold-load: equal within noise.

CapRL is *not* disqualified — its §13 obedience risk resolved positively (perfect insertion, no policy violation). It is the runner-up if Qwen fails downstream.

## Why MiniCPM-V 4.5 is disqualified

- **Hybrid thinking cannot be reliably disabled under the fixed protocol.** Two attempts: (a) server-side `--reasoning-budget 0` — ignored by the GGUF chat template; (b) prompt-side `/no_think` (its LLM is Qwen3-8B) — still auto-thinks on 4/10 images. In both attempts the model burned the entire 512-token budget inside `reasoning_content` and returned an **empty caption** (`finish_reason: length`) on 4 items (different items per attempt — nondeterministic across configs). Empty captions are structural per-item failures, not scoring noise.
- **Must-Right failure when it does answer**: on `mcm-planecrash` it dropped the supplied name entirely (“A person with long hair…”), the exact injected-name-weaving failure this bake-off exists to catch.
- Highest RSS (11.2 GB) and slowest cold load (73 s). **Only the `/no_think` attempt is committed for audit** (`MiniCPM-V-4.5-run-record`): 4 empty-caption items (`quiet-nye`, `ccqw-candid`, `linen-kestrel-painting`, `muted-bar`), each `finish_reason: length` with the full 512-token budget in `reasoning_content`, plus the `mcm-planecrash` dropped-name failure — this record alone fully supports disqualification. The thinking-mode (`--reasoning-budget 0`) attempt lives only in `scripts/eval_harness/out/` (git-ignored) and is **not** repo-auditable; the "different items per attempt / nondeterministic across configs" observation rests on that uncommitted run.

## Protocol notes / caveats

- Face-detection/identification sections of the REPORTs are **vacuous by design** (stub `analyze`/`media_identities`; face metrics out-of-band per scope §5). Tag coverage is N/A (candidates emit no `objects`). Neither was used as a discriminator.
- `--image-max-tokens 1536` was required: without it, Qwen3-VL dynamic resolution pushed large images past a 600 s timeout (first attempt aborted via bounded-stall, rg-007 working as designed). The cap applies identically to all candidates.
- Insertion rate measures *weaving of supplied names* only (merge-only, §3a); candidates performed no recognition.

## Hand-off to the adapter-build task

Build the detailed-tier `DescriptionAdapter` around **Qwen3-VL-4B-Instruct Q4_K_M + mmproj Q8_0** (llama.cpp ≥ b9893, `--image-max-tokens 1536`, greedy). Expected serving envelope on the A1: ~7 GB RSS, ~27 s cold load, ~3.5 min/image at 3 threads. Do not register `PROFILE_SPECS` from this task (out of scope).
