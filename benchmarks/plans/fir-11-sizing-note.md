# FIR-11 Slice 0 — Provisional power-ceiling sizing note

**Status:** **provisional pending Slice 4's measured ρ.** Exact IU-inflation rows are copied from the Measurement Contract's per-test power row (rev 6/7); they are **copied, not re-derived**. Slice 4 validates them.

**Slice 5 reference.** The Slice 5 report's under-powered banner ("under-powered for δ=10pp; not a ship gate") references this note.

This note is the Slice 0 hard gate: nobody spends labeling hours on a corpus that provably cannot gate. Re-labeling the existing pool does not produce a powered δ=10pp IU ship gate.

## Unit discipline

Connor's 157 is a count of **independent paired subjects per stratum** — at p_d = 0.20 that is ≈31 expected discordant pairs (the same quantity the Slice 4 McNemar row lists as 30 at p₁ = 0.75). Three units must not be stacked:

| Unit | What it counts |
| --- | --- |
| **Subject** | An identity. The Contract's analysis unit. Connor / NI sizing is in paired subjects. |
| **Occasion** | The PSU: one independent capture event for one identity. Two frames of the same person from the same shoot are one PSU. |
| **Probe** | A named face box. `m ≈ 3.3` is mean named probes per occasion (golden150, **provisional**). |

**DEFF never multiplies a subject count.** The only quantity this plan names `DEFF` is the Measurement Contract's occasion-level `1 + (m − 1)·ρ` at m ≈ 3.3, over named probes, on non-overlapping occasion PSUs. DEFF converts n_eff to raw n *within* the probe level. Rev 4 multiplied subjects by the probe-level DEFF 3.1; the Contract's statistic–interval pairing row forbids that unit-stacking.

The 1.86× IU inflation is a **provisional wrong-family illustration** (normal-theory continuous-endpoint glue). The exact factor under the discordant-pair sizing is **1.93 at the locked k = 8**, computed in the Contract's per-test power row.

Occasions do not mint subjects: 80 identities × 12 occasions is still 80 subjects.

## Provisional arithmetic

Using the Contract's declared values and DEFF at ρ=0.9 (recomputed in Slice 4 once ρ is measured). Multiplier constants are **provisional** except where marked **exact**. The ~292 / ~965 / ~6,750 chain is a **normal-theory illustration** — order unchanged vs the exact 290 @ k=8.

