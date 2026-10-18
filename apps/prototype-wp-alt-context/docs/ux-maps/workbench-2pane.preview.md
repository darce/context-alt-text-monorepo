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
> therefore invalidates existing clusters and their `clusterMapLayout` — see the plan's **DEP-2
> consistency model** (the map is versioned by `clusterMapVersion`; a layout whose version does
> not match the live cluster set is rejected and re-requested, never silently drawn stale).
>
> Four backend dependencies the preview draws but the current backend does not provide, each
> tracked as a **DEP** row in the plan: **DEP-1** — the **long-description** column persists to
> WordPress `post_content` (the attachment description written via `DescribeMediaService::maybe_write_long_description`),
> not a new schema field; `WorkbenchMediaItem` exposes only `altText` today. **DEP-2** — the
> **cluster map** scatter needs a new `clusterMapLayout` endpoint returning 2D layout coordinates
> (today the backend has only bbox + 3D head pose, no 2D layout), so **day one ships the cluster
> _list_** and the scatter lands with DEP-2 in Slice 4. **DEP-3** — filtering the library to a
> cluster needs a new **`cluster_id`** query param on the media **list** read path (`fetchWorkbenchMedia`
> today accepts only page/per_page/status/search; `ids[]` belongs to the separate `fetchWorkbenchMediaDetail`
> endpoint). **DEP-4** — commit-before-reveal and merge/split need persisted pre-reveal state + multi-level
> undo the current single-write mutation path lacks. UI copy for the **new cluster-map layout** says
> "cluster map", never "embeddings" or "projection" — `projection` is the banned token in
> `banned-vocabulary.test.tsx` `BANNED_STRINGS` (substring-checked); `embeddings` is asserted
> separately in the same test. The roster status label portrayed in §6 is **roster sync**
> (the internal symbol `projectionSyncState` is never rendered copy).

---

## 1. Two-pane shell (wide, ≥1100px)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Alt-Context · Workbench      endpoint: InsightFace :10010 (interim) ● healthy [ⓘ]   ⟳ sync ✓│ (z-topbar, read-only)
├──────────────────────────────────────────┬─┬───────────────────────────────────────────────────┤
│ CONTROL — recognize · name · curate      │◀│ MEDIA LIBRARY — caption · describe                │
│                                          │ │                                                   │
│  ┌─ Endpoint + health ─────────────┐     │▐│ filter: [all▼] □needs-alt □needs-desc  🔍[____]    │
│  │ InsightFace :10010   ● healthy │     │▐│  ┌───────────────────────────────────────────────┐│
│  └─────────────────────────────────┘     │ │  │□ thumb title        status  alt-text   desc   ││
│ [ ⟳ Run recognition ]  thr ▐▐▐▐░ 0.62   │ │  │□ [▦] conf.jpg     ✓ done  "Ada at…"  "A wo…"││
│  ┌─ Face-group status ─────────────┐     │ │  │☑ [▦] group.jpg    ⧗ queue ✎ empty   ✎ empty  ││
│  │ Ready · 18 groups (status only) │     │▐│  │□ [▦] keynote.png  ⚠ fail  "Two…"    ✎ empty ││
│  │ not a 2D scatter plot           │     │▐│  └───────────────────────────────────────────────┘│
│  └─────────────────────────────────┘     │ │ ▼ group.jpg — inline edit                         │
│                                          │ │ alt [ Two people seated at a panel… ] 63/125      │
│ Clusters      sort:[ unnamed first ▼ ]   │ │ AI: "Two panelists at a table" [use][edit]        │
│ ▸①  42  0.91  «unnamed»        [select]│ │ long[ …expandable textarea… ]                     │
│ ▸②  31  0.88  Ada Lovelace             │▐│ ───────────────────────────────────────────────   │
│ ▸③  17  0.55  «low conf» ⚠            │ │ 2 selected · [ Describe 2 selected ⟳ ] est.$0.03  │
│                                          │ │                                                   │
│ (z-left-host → workbench-control)        │ │ (z-right-host → workbench-library)                │
└──────────────────────────────────────────┴─┴───────────────────────────────────────────────────┘
                          (z-splitter: drag to resize · ◀ collapse left)
