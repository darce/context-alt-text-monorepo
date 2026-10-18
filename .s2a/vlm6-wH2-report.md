# Lane wH2 — operator instructions that no longer describe the harness

**Branch:** `fix/wh2` · **Base:** `271265886b075b1078cec7e30c224152708ec7fb`  
**Owned files:** eval-harness README / operator docs, `generate_face_determinism_anchor.py` (comments only), `cli.py` (help/docstrings only)  
**Not touched:** `report.py`, `face_bakeoff.py`, assignment/metrics/manifest, tests, bakeoff-results artifacts, Makefile (cross-lane).

**Posture:** documentation + comments only. **No runtime behaviour change. No tests added** (TEST-15: a code test of prose would be vacuous; evidence is executed command transcripts).

---

## Finding 1 — Score-time man for caption freeze is bakeoff-results man, not golden (wG3 residual 3)

### Reproduction probe (verbatim — stale documented procedure)

```text
cd apps/prototype-description-service
./.venv/bin/python -m scripts.eval_harness.cli score \
  --manifest scene/tests/seed/golden.json \
  --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
  --rubric-gate skip
```

### RED capture (verbatim)

```text
score manifest-drift gate: scored against score_manifest_sha256=83bfdc4e50b441dd60f4d7b6613dac57f42e8bb1e216f53cfeab147984cfd737 but fetched under 7462d3259f068aa187cd5f2dc3cd934eaa3b4b2a71e441f9e362f7e6cbfc9fd3 (manifest_matches_fetch=false); numbers are not comparable to a baseline scored on the fetch-time corpus (EVAL-13). …
scored=37/38 insertion_rate=0.0 wrong_names=4 verdict=fail wrong_name_rate=0.1081 wrong_name_rate_floor=0.0 rubric_gate=skip
EXIT_CODE:1
```

Same path under `--check-determinism --expect-report … --freeze-certification` → `determinism check ANCHOR_MISMATCH [score]` EXIT 1 — looks exactly like freeze drift, but the man is wrong (rg-006 false alarm).

wG3 established: freeze corpus = golden seed + media 39; freeze man lives at
`docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json`
(38 entries, `face_boxes` 1/38). Run `provenance.manifest_sha256` prefix `sha256:7462d325…`.
Golden seed stays 37 entries, sha prefix `sha256:83bfdc4e…`, 0/37 face_boxes.

### Fix

1. **README** — every freeze score example / operator path that named `--manifest scene/tests/seed/golden.json` now names the caption freeze man. Corpus-coverage section distinguishes **Golden seed** vs **Caption freeze man**. Example transcript uses `scored=38/38` / `wrong_name_rate=0.1053`. Explicit anti-pattern: do not pass bare golden for freeze checks.
2. **cli.py** — `--manifest` help on `_common` (score/fetch/run) documents freeze man requirement; `score-face --manifest` help notes golden is unsuitable for the synthetic face freeze.
3. **Makefile `eval-anchor-check`** still hardcodes golden — **not owned**; Cross-lane request below. README warns until that recipe is fixed.

### GREEN capture (verbatim — corrected command executed)

Live score against freeze man (no expect — proves man/run agreement; adoption floor still hard without `--freeze-certification`):

```text
$ ./.venv/bin/python -m scripts.eval_harness.cli score \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
    --rubric-gate skip
score wrong-name floor gate: wrong_name_rate=0.1053 exceeds floor=0.0 …
scored=38/38 insertion_rate=0.0 wrong_names=4 verdict=fail wrong_name_rate=0.1053 wrong_name_rate_floor=0.0 rubric_gate=skip
EXIT_CODE:1   # adoption floor only — no manifest-drift
```

Freeze-cert with corrected man (report bytes still pre-regen stale — Expected-red, regen stage owns):

```text
$ ./.venv/bin/python -m scripts.eval_harness.cli score \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.json \
    --check-determinism \
    --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json \
    --rubric-gate skip \
    --freeze-certification
determinism check ANCHOR_MISMATCH [score]: fresh re-score does not match --expect-report …/S2A-determinism-anchor-run-20260811-report.json …
EXIT_CODE:1
```

Help text verified live:

```text
$ ./.venv/bin/python -m scripts.eval_harness.cli score --help
  --manifest MANIFEST   … Caption determinism freeze must pass the
                        bakeoff-results caption man S2A-determinism-anchor-
                        manifest-* (golden+media-39 trap), not bare
                        golden.json — otherwise manifest-drift / scored=37/38
                        (wG3 / rg-006). Live run/fetch keep the golden default.
```

---

