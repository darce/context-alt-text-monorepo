# UX Map — guided-prototype

**Product:** `AltContext — authenticated guided prototype`

## Goals
- Implementation inventory and correction target for feature/guided-prototype-1; one in-memory example inside authenticated WordPress admin, not the public homepage.
- Show visual draft + confirmed identity + page context → named description; editing/rejection never applies automatically.
- Only the saved candidate can be applied; pending text is labelled and must be saved or discarded before Apply.
- Guide navigation reaches its named region; reset dialog preserves edits on cancel; all disappearing actions restore focus.
- Clear illustrative provenance, bundled sample with text fallback, no live inference dependency.
- State variants share one route; refresh resets memory, and the UI explains this.

## Jobs
- `review` — Review identity-informed description and apply to practice copy
- `recover` — Undo or reset practice without hidden losses

## Screens
| id | kind | route | title |
| --- | --- | --- | --- |
| `intro` | screen | `#/guided-prototype` | Guided prototype entrance |
| `guide` | screen | `#/guided-prototype` | Inline guided review nav |
| `evidence` | screen | `#/guided-prototype` | Image and page context |
| `draft` | screen | `#/guided-prototype` | Description review |
| `apply` | screen | `#/guided-prototype` | Review exact application |
| `result` | screen | `#/guided-prototype` | Applied result and history |
| `reset` | overlay | `#/guided-prototype` | Reset practice confirmation |
| `image-fallback` | screen | `#/guided-prototype` | Image unavailable, text evidence remains |
| `case-study` | exit | `https://darce.xyz/projects/altcontext/` | Authoritative case study |

## Code references
- `screen:intro` — `apps/prototype-wp-alt-context/js/admin/pages/GuidedPrototypeEntrance.tsx`
- `screen:guide` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypeGuide.tsx`
- `screen:evidence` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypePage.tsx`
- `screen:draft` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx`
- `screen:apply` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx`
- `screen:result` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypePage.tsx`
- `screen:reset` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedResetDialog.tsx`
- `screen:image-fallback` — `apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx`
- `screen:case-study` — `apps/prototype-wp-alt-context/js/admin/pages/GuidedPrototypeEntrance.tsx`

### Guided prototype entrance (`intro`)

```
+------------------------------------------------------------+
| Guided prototype entrance  [screen]  #/guided-prototype    |
| Explains illustrative memory-only scope; case study and c… |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Branded heading, scope and current build status (cont… |
|   - Start the guided walkthrough and case study exit (nav… |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Start the guided walkthrough -> guide          |
|   [secondary] Read the case study -> case-study            |
+------------------------------------------------------------+
| states: default                                            |
+------------------------------------------------------------+
```

### Inline guided review nav (`guide`)

```
+------------------------------------------------------------+
| Inline guided review nav  [screen]  #/guided-prototype     |
| Persistent inline nav shows the current step, lets you sh… |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Status bar: current step label, skip-to-current-secti… |
|   - Expanded step list (understand/identity/review/apply)… |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [secondary] Show guide / Hide guide -> guide             |
|   [secondary] Jump to a guide step (understand/identity/r… |
|   [tertiary] End guide -> evidence                         |
|   [tertiary] Skip guide to current section -> evidence     |
+------------------------------------------------------------+
| states: first_time | default                               |
+------------------------------------------------------------+
```

### Image and page context (`evidence`)

```
+------------------------------------------------------------+
| Image and page context  [screen]  #/guided-prototype       |
| Inspect sample photograph/text equivalent, source record … |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Photograph with descriptive fallback; figcaption show… |
|   - Provenance list with humanised scenario-origin label,… |
+------------------------------------------------------------+
| states: default                                            |
+------------------------------------------------------------+
```

### Description review (`draft`)

```
+------------------------------------------------------------+
| Description review  [screen]  #/guided-prototype           |
| Identity evidence card, saved draft and immutable visual-… |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Identity evidence card: confirm sample identity or le… |
|   - Before (generic draft) vs Proposed draft with humanis… |
|   - Labelled editor with save/discard/reject actions; inl… |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Save description edit -> apply                 |
|   [secondary] Confirm Keanu Reeves -> draft                |
|   [secondary] Reject draft -> draft                        |
|   [tertiary] Discard unsaved edit -> draft                 |
|   [tertiary] Keep the person unidentified -> draft         |
+------------------------------------------------------------+
| states: default | error                                    |
+------------------------------------------------------------+
```

### Review exact application (`apply`)

```
+------------------------------------------------------------+
| Review exact application  [screen]  #/guided-prototype     |
| Before/after shows current practice value and the actual … |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Current value and reviewed saved candidate; explicit … |
|   - Apply / Undo actions; blocked with explanation while … |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Apply to practice copy -> result               |
|   [tertiary] Undo practice apply -> apply                  |
+------------------------------------------------------------+
| states: default | error                                    |
+------------------------------------------------------------+
```

