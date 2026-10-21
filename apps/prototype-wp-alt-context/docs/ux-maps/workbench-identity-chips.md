# UX Map — workbench-identity-chips

**Product:** `prototype-wp-alt-context`
**Source fixture:** `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx`

## Goals
- Show one person chip per person in each media row; a person's face-group membership stays in the +N count instead of becoming duplicate chips.
- Render the store's representative face crop before the person label (HAI-01/HAI-17); use the current face only when representative evidence is unavailable.
- Keep optional person_id and representative_face absence unresolved and visible without fabricating a person or representative image (rg-015, DDIA).
- Keep ungrouped residue in one Not yet grouped (N) section with every unresolved face; never render N Unnamed person cards or visually deduplicate faces (GPUFLOW-2 C5).
- Expose an N face groups badge when one person spans more than one face group, and let the chip expand into the existing face review panel.
- Let chip name, avatar, and face-group-count buttons open the person workspace while preserving reversible roster merge behavior (INT-07, INT-09).
- UXREC-1 proposed repeated exact-face evidence disclosure awaiting map gate: link observations across groups without collapsing groups, changing mutation targets or inferring identity from filenames. The user supplies the Emma same-person ground truth; no new identity inference. See UXREC-1 inventory.
- Source correction: ClusterPreview is a noninteractive thumbnail; IdentityClusterItem label enters naming. This pre-existing map describes target chip navigation, not a verified current avatar-to-workspace action. UXREC-1 must reuse available review navigation or request coordinated extension; never fabricate a merge control.

## Jobs
- `job-media-person-chips` — Read person chips in a media row and verify face evidence
- `job-review-person-evidence` — Expand a person chip into face-group review or the person workspace

## Code references
- `screen:workbench-media-row-person-chips` — `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterList.tsx`
- `screen:workbench-media-row-face-group-badge` — `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`
- `screen:workbench-media-row-current-face-fallback` — `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx`
- `screen:workbench-person-chip-expanded` — `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/ClusterReviewPanel.tsx`
- `screen:exit-roster` — `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx`

## Screens
| id | kind | route | title |
| --- | --- | --- | --- |
| `workbench-media-row-person-chips` | screen | `#/workbench?media=` | Media row — person chips |
| `workbench-media-row-face-group-badge` | screen | `#/workbench?media=` | Media row — person with multiple face groups |
| `workbench-media-row-current-face-fallback` | screen | `#/workbench?media=` | Media row — current-face fallback |
| `workbench-person-chip-expanded` | overlay | `#/workbench?media=&cluster=` | Expanded person chip — review faces |
| `exit-roster` | exit | `#/roster?person=` | Person workspace |

### Media row — person chips (`workbench-media-row-person-chips`)

Purpose: Design target; referenced component does not establish implemented navigation. A media row renders one chip per resolved person: the representative face evidence comes first, followed by the person label and member +N count; unresolved faces remain available for face-group review in one Not yet grouped (N) section.

