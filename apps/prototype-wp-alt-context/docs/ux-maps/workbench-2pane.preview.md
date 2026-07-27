# ASCII Preview — Workbench 2-pane + Roster v1

> Durable visual companion to `workbench-2pane.uxmap.json` and `roster-people.uxmap.json`.
> The `.uxmap.json` files are the SSOT for screens/zones/states/flows; this file is the
> **spatial** preview the structural renderer cannot draw. Zone ids in `(z-…)` map back to
> the SSOT. Heuristic ids in `[XXX-nn]` are cited in the task plan, not re-argued here.
>
> Endpoint note: recognition runs against **InsightFace on `localhost:10010`** as the interim
> route until the FIR endpoint is stable. The endpoint is **server-resolved** (`ACX_RECOGNITION_URL`
> constant / filter, per RECOG-1) — the topbar shows it **read-only**, there is no UI switcher.
> Switching endpoints changes embedding dimensionality (512d InsightFace vs 128d SFace/FIR) and
> therefore invalidates existing clusters — see the plan's endpoint-switch open question.
>
> Two data dependencies the preview draws but the backend does not yet provide: (1) the
> **long-description** column needs a new media schema field (`WorkbenchMediaItem` has only
> `altText` today); (2) the **cluster map** scatter needs a new backend 2D-projection endpoint
> (no projection data exists; only bbox + 3D head pose). UI copy says "cluster map", never
> "embeddings" (banned UI vocabulary). Both are called out as DEP open questions in the plan.

---

## 1. Two-pane shell (wide, ≥1100px)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Alt-Context · Workbench      endpoint: InsightFace :10010 (interim) ● healthy [ⓘ]   ⟳ sync ✓    │ (z-topbar, read-only)
├──────────────────────────────────────────────┬─┬─────────────────────────────────────────────────┤
│ CONTROL — recognize · name · curate          │◀│ MEDIA LIBRARY — caption · describe               │
│                                              │ │                                                  │
│  ┌ Endpoint + health ───────────────────┐   │▐│  filter: [all▼] □needs-alt □needs-desc  🔍[____] │
│  │ InsightFace :10010   ● healthy        │   │▐│  ┌──────────────────────────────────────────────┐│
│  └───────────────────────────────────────┘   │ │  │□ thumb title        status  alt-text   desc  ││
│  [ ⟳ Run recognition ]  thr ▐▐▐▐░ 0.62       │ │  │□ [▦] conf.jpg     ✓ done  "Ada at…"  "A wo…" ││
│  ┌ Cluster map (UMAP) ───────────────────┐   │ │  │☑ [▦] group.jpg    ⧗ queue ✎ empty   ✎ empty ││
│  │   ·· ●②    ·  ●①●    ·                 │   │▐│  │□ [▦] keynote.png  ⚠ fail  "Two…"    ✎ empty ││
│  │  ·   ●●   ·    ●●    ·· ●④             │   │▐│  └──────────────────────────────────────────────┘│
│  │     ●③●        ··  ·                   │   │ │  ▼ group.jpg — inline edit                        │
│  └───────────────────────────────────────┘   │ │  alt [ Two people seated at a panel… ] 63/125     │
│  Clusters      sort:[ unnamed first ▼ ]      │ │  AI: "Two panelists at a table" [use][edit]       │
│  ▸①  42  0.91  «unnamed»        [select]     │ │  long[ …expandable textarea… ]                    │
│  ▸②  31  0.88  Ada Lovelace                  │▐│  ───────────────────────────────────────────────  │
│  ▸③  17  0.55  «low conf» ⚠                  │ │  2 selected · [ Describe selected ⟳ ] est.$0.03   │
│                                              │ │                                                  │
│  (z-left-host → workbench-control)           │ │  (z-right-host → workbench-library)              │
└──────────────────────────────────────────────┴─┴─────────────────────────────────────────────────┘
                                            (z-splitter: drag to resize · ◀ collapse left)