```

The left pane's face-group zone is a **status region**, not a 2D scatter. Face-group list
selection still uses **number + shape** (①◆ ②▲ ③● ④■), never colour alone `[VIZ-07]/[A11Y-06]`.

---

## 2. Control surface (left pane, detailed) — `workbench-control`

```
┌─ CONTROL ────────────────────────────────────────────────┐
│ Endpoint: InsightFace :10010 (interim)      ● healthy   │  (z-endpoint · status)
│ ⚠ FIR endpoint not yet stable — using interim route     │
├──────────────────────────────────────────────────────────┤
│ [ ⟳ Run recognition ]   threshold ▐▐▐▐░ 0.62            │  (z-recognition-controls · job)
│ last run 3m ago · 214 faces · 18 clusters · 41 unnamed   │
│ ▸ Run recognition is COSTLY — preview: 214 faces, ~$0.02│  [preview_required]
├──────────────────────────────────────────────────────────┤
│ Face-group status                       [ Retry ]        │  (z-cluster-umap · status)
│ Ready · last scan 3m ago · 18 groups                     │
│ Empty: "No face groups yet."  Error: load failed+Retry   │
├──────────────────────────────────────────────────────────┤
│ Clusters (day-one list)       sort:[ unnamed first ▼ ]   │  (z-cluster-list · queue)
│ id = number + glyph (non-colour) · sel = ▶ + bold       │  [VIZ-07]/[A11Y-06]
│▶▶①◆ ·····  42  0.91  «unnamed»      [✓ selected]    │  ← sel: marker+weight, not hue
│   ②▲ ·····  31  0.88  Ada Lovelace      [select]       │
│   ③● ·····  17  0.55  «low confidence» ⚠ [select]     │
│   ④■ ·····   9  0.80  «unnamed»          [select]      │
├──────────────────────────────────────────────────────────┤
│ NAME & CURATE — cluster ① (42 faces)                    │  (z-name-curate · commit-before-reveal)
│ phase 1 · judgment_pending — your call BEFORE model      │  [HAI-15]
│ model candidates NOT shown yet (no node mounted)         │  reveal-gate
│ evidence ▸ 5 source frames · 3 captures                 │  [HAI-01/17]
│ name [ __________________________ ]  ○ can't tell        │
│ [ Commit my name ▸ reveal ]                             │
│ [ Merge ▸ ] [ Split ▸ ] [ Not a face ✕ ]               │
│  Merge/Split are COSTLY + preview affected media         │  [preview_required]
└──────────────────────────────────────────────────────────┘
```

### 2b. Name & curate — commit-before-reveal state machine `[HAI-15]`

The name step is a two-phase gate: the operator commits a judgment **before** any model
candidate is shown, so the model cannot anchor the human. State: `judgment_pending → revealed`.

```
┌─────────────────────────────────────────┐           ┌─────────────────────────────────────────┐
│ NAME · cluster ① — phase 1             │           │ NAME · cluster ① — phase 2             │
├─────────────────────────────────────────┤           ├─────────────────────────────────────────┤
│ evidence ▸ 5 frames · 3 captures       │           │ your name:  Ada Lovelace                │
│ model candidates: ░░ NOT SHOWN ░░   │           │ model said: Ada Lovelace  ✓ agree      │
│   (reveal node not mounted)             │commit ──▶│   0.94 · 2nd: Grace (0.11)              │
│ your name [ Ada Lovelace____ ]          │           │ provenance: human-first [HAI-15]        │
│ ○ can't tell  (abstain = a commit)      │           │ [ Keep mine ] [ Adopt ] [ Undo ]        │
│ [ Commit my name ▸ reveal ]            │           │                                         │
└─────────────────────────────────────────┘           └─────────────────────────────────────────┘
  the reveal node is UNMOUNTED in phase 1 (not CSS-hidden) — model output cannot reach the
  DOM before commit [HAI-15]. Post-commit, agreement/disagreement + which side led are
  recorded [HAI-15], so the audit trail can't be gamed by peeking.
```

`○ can't tell` is a first-class commit (abstain): it advances to `revealed` as an explicit
judgment, not a skip. **Undo** (day-one, session-local **single step**) returns to `judgment_pending`
with the model node unmounted again — no peeking via the back-button. **Multilevel atomic per-affected-cluster LIFO** undo
of name/merge/split is **DEP-4**.

---

## 3. Media library (right pane, detailed) — `workbench-library`