## Finding 2 — Obsolete `float(y)` rationale on face media 11 (wG2 residual 3)

### Reproduction probe

```text
grep -n 'float(y)\|Zero detections so face association' \
  apps/prototype-description-service/scripts/eval_harness/generate_face_determinism_anchor.py
```

### RED capture (pre-edit)

```text
100:# Zero detections so face association never float()-coerces the null y.
398:                # detections so face association never float()-coerces null y.
538:            faces=[],  # VLM6-R2-G-01: order_degraded trap; no det so no float(y)
```

wG2 made null-y + `n_det>0` safe via `geometry_incomplete_gt` stamp. Comments documented a phantom constraint.

### Fix

Comments rewritten to state: (1) media 11 exists so `labeled_y_missing_images` / `order_degraded` can leave structural 0; (2) `faces=[]` is deliberate **isolation of that counter**, not a crash dodge; (3) null-y+dets is safe since wG2.

### GREEN capture

```text
100:# Null-y + detections is now safe (wG2: associate_detections stamps
101:# geometry_incomplete_gt instead of float(y)); this media still uses faces=[]
…
403:                # faces=[] on the matching run item is deliberate isolation of
404:                # the order_degraded counter — not a crash dodge. wG2 made
…
544:            faces=[],  # VLM6-R2-G-01: order_degraded trap; faces=[] isolates counter (null-y+dets safe since wG2)
```

No behaviour change (comments/docstrings only).

---

## Task 3 — same-class sweep (inspected-sites table)

### Task 1 + 3 combined: every hit inspected

| file:line | claim | still true? | changed? |
| --- | --- | --- | --- |
| `README.md:5` | scores against 37-image golden | **yes** for live default; freeze is separate corpus | no (live default still golden) |
| `README.md:41–62` (was 51 golden) | freeze CLI uses `--manifest golden.json` | **no** — freeze man is bakeoff-results caption man | **yes** → freeze man path + warning |
| `README.md:124–136` (was) | Caption corpus = golden only, face_boxes 0/37 | golden seed still true; freeze man different | **yes** — split Golden seed vs Caption freeze man table |
| `README.md:151–157` | (new) freeze man 38 entries / 1 face_boxes | **yes** (measured: man n=38, face_boxes=1) | **yes** added |
| `README.md:176–181` | Face freeze is byte-stability / dim=8 | **yes** | wording: dedicated face man (not golden) |
| `README.md:203–213` (was) | S2A anchor over full golden 37 | **no** — freeze is 38 = golden+trap | **yes** |
| `README.md:239` (was) / `265` | freeze example `--manifest golden.json` | **no** | **yes** → caption man; scored=38/38 |
| `README.md:261–263` (was) | frozen triple under run stem only | incomplete — man is co-equal | **yes** — frozen set includes man |
| `README.md:379–390` | Caption freeze path + make eval-anchor-check | make still wrong (Makefile) | **yes** — names freeze man; make caveat |
| `README.md:74` | hosted matrix over golden | **yes** (live hosted, not freeze) | no |
| `README.md:429–435` | Rubric status on golden-37 | **yes** | no |
| `README.md:482–487` | face freeze CLI uses face man | **yes** already | no |
| `cli.py:3` | fetch walks golden manifest | **yes** for live default | no |
| `cli.py:2421–2431` | `--manifest` default golden, no freeze guidance | default ok; freeze guidance missing | **yes** help text |
| `cli.py:2506–2516` | expect-report help | **yes** | no |
| `cli.py:2517–2528` | freeze-certification help | **yes** | no |
| `cli.py:2589` (was bare default) | score-face `--manifest` default golden | default ok for live; freeze needs face man | **yes** help text |
| `cli.py:2590–2615` | score-face determinism/expect/freeze help | **yes** | no (except manifest help) |
| `generate_face…:8–12` | golden unsuitable face freeze (0 face_boxes) | **yes** | no |
| `generate_face…:97–103` | Zero dets so no float(y) | **no** (wG2 fixed crash) | **yes** |
| `generate_face…:111–117` | corpus_traps sampling frame | **yes** | no |
| `generate_face…:141–144` | media 11 trips labeled_y_missing | **yes** | no |
| `generate_face…:179–183` | Not golden for face man | **yes** | no |
| `generate_face…:196` | Bob y / Alice omits y mixed shape | **yes** | no |
| `generate_face…:399–406` | float(y) crash dodge comment | **no** | **yes** |
| `generate_face…:512,528,536` | faces=[] FN / HARM-05 | **yes** (true zero-det misses) | no |
| `generate_face…:544` | faces=[] no float(y) | **no** as crash rationale | **yes** |
| `generate_face…:563–573` | fixture sentinels / corpus_traps | **yes** | no |
| `Makefile:639` | `eval-anchor-check` caption man = golden | **no** | **no** (not owned) → Cross-lane |
| `Makefile:646` | face leg uses face man | **yes** | no (inspected) |
| `scene/tests/seed/README.md:71–81` | determinism evidence points at harness README | **yes**; no freeze man claim | no (not owned; not stale on freeze man) |
| `docs/tasks/vlm/VLM-6-gpu-…md` freeze compare via make | names make/expect-report, not golden man path | partially stale via make | no (task plan; make is the bug) |
| `docs/tasks/vlm/VLM-2A/2B/2C` plans | score/run against golden for **live** work | **yes** | no |
| `docs/tasks/vlm/bakeoff-results/*` | freeze artifacts | out of scope | not edited |
| `generate_determinism_anchor.py:16–20` | freeze = golden+trap; score man is bakeoff man | **yes** (generator owns truth) | not owned; verified still correct |
| Other eval_harness `*.md` | only README.md | n/a | n/a |

