# Lane F17 — DESCQUAL-2 scope doc redesign (prose and arithmetic only)

Owned file: `docs/scopes/descqual-2-fact-annotation-pilot.md`.
No production code. Frozen frame: `/home/ubuntu/l1/fir12-n3/benchmarks/manifests/fir12-selection-v1.json`.
Shipped module: `scripts.eval_harness.audit_sampling`.
Python: `/home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python`.

This lane has no pytest of its own. Evidence for every published number is the
exact call against the shipped module and frozen frame, pasted below.
TEST-15 for prose: OLD vs NEW numbers, and a mutant that would republish the
rejected design.

---

## BR-17 (GATE-BLOCKING) — demote the ~30-image draw; pre-register planning ICC

**Canon:** AUDIT-11, AUDIT-09.

**What changed.** The ~30-image draw is now a **cost and instrument pilot**
(minutes per image, rubric α, gold-item QC). It is not the source of `deff`.
Full-study n is a **pre-registered planning ICC of 0.20 → n = 216**, with the
**0.30 → n = 261** sensitivity row printed beside it. A **subject-stage draw
over the 65 subjects with m ≥ 3 (195 images)** is a named conditional follow-on,
not the baseline; that design reports the Fisher-Z **upper** CI bound.

OLD success criterion: "the pilot outputs a measured ICC and a design effect,
and the full-sample n is derived from them rather than chosen."
NEW: pilot does not output a measured ICC; n = 216 (planning) / 261 (sensitivity).

OLD table (HEAD `9879c2e8`, arithmetic-mean M=4.9): ICC 0.1/0.2/0.3 → n 117/150/183,
and "ICC is measured, not assumed."
NEW table (Kish a=12.90, N=640): 84/124/159/**216**/**261**/327.

**Calls (frame + module).**

Frame facts used in the redesign (not `size_for_margin` outputs):

```
N=640, labeled subjects=130, Σm=544, empty present_identities=115
sum m(m-1)=6476
m≥2: 76 subjects; m≥3: 65 subjects
E[within-subject pairs at n=30] = C(30,2)*6476/(640*639) = 6.888350938967136
```

```
>>> from scripts.eval_harness.audit_sampling import size_for_margin, design_effect
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.2).n
216
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.3).n
261
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.045).n
121
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=0.360).n
284
>>> size_for_margin(margin=0.10, population=640, cluster_size=12.90, icc=1.0).n
423
```

Fisher-Z 95% CI at ρ=0.20, k=65, m=3: **[0.0449, 0.3595]** → published **[0.045, 0.360]**.
Implied n on a=12.90: **121..284**.
k=4, m=2, ρ=0.20: **[−0.828, 0.920]** → published [−0.83, 0.92]; implied n 84..423.

**Mutant (TEST-15).** Restore the OLD success criterion and plug a 30-image ICC
point estimate into `size_for_margin`. Fisher-Z 95% CI at true ρ=0.2 with k=4
clusters of size 2 is [−0.83, 0.92] (effectively [0, 1]). Implied n over that
CI is 84..423 — the entire planning table plus the ICC=1 cap. That is the RED:
the published n is not identified at this pilot size.

**Could not close.** Nothing. Partition (`a` vs `N`) is BR-22; grain is BR-19;
hand-typed cells are BR-23.

---

## BR-22 (high) — one PSU partition for both Kish `a` and `N`

**Canon:** AUDIT-11.

**What changed.** Declared a single image-level PSU partition used for both `a`
and `N`: unlabeled images stay in N=640 as singleton clusters; a multi-identity
image is assigned to its **first-listed** `present_identities` name. Planning
table regenerated on that partition.

| quantity | OLD | NEW |
| --- | --- | --- |
| Kish `a` (whole frame) | 12.90 (130 labeled subjects, Σm=544, applied to N=640) | **10.846875** = 6942/640 (241 PSUs, Σm=N=640) |
| planning n (ICC=0.20) | 216 | **198** |
| sensitivity n (ICC=0.30) | 261 | **239** |
| ICC table n | 84/124/159/216/261/327 | **84/118/148/198/239/302** |
| B_eyewear Kish `a` | 2.36 (75 memberships / 47 subjects, applied to N_h=80) | **2.1** = 168/80 |
| B_eyewear clustered floor | 49 | **48** |
| follow-on ICC draw | 65 subjects × 3 = 195; CI [0.045, 0.360]; n 121..284 | **64 PSUs × 3 = 192**; CI [0.044, 0.361]; n **114..261** |

The brief's overlapping-plus-singletons construction (a=10.827, n=198) keeps the
16-image overlap and is cited as a contrast, not the partition. First-listed
assignment changes `a` (10.846875 vs 10.827) but not n at ICC=0.2.

**Calls.**

```
# PSU = first present_identity, else unlabeled:{media_id}
sizes = tuple(partition_counts.values())   # 241 PSUs, sum 640, sum_sq 6942
a = kish_effective_cluster_size(sizes)     # 10.846875
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.2).n  # 198
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.3).n  # 239
size_for_margin(margin=0.10, population=80,  cluster_size=2.1, icc=0.2).n       # 48
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=1.0).n  # 397
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.044).n # 114
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.361).n # 261
```

Frame: 16 multi-identity images, 19 extra memberships, 115 empty
`present_identities`. Four identities never appear first and are not PSUs:
Auburn Hollow, Tidal Quarry, Vellum Warren, Verdant Beacon.

**Mutant (TEST-15).** Restore labeled-only `a=12.90` against N=640:
`size_for_margin(..., cluster_size=12.90, icc=0.2).n` → **216** (RED against
the published 198). Same hole at B: `cluster_size=2.36` → 49, not 48.

**Could not close.** Grain of the estimand (image vs fact) is BR-19. Display
rounding of deff (1.98 vs 1.985 → n 147 vs 148) is BR-28.

---

## BR-19 (high) — estimand grain is the image

**Canon:** AUDIT-11.

**What changed.** The doc mixed three grains: n and `fabricated_fact_rate` are
image-level, Kish `a` is images per subject, but the (now-removed) pilot
language measured "ICC on fact-level correctness". Picked **image-level** and
defined Y_i as the image's fabricated-fact indicator (caught / not), matching
`fabricated_fact_rate` (`over='all'`). Planning ICC 0.20 is image-within-subject
correlation of that Y. Fact-within-image correlation is absorbed into the
image-level aggregate and is not a second `deff` term. A fact-level n would
need a facts-per-image cluster size and composed design effects; that is not
this study.

**Why image, not fact.** n is already an image count; the PSU partition from
BR-22 is images-within-subject; `fabricated_fact_rate` is documented as
"Fraction of IMAGES caught fabricating". Facts-per-image is unknown before
annotation, so a fact-level `a` would be another assumed input the 30-image
pilot is not sized to estimate.

**Calls.** None new — this finding does not change a number. The table from
BR-22 still holds because it already sized an image-level proportion.

**Mutant (TEST-15).** Restore "intra-subject ICC on fact-level correctness"
as the quantity plugged into `deff = 1+(a−1)ρ` with a = images/subject.
That multiplies a fact-level ρ by an image-cluster `a` — the wrong `deff`.
RED against the grain paragraph.

**Could not close.** Nothing.

---