url_params: `media`

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-media-row` | Selected media row (title, description status, and person chip rail) | content | default, loading, empty, error |
| `z-person-chip-rail` | One person chip per person (no duplicate chip for each face group) | ai_review | default, loading, empty, error, degraded |
| `z-ungrouped-residue` | Not yet grouped section (every unresolved face, never N Unnamed person cards) | ai_review | default, error, degraded |
| `z-representative-avatar` | Representative face avatar (store reference crop rendered before the person's label) | ai_review | default, error, degraded |
| `z-member-count` | Member count (+N faces on this person chip) | status | default, loading, empty, error |
| `z-chip-actions` | Person chip buttons (expand face-group review or open person workspace) | form | default, loading, error |
| `z-repeated-face-summary` | Proposed compact repeated-evidence summary only when observed: same source face appears in N groups; expand to inspect source/crop/group references. Not a new guessed person label. | ai_review | default, loading, empty, error, degraded |

```
+------------------------------------------------------------+
| Media row — person chips  [screen]  #/workbench?media=     |
| Design target; referenced component does not establish im\ |
|   plemented navigation. A media row renders one chip per \ |
|   resolved person: the representative face evidence comes\ |
|    first, followed by the person label and member +N coun\ |
|   t; unresolved faces remain available for face-group rev\ |
|   iew in one Not yet grouped (N) section.                  |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Selected media row (title, description status, and pe\ |
|   rson chip rail) (content) states=[default,loading,empty\ |
|   ,error]                                                  |
|   - One person chip per person (no duplicate chip for eac\ |
|   h face group) (ai_review) states=[default,loading,empty\ |
|   ,error,degraded]                                         |
|   - Not yet grouped section (every unresolved face, never\ |
|    N Unnamed person cards) (ai_review) states=[default,er\ |
|   ror,degraded]                                            |
|   - Representative face avatar (store reference crop rend\ |
|   ered before the person's label) (ai_review) states=[def\ |
|   ault,error,degraded]                                     |
|   - Member count (+N faces on this person chip) (status) \ |
|   states=[default,loading,empty,error]                     |
|   - Person chip buttons (expand face-group review or open\ |
|    person workspace) (form) states=[default,loading,error] |
|   - Proposed compact repeated-evidence summary only when \ |
|   observed: same source face appears in N groups; expand \ |
|   to inspect source/crop/group references. Not a new gues\ |
|   sed person label. (ai_review) states=[default,loading,e\ |
|   mpty,error,degraded]                                     |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Expand face-group review -> workbench-person-\ |
|   chip-expanded                                            |
|   [secondary] Open person workspace -> exit-roster         |
+------------------------------------------------------------+
| states: default | loading | empty | error | degraded       |
+------------------------------------------------------------+
```

### Media row — person with multiple face groups (`workbench-media-row-face-group-badge`)

Purpose: Design target; referenced component does not establish implemented navigation. The same person keeps one chip when person_id spans several face groups; the chip adds an N face groups badge while retaining the representative avatar and member +N count.

url_params: `media`

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-multi-group-chip` | One person chip spanning multiple face groups (person_id is the grouping key) | ai_review | default, loading, error, degraded |
| `z-face-group-badge` | N face groups badge when the person spans more than one face group | status | default, error, degraded |
| `z-multi-group-avatar` | Representative face avatar shared by the person chip | ai_review | default, error, degraded |
| `z-multi-group-member-count` | Member count (+N faces across this person's face groups) | status | default, loading, error |
| `z-multi-group-actions` | Person chip buttons (review the face groups or open the person workspace) | form | default, loading, error |

```
+------------------------------------------------------------+
| Media row — person with multiple face groups  [screen]  #\ |
|   /workbench?media=                                        |
| Design target; referenced component does not establish im\ |
|   plemented navigation. The same person keeps one chip wh\ |
|   en person_id spans several face groups; the chip adds a\ |
|   n N face groups badge while retaining the representativ\ |
|   e avatar and member +N count.                            |
+------------------------------------------------------------+
| ZONES                                                      |
|   - One person chip spanning multiple face groups (person\ |
|   _id is the grouping key) (ai_review) states=[default,lo\ |
|   ading,error,degraded]                                    |
|   - N face groups badge when the person spans more than o\ |
|   ne face group (status) states=[default,error,degraded]   |
|   - Representative face avatar shared by the person chip \ |
|   (ai_review) states=[default,error,degraded]              |
|   - Member count (+N faces across this person's face grou\ |
|   ps) (status) states=[default,loading,error]              |
|   - Person chip buttons (review the face groups or open t\ |
|   he person workspace) (form) states=[default,loading,err\ |
|   or]                                                      |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [secondary] Open person workspace -> exit-roster         |
|   [secondary] Review N face groups -> workbench-person-ch\ |
|   ip-expanded                                              |
+------------------------------------------------------------+
| states: default | loading | error | degraded               |
+------------------------------------------------------------+
```

### Media row — current-face fallback (`workbench-media-row-current-face-fallback`)

Purpose: Design target; referenced component does not establish implemented navigation. When representative_face is absent or its image fields are unavailable, show the current face as a fallback and expose the representativeVocabulary copy “Representative image unavailable”; never synthesize representative evidence.

url_params: `media`

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-current-face-avatar` | Current face fallback avatar (used only when representative evidence is unavailable) | ai_review | default, loading, error, degraded |
| `z-representative-unavailable-copy` | Fallback copy: Representative image unavailable (canonical representativeVocabulary text) | status | default, error, degraded |
| `z-fallback-member-count` | Member count remains visible (+N faces) while representative evidence is unavailable | status | default, loading, error |
| `z-fallback-actions` | Fallback chip buttons (expand face-group review or open person workspace) | form | default, loading, error |

```
+------------------------------------------------------------+
| Media row — current-face fallback  [screen]  #/workbench?\ |
|   media=                                                   |
| Design target; referenced component does not establish im\ |
|   plemented navigation. When representative_face is absen\ |
|   t or its image fields are unavailable, show the current\ |
|    face as a fallback and expose the representativeVocabu\ |
|   lary copy “Representative image unavailable”; never syn\ |
|   thesize representative evidence.                         |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Current face fallback avatar (used only when represen\ |
|   tative evidence is unavailable) (ai_review) states=[def\ |
|   ault,loading,error,degraded]                             |
|   - Fallback copy: Representative image unavailable (cano\ |
|   nical representativeVocabulary text) (status) states=[d\ |
|   efault,error,degraded]                                   |
|   - Member count remains visible (+N faces) while represe\ |
|   ntative evidence is unavailable (status) states=[defaul\ |
|   t,loading,error]                                         |
|   - Fallback chip buttons (expand face-group review or op\ |
|   en person workspace) (form) states=[default,loading,err\ |
|   or]                                                      |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [secondary] Open person workspace -> exit-roster         |
|   [secondary] Review current face evidence -> workbench-p\ |
|   erson-chip-expanded                                      |
+------------------------------------------------------------+
| states: default | loading | error | degraded               |
+------------------------------------------------------------+
```

### Expanded person chip — review faces (`workbench-person-chip-expanded`)

Purpose: Design target; referenced component does not establish implemented navigation. The expanded chip enters the existing member review panel so the operator can inspect face evidence, show all members, remove a face, close the panel, or open the person workspace. UXREC-1 proposed adjacent evidence disclosure shows source media, crop geometry, exact face/identity and group references, displayed/total counts and any incomplete coverage. Review remains navigation into existing cluster review, not a new merge UI.

url_params: `media`, `cluster`

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-expanded-face-evidence` | Expanded face evidence (representative and current faces remain linked to their media) | ai_review | default, loading, empty, error, degraded |
| `z-expanded-face-members` | Expanded face members (show all members or remove this face) | forced_choice | default, loading, empty, error, degraded |
| `z-expanded-actions` | Close face review / open person workspace | form | default, loading, error |
| `z-repeated-face-evidence` | Proposed evidence: same source/crop reported in multiple groups; show aligned proportional thumbnails, visible source labels, exact group and face references in disclosure, displayed/available totals and Show all. No automatic identity merge. | ai_review | default, loading, empty, error, degraded |

```
+------------------------------------------------------------+
| Expanded person chip — review faces  [overlay]  #/workben\ |
|   ch?media=&cluster=                                       |
| Design target; referenced component does not establish im\ |
|   plemented navigation. The expanded chip enters the exis\ |
|   ting member review panel so the operator can inspect fa\ |
|   ce evidence, show all members, remove a face, close the\ |
|    panel, or open the person workspace. UXREC-1 proposed \ |
|   adjacent evidence disclosure shows source media, crop g\ |
|   eometry, exact face/identity and group references, disp\ |
|   layed/total counts and any incomplete coverage. Review \ |
|   remains navigation into existing cluster review, not a \ |
|   new merge UI.                                            |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Expanded face evidence (representative and current fa\ |
|   ces remain linked to their media) (ai_review) states=[d\ |
|   efault,loading,empty,error,degraded]                     |
|   - Expanded face members (show all members or remove thi\ |
|   s face) (forced_choice) states=[default,loading,empty,e\ |
|   rror,degraded]                                           |
|   - Close face review / open person workspace (form) stat\ |
|   es=[default,loading,error]                               |
|   - Proposed evidence: same source/crop reported in multi\ |
|   ple groups; show aligned proportional thumbnails, visib\ |
|   le source labels, exact group and face references in di\ |
|   sclosure, displayed/available totals and Show all. No a\ |
|   utomatic identity merge. (ai_review) states=[default,lo\ |
|   ading,empty,error,degraded]                              |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [secondary] Close face review -> workbench-media-row-pe\ |
|   rson-chips                                               |
|   [secondary] Open person workspace -> exit-roster         |
+------------------------------------------------------------+
| states: default | loading | empty | error | degraded       |
+------------------------------------------------------------+
```

### Person workspace (`exit-roster`)

Purpose: Design target; referenced component does not establish implemented navigation. Person chip name, avatar, or face-group-count button opens the named person's workspace and preserves the media-row context when the operator returns.

url_params: `person`, `media`

| zone id | label | role | states |
| --- | --- | --- | --- |
| `z-roster-person-entry` | Person workspace entry from a chip button | nav | default |

```
+------------------------------------------------------------+
| Person workspace  [exit]  #/roster?person=                 |
| Design target; referenced component does not establish im\ |
|   plemented navigation. Person chip name, avatar, or face\ |
|   -group-count button opens the named person's workspace \ |
|   and preserves the media-row context when the operator r\ |
|   eturns.                                                  |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Person workspace entry from a chip button (nav) state\ |
|   s=[default]                                              |
+------------------------------------------------------------+
| states: default | loading | error                          |
+------------------------------------------------------------+
```

## Actions

| id | verb | target | hierarchy | costly | irreversible | preview required | screen id |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `act-expand-person-chip` | Expand face-group review | `workbench-person-chip-expanded` | primary | no | no | no | `workbench-media-row-person-chips` |
| `act-open-person-workspace-from-chip` | Open person workspace | `exit-roster` | secondary | no | no | no | `workbench-media-row-person-chips` |
| `act-review-multi-group-person` | Review N face groups | `workbench-person-chip-expanded` | secondary | no | no | no | `workbench-media-row-face-group-badge` |
| `act-open-person-workspace-from-multi-group-chip` | Open person workspace | `exit-roster` | secondary | no | no | no | `workbench-media-row-face-group-badge` |
| `act-review-current-face-fallback` | Review current face evidence | `workbench-person-chip-expanded` | secondary | no | no | no | `workbench-media-row-current-face-fallback` |
| `act-open-person-workspace-from-fallback` | Open person workspace | `exit-roster` | secondary | no | no | no | `workbench-media-row-current-face-fallback` |
| `act-close-person-chip-review` | Close face review | `workbench-media-row-person-chips` | secondary | no | no | no | `workbench-person-chip-expanded` |
| `act-open-person-workspace-from-review` | Open person workspace | `exit-roster` | secondary | no | no | no | `workbench-person-chip-expanded` |

## Flows
### Media row person chip → evidence review → person workspace (`flow-person-chip-evidence`)

```
flow: Media row person chip → evidence review → person worksp\
  ace (flow-person-chip-evidence) job=job-review-person-evide\
  nce
  1. Media row — person chips [workbench-media-row-person-chi\
  ps]
     --one chip per person; representative face and member +N\
   count are visible-->
  2. Media row — person with multiple face groups [workbench-\
  media-row-face-group-badge]
     --if the person spans groups, show N face groups without\
   duplicating the chip-->
  3. Media row — current-face fallback [workbench-media-row-c\
  urrent-face-fallback]
     --if representative evidence is unavailable, show curren\
  t face + Representative image unavailable-->
  4. Expanded person chip — review faces [workbench-person-ch\
  ip-expanded]
     --expand the chip into the existing face review panel-->
  5. Person workspace [exit-roster]
```

```mermaid
flowchart TD
  %% flow: Media row person chip → evidence review → person workspace job=job-review-person-evidence
  %% steps: [{"screen_id":"workbench-media-row-person-chips","branch_label":"one chip per person; representative face and member +N count are visible"},{"screen_id":"workbench-media-row-face-group-badge","branch_label":"if the person spans groups, show N face groups without duplicating the chip"},{"screen_id":"workbench-media-row-current-face-fallback","branch_label":"if representative evidence is unavailable, show current face + Representative image unavailable"},{"screen_id":"workbench-person-chip-expanded","branch_label":"expand the chip into the existing face review panel"},{"screen_id":"exit-roster","branch_label":"chip name, avatar, or face-group-count button opens the person workspace"}]
  n_workbench_media_row_person_chips["Media row — person chips (screen)"]
  n_workbench_media_row_face_group_badge["Media row — person with multiple face groups (screen)"]
  n_workbench_media_row_person_chips -->|one chip per person; representative face and member +N count are visible| n_workbench_media_row_face_group_badge
  n_workbench_media_row_current_face_fallback["Media row — current-face fallback (screen)"]
  n_workbench_media_row_face_group_badge -->|if the person spans groups, show N face groups without duplicating the chip| n_workbench_media_row_current_face_fallback
  n_workbench_person_chip_expanded["Expanded person chip — review faces (overlay)"]
  n_workbench_media_row_current_face_fallback -->|if representative evidence is unavailable, show current face + Representative image unavailable| n_workbench_person_chip_expanded
  n_exit_roster["Person workspace (exit)"]
  n_workbench_person_chip_expanded -->|expand the chip into the existing face review panel| n_exit_roster
```

## Open questions
- When person_id is absent, should the unresolved face-group result show a neutral chip action or remain only in the review queue?
- Should returning from the person workspace restore the expanded face review panel or only the media row scroll position?

## Suggested task-slice decomposition (from map)

1. Group media identities by optional person_id while preserving unresolved face groups
2. Render representative face evidence, N face groups, and member +N chip states
3. Render current-face fallback with canonical Representative image unavailable copy
4. Connect chip actions to face review and the person workspace
5. Collapse ungrouped residue into one Not yet grouped (N) section without visually deduplicating faces
6. UXREC-1 IDENTITY proposed: derive explicit cross-group repeated evidence alongside unchanged person/cluster grouping; review-only disclosure and wrapper tests preserve identityClusterIds and existing naming/mutation targets.

## Parity index

Machine-checked by `js/admin/__tests__/uxmap-parity.test.ts` and
`js/admin/__tests__/uxmap-render-parity.test.ts`: every id, state, and verbatim label
below must exist in the sibling `.uxmap.json`, and no `z-*`/`act-*` id may appear here
that the JSON does not define. Regenerate with `docs/ux-maps/render_ux_maps.py` — never
hand-edit one side.

Zone ids: z-media-row z-person-chip-rail z-ungrouped-residue z-representative-avatar z-member-count z-chip-actions z-repeated-face-summary z-multi-group-chip z-face-group-badge z-multi-group-avatar z-multi-group-member-count z-multi-group-actions z-current-face-avatar z-representative-unavailable-copy z-fallback-member-count z-fallback-actions z-expanded-face-evidence z-expanded-face-members z-expanded-actions z-repeated-face-evidence z-roster-person-entry

Action ids: act-expand-person-chip act-open-person-workspace-from-chip act-review-multi-group-person act-open-person-workspace-from-multi-group-chip act-review-current-face-fallback act-open-person-workspace-from-fallback act-close-person-chip-review act-open-person-workspace-from-review

Zone labels (verbatim; the tables above escape `|` for markdown, this list does not):

- Selected media row (title, description status, and person chip rail)
- One person chip per person (no duplicate chip for each face group)
- Not yet grouped section (every unresolved face, never N Unnamed person cards)
- Representative face avatar (store reference crop rendered before the person's label)
- Member count (+N faces on this person chip)
- Person chip buttons (expand face-group review or open person workspace)
- Proposed compact repeated-evidence summary only when observed: same source face appears in N groups; expand to inspect source/crop/group references. Not a new guessed person label.
- One person chip spanning multiple face groups (person_id is the grouping key)
- N face groups badge when the person spans more than one face group
- Representative face avatar shared by the person chip
- Member count (+N faces across this person's face groups)
- Person chip buttons (review the face groups or open the person workspace)
- Current face fallback avatar (used only when representative evidence is unavailable)
- Fallback copy: Representative image unavailable (canonical representativeVocabulary text)
- Member count remains visible (+N faces) while representative evidence is unavailable
- Fallback chip buttons (expand face-group review or open person workspace)
- Expanded face evidence (representative and current faces remain linked to their media)
- Expanded face members (show all members or remove this face)
- Close face review / open person workspace
- Proposed evidence: same source/crop reported in multiple groups; show aligned proportional thumbnails, visible source labels, exact group and face references in disclosure, displayed/available totals and Show all. No automatic identity merge.
- Person workspace entry from a chip button

States (all zones and screens): default loading empty error degraded

## Not doing
- Creating one person chip per face group
- Showing a guessed representative image when representative_face is absent
- Auto-merging people from a matching label without a preview
- Pixel or token design; implementation uses the existing --acx-* system
- No auto-transitive similarity merge, filename-based identity, new merge endpoint, detector threshold tuning or backend activation. Camera/detector duplicate and identity-recall hypotheses require separate corpus evidence.
