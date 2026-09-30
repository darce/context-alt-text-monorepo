# GUIDEV4-1 proposed screens: public guide at /guide/

Status: **proposal, not built.** Nothing below is implemented yet.

"Before" screens were taken from the live page on 23 September 2026 (screenshots at 1440 px and
390 px). "After" screens show the proposed changes. The task plan
(`GUIDEV4-1-public-guide-flow-layout-copy-task-plan.md`) is written once these screens are
approved. The admin page does not change.
Rule IDs are from the [heuristics canon](https://github.com/darce/heuristics-canon).

Legend:

```text
[Button]     button             ( ) (*)   answer: not chosen / chosen
> Summary    collapsed section  (!)       warning icon, always with words
✓ text       status line, read out by screen readers
<- focus     where keyboard focus lands after the action
↗            link that leaves the demo
------       one divider line between rows (mobile)
```

### A1. Hero, desktop 1440 px, before

```text
+------------------------------------------------------------------------------------------+
|                                                                                          |
|    Home  Case study                                                                      |
|    GUIDED PROTOTYPE                                                                      |
|                                                                                          |
|    WHO'S IN THE PHOTO                                                                    |
|    BELONGS IN THE ALT             .    .    .    empty half    .    .    .               |
|    TEXT.                                                                                 |
|                                                                                          |
|    Compare descriptions of two photos, choose which names                                |
|    to include, then edit and apply each draft.                                           |
|                                                                                          |
|    Recorded example. Changes stay in this tab; WordPress                                 |
|    and the server roster are unchanged.                                                  |
|                                                                                          |
|    [Start the walkthrough]  [Read the case study]                                        |
|                                                                                          |
| +------------------------------------------------------------------------------------+   |
| | DEMO STEPS                                                            [Hide steps] |   |
| | Step 1 of 2: Choose names                                                          |   |
| | [(1) Choose names]  [(2) Review and apply]                                         |   |
```

### A2. Hero, desktop 1440 px, after

```text
+------------------------------------------------------------------------------------------+
|                                                                                          |
|    Home  Case study↗                                                                     |
|                                                                                          |
|    DEMO                                                                                  |
|    YOU DECIDE WHO IS                               What you'll do                        |
|    NAMED IN EACH PHOTO                             1. Check the names suggested for      |
|    DESCRIPTION.                                       each photo.                        |
|                                                    2. Read and edit the suggested        |
|    See how AltContext suggests image                  description.                       |
|    descriptions (alt text) and possible            3. Use it on the demo image, or keep  |
|    names, and how you decide which names              the current one.                   |
|    to use.                                                                               |
|                                                                                          |
|    The names and descriptions were                                                       |
|    suggested by AI in advance. Your changes                                              |
|    stay on this page and clear when you                                                  |
|    reload.                                                                               |
|                                                                                          |
|    [Start the demo]  [Read the case study↗]                                              |
|                                                                                          |
|    [--------- column 1: up to 38em ---------] 3rem [----- column 2: 12em to 1fr ------]  |
|                                                                                          |
|    (the gap below the hero is at least twice the gap under the heading)                  |
+------------------------------------------------------------------------------------------+
```

- The heading stays at 20 characters per line at most and the intro at 36em. Stretching the
  heading across the full width would give lines far past a readable length (TYPE-01, TYPE-02).
- The empty right half gets a job: the three-step plan (LAY-05, LAY-01, LAY-02). The visitor
  sees the whole task before starting (NAV-09, COG-03).
- A bigger gap after the hero than inside it, so the hero reads as one group (LAY-03, PERC-01,
  UI-03). Two columns from 60em, one column below that (A11Y-08).

### B. Page flow, desktop: before (left) and after (right)

```text
+-------------------------------------------+  +-------------------------------------------+
| Hero                                      |  | Hero + What you'll do                     |
| DEMO STEPS  Step 1 of 2  [Hide steps] (3) |  | [Start the demo]                      (1) |
| [(1) Choose names] [(2) Review and apply] |  |                                           |
|-------------------------------------------|  |-------------------------------------------|
| CHOOSE NAMES                 [Reset demo] |  | Two photos to check          [Start over] |
|  Tribeca photo + 2 name cards         (1) |  | Photo 1 of 2: Tribeca                     |
|  Coachella photo + 2 name cards       (1) |  |  1. Check the suggested names         (2) |
|  [Review drafts]                      (2) |  |  2. Check the suggested description   (3) |
|-------------------------------------------|  |  [Use this description] ✓ [Undo]      (4) |
|  Current name choices: ...                |  | Photo 2 of 2: Coachella                   |
| REVIEW AND APPLY                      (4) |  |  1. names, 2. description (same)          |
|  Tribeca again, smaller, + editor         |  |-------------------------------------------|
|  Coachella again, smaller, + editor       |  | You checked both photos               (5) |
| YOUR DEMO COPY IS UPDATED             (5) |  |  Provenance line (date, no live matching) |
+-------------------------------------------+  +-------------------------------------------+
```

Before:

1. The visitor answers four name questions spread over two photo cards.
2. They press Review drafts. The page does not move.
3. The stepper now says Step 2, but it sits at the top, out of view.
4. They scroll down past both photos to reach the editors, which repeat both photos. The editors
   show buttons and "No recorded draft is available for these choices." before any answer.
5. "Your demo copy is updated" appears after only one photo, with a "Return to the draft" button.

After:

1. Start moves keyboard focus to the first question. Nothing else moves (A11Y-11).
2. Each photo has its own name questions (option B, see C1).
3. The description opens in place, under the names, once both people in that photo have an
   answer. There is no stepper, no Hide steps and no scrolling on its own (COG-03, NAV-02,
   A11Y-20). The numbered headings inside each card show the order (NAV-09).
4. Status and Undo appear beside the button just pressed (PERC-05, A11Y-21).
5. The summary appears only when both photos are done.

Why the review merges into each photo card and not into the context block at the top: the
description has to sit with its photo and its names (PERC-01, VIZ-16). Two editors in the top
block would sit far from both photos.

### C1. Photo card, desktop 1440 px, after: names not yet answered

```text
+------------------------------------------------------------------------------------------+
| Two photos to check                                                         [Start over] |
| Naming people helps readers when you are sure who they are. Leaving someone              |
| unnamed is always a valid choice.                                                        |
|                                                                                          |
| +--------------------------------------------------------------------------------------+ |
| | Photo 1 of 2                                                                         | |
| | Tribeca Festival, New York, June 2026                                                | |
| |                                                                                      | |
| | +------------------------------------+    1. Check the suggested names               | |
| | |                                    |    AltContext compared each face with         | |
| | |                                    |    reference photos from a list of people.    | |
| | |       Tribeca photo                |    Use a name only if you agree. Not sure?    | |
| | |       (alt = current description)  |    Leave the person unnamed.                  | |
| | |                                    |    ------------------------------------------ | |
| | |    [Justin Trudeau]   [Katy Perry] |    +----+ Justin Trudeau     [Compare photos] | |
| | |                                    |    |crop| Strong match                        | |
| | |                                    |    +----+                                     | |
| | +------------------------------------+    Name the person on the left?               | |
| | Photo credit: Colleen Sturtevant,         ( ) Use Justin Trudeau                     | |
| | CC BY-SA 4.0, resized                     ( ) Leave unnamed                          | |
| |                                           ------------------------------------------ | |
| | > How another tool describes this         +----+ Katy Perry         [Compare photos] | |
| |   photo                                   |crop| No score: the saved group for       | |
| |                                           +----+ this name started from this face    | |
| |                                                  Compare photos before you use it.   | |
| |                                           Name the person on the right?              | |
| |                                           ( ) Use Katy Perry                         | |
| |                                           ( ) Leave unnamed                          | |
| |                                                                                      | |
| |                                           2. Check the suggested description         | |
| |                                           Choose an option for both people above     | |
| |                                           to see the suggested description.          | |
| +--------------------------------------------------------------------------------------+ |
|                                                                                          |
| Photo 2 of 2  ...                                                                        |
```

- The main photo's alt text is always the current description, so the photo itself shows the
  result. The second, smaller copy of each photo is gone.
- The static AltContext caption is removed: it showed the named answer before the visitor
  decided (HAI-01, HAI-12, CLM-05). The AltText.ai caption moves into the collapsed
  "How another tool describes this photo", with "For comparison only, not a benchmark.
  AltText.ai was given no names or keywords."
- Strength in words, no percentages anywhere, including the labels on the photo (HAI-08,
  AIPX-10).
- Names are answered per photo (option B). The evidence differs per photo: the right-hand match
  in the Coachella photo is weak. In the Tribeca photo, the saved score of 1 for the same name is
  not a match result. That face is the one the saved group started from (`isClusterAnchor` in
  `state.ts`), so it was compared with itself. The row says so instead of "Strong match" (UX-13;
  MLDATA-16, AIPX-10, CLM-04). Neither photo has a strong independent match for that name.
  One answer for both photos would carry the weak case over silently (HAI-08, HITL-14, HAI-17,
  CAL-10). The cost is four answers instead of two.
- Nothing in section 2 shows until both people in this photo have an answer: no buttons and no
  errors (FORM-05).

### C2. Right column of the card, desktop: both names answered (left), after Use (right)

```text
+-------------------------------------------+  +-------------------------------------------+
| Name the person on the right?             |  | Name the person on the right?             |
| (*) Use Katy Perry                        |  | (*) Use Katy Perry                        |
| ( ) Leave unnamed                         |  | ( ) Leave unnamed                         |
|                                           |  |                                           |
| 2. Check the suggested description        |  | 2. Check the suggested description        |
| Written by AI in advance from the photo,  |  | Written by AI in advance from the photo,  |
| the page it appears on, and the names     |  | the page it appears on, and the names     |
| you chose.                                |  | you chose.                                |
|                                           |  |                                           |
| Current description                       |  | Current description            <- updated |
| A man in a black suit and a woman in a    |  | Justin Trudeau and Katy Perry pose        |
| white dress pose together, smiling, in    |  | together on the red carpet at the         |
| front of a Tribeca Festival               |  | Tribeca Festival, standing in front ...   |
| step-and-repeat backdrop.                 |  |                                           |
|                                           |  |                                           |
| Suggested description                     |  | Suggested description                     |
| Edit anything that is wrong or that you   |  | Edit anything that is wrong or that you   |
| would not publish.                        |  | would not publish.                        |
| +---------------------------------------+ |  | +---------------------------------------+ |
| | Justin Trudeau and Katy Perry pose    | |  | | Justin Trudeau and Katy Perry pose    | |
| | together on the red carpet at the     | |  | | together on the red carpet at the     | |
| | Tribeca Festival, standing in front   | |  | | Tribeca Festival, standing in front   | |
| | of a backdrop with the event's logo.  | |  | | of a backdrop with the event's logo.  | |
| | Trudeau is wearing a black tuxedo ... | |  | | Trudeau is wearing a black tuxedo ... | |
| +---------------------------------------+ |  | +---------------------------------------+ |
| Only the demo image on this page changes. |  | Only the demo image on this page changes. |
|                                           |  |                                           |
| [Use this description]                    |  | [Use this description]  (dimmed)          |
| [Keep the current description]            |  | [Keep the current description]            |
|                                           |  |                                           |
|                                           |  | ✓ The demo image now uses this            |
|                                           |  |   description.                            |
+-------------------------------------------+  | [Undo this change]  <- focus              |
                                               +-------------------------------------------+
```

- One strong action, verb-plus-object labels (INT-05, INT-06). The current and suggested
  descriptions sit together before you commit (INT-07). Undo is right there (INT-09, A11Y-18),
  and the status is read out (A11Y-21).
- The origin line says the text was written by AI in advance: it is a proposal, not the answer
  (HAI-12, HAI-14).
- After Use, the old "This demo image already uses this text." is not shown next to the success
  status. Before, both lines showed at once.
- Keep the current description shows "✓ You kept the current description."
- Changing a name after editing this photo's description asks first (see D).

### D1. End of the page, desktop: after both photos are done

```text
+------------------------------------------------------------------------------------------+
| You checked both photos                                                                  |
| Tribeca Festival, New York, June 2026: uses the new description.                         |
| Coachella festival photo, 2026: kept the current description.                            |
|                                                                                          |
| Nothing was saved or published. Your changes clear when you reload.                      |
| In real use, you would review each new photo the same way.                               |
+------------------------------------------------------------------------------------------+

AltContext suggested these names and descriptions on 9-10 September 2026.
Nothing on this page compares faces.
```

- One line per photo, shown only when both photos are done (WRIT-37). No "Return to the draft"
  button.
- The dates are the real ones: the name suggestions ran on 10 September 2026 and the descriptions
  on 9 September 2026.

### D2. Dialogs: Start over (left) and changing a name after edits (right)

```text
+-------------------------------------------+  +-------------------------------------------+
| Start over?                               |  | Replace your edits?                       |
|                                           |  |                                           |
| This clears your name choices and         |  | Changing a name loads a new suggested     |
| edits, and puts back the original         |  | description for this photo. Your edits    |
| descriptions.                             |  | to it will be replaced.                   |
|                                           |  |                                           |
| [Keep my work]  [Start over]              |  | [Keep my edits]  [Change the name]        |
|   ^ focus                                 |  |   ^ focus                                 |
+-------------------------------------------+  +-------------------------------------------+
```

- Both ask first, and the safe button has focus (A11Y-18).
- After Start over: "✓ Started over. The original descriptions are back." beside the button,
  and focus moves to the first question.

### E. Suggested names, mobile 390 px: before (left) and after (right)

```text
+----------------------------------------+    +----------------------------------------+
| +------------------------------------+ |    | Photo 2 of 2                           |
| | CHOOSE NAMES                       | |    | Coachella festival photo, 2026         |
| | +--------------------------------+ | |    | (photo, credit, collapsed comparison)  |
| | | Coachella festival             | | |    |----------------------------------------|
| | | photo, 2026                    | | |    | 1. Check the suggested names           |
| | | (photo, 2 captions)            | | |    | AltContext compared each face with     |
| | | +----------------------------+ | | |    | reference photos from a list of        |
| | | | Names suggested by         | | | |    | people. Use a name only if you agree.  |
| | | | AltContext                 | | | |    | Not sure? Leave the person unnamed.    |
| | | | +------------------------+ | | | |    |----------------------------------------|
| | | | | +----+                 | | | | |    | +--+ Justin Trudeau   [Compare photos] |
| | | | | |crop|                 | | | | |    | |  | Strong match                      |
| | | | | +----+                 | | | | |    | +--+                                   |
| | | | | Justin Trudeau -       | | | | |    | Name the person on the left?           |
| | | | | 70.2% match            | | | | |    | ( ) Use Justin Trudeau                 |
| | | | | +--------------------+ | | | | |    | ( ) Leave unnamed                      |
| | | | | | Enlarge comparison | | | | | |    |----------------------------------------|
| | | | | +--------------------+ | | | | |    | +--+ Katy Perry       [Compare photos] |
| | | | | Saved suggestion:      | | | | |    | |  | (!) Weak match. Compare the       |
| | | | | Justin Trudeau         | | | | |    | +--+ photos before you use this name.  |
| | | | | v Compare the left     | | | | |    | Name the person on the right?          |
| | | | |   face and reference   | | | | |    | ( ) Use Katy Perry                     |
| | | | |   photos               | | | | |    | ( ) Leave unnamed                      |
| | | | | [.][.][.]  <- 24px     | | | | |    |----------------------------------------|
| | | | | All 3 reference        | | | | |    | 2. Check the suggested description     |
| | | | | photos are shown.      | | | | |    | Choose an option for both people       |
| | | | | Name choice for the    | | | | |    | above to see the suggested             |
| | | | | left face              | | | | |    | description.                           |
| | | | | ( ) Use Justin         | | | | |    +----------------------------------------+
| | | | |     Trudeau            | | | | |      ^
| | | | | ( ) Leave this person  | | | | |      16 px from the screen edge to text
| | | | |     unnamed            | | | | |
| | | | +------------------------+ | | | |
| | | +----------------------------+ | | |
| | +--------------------------------+ | |
| +------------------------------------+ |
+----------------------------------------+
  ^ ^ ^ ^ ^
  5 edges before the button text
```

- Before: the text column is about 140 px wide and starts about 124 px from the screen edge.
  Every name card (including `#guided-name-tribeca-left-enlarge`) sits inside five edges.
  Cause: the "Cards rule" in `_theme-darce-components.scss` gives media-card, scenario, faces
  and face__card each a border, 24 px padding and a dither shadow, and the workspace section
  adds one more.
- After: one surface. 16 px gutter, one divider between rows, no nested borders, padding or
  shadows (LAY-06, A11Y-29, UI-03, PERC-01). The text column is 358 px wide.
- Each row: `padding: 12px 16px`, `min-height: 64px`, grid `48px 1fr auto` (crop, name and
  strength, Compare photos). Compare photos and each answer row are at least 44 px tall
  (A11Y-14).

### F. Mobile 390 px: hero (left) and a description after Use (right)

```text
+----------------------------------------+    +----------------------------------------+
| Home  Case study↗                      |    | (*) Use Katy Perry                     |
|                                        |    | ( ) Leave unnamed                      |
| DEMO                                   |    |----------------------------------------|
| YOU DECIDE WHO IS                      |    | 2. Check the suggested description     |
| NAMED IN EACH PHOTO                    |    | Written by AI in advance from the      |
| DESCRIPTION.                           |    | photo, the page it appears on, and     |
|                                        |    | the names you chose.                   |
| See how AltContext suggests image      |    |                                        |
| descriptions (alt text) and possible   |    | Current description         <- updated |
| names, and how you decide which names  |    | Justin Trudeau and Katy Perry pose     |
| to use.                                |    | together on the red carpet at ...      |
|                                        |    |                                        |
| The names and descriptions were        |    | Suggested description                  |
| suggested by AI in advance. Your       |    | Edit anything that is wrong or that    |
| changes stay on this page and clear    |    | you would not publish.                 |
| when you reload.                       |    | +------------------------------------+ |
|                                        |    | | Justin Trudeau and Katy Perry      | |
| [           Start the demo           ] |    | | pose together on the red carpet    | |
| [        Read the case study↗        ] |    | | at the Tribeca Festival, ...       | |
|                                        |    | +------------------------------------+ |
| What you'll do                         |    | Only the demo image on this page       |
| 1. Check the names suggested for each  |    | changes.                               |
|    photo.                              |    | [        Use this description        ] |
| 2. Read and edit the suggested         |    | [    Keep the current description    ] |
|    description.                        |    |                                        |
| 3. Use it on the demo image, or keep   |    | ✓ The demo image now uses this         |
|    the current one.                    |    |   description.                         |
+----------------------------------------+    | [Undo this change]  <- focus           |
                                              +----------------------------------------+
```

- The hero keeps its source order on mobile: heading, intro, note, buttons, then the plan.
  Start stays near the top.
- Full-width buttons on mobile. The status and Undo sit right under them.

### G. Compare photos dialog, mobile 390 px: before (left) and after (right)

```text
+----------------------------------------+    +----------------------------------------+
| (page dimmed behind)                   |    | +------------------------------------+ |
| +------------------------------------+ |    | | Compare with photos of     [Close] | |
| | Enlarged comparison                | |    | | Justin Trudeau                     | |
| | Compare the left face and          | |    | |                                    | |
| | reference photos                   | |    | | In this photo                      | |
| | +------------------------+         | |    | | +--------------+                   | |
| | |                        |         | |    | | |              |                   | |
| | |                        |         | |    | | |              |                   | |
| | |  crop from this photo  |         | |    | | |   ~159 px    |                   | |
| | |                        |         | |    | | |              |                   | |
| | |                        |         | |    | | |              |                   | |
| | |                        |         | |    | | +--------------+                   | |
| | +------------------------+         | |    | |                                    | |
| | Justin Trudeau - 89.4% match       | |    | | Reference photos of Justin Trudeau | |
| |      [.][.][.]  <- 24 px each      | |    | | +--------------+  +--------------+ | |
| | All 3 reference photos are shown.  | |    | | |              |  |              | | |
| |                 [Close comparison] | |    | | |              |  |              | | |
| +------------------------------------+ |    | | |   ~159 px    |  |   ~159 px    | | |
| (page dimmed behind)                   |    | | |              |  |              | | |
+----------------------------------------+    | | |              |  |              | | |
                                              | | +--------------+  +--------------+ | |
                                              | | © European        Lea-Kim          | |
                                              | | Union, 2025, EU   Chateauneuf, CC  | |
                                              | | reuse licence,    BY-SA 4.0,       | |
                                              | | resized           resized          | |
                                              | | +--------------+                   | |
                                              | | |              |                   | |
                                              | | |              |                   | |
                                              | | |   ~159 px    |                   | |
                                              | | |              |                   | |
                                              | | |              |                   | |
                                              | | +--------------+                   | |
                                              | | Jonathan Miranda /                 | |
                                              | | Presidencia de la República        | |
                                              | | del Ecuador, public domain         | |
                                              | |                                    | |
                                              | | All 3 reference photos are shown.  | |
                                              | +------------------------------------+ |
                                              +----------------------------------------+
```

- Before: the reference photos are 24 px wide on mobile (48 px on desktop). Cause: the gallery
  images in `_guided-prototype.scss` are sized with the spacing token `--acx-space-80`, which is
  48 px on desktop and 24 px at 768 px and below (`js/guide/_theme-darce.scss`).
- After: the crop from this photo comes first, then every reference photo at the same size, two
  per row. Dialog `width: min(100vw - 32px, 40rem)`, 16 px padding, 8 px gap, so each photo is
  about 159 px wide at 390 px. Same-size photos side by side are easier to compare (VIZ-16,
  HAI-17, HITL-14).
- The credit shows under each reference photo; today it is only in screen-reader text. CC BY
  and BY-SA licences expect visible credit.
- Close is at least 44 px (A11Y-14). Escape also closes, and focus returns to the Compare photos
  button that opened it (A11Y-11). Katy Perry's dialog keeps "3 of 5 reference photos are
  included in this demo."