```
┌─ MEDIA LIBRARY ─────────────────────────────────────────────────────────────────────────────────┐
│ filter: status[ all ▼ ]  □ needs-alt  □ needs-desc   cluster:[ ① ✕ ](DEP-3)  search[______] 🔍  │ (z-lib-filters · form)
├──┬───────┬──────────────────┬─────────────┬─────────────────────┬────────────────────┬──────────┤
│▢ │ thumb │ title            │ status      │ alt-text            │ long description   │people    │ (z-lib-table · queue)
├──┼───────┼──────────────────┼─────────────┼─────────────────────┼────────────────────┼──────────┤
│▢ │ [▦]  │ conf-2019-07.jpg │ ✓ described│ "Ada at the podium" │ "A woman in a dark…│ Ada      │
│☑ │ [▦]  │ group-shot.jpg   │ ⧗ queued    │ ✎ (empty)           │ ✎ (empty)          │ ①,②    │
│▢ │ [▦]  │ keynote.png      │ ⚠ failed   │ "Two people on…"    │ ✎ (empty)          │ —        │
├──┴───────┴──────────────────┴─────────────┴─────────────────────┴────────────────────┴──────────┤
│ ▼ group-shot.jpg — inline edit                                                                  │ (z-lib-inline-edit · form)
│   alt-text  [ Two people seated at a panel table________________ ]  63/125                      │
│   AI suggests: "Two panelists at a table with microphones"      [ use ] [ edit ]                │ (z-lib-ai-suggest · ai_review)
│   long desc [ A wide shot of two panelists seated behind a table… ] (expandable)                │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2 selected · [ Describe 2 selected ⟳ ]  est. $0.03  · job: idle                                 │ (z-lib-actions · job)
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
  columns are truncated + hover-expand; alt-text and long-description are SEPARATE columns so
  a scanning operator sees at a glance which rows still need each field (needs-alt ≠ needs-desc).
  Day-one shows reciprocal **highlight** of cluster-① rows on the loaded page; the cluster
  **filter chip + filtered table** is **DEP-3**.
```

---

### 3b. Footer job zone — the three idle states + identifying (`z-lib-actions`)

```
┌─ idle · ON ──────────────────────────────────────────────────────────────────────────────────┐
│ recognition ON (Settings default)                                                            │
│   2 selected · [ Describe 2 selected ⟳ ]  est. $0.03  · job: idle                            │
│   ▸ names people it knows while describing                        (aria-describedby, INT-04) │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌─ idle · OFF ─────────────────────────────────────────────────────────────────────────────────┐
│ recognition OFF                                                                              │
│   2 selected · [ Describe 2 selected ⟳ ]  est. $0.03  · job: idle                            │
│   ▸ descriptions only — turn people naming on in Settings         (aria-describedby)         │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌─ idle · unknown ─────────────────────────────────────────────────────────────────────────────┐
│ settings not loaded yet (unknown)                                                            │
│   2 selected · [ Describe 2 selected ⟳ ]  aria-disabled="true" · focusable                   │
│   ▸ checking recognition setting…            never starts describe on a guessed policy (F3)  │
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌─ identifying ────────────────────────────────────────────────────────────────────────────────┐
│ recognition ON, scan running before describe                                                 │
│   2 selected · [ Identifying people… ⟳ ]  aria-disabled="true" · focusable · [ Cancel ]      │
│   ▸ never HTML-disabled (same invariant as offline) — RLSE-04, A11Y-21; Cancel aborts the run│
└──────────────────────────────────────────────────────────────────────────────────────────────┘

┌─ idle · zero selection ──────────────────────────────────────────────────────────────────────┐
│ zero selection (rg-003: the primary stays reachable from the zero state)                     │
│   0 selected · [ Describe selected ]  aria-disabled="true" · focusable · click is a no-op    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

One footer primary in every state (NAV-01, INT-05): recognition is a **global Settings toggle**
disclosed under the button, never a second competing CTA (COG-03). The identifying and unknown
states are `aria-disabled` only — HTML `disabled` would drop the sole job entry out of tab order.

---


## 4. Coordinated selection — day-one linked-highlight · **DEP-3** filter

```
   CONTROL                                    MEDIA LIBRARY
   ┌──────────────────────────┐                   ┌────────────────────────────────────────────┐
   │ cluster map              │   select ①       │ filter: cluster:[ ① ✕ ]                   │
   │   ·· ●②  ·  ⟦●①●⟧  ·│ ───────────────▶ │ (DEP-3: table filtered to cluster-① media)│
   │  ·   ●●  ·   ⟦●●⟧  · │                   │ □ conf.jpg   ✓  "Ada…"  … people: Ada     │
   │      ●③●     ··  ·    │                   │ □ podium.jpg ✓  "Ada…"  … people: Ada     │
   └──────────────────────────┘                   └────────────────────────────────────────────┘
   Day-one: selecting a cluster **highlights** that cluster's rows already on the page
   (url ?cluster=①). **With DEP-3**, the same selection **filters** the right pane to that
   cluster's media. Coordination is **exactly one** active cluster; a multi-cluster row
   (e.g. the ①,② row in §3) selects via a chip, not the bare row. Naming ① in z-name-curate
   updates the "people" column live. Two coordinated views over one selection; no context
   switch, no lost place.