```

---

## 2. Control surface (left pane, detailed) — `workbench-control`

```
┌─ CONTROL ──────────────────────────────────────────────┐
│ Endpoint: InsightFace :10010 (interim)      ● healthy   │  (z-endpoint · status)
│ ⚠ FIR endpoint not yet stable — using interim route     │
├─────────────────────────────────────────────────────────┤
│ [ ⟳ Run recognition ]   threshold ▐▐▐▐░ 0.62            │  (z-recognition-controls · job)
│ last run 3m ago · 214 faces · 18 clusters · 41 unnamed  │
│ ▸ Run recognition is COSTLY — preview: 214 faces, ~$0.02│  [preview_required]
├─────────────────────────────────────────────────────────┤
│ Cluster map · faces (UMAP)              [ lasso | pan ] │  (z-cluster-umap · ai_review, evidence)
│                                                         │
│      · · ·        ·· ●●●                                 │   legend:
│     ·  ·  ●②     ·   ●①●   ← hover ①: 42 faces, 0.91    │    ● named   (hue per person)
│    ·       ●●     ·   ●●                                 │    ● unnamed (grey)
│        ●③●            ·· ·                               │    ⚠ low-confidence ring
│     ·  ·  ⚠     ·  ●④  ·                                 │   select region → drives right pane
├─────────────────────────────────────────────────────────┤
│ Clusters                     sort:[ unnamed first ▼ ]   │  (z-cluster-list · queue)
│ ▸ ①  ·····  42  0.91  «unnamed»              [select]   │
│ ▸ ②  ·····  31  0.88  Ada Lovelace           [select]   │
│ ▸ ③  ·····  17  0.55  «low confidence» ⚠     [select]   │
│ ▸ ④  ·····   9  0.80  «unnamed»              [select]   │
├─────────────────────────────────────────────────────────┤
│ NAME & CURATE — cluster ① (42 faces)                    │  (z-name-curate · forced_choice, max 5)
│ Candidates:  ○ Ada Lovelace   0.88                      │
│              ○ Grace Hopper   0.42                      │
│              ○ + new person…                            │
│ name [ __________________________ ]                     │
│ [ Confirm ] [ Merge ▸ ] [ Split ▸ ] [ Not a face ✕ ]   │
│  Merge/Split are COSTLY + preview the affected media    │  [preview_required]
└─────────────────────────────────────────────────────────┘
```

---

## 3. Media library (right pane, detailed) — `workbench-library`

```
┌─ MEDIA LIBRARY ─────────────────────────────────────────────────────────────────────────┐
│ filter: status[ all ▼ ]  □ needs-alt  □ needs-desc   cluster:[ ① ✕ ]   search[______] 🔍 │ (z-lib-filters · form)
├──┬───────┬──────────────────┬───────────┬─────────────────────┬────────────────────┬──────┤
│▢ │ thumb │ title            │ status    │ alt-text            │ long description   │people│ (z-lib-table · queue)
├──┼───────┼──────────────────┼───────────┼─────────────────────┼────────────────────┼──────┤
│▢ │ [▦]   │ conf-2019-07.jpg │ ✓ described│ "Ada at the podium" │ "A woman in a dark…│ Ada  │
│☑ │ [▦]   │ group-shot.jpg   │ ⧗ queued  │ ✎ (empty)           │ ✎ (empty)          │ ①,②  │
│▢ │ [▦]   │ keynote.png      │ ⚠ failed  │ "Two people on…"    │ ✎ (empty)          │ —    │
├──┴───────┴──────────────────┴───────────┴─────────────────────┴────────────────────┴──────┤
│ ▼ group-shot.jpg — inline edit                                                             │ (z-lib-inline-edit · form)
│   alt-text  [ Two people seated at a panel table________________ ]  63/125                 │
│   AI suggests: "Two panelists at a table with microphones"      [ use ] [ edit ]           │ (z-lib-ai-suggest · ai_review)
│   long desc [ A wide shot of two panelists seated behind a table… ] (expandable)           │
├────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2 selected · [ Describe selected ⟳ ]  est. $0.03  · job: idle                              │ (z-lib-actions · job)
└────────────────────────────────────────────────────────────────────────────────────────────┘
  columns are truncated + hover-expand; alt-text and long-description are SEPARATE columns so
  a scanning operator sees at a glance which rows still need each field (needs-alt ≠ needs-desc).
```

---

## 4. Coordinated selection (UMAP → library) — the core interaction

```
   CONTROL                                    MEDIA LIBRARY
   ┌───────────────────────┐                  ┌──────────────────────────────────────┐
   │ UMAP                   │   select ①      │ filter: cluster:[ ① ✕ ]               │
   │   ·· ●②  ·  ⟦●①●⟧  ·   │ ───────────────▶ │ (table now shows only cluster-① media)│
   │  ·   ●●  ·   ⟦●●⟧  ·   │                  │ □ conf.jpg   ✓  "Ada…"  … people: Ada │
   │      ●③●     ··  ·     │                  │ □ podium.jpg ✓  "Ada…"  … people: Ada │
   └───────────────────────┘                  └──────────────────────────────────────┘
   selecting a cluster point/region on the left FILTERS the right pane to that cluster's
   media (url ?cluster=①). Naming ① in z-name-curate updates the "people" column live.
   Two coordinated views over one selection; no context switch, no lost place.
```

---

## 5. Narrow viewport (<1100px) — left collapses to a drawer

```
┌──────────────────────────────────────────────────┐
│ ☰ Control   Workbench   endpoint:[:10010▼] ● ⟳✓  │
├──────────────────────────────────────────────────┤
│ MEDIA LIBRARY (full width)                        │
│ filter: […]                                        │
│ □ thumb title        status  alt-text   desc people│
│ …                                                  │
└──────────────────────────────────────────────────┘
   ☰ Control opens the control surface as a left overlay drawer; primary caption/library
   work stays reachable at all widths (control is not gated behind a wide viewport).