### Applied result and history (`result`)

```
+------------------------------------------------------------+
| Applied result and history  [screen]  #/guided-prototype   |
| Applied value is separate from draft; history preserves o… |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Applied description and unchanged original media scop… |
|   - Chronological decision history; empty state before an… |
|   - Reset practice trigger in the workspace header (nav) … |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [tertiary] Reset practice -> reset                       |
+------------------------------------------------------------+
| states: default | empty                                    |
+------------------------------------------------------------+
```

### Reset practice confirmation (`reset`)

```
+------------------------------------------------------------+
| Reset practice confirmation  [overlay]  #/guided-prototype |
| Radix dialog overlay; safe default Cancel preserves unsav… |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Explicit effects: remove practice changes, preserve o… |
|   - Cancel / Reset practice; Escape cancels (form) states… |
+------------------------------------------------------------+
| ACTIONS                                                    |
|   [PRIMARY] Cancel -> draft                                |
|   [DESTRUCTIVE] Reset practice -> evidence (preview,irrev… |
+------------------------------------------------------------+
| states: default                                            |
+------------------------------------------------------------+
```

### Image unavailable, text evidence remains (`image-fallback`)

```
+------------------------------------------------------------+
| Image unavailable, text evidence remains  [screen]  #/gui… |
| Image load failure does not invent a rendered photograph … |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Visible image unavailable explanation and independent… |
|   - Sample record and text-based review remain available … |
+------------------------------------------------------------+
| states: default                                            |
+------------------------------------------------------------+
```

### Authoritative case study (`case-study`)

```
+------------------------------------------------------------+
| Authoritative case study  [exit]  https://darce.xyz/proje… |
| External destination in a new tab; browser owns network f… |
+------------------------------------------------------------+
| ZONES                                                      |
|   - Case study content (content) states=[default]          |
+------------------------------------------------------------+
| states: default                                            |
+------------------------------------------------------------+
```

## Flows
### Confirmed identity woven into description, reviewed and applied (`named`)

```mermaid
flowchart TD
  %% flow: Confirmed identity woven into description, reviewed and applied job=review
  n_intro["Guided prototype entrance (screen)"]
  n_guide["Inline guided review nav (screen)"]
  n_intro --> n_guide
  n_evidence["Image and page context (screen)"]
  n_guide --> n_evidence
  n_draft["Description review (screen)"]
  n_evidence --> n_draft
  n_apply["Review exact application (screen)"]
  n_draft --> n_apply
  n_result["Applied result and history (screen)"]
  n_apply --> n_result
```

### Unresolved identity keeps description generic (`unnamed`)

```mermaid
flowchart TD
  %% flow: Unresolved identity keeps description generic job=review
  n_evidence["Image and page context (screen)"]
  n_draft["Description review (screen)"]
  n_evidence --> n_draft
  n_apply["Review exact application (screen)"]
  n_draft --> n_apply
  n_result["Applied result and history (screen)"]
  n_apply --> n_result
```

### Pending edit cannot apply old candidate (`pending`)

```mermaid
flowchart TD
  %% flow: Pending edit cannot apply old candidate job=review
  n_draft["Description review (screen)"]
  n_apply["Review exact application (screen)"]
  n_draft --> n_apply
  n_result["Applied result and history (screen)"]
  n_apply --> n_result
```

### Apply two revisions and undo in order (`undo-flow`)

```mermaid
flowchart TD
  %% flow: Apply two revisions and undo in order job=recover
  n_draft["Description review (screen)"]
  n_apply["Review exact application (screen)"]
  n_draft --> n_apply
  n_result["Applied result and history (screen)"]
  n_apply --> n_result
  n_result --> n_draft
  n_draft --> n_apply
  n_apply --> n_result
  n_result --> n_apply
```

### Cancel or confirm reset safely (`reset-flow`)

```mermaid
flowchart TD
  %% flow: Cancel or confirm reset safely job=recover
  n_draft["Description review (screen)"]
  n_reset["Reset practice confirmation (overlay)"]
  n_draft --> n_reset
  n_evidence["Image and page context (screen)"]
  n_reset --> n_evidence
```

### Text fallback retains review path (`image-error`)

```mermaid
flowchart TD
  %% flow: Text fallback retains review path job=review
  n_image_fallback["Image unavailable, text evidence remains (screen)"]
  n_draft["Description review (screen)"]
  n_image_fallback --> n_draft
  n_apply["Review exact application (screen)"]
  n_draft --> n_apply
```

## Not doing
- Public homepage or marketing deployment
- Guest-session authentication or credentials settings
- Live generation
- Multi-scenario library and production privacy settings
- Full WordPress or screen-reader conformance claim from component-only browser tests
