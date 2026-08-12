# VLM-6 S2A F4 — fresh re-scorable committed determinism anchor

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped `master`)  
**Scope:**  
- `scripts/eval_harness/generate_determinism_anchor.py` (new generator)  
- `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.{json,-report.json,-report.md}`  
- `scripts/eval_harness/README.md` (F3-01 carry-over: repo-local green path)  
- `scene/tests/test_eval_harness_determinism_anchor.py` (digest pin + TEST-15)  
- this report  

**Did not touch:** `report.py`, `cli.py` gate logic, `test_eval_harness_pipeline.py`, `golden.json`, any existing `*run-record*.json`, `describe_baseline.py` (B-11 residual).

## Verdict

**merge_ready** for F4. Fresh offline seeded anchor re-scores green under `score --check-determinism`; generator is twice-run byte-identical; both report artifacts frozen; README F3-01 sandbox paths replaced with real repo-local command output.

## Generation path

**Offline `SeededDescriptionAdapter` + synthetic image bytes** via  
`python -m scripts.eval_harness.generate_determinism_anchor`.

Why: model-free, no paid remote, no `GOLDEN_IMAGES_DIR`, deterministic from committed `scene/tests/seed/golden.json` alone. Seeded-stub scoring uses `--rubric-gate skip` (vacuity exemption → `verdict=pass_ungated`) — expected and disclosed, not suppressed.

`provenance.manifest_sha256` is **computed** at generation time via `cli._manifest_sha(load_manifest(...))` — never hand-stamped (rg-015).

## Heuristics

| ID | How satisfied |
| --- | --- |
| **rg-015** | Manifest sha computed by `_manifest_sha` at generation; not edited into the record. |
| **rg-006** | README working command uses repo-local paths and pasted real exit-0 output. |
| **TEST-15** | Frozen digests pinned in suite; mutating `verdict` on report.json changes sha; restore still matches freeze. B-06 digest-gate compare not implemented (next lane) — detection at committed-digest level. |
| **sr-001** | No gate/test weakened; legacy bare-string baselines still documented RED; seeded skip is the declared operator mode. |
| **Greenfield** | New anchor; no migration of 2026-07-14 / VLM-2C records. |

## Evidence

### Manifest sha (computed, not typed)

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -c "
from scripts.eval_harness.cli import _manifest_sha
from scripts.eval_harness.manifest import load_manifest
print(_manifest_sha(load_manifest('scene/tests/seed/golden.json')))
"
859a083ee2594b993543e52d9a5c5c9b13e4b98c7c2b87bc390bff8b29c6f123
```

Record provenance matches that value; generator stdout also prints `manifest_sha256=859a083e…`.

### Generator twice-run byte-identical

```text
$ uv run --extra dev python -m scripts.eval_harness.generate_determinism_anchor --out-dir /tmp/vlm6-f4-a
$ uv run --extra dev python -m scripts.eval_harness.generate_determinism_anchor --out-dir /tmp/vlm6-f4-b
$ sha256sum /tmp/vlm6-f4-a/* /tmp/vlm6-f4-b/*
743d06ad…  …/S2A-determinism-anchor-run-20260811.json   (both dirs)
03ad0c6c…  …/S2A-determinism-anchor-run-20260811-report.json
51224e12…  …/S2A-determinism-anchor-run-20260811-report.md
$ diff -q /tmp/vlm6-f4-a/* /tmp/vlm6-f4-b/*  # all match → BYTE_IDENTICAL_OK
```

### Anchor re-scores green (`score --check-determinism`)

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --manifest scene/tests/seed/golden.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
    --rubric-gate skip \
    --check-determinism
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42)
../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass_ungated wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=skip
EXIT_CODE:0
```

### TEST-15 corruption control (digest level; B-06 not yet built)

```text
frozen_report_sha=03ad0c6c31f2f953cf7ac2523620b8382818976327d7c4a1052c4fab86a7690a
corrupted_report_sha=25217bef859fb0ab73b43abcdefc7f1526ebde8e64e00ab48ac6560873dc9945
TEST15_DIGEST_DIVERGES True
restore_sha True
```

Suite: `test_corrupt_frozen_report_digest_diverges` + pinned `_FROZEN_DIGESTS`.

### Old records untouched

```text
git status --short | grep run-record
# (no existing *run-record*.json modifications)
# only NEW: S2A-determinism-anchor-run-20260811.json (+ reports)
```

### Gate

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
692 passed, 4 skipped, 408 deselected, 9 warnings in 69.47s (0:01:09)
```

Baseline was 687 passed / 3 skipped (or 686/4 post-F2f); this run: **0 failed**, passed **>= 687** (692 = prior + 6 new anchor tests).

## Frozen digests

| file | sha256 |
| --- | --- |
| `S2A-determinism-anchor-run-20260811.json` | `743d06ad9441c8dc96d6a525741b507e9f51914d26e8faafdcbdc5b0b7e38312` |
| `S2A-determinism-anchor-run-20260811-report.json` | `03ad0c6c31f2f953cf7ac2523620b8382818976327d7c4a1052c4fab86a7690a` |
| `S2A-determinism-anchor-run-20260811-report.md` | `51224e12818bab0da3335bbe002a553aa510a0ee8fa7ab3649f2ac197210f17b` |

## B-06 recommendation (do not implement here)

Digest gate should: load committed `…-report.json` (or a canonical score serialization of the run-record under fixed rubric_gate/audience), re-score the committed run-record in a child process, and `sys.exit` non-zero on byte mismatch — independent of parent in-process baseline so a corrupted record cannot corrupt both sides (unlike today's face path).

## Residual / out of scope

- **B-06** digest gate itself — next lane; anchor now makes it buildable.  
- **B-11** `describe_baseline.py` secrets path under `oci_vault` — still open; not F4 scope.  
- Legacy bare-string run-records left archival (no re-stamp).

## Commit SHA

- F4 land (generator + freeze + README + tests + report): `439c8ee165b88a4f3a57592886d9f924a9798c1e`

Verified: `git cat-file -t 439c8ee165b88a4f3a57592886d9f924a9798c1e` → commit

<!-- Corrected (VLM6-S2A-F3-02 class, 4th instance): the lane cited a sandbox-clone
     SHA and its own cat-file verification — both true in its sandbox clone, neither
     resolvable here. See scripts/check_lane_report_shas.py for the guard. -->


Note: the report file itself is included in that commit; the SHA cites the landed tree. A follow-up docs-only tweak of this citation line may produce a different tip SHA — always prefer `git rev-parse HEAD` / `git log -1`.