**Judgement on wave-changed claims specifically:**

| Class | Sites | Verdict |
| --- | --- | --- |
| `y` required / float(y) crash dodge | generate_face L100, L398, L538 | **fixed** (L100–103, L399–406, L544) |
| association always complete | none in owned docs asserting completeness without stamp | left alone |
| face report lacks ordering counters | not claimed in owned operator docs | left alone |
| namedness per-call-site | not claimed in owned docs | left alone |
| freeze scores against golden | README + cli help + Makefile | README+cli fixed; Makefile cross-lane |

---

## Disagreements

**None** after live probes:

1. wG3 residual 3 confirmed: golden score of freeze run → manifest-drift + 37/38; caption man → 38/38 no drift.
2. wG2 residual 3 confirmed: three float(y) rationale comments present pre-edit.
3. Face freeze docs already used the dedicated face man — no parallel bug on that path in README examples.

---

## New findings (not owned)

1. **`Makefile` `eval-anchor-check` still passes `scene/tests/seed/golden.json` for the caption leg** — the one-shot operator target the README pointed at is still the stale procedure. Fix is a one-line `--manifest` swap to the caption freeze man (face leg already correct).
2. Any CI/docs that shell out to `make eval-anchor-check` inherit that bug until the Makefile is fixed.
3. Freeze report ANCHOR_MISMATCH under correct man remains (pre-existing regen debt) — not a doc defect.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1403 passed, 4 skipped` (190.80s) — **identical to base**.

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | Pre-existing caption report freeze staleness (regen stage). |
| `test_expect_report_matches_committed_freeze_green` | Same. |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | Pre-existing face report freeze staleness (regen stage). |
| `test_face_expect_report_matches_committed_freeze_green` | Same. |
| `test_cli_score_face_expect_report_end_to_end_green` | Same. |

### Unexpected-red

**None.** Doc/comment-only lane added zero new reds.

### Tests added

**None.** Documentation lane; a vacuous code test would itself be the failure mode this wave sequence convicts (TEST-15). Evidence is executed command transcripts above.

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base 271265886b075b1078cec7e30c224152708ec7fb
 .../scripts/eval_harness/README.md                 | 115 ++++++++++++++-------
 .../scripts/eval_harness/cli.py                    |  22 +++-
 .../generate_face_determinism_anchor.py            |  14 ++-
 3 files changed, 106 insertions(+), 45 deletions(-)
 + .s2a/vlm6-wH2-report.md (this report)
```

---

## Could not verify

- Post-regen freeze-cert EXIT 0 under corrected man (report regen is a later stage; live re-score already matches man/run at scored=38/38 with no drift).
- Whether any out-of-tree operator scripts hardcode golden for freeze checks.
- Makefile fix effect end-to-end after regen (not owned; cross-lane).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Makefile / harness tooling owner** | In monorepo-root `Makefile` target `eval-anchor-check` (≈L639), change caption `--manifest scene/tests/seed/golden.json` → `--manifest ../../docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-manifest-20260811.json`. Face leg already correct. Without this, `make eval-anchor-check` remains the stale procedure README now warns about. |
| **Caption freeze regen stage** | Regenerate caption report JSON/MD from wG3 man+run (not golden). After regen, freeze-cert with the caption man path above should go green. Do not re-point score man at golden. |
| **Face freeze regen stage** | Unrelated to this lane's doc fix; still needs report regen for the three face Expected-reds. |
