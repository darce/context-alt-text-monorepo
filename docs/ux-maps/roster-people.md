# UX Map — roster and people

**Product:** Alt Context People roster and person workspace

**Source fixture:** `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx`, and the roster components cited below. The current route is People; the old clusters tab is retired, while `?cluster=` remains a detail-drawer deep-link shim (`apps/prototype-wp-alt-context/js/admin/pages/roster/rosterRoute.ts:7-29`).

## Goals

- Make People the home for named faces and the Review Queue the single home for unnamed face groups (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:188-239`, `apps/prototype-wp-alt-context/js/admin/pages/roster/rosterRoute.ts:174-217`).
- Render one person card per person, grouping identities by person first, then cluster, with a final ungrouped bucket and spatial duplicate suppression (`apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/utils.ts:102-194`).
- Give a named person a workspace for face evidence, representative/cover choices, photos, person intersection, and queued follow-up work (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:556-920`).
- Keep merge suggestions optional and interruptible: show one prompt only when a pending suggestion is available, then consume it on Yes, No, or Skip (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:100-198`).

## Jobs

| Job | Entry | Successful outcome |
| --- | --- | --- |
| Find a named person | People roster search/filter or a person card | The person workspace opens on a canonical person route (`apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:134-193`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:152-186`). |
| Verify a person’s evidence | Person workspace | The operator selects a face, inspects metadata, and optionally pins a representative or cover (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:402-483`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:620-735`). |
| Find photos shared with other people | Person workspace Photos section | The operator adds up to five named people and gets the intersection with real pagination (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:181-211`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:738-864`). |
| Resolve a follow-up queue item | Person workspace queue section | A queued action opens the workbench Review Queue; an unavailable identifier leaves the action disabled (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:867-906`). |
| Decide whether two groups are the same person | Same person prompt | Yes accepts, No rejects, and Skip consumes the one-session prompt (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:100-198`). |

## Screens

| Screen or region | Route / placement | Primary purpose |
| --- | --- | --- |
| People roster | `/roster` | Show named people, search/filter entries, and hand unnamed groups to Review Queue (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:188-239`, `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:366-407`). |
| Person workspace | `/roster?person=<person_uuid>` | Inspect one person’s evidence, photos, intersections, and queued work (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:33-108`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:556-920`). |
| Same or different person? | Inline card on `/roster` | Resolve one pending merge suggestion without opening a second roster surface (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:140-198`). |
| Cluster detail drawer | `/roster?cluster=<cluster_id>` | Preserve the cluster deep-link shim for detail, rescan, commit, and the handoff to a person workspace (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:33-80`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:242-284`). |
| Face lightbox | Overlay from person evidence or photos | Inspect a croppable face image without losing the workspace context (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:235-281`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:908-920`). |

### People roster

```text
+-- People ------------------------------------------------------------------+
| Alt Context                                                               |
| People                                                                    |
| These are the faces you have named. Unnamed face groups are reviewed      |
| in the Review Queue.                                                      |
|                                                                            |
| [Same or different person?]  (optional, one pending suggestion)           |
|                                                                            |
| [search people] [queue/filter controls]                                   |
| [person card] [person card] [person card]                                 |
|                                                                            |
| [projection gate / roster error / no matching people]                     |
|                                                                            |
| Unnamed faces waiting / No unnamed face groups right now                  |
| [Open Review Queue]                                                       |
+----------------------------------------------------------------------------+
```

The shell has a People heading and explicitly states the boundary between named faces and unnamed review work (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:188-207`). Roster entries provide search, queue filters, add-person, and true-zero versus filtered empty states (`apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:134-193`, `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:295-364`).

The implemented roster states are entries loading or error, projection shape unavailable, projection refreshing, stale, failed, an unmatched person route, a selected cluster drawer, and the count-based unnamed-face CTA (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:33-108`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:210-239`). The SamePersonPrompt is absent when the session was consumed or no suggestion exists, and present with busy or error feedback when a suggestion is actionable (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:100-198`).

### Person workspace

```text
+-- Person workspace: [name] -----------------------------------------------+
| [face group count] [projection status] [refreshed / record version]        |
|                                                                            |
| Face groups                                                                |
| [selected face preview] [metadata] [Set as representative] [Use as cover] |
| [face filmstrip]                                                           |
|                                                                            |
| Photos                                                                     |
| [Also with… Search people] [person chip] ...                               |
| [photo] [photo] [photo] ...                         [Previous] [Next]       |
|                                                                            |
| Follow-up queues                                                           |
| Singleton proposals · Hard examples · Needs confirmation after merge       |
+----------------------------------------------------------------------------+
```

The header reports the person name, face-group count, projection status, refresh time, and record version (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:556-578`). Face data distinguishes failed, refreshing, stale, current, no groups, and representative-unavailable branches; selected evidence exposes metadata, representative pinning, cover actions, and undo feedback (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:580-735`).

Photos have explicit disabled, loading, error, empty, populated, and paginated states. The Also with combobox excludes the current person and already selected people, supports at most five positive person IDs, and sends the selected IDs as `with_person_ids[]` on the media query (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:181-211`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:738-864`).