| Step | Value |
| --- | --- |
| Connor requirement, δ=10pp at p_d=0.20 | **157 independent paired subjects per stratum** (≈31 expected discordant pairs) |
| IU inflation, joint 80% → per-test `0.80^(1/k)` | × 1.86 normal-theory (**exact rows copied from the Contract's per-test power row**, not re-derived — at the locked k=8 the exact discordant-pair search gives **290 paired subjects per stratum** (n_d = 58), normal cross-check 301; the ~292 shown in the rows below is the normal-theory figure and stands as the chain's **illustration** — order unchanged; Slice 4 **validates** these rows, it does not derive them) → **~292 paired subjects per stratum** |
| Probe-supply conversion via **m ≈ 3.3 named probes per occasion**, at the **optimistic** one occasion per subject (one occasion per subject *understates* probe demand whenever subjects need multiple occasions; DEFF converts n_eff to raw n *within* the probe level and never multiplies a subject count) | × 3.3 → **~965 raw named probes per stratum** as a supply-side **illustration**; moves when `m` is re-measured after Slice 3 |
| × 7 strata (Product A **illustration**; Product B re-derives at locked k) | **~6,750 raw named probes** |
| Cross-check against Product B's own spec | Slice 6 targets 60–80 identities — **tens of subjects per stratum**, not ~292. **Decision rule:** the Slice 4 sizing-note author reconciles them before any capture spend; the **default resolution is that the capture spec grows** to the re-derived per-stratum subject demand — **in identity units** (occasions do not mint subjects: 80 identities × 12 occasions is still 80 subjects; growing toward ≈290 per-stratum subjects means recruiting more identities, with occasions-per-identity moving only m and DEFF) — with δ-relaxation or k-reduction available only as post-lock change-control decisions. Slice 6's 60–80 and the Cost Model's Slice 6 line are **placeholders** until then |
| golden150 has today (post fail-closed drop of unprovenanced + celeb/fixture) | **160** raw named probes |
| …after the per-entry attestation pass (the retired filename census is the **planning prior** only; worst case, all 110 adjudicable entries dropped; realized count re-derived at Slice 1) | **30** — see Slice 1's re-derivation |
| golden150 ∪ corpus646 (the union **is** v3's unique-image set; golden150 is fully contained) | **643** unique images. In this table's own unit — **raw named probes** — the union's supply is v3's corpus-wide **584 named boxes** (≥584 counting golden150's non-subsumed box records; order unchanged): **111** from the 96 hand-tagged images (max hard stratum: profile 50; sunglasses 13, masked 5) and **473** from the 550 untagged, which land in no stratum without new tagging |

## Exact inflation rows (copied from the Measurement Contract)

The following is **copied** from the Measurement Contract's **Per-test power** row. It is not re-derived here. Slice 4's `test_power_sizing.py` **validates** these rows.

`0.80^(1/k)` at the locked k — `0.969` at k=7 (Product A **illustration**), `≈0.973` at k=8 (Product B, locked).

**Exact conditional-binomial sizing rows** (an exact one-sided *conditional binomial* search on discordant pairs, a different family from the unconditional Tango score test the H0 row names as the decision statistic; computed 2026-08-14, π₀ = 0.25 vs π₁ = 0.50, α ≤ 0.025: smallest n_d whose critical value attains size ≤ .025 with power ≥ target):

| Target | n_d | crit | size | power |
| --- | --- | --- | --- | --- |
| 80% power | **30** | 13 | .0216 | .819 |
| per-test 0.96863 (k=7 **illustration**) | **55** | 21 | .0210 | .971 |
| per-test 0.97249 (locked k=8) | **58** | 22 | .0200 | .976 |

Subject conversion at p_d = 0.20: **150 / 275 / 290 paired subjects per stratum**.

Connor normal-family cross-check at the same powers: 157 / 292 / 301 — normal inflation 1.86× (k=7) / 1.92× (k=8), exact inflation 1.83× / 1.93×.

**Copied design assumption (GF-09):** `0.80^(1/k)` assumes independent per-stratum pass events; the strata share subjects, and the product-bound direction depends on the sign of that dependence (positive association ⇒ conservative, negative ⇒ not). The allocation is a **stated design assumption, not a proven can-oversize-never-undersize guarantee**.

## Shortfall

Per reading, re-derived on the corrected chain and denominators:

**Probe units**

- **~12×** on the merged pool (6,750 / 584 named probes)
- **~42×** on golden150 as-is (6,750 / 160)
- up to **≈225×** after the provenance-attestation pass in the all-drop worst case (6,750 / 30 = 225 exactly)

**Subject units**

- The merged pool's **137** total labeled identities (buffalo's merge-only partition IDs; exact in **labeled-identity units** — the only usable subject supply) **< 157** un-inflated one-stratum demand. No stratum, in any pool, under any inflation factor, can reach floor.
- golden150's clean stratum **~3–6×**
- masked / sunglasses **12–31×**: these two compare tagged *entries* to a subject demand — **5 entries bound the masked subjects at ≤5** and **13 bound sunglasses at ≤13**, so the direction is conservative and the bound is honest in **entry units**
- `similar_people` = **0**

Hard strata can never resolve 10pp regardless of arithmetic.

## What re-labeling cannot buy

Re-labeling changes none of these numbers. It changes procedure, not sample design. It mints **no new occasions**, **no new hard-condition captures**, **no new multi-shot identities**, and **no `similar_people` pairs** (that stratum has zero members and no amount of re-boxing invents lookalikes).

## Committed source artifacts

Recorded so a hash change forces a re-derivation pass, not a merge. `golden150-draft-20260723.json` is the plan's **post-roster-fix pin**.

| Path | sha256 |
| --- | --- |
| `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` | `b02417683814e546720d418580e8add9dad4bf13a4e97c68573d42b3b1afecd3` |
| `benchmarks/manifests/corpus-manifest-v3.json` | `5432bbda8abb163abcc034162fdb8c332a2ff7451e915144f632ed801ef98152` |
| `benchmarks/manifests/golden150-draft-20260723.json` | `4ae541dc0060ca37b8b2f37383b96175f0f3b9120295a30452453f421b61671e` |