```

---

## 5. Medium viewport (<1100px) — control collapses to an optional drawer (IA, not the WCAG reflow)

```
┌────────────────────────────────────────────────────┐
│ ☰ Control   Workbench   endpoint :10010 ⓘ  ● ⟳✓ │
├────────────────────────────────────────────────────┤
│ MEDIA LIBRARY (full width)                         │
│ filter: […]                                        │
│ □ thumb title        status  alt-text   desc people│
│ …                                                  │
└────────────────────────────────────────────────────┘
   ☰ Control opens the control surface as a left overlay drawer; primary caption/library
   work stays reachable at all widths (control is not gated behind a wide viewport).
   This <1100px drawer is **optional IA**. The **hard WCAG 1.4.10 reflow** at ≤320px / 200%
   zoom instead **stacks vertically, library-first** (control host below), splitter→section
   toggle, no 2-D scroll — see plan Slice-1 `[A11Y-08]`. The reflow stack **overrides** the drawer.
```

---

## 6. Roster v1 — `roster-people`

### 6a. Roster shell (people-first)

```
┌─ ROSTER (People) ────────────────────────────────────────────────────────┐
│ [ ● Needs assignment (12) ]  [ All people ]      search[__________] 🔍   │ (z-needs-assignment / filters)
│ ⓘ roster sync: current  (existing roster concept)                       │ (z-projection-gate · status)
├──────────────────────────────────────────────────────────────────────────┤
│ person              media  identities  last seen        │                │ (z-entries · content)
│ ▸ Ada Lovelace       31       2        conf-2019-07.jpg│ [ open ]       │
│ ▸ Grace Hopper        8       1        keynote.png     │ [ open ]       │
│ ▸ «unassigned ①»     42       —        —              │ [ assign ]     │
│ ▸ «unassigned ③» ⚠   17       —        low-confidence│ [ review ]     │
├──────────────────────────────────────────────────────────────────────────┤
│ (person workspace + cluster drawer open here — see 6b/6c)                │ (z-person-host / z-cluster-host)
└──────────────────────────────────────────────────────────────────────────┘
   Clusters are RETIRED from Roster as a tab — cluster review is a drawer (?cluster=),
   and cluster building lives in the Workbench control pane. Roster is the people directory.
```

### 6b. Person workspace (deep-linked `?person=`)

```
┌─ Ada Lovelace ───────────────────────────────────────────┐ (roster-person-workspace)
│ 31 media · 2 identities · roster sync ✓                 │ (z-person-header)
├──────────────────────────────────────────────────────────┤
│ Linked identities / faces (evidence)                     │ (z-person-identities · ai_review)
│  [▦][▦][▦][▦][▦]  +26   · confidence 0.88           │
│  ⚠ 1 identity below threshold — [ review ]              │
├──────────────────────────────────────────────────────────┤
│ name [ Ada Lovelace_______ ]  [ Save ] [ Assign faces▸ ]│ (z-person-actions · form)
│  Save is COSTLY + previews affected media                │ [preview_required]
└──────────────────────────────────────────────────────────┘
```

### 6c. Cluster drawer (`?cluster=`)

```
                        ┌─ Cluster ① drawer ──────────────┐ (roster-cluster-drawer · overlay)
                        │ Sample identities (max 8)        │ (z-cluster-samples · forced_choice)
                        │  [▦][▦][▦][▦][▦][▦][▦][▦]│
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
                    [control: cluster map + list]
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

### 7c. Cluster map select → library (`flow-umap-select-to-library`, job-cluster-recognize) · DEP-2 scatter + DEP-3 filter

```
 [control: cluster map scatter] ──lasso/click cluster──▶ [?cluster=① set]
                                                        │
                                                        ▼
                                          [library filtered to cluster-① media] (DEP-3)
```

### 7d. Conflicts / dead-letter (triage, overlays — unchanged from baseline)

```
 [control: recognition → conflicts] ──▶ [overlay: Conflict Inbox] ──resolve──▶ [exit: Roster?]
 [shell: degraded sync strip]       ──▶ [overlay: Dead Letter]    ──retry/discard──▶ [sync]
```

---

## 8. State coverage (per screen)

| screen                  | default | loading | empty | error | first_time | degraded | offline |
| ----------------------- | ------- | ------- | ----- | ----- | ---------- | -------- | ------- |
| workbench-2pane-shell   | ✓       | ✓       | —     | ✓     | —          | ✓        | ✓       |
| workbench-control       | ✓       | ✓       | ✓     | ✓     | ✓          | ✓        | —       |
| workbench-library       | ✓       | ✓       | ✓     | ✓     | ✓          | —        | —       |
| roster-shell            | ✓       | ✓       | ✓     | ✓     | ✓          | ✓        | —       |
| roster-person-workspace | ✓       | ✓       | ✓     | ✓     | —          | ✓        | —       |

`empty` and `first_time` are distinct: first_time (never run recognition / no media described)
gets guidance + the primary CTA; empty (filtered to zero) gets a clear-filter affordance.