The follow-up sections distinguish queued work from an empty queue. A queued action is enabled only when the person has a route identifier; otherwise the action is unavailable while its empty state remains visible (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:867-906`).

### Same or different person?

```text
+-- Same or different person? ----------------------------------------------+
| [face A]                         [face B]                                  |
|                                                                            |
| Same or different person?                                                 |
| [Yes]                         [No]                         [Skip]           |
| [error, if the choice could not be saved]                                 |
+----------------------------------------------------------------------------+
```

The prompt renders one pending suggestion with cropped face thumbnails when media and a bounding box are available, otherwise an avatar fallback. Yes and No are mutations; Skip only consumes the prompt. All three are disabled while a mutation is busy, and mutation errors use an alert (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:68-98`, `apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:140-198`). Reserved `cluster-*` labels are presented as Unnamed person rather than as confirmed names (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:17-66`).

### Cluster detail and lightbox

The `cluster=` route is a detail-only shim. The drawer receives loading, error, retry, rescan, commit, drag/drop, reassign, close, and Open person workspace seams from the roster shell; the current route explicitly marks reassign as unavailable until a scoped target query exists (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:110-149`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:242-284`, `apps/prototype-wp-alt-context/js/admin/pages/roster/rosterRoute.ts:174-203`). Face evidence and photos may open the lightbox, which closes back to the same person workspace (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:235-281`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:908-920`).

## Actions

| Surface | Action | Result, next step, or stop |
| --- | --- | --- |
| People roster | Search or apply queue filters | Narrows the person cards; an empty filtered result is distinct from a true empty roster (`apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:107-193`, `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:337-364`). |
| People roster | Add person | Validates a non-empty name, creates the entry, and keeps the add flow in the roster (`apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:295-335`). |
| Person card | Open person workspace | Clears unrelated route parameters and sets `person=<person_uuid>`; an optional queue ID is preserved (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:152-186`). |
| Roster CTA | Open Review Queue | Opens the single unnamed-face home, including the zero, positive-count, and unavailable-count copy (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:210-239`, `apps/prototype-wp-alt-context/js/admin/pages/roster/rosterRoute.ts:206-217`). |
| Same-person prompt | Yes, No, Skip | Accepts or rejects the pending suggestion, or consumes it without a merge; all choices are gated while busy (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:100-198`). |
| Face evidence | Select a face; Set as representative | Updates the selected-face cursor and pins the chosen identity, with a live announcement and an error path (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:402-483`). |
| Face evidence | Use as cover; Undo | Applies an optimistic cover choice, announces success, and offers an explicit Undo for the previous choice (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:437-523`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:620-735`). |
| Photos | Add or remove an Also with person | Adds only a positive, distinct, non-current person and resets pagination; the selector disables at five people or when roster data is unavailable (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:330-343`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:525-544`). |
| Photos | Previous / Next | Paginates the real person-media result and preserves the selected intersection (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:738-864`). |
| Follow-up queue | Open a queued action | Opens the workbench queue for the person’s queue ID when an identifier is present; otherwise it remains disabled (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:867-906`). |
| Cluster drawer | Close, Retry roster, Rescan, Commit, Open person workspace | Returns to the roster, retries or mutates the selected cluster, or transitions to the canonical person route (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:152-186`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:242-284`). |
| Face lightbox | Close | Returns to the evidence or photos context without changing the person route (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:908-920`). |

## Flows

### Open a person workspace

1. The operator searches or filters the People roster and opens a named person (`apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:107-193`, `apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesSection.tsx:229-247`).
2. The route is accepted only when the canonical projection shape is available and current. Missing shape, refreshing, stale, failed, and unmatched-person states stay on the roster with a specific gate notice (`apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:33-108`).
3. When current, the workspace shows face evidence, photos, intersections, and follow-up queues. Changing the entry resets lightbox, pagination, Also with selections, and cover UI (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:366-380`).

### Curate face evidence

1. The operator selects a face from the cursor/filmstrip; the workspace announces its position and renders that face’s metadata (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:402-434`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:620-735`).
2. Set as representative and Use as cover are explicit actions. Pin errors are announced; a successful cover mutation exposes Undo (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:437-523`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:620-735`).
3. A croppable image opens in the lightbox; closing it returns to the same workspace rather than changing the selected person (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:235-281`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:908-920`).

### Find photos with other people

1. The operator opens Also with and adds up to five named people. The current person, duplicate selections, blank names, non-positive IDs, and a sixth selection are rejected or unavailable (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:330-343`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:525-544`).
2. The query sends the person ID plus `with_person_ids[]`; the backend result is the intersection, and the UI uses the returned limit, offset, total, and truncated metadata for pagination (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:62-77`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:109-178`).
3. The UI distinguishes loading, error, empty, and populated photos. Removing a chip resets the offset and reruns the same person-media query (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:525-554`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:738-864`).

### Resolve a prompt or follow-up queue

1. If the session has not consumed the prompt and a pending merge suggestion is returned, the operator sees two faces and chooses Yes, No, or Skip (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:100-198`).
2. Accept and reject invalidate the relevant suggestion and roster queries; Skip writes the session-consumed marker and hides the card (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:17-66`, `apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:100-137`).
3. A person’s queued follow-up item opens the workbench Review Queue only when its person route identifier is available. The Review Queue remains the single destination for unnamed groups (`apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:867-906`, `apps/prototype-wp-alt-context/js/admin/pages/RosterPage.tsx:188-239`).

### Roster and wire boundaries

The person-media flow mirrors the frozen intersection contract: no more than five positive `with_person_ids[]` values, media where the path person and every selected person appear, and pagination from the real query (`docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md:85-88`, `apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx:109-178`). Reserved or auto-shaped cluster labels remain neutral Unnamed person copy, and ungrouped identities remain a single presentation bucket rather than becoming phantom people (`apps/prototype-wp-alt-context/js/admin/pages/roster/SamePersonPrompt.tsx:17-66`, `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/utils.ts:71-194`).