```

---

## 6. Roster v1 — `roster-people`

### 6a. Roster shell (people-first)

```
┌─ ROSTER (People) ───────────────────────────────────────────────────────┐
│ [ ● Needs assignment (12) ]  [ All people ]      search[__________] 🔍   │ (z-needs-assignment / filters)
│ ⓘ projection current                                                     │ (z-projection-gate · status)
├──────────────────────────────────────────────────────────────────────────┤
│ person              media  identities  last seen        │                 │ (z-entries · content)
│ ▸ Ada Lovelace       31       2        conf-2019-07.jpg  │ [ open ]        │
│ ▸ Grace Hopper        8       1        keynote.png       │ [ open ]        │
│ ▸ «unassigned ①»     42       —        —                 │ [ assign ]      │
│ ▸ «unassigned ③» ⚠   17       —        low-confidence    │ [ review ]      │
├──────────────────────────────────────────────────────────────────────────┤
│ (person workspace + cluster drawer open here — see 6b/6c)                  │ (z-person-host / z-cluster-host)
└──────────────────────────────────────────────────────────────────────────┘
   Clusters are RETIRED from Roster as a tab — cluster review is a drawer (?cluster=),
   and cluster building lives in the Workbench control pane. Roster is the people directory.
```

### 6b. Person workspace (deep-linked `?person=`)

```
┌─ Ada Lovelace ──────────────────────────────────────────┐ (roster-person-workspace)
│ 31 media · 2 identities · projection ✓                   │ (z-person-header)
├──────────────────────────────────────────────────────────┤
│ Linked identities / faces (evidence)                     │ (z-person-identities · ai_review)
│  [▦][▦][▦][▦][▦]  +26   · confidence 0.88                │
│  ⚠ 1 identity below threshold — [ review ]                │
├──────────────────────────────────────────────────────────┤
│ name [ Ada Lovelace_______ ]  [ Save ] [ Assign faces▸ ] │ (z-person-actions · form)
│  Save is COSTLY + previews affected media                │ [preview_required]
└──────────────────────────────────────────────────────────┘
```

### 6c. Cluster drawer (`?cluster=`)

```
                        ┌─ Cluster ① drawer ──────────────┐ (roster-cluster-drawer · overlay)
                        │ Sample identities (max 8)        │ (z-cluster-samples · forced_choice)
                        │  [▦][▦][▦][▦][▦][▦][▦][▦]         │
                        │ Assign to: ○ Ada  ○ + new person │
                        │ [ Assign ] [ Dismiss ]           │ (z-cluster-actions · form)
                        └──────────────────────────────────┘
```

---

## 7. UX workflows (ASCII flow)

### 7a. Recognize → name → curate (`flow-recognize-name-curate`, job-name-curate)

```
 [shell] ──enter──▶ [control: Run recognition]
                          │ (costly, preview 214 faces)
                          ▼
                    [control: UMAP + cluster list]
                          │ select cluster ①
                          ▼
                    [control: Name & curate ①]──confirm/merge/split──▶ identity-store
                          │
                          ▼
                    [library: people column reflects assignment]
```

### 7b. Caption the library (`flow-caption-library`, job-caption-library)

```
 [library: filter needs-alt] ──▶ [row: AI caption suggested] ──use/edit──▶ [alt-text saved]
                                        │
                                        ▼
                                 [row: long description] ──edit──▶ [description saved]
```

### 7c. UMAP select → library (`flow-umap-select-to-library`, job-cluster-recognize)

```
 [control: UMAP scatter] ──lasso/click cluster──▶ [?cluster=① set]
                                                        │
                                                        ▼
                                          [library filtered to cluster-① media]
```

### 7d. Conflicts / dead-letter (triage, overlays — unchanged from baseline)

```
 [control: recognition → conflicts] ──▶ [overlay: Conflict Inbox] ──resolve──▶ [exit: Roster?]
 [shell: degraded sync strip]       ──▶ [overlay: Dead Letter]    ──retry/discard──▶ [sync]
```

---

## 8. State coverage (per screen)

| screen | default | loading | empty | error | first_time | degraded | offline |
|---|---|---|---|---|---|---|---|
| workbench-2pane-shell | ✓ | ✓ | — | ✓ | — | ✓ | ✓ |
| workbench-control | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| workbench-library | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| roster-shell | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| roster-person-workspace | ✓ | ✓ | ✓ | ✓ | — | ✓ | — |

`empty` and `first_time` are distinct: first_time (never run recognition / no media described)
gets guidance + the primary CTA; empty (filtered to zero) gets a clear-filter affordance.
