# Asymmetric Typography (Jan Tschichold) — distilled

> **Source**: Jan Tschichold, *Asymmetric Typography* (Faber & Faber / Cooper & Beatty, 1967 English ed.; integral translation of *Typographische Gestaltung*, Basle 1935; tr. Ruari McLean, author-approved) · extracted from `../asymmetric-typography.txt` · distilled 2026-07-09 (spec v1)
> **Contributes**: This lane’s closest **grid-design / composition** source. **Asymmetry as information hierarchy** (not decoration); **active white space** as a design element equal to type; **off-centre axis** and unequal-margin rules; **contrast of size / weight / position / silhouette** as the layout engine; **grouping** (sense-first units, three-group default); when **centred / decorative typography** is correct; type and colour only as they serve **compositional clarity**. Named concepts: **asymmetric typography**, **new / functional typography**, **decorative typography**, **centred / axial typography**, **active white space**, **tension**, **right position**, **grouping**, **unequal intervals**, **contrast engine**, **form–content harmony**, **spiritual content beyond utility**.

## Chapter map

- ch-1 — Scope boundary (composition lane, not eng UI)
- ch-2 — Historical problem: why centred form failed hierarchy
- ch-3 — Meaning and aim of new / functional typography
- ch-4 — Two systems: asymmetry vs symmetry (when each is correct)
- ch-5 — The contrast engine (size, weight, position, silhouette)
- ch-6 — Active white space and the “right position”
- ch-7 — Off-centre axis, margins, and reading direction
- ch-8 — Grouping: three units, unequal intervals, sense order
- ch-9 — Lines, emphasis, measure, and paragraph articulation
- ch-10 — Type sizes, headings, mixtures (compositional use only)
- ch-11 — Rules, colour, paper as compositional instruments
- ch-12 — Jobbing, posters, books: application patterns
- ch-13 — Abstract art method: study materials, forge contrast
- pipeline — Layout decision pipeline (testable composition checks)
- Decision rules (summary)
- Anti-patterns
- Applicability & exemptions
- Candidate lexicon rows

---

## ch-1 — Scope boundary (composition lane, not eng UI) {#ch-1}

This distillate feeds **design-aesthetics heuristics** for **layout composition**. It does **not** restate engineering UI mechanics already owned by Refactoring UI / eng lexicon: predefined type scales, spacing-signals-grouping as product-UI primitives, weight-over-size as default UI hierarchy recipe, shade ramps, elevation systems, WCAG floors. Keep only the **compositional / identity / typographic-system** half; tag borders `↔ eng UI-*`.

| This lane owns | Hand off to eng lexicon |
|---|---|
| Asymmetry vs symmetry as **layout ideology** | Component grids, 4/8-pt spacing tokens |
| Active white space as **compositional mass** | Density tokens for product chrome |
| Off-centre axis, unequal margins, group intervals | Responsive column primitives |
| Contrast of size/weight/position as **hierarchy engine** | Default body/UI type steps |
| When centred work is culturally/functionally correct | Interaction states, a11y floors |
| Type *character* and mixture for voice + contrast | Font loading, scale generation |

**Era note (mandatory):** Written 1935 (English 1967). Sans-as-universal, letterpress/machine-composition constraints, and hard rejection of ornament are **period positioning**. Extract **falsifiable composition rules**; do not prescribe 1930s production tech or “only sans forever.” McLean’s foreword and Tschichold’s 1965 footnote: asymmetry is **one of two** valid systems, not the sole gospel of youth.

↔ eng UI: “leading,” “measure,” “weight contrast” here are **print-composition hierarchy** lessons, not product type-token recipes.

---

## ch-2 — Historical problem: why centred form failed hierarchy {#ch-2}

Until ~1920, almost all typography was **centred / axial**. Exceptions: some pre-1500 pages; brief 1895–1905 experiments. **Decorative typography** = axial work where **pure form precedes meaning of words**.

**Diagnosis of the old system:**

| Symptom | Cause | Compositional cost |
|---|---|---|
| Jobs look alike despite different purposes | Everything centred + grey uniform colour | No individual solution |
| Important matter cannot stand out | Bold/extra bold treated as ugly; grey page ideal | Hierarchy suppressed |
| Wording invented to fit layout | Renaissance symmetry as façade | Content subordinated to ornament |
| Ornament required for distinction | Centred layouts share the same plan | Decoration = fake individuality |
| Block / box styles as “order” | Anxiety for any order (pre-1912) | Denial of organic reading form |

**Architecture parallel (keep the signal mechanic):** Renaissance façades put windows as ornament; rooms behind forced to fit. In type, rigid centring makes a good *sense* solution “infinitely more difficult.”

**Didot / Bodoni / Brun lesson:** classical masters cared about line length *and* page “colour” (density of black). Imitators substituted letter-spacing and destroyed word shape. **Rule:** do not fake rhythm by letter-spacing lower case to fill a silhouette.

**Incunabula vs Renaissance books:** early books closer to new typography — functional organization by size contrast and natural page endings — than vase-symmetry title-pages. Gutenberg’s short Latin lines (abbreviations allowed) are **not** a modern measure model.

**Poeschel revival:** classical types good; using them only in period costume is feeble. **Rule:** classical faces allowed under **new arrangement rules**, not museum restaging.

Scenario → lesson: scientific books followed classical French rules but drifted grey and lifeless; Expressionism then chaos with no rules. **Lesson:** the cure is not more ornament or more novelty faces — it is **rules that make hierarchy and individual purpose visible**.

---

## ch-3 — Meaning and aim of new / functional typography {#ch-3}

**Core purpose:** more matter is printed; readers will not read what is troublesome. Important must **stand out**; unimportant must be **subdued**. Distinctions cannot live inside uniform grey + forced centring.

**Unsymmetrical arrangements** are more flexible and better suited to practical *and* aesthetic needs when jobs have different natures and purposes.

**Success criteria (all three required):**

1. **Fitness for purpose** — logical layout from understood manuscript.
2. **Technical integrity** — producible by available means (hand and machine under same rules).
3. **Beauty** — visual/aesthetic decisions within sense and purpose; not ornament bolted on.

> Typography must be not only suitable and easy to produce, but also **beautiful**. Within limits of sense and purpose, **purely visual decisions** still must be made.

**Functionalism ≠ utilitarianism only.** “Fitness for purpose” is prerequisite; **spiritual content** and a new beauty bound to materials make the work art. Plain utility and modern design remain two different things.

**Rhythm and proportion** matter more once ornament is stripped: every element takes new importance; interaction of visual relationships drives the general effect. Harmonious relation of parts — always different per job — yields **individual yet pleasing** appearance integrated with meaning.

**Design process:** read manuscript first (sense); exact sketches for complex jobs; work **detail → whole** for unity; simpler means demand more care on each element and white space; proof on right paper/ink (asymmetry makes impression material).

**Machine constraint as virtue:** design must be producible; complete stick freedom often harms. Do not invent layouts that require faking copy length to fit a silhouette.

---

## ch-4 — Two systems: asymmetry vs symmetry (when each is correct) {#ch-4}

**Binary (McLean / late Tschichold):** all typography is either **asymmetrical** or **symmetrical**. Asymmetry is not the only way — it is one of two. Asymmetric work is **harder than it looks**; when successful, highly satisfying.

| System | Strengths | Weaknesses | Prefer when |
|---|---|---|
| **Centred / decorative** | Easy arrangement of fortuitous line lengths; compositor can swap sizes without destroying plan | Inflexible; jobs look alike; needs ornament for distinction; pure form before sense; wording often forced | Contents are conventional/classical; tradition expected; form must harmonize with conservative content; short ornamental identity pieces where axial dignity is the brief |
| **Asymmetric / functional** | Hierarchy and individual purpose; flexible placement; contrast engine; active white space | Harder craft; bad execution looks accidental or fashion-only | Multi-level information; jobbing, ads, modern books/identity; meaning must drive structure; contemporary voice required |

**Form–content harmony (hard rule):**

- Do **not** put an asymmetric title-page on a conventionally designed book.
- Do **not** “dress modern” a book whose contents and interior are conventional — traditional typography is then correct.
- Form and contents should harmonize.

**Author’s 1965 caveat:** harsh rejection of the previous style was a condition for creating a different one; he no longer entirely agrees with every 1935 blast — but the **principles of asymmetric composition remain sound**.

**Test:** if the layout’s hierarchy would still be clear with ornaments removed and centring forbidden, you are in the asymmetric system. If hierarchy depends on border ornament or vase silhouette, you are in decorative centring — own that choice deliberately.

---

## ch-5 — The contrast engine (size, weight, position, silhouette) {#ch-5}

**Master law:** the strongest effect of any typographic design is when **contrasts are most clearly defined**. Significance of contrast is the basis of all modern designing.

**Contrast dimensions (compositional):**

| Dimension | Weak (anti) | Strong (prefer) |
|---|---|---|
| Size | Adjacent sizes too close (e.g. 9/10, 14/16) | Clear steps; limit families of sizes |
| Weight | Unity-of-type grey; one weight only | Semi-bold / bold / light as hierarchy (not letter-spacing) |
| Position | Everything centred or edge-aligned by habit | Off-centre, unequal margins, intentional opposition |
| Silhouette | Repetition of same shape | Long after short; single-line group next to 2–3 line group |
| Density | Even grey | Closely knit vs loosely knit parts — **tension** |
| Form family | Random mixes; shaded 3D types | Planned mixtures within limits (ch-10) |

**Avoid repetition or similarity of silhouette.** If top has a one-line group, next group should prefer two or three lines. Long shapes followed by short; heavy by light.

**Tension, not accident:** intervals and positions intentional. Absolute weight of contrasts is less important than the **tension they create**.

**Visiting-card micro-lesson:** an ordinary centred card is neutral, expresses nothing; place the name **off-centre** and the reader experiences new form — becomes aware white space plays a part, that proportion and contrast are being used.

**Double contrasts:** heavy rules with light types; large spaces between long and short lines; reverse (white on black) against normal black on white; boxed vs ragged groups; circle-isolated unit vs free groups.

**Cap on complexity:** too many units cannot be absorbed at a glance. Prefer **three groups** (ch-8). Six type styles in one job is a hard upper bound and should be rare.

↔ eng UI: do not import this as “always bigger = primary button hierarchy only.” Here contrast is **full-page composition**, including position and white mass.

---

## ch-6 — Active white space and the “right position” {#ch-6}

**All typography is arrangement of elements in two dimensions.** Right placing of words and lines is as important as significant contrasts — integral to them.

**Active white space:** space is not leftover. Every shape exists only **in relation to the space around it**. The same line has a totally different effect in large vs small white area. Placing that works in one frame may fail in another.

**Right position:** there is a “right” position for every shape on every occasion. Finding it *is* the job. Not one unique diagram forever — several significant arrangements exist when multiple elements are present; accidental lining-up of equal elements is the boring failure mode.

**Abstract arrangement lessons (Tschichold’s six diagrams, verbalized):**

| Pattern | Compositional reading |
|---|---|
| (a) Three elements stacked, equal | Boring, visually meaningless — no tension |
| (b) Strict horizontal–vertical geometry | Ordered tension via axis discipline |
| (c) Elements follow page outline but freer mutual relation | Outline-aware without rigid grid lock |
| (d) Line+circle tight; square opposed to outline | Cluster + opposition |
| (e) Square+line united against outline | Coalition of elements vs field |
| (f) Elements strike different directions; circle calm | Multi-vector energy with one rest element |

**Rules for space between groups:**

1. Intervals **must be unequal** (distinguishable) — equal intervals lose tension.
2. Intervals must still **accord with coherence** of text parts (sense governs closeness).
3. Leading **inside** a group must relate to intervals **between** groups — one symphony.
4. Do **not** centre an asymmetric layout on its paper or ad area (narrow columns: rare exception). Margins left and right **can and should be distinctly different**.

**White space around type affects spacing:** lines in much white, or leading > body, may need slightly wider word-spacing so thick spacing does not look tight.

**Posters:** proper leading + white space make the sheet comprehensible at a glance; word-spacing greater than book work (distance reading).

**Books:** enough white between chapters (~head margin or more) avoids blockish compact effect; moving folios out from type area makes paper field visible and type “in suspense.”

---

## ch-7 — Off-centre axis, margins, and reading direction {#ch-7}

**Principal rule of the new book (and by extension jobbing):** **nothing is centred** — not headings, chapter titles, folios, “End,” or imprint — when working in the asymmetric system.

**Reading direction locks alignment choices:**

| Case | Rule |
|---|---|
| Lines of equal importance, different lengths (lists, contents, verse) | Align **left**; right-aligning equal lines is wrong for LTR scripts |
| Why | Eye returns to start; if next line does not begin underneath, disturbance compounds |
| Lines of different importance / different sizes | Not free whim; left-aligning lines generally read as more important than right-aligning — **unless** right-aligners are bolder and reverse the impression |
| Unrelated lines, different sizes | May align right |
| Marginal notes | Exception cases allowed |

**Asymmetry forbids:** centring an asymmetric composition on the sheet. **Margins:** left ≠ right by intention; exact amounts = trained taste (no formula replaces judgment).

**Book type area (stable classical margin progression, still useful):** back narrowest; head, fore-edge, foot progressively larger; foot clearly wider than fore-edge. Sensitive proportion within that rule separates ordinary from well-designed. Deep type area with starved foot is a common fault.

**Folio placement as composition tool:**

| Placement | Effect |
|---|---|
| Close to type foot, aligned or indented | Folio joins type mass; white border around type; paper field weak |
| Far from type area | Paper area becomes visible; column “in suspense”; margins emphasized |

Headings in bolder type may carry bold folios. Large formats: double columns often more readable than long single measure; if type moves out from back, reduce other margins; keep folios outside type, not jammed into enlarged back.

**Oblique lines:** allowed sparingly for eye-catch; single long lines more effective than short words (oblique otherwise unnoticed). Horizontal remains the default of reading and setting.

**Title-page in asymmetric books:**

- Visual harmony with following pages.
- Foot generally on last line of normal full page.
- Not farther from the back than normal; not wider than page measure; depth may vary.
- Register title/heading with first text page for rhythm.
- Asymmetric title without modern interior = incoherence (ch-4).

---

## ch-8 — Grouping: three units, unequal intervals, sense order {#ch-8}

**Grouping is new relative to conventional loose connection of parts.** Modern reading needs quick, exact transfer of words — sharp distinctions by sense.

| Rule | Spec |
|---|---|
| Default group count | **Three** groups |
| Two groups | Only very short, simple copy |
| Four groups | Only very long copy — four already requires counting |
| Comprehension test | Groups defeat purpose if they must be counted rather than absorbed at a glance |
| Separation | Each unit distinct; coherence not spoiled by a neighbour too close |
| Sequence | Placement below/beside follows **common sense of reading order** |
| Intervals | Unequal; sense-coherent; related to internal leading |

**Line length in multi-line headings (sense first):** length depends on sense and reading pauses, not decorative equal lengths. First line may be longer or shorter than second. Avoid word breaks. **Equal-length lines in a heading** — even accidental — are unsightly; fix with slight spacing change; never introduce intentionally for decorative block look.

**Words connected by sense** stay together even in large titles (“The New Typography” not “The New / Typography” when avoidable).

**Indentation (paragraph articulation):**

- Full-out-left headings do **not** imply abolishing paragraph indents.
- Indent (~1 em, more for very long heavily leaded lines) is best technical and aesthetic paragraph mark.
- No indent at chapter start if unnecessary; no indent when blank line separates paragraphs or only one paragraph.
- Extra space between paragraphs is **not** a substitute for indent in good book/magazine work (register matters); newspapers/cheap pamphlets only.
- Avoid widows (esp. page heads); early printers shortened pages to avoid them — head more noticeable than foot.
- Do not right-space last lines of paragraphs as fake indent — eye searches, white gaps disturb.

---

## ch-9 — Lines, emphasis, measure, and paragraph articulation {#ch-9}

**Measure (compositional readability, not eng scale tokens):**

| Observation | Action |
|---|---|
| < ~5 words justified | Prefer unjustified (verse-like fixed spacing) — justification cannot space well |
| > ~12 words, little leading | Hard to read |
| Aim | ~**8–10 words** per line as general target |
| Leading vs word space | Apparent interline space ≥ interword space; solid setting rarely clear (black-letter exception) |
| Sans solid | Especially gains from strong leading |

**Emphasis in the line (hierarchy without size thrash):**

| Context | Prefer | Avoid |
|---|---|---|
| Body | Italic (slight); semi-bold (key); occasionally both | Changing type size inside the line |
| Display | Italic / semi-bold / bold; same size | Letter-spacing for emphasis |
| Most important display only | One larger word + perfect alignment; **never more than two sizes in one line** | Size changes as habit |
| Caps | Rare; bold display preferred; if caps, faultless letter-spacing | Unspaced caps; letter-spaced lower case for fill |

**Word unit:** correctly set word is starting point. Letter-spacing lower case is **unacceptable** in new typography — harms legibility, beauty, economy; do not use to force predetermined line length. Layouts that depend on exact predetermined lengths rarely look natural.

**Close spacing** is the rule; optically equal word-spacing in headings; no decorative em-space after periods (nineteenth-century remnant).

↔ eng UI: measure/leading numbers are **composition tests for reading blocks and posters**, not a mandate to replace product design tokens.

---

## ch-10 — Type sizes, headings, mixtures (compositional use only) {#ch-10}

**Order of determination:** (1) format and purpose, (2) sense of contents, (3) feeling for visual relationship of sizes.

| Constraint | Rule |
|---|---|
| Count of sizes | Generally **≤3**; two for short jobs; four only for complicated matter |
| Clear difference | Do not pair near-identical sizes |
| Headings | Same size OK if heavier weight; different face for heads should also be heavier |
| Two bolds close | Never two different sizes of same bold face close together when sizes are near |
| One body + one display | Prefer for over-all appearance; fight dullness via contrast and space, not font zoo |
| Caps vs bold | Display prefers bold weight over capitals for contemporary character |

**Mixtures that create contrast (allowed patterns):**

- Weights within a family (semi-bold sans + ordinary sans; bold roman + ordinary).
- Size + weight stacked (e.g. large bold + small ordinary).
- Contrasting forms (Egyptian heads with roman text; black-letter with script) — **one** contrasting face with roman–italic partnership.
- Lettering vs type (freedom vs precision).

**Hard bans / cautions:**

- Sans + Egyptian together: **no**. Egyptian display → roman text. Sans text → bolder sans display, never Egyptian.
- Do not mix different sans designs (e.g. Venus + Futura).
- Shaded / three-dimensional types contradict **one-plane** character of new typography.
- Condensed faces: seldom needed; overused.
- Lower-case-only orthography: not recommended as abolition of caps.

**Type choice and voice:** effect of unusual faces must not conflict with content character — but do not pedantically costume type to topic. Classical romans remain valid under new arrangement rules. Sans is historically argued as all-purpose for the period; skill required — unskilled sans disappoints. **Era-correct use today:** treat sans-as-default as a **modernist signal**, not a forever law.

**Planned range (printer / brand type kit):** extend families with italics and bolds deliberately; do not add faces by customer whim. First kit historically: multi-weight sans, classical roman + italic + medium bold, fat face, then Egyptian/script.

---

## ch-11 — Rules, colour, paper as compositional instruments {#ch-11}

### Rules (lines)

| Use | Prefer | Avoid |
|---|---|---|
| Tables | Fewest rules; medium under heads if columns wide; vertical only if misread risk | Net of boxes; thick-and-thin 1880 style; >2 rule kinds |
| Layout join/separate | Medium and fine rules; thin rule often “key to whole page” | Heavy-rule fashion of early new typography as default |
| Underline | Rare; light/medium faces only if at all | Underline bold with thick rule |
| Asymmetric work | Simple lines, simple borders, screens | Thick-thin rules; rule-combination borders (belong to centred system) |

### Colour (meaning + restraint)

| Role | Mechanic |
|---|---|
| Emphasis | Red stirs; yellow aggressive; blue cool/retiring but livelier than black as bright colour |
| Structure | Separate/distinguish parts of prospectus or book |
| Mood | Overall note harder to define — proof on real paper |
| Restraint | Second colour more powerful when **sparing**; top type + later rule beats sprinkle-everywhere |
| Register | Avoid two colours in one line — imperfect register unsightly; often bold black achieves goal |
| Area physics | Flat colour field ≠ type in same ink; same ink different area sizes → different effect |
| Palette | Primary lively colours **or** grey/sepia/black — both valid |

↔ eng UI: no shade-ramp recipes; colour here is **semantic emphasis and compositional thrift**.

### Paper / material contrast

Contrast of stocks (glossy/dull/rough; cartridge vs coated plates) is a compositional resource. Avoid false materials (fake deckles). Halftone quality is decisive when photography is used.

---

## ch-12 — Jobbing, posters, books: application patterns {#ch-12}

### Jobbing / advertisements

- Hierarchy by weight and grouping, not ornament frames.
- One body + one display; sketches for complexity.
- Short ads: optional hanging-indent patterns for emphasis.
- Tables: pleasure when rules minimized; repeat words not ditto marks.

### Posters

- Comprehensible at a glance: leading + white space.
- Normal-weight text types can contrast with bold display (not bold-only).
- Large wood letters often need letter-spacing (body-full cuts); smaller well-spaced may beat larger cramped.
- Greater word-spacing for distance.
- Flat tints, coloured paper, occasional historical face for surprise — sparingly.

### Books (asymmetric system)

| Element | Rule |
|---|---|
| Unity | Binding, jacket, interior one hand/spirit |
| Title-page | Expresses interior style; asymmetric only if book is |
| Headings / folios | Off-centre; shared type family/weights |
| Chapters | White ≥ ~head margin |
| Initials | Seldom; deep insets pull back to block/baroque compact |
| Images | Width = measure, half, or golden-mean to measure; not centred; captions smaller; no type wrap around blocks |
| Bleeds | ≤2 per page (prefer 1) |
| Jacket | Book’s poster; modern jacket on conventional interior fails unity |
| Spine | Lettering required even on thin booklets |

**Photography / drawing:** pictures often faster than words. Photograms, negatives, montage OK if clarity holds. Subordinate type + photo + line to the whole.

---

## ch-13 — Abstract art method: study materials, forge contrast {#ch-13}

**Genealogy:** new typography and modern architecture both descend from **non-representational / abstract painting**, not from each other. Do not import architectural severity without its lyric quality; type and architecture have different laws.

**Working method shared with abstract art:**

1. Scientific study of available materials/elements.
2. Using **contrast**, forge them into an entity.
3. Elements clearly defined **and** clearly related.
4. Order out of simple contrasting parts — stimulus from abstract painting, not literal copy.
5. Stay inside technique and purpose or descend into **formalism**.

**Richness of simplicity:** after training, simplicity’s “intoxicating qualities” appear. First: exact knowledge of materials, processes, elements. Then contrast.

**Elements toolkit (beyond letters):** lines, surfaces, frames, stripes, circles, dots, triangles, arrows; reverse; overprint transparency; screens/tints; rules at angles/weights.

**Success definition:** use familiar material so it appears completely new — without abandoning legibility or technical integrity.

---

## pipeline — Layout decision pipeline (testable composition checks) {#pipeline}

Use this sequence when a layout decision must be justified or reviewed.

```
1. SYSTEM CHOICE
   □ Is content contemporary / multi-level hierarchy? → asymmetric
   □ Is content conventional / tradition-required? → centred OK
   □ Do form and content agree? (no modern shell on classical body)

2. SENSE STRUCTURE
   □ Manuscript understood; important vs subdued named
   □ Groups = sense units (default 3); reading order left-to-right respected
   □ No decorative line breaks against sense

3. CONTRAST ENGINE
   □ One clear dominant vs subordinates (size and/or weight and/or position)
   □ Silhouettes not repetitive
   □ Weights carry emphasis; not letter-spaced lower case; not size thrash in-line

4. SPACE
   □ White is placed, not residual
   □ Group intervals unequal + sense-coherent
   □ Asymmetric layout not re-centred on the field
   □ Left/right margins intentionally unequal when asymmetric

5. AXIS & ALIGNMENT
   □ Equal-importance lines left-aligned (LTR)
   □ Nothing centred by default under asymmetric system
   □ Folios/heads position chosen for paper-field effect, not habit

6. THRIFT OF MEANS
   □ ≤3 type sizes typical; one body + one display
   □ Second colour sparse if used
   □ Rules minimal; no thick-thin ornament system
   □ Producible without faking copy to fit silhouette

7. UNITY
   □ Jobbing piece / poster / book parts share one composition logic
   □ Beauty + fitness + technical integrity all present
```

**Pass test:** cover the brand mark — hierarchy and rhythm still read. Fail test: remove ornaments and the page becomes grey mush or random scatter.

---

## Decision rules (summary)

| Trigger (observable in mockup / brief / proof) | Rule | Rationale | Src |
|---|---|---|---|
| Multi-purpose jobs all look the same under centre+grey | Switch to **asymmetric hierarchy**: important out, unimportant subdued | Centring + grey cannot differentiate purpose | ch-2, ch-3 |
| Brief mixes modern shell with conventional content | Enforce **form–content harmony**; pick one system | Mismatched systems read as costume | ch-4 |
| Layout is “asymmetric” but re-centred on the artboard | Stop; **unequal margins**; do not centre asymmetric compositions | Centring cancels the system | ch-6, ch-7 |
| Equal gaps between all content blocks | Make **intervals unequal** but sense-coherent | Equal intervals kill tension | ch-6, ch-8 |
| >4 competing units at a glance | Regroup to **~3 sense groups** | Four+ must be counted, not absorbed | ch-8 |
| Hierarchy relies on borders/ornament | Replace with **weight/size/position contrast** | Ornament fakes individuality in centred work | ch-2, ch-5 |
| Everything same size/weight | Force **contrast engine** (size and/or weight and/or silhouette) | Strongest effect when contrasts clearly defined | ch-5 |
| Silhouettes repeat (all one-line blocks) | Alternate long/short, 1-line vs 2–3-line groups | Avoid similarity of silhouette | ch-5 |
| Equal-importance list right-aligned (LTR) | **Left-align**; eye returns to start | Reading direction is not optional | ch-7 |
| Heading lines forced to equal length | Break by **sense**; avoid intentional equal lengths | Decorative equality is unsightly | ch-8 |
| Letter-spacing body/display lower case to fill width | Forbid; redesign so length is not predetermined | Destroys word shape; unnatural | ch-9, ch-2 |
| Emphasis by size changes inside a line | Prefer **italic/semi-bold/bold** same size; ≤2 sizes if any | Size thrash is compositor-hostile and noisy | ch-9 |
| >3 type sizes or font zoo | Cap sizes; **one body + one display** | Too many sizes seldom succeed | ch-10 |
| Sans heads with Egyptian text or vice-mixing bans | Respect **mixture bans** (no sans+Egyptian) | Form clash without hierarchy gain | ch-10 |
| Second colour everywhere | Use **sparingly** for emphasis structure | Restraint increases power | ch-11 |
| Tables look like nets | Remove rules until misread risk forces them | Fewer rules = clearer + better looking | ch-11 |
| White space is leftover empty | Treat as **active mass**; find **right position** per field | Shape only exists relative to space | ch-6 |
| Poster unreadable at distance | Increase leading, word-space, glance-group clarity | Distance reading needs looser space | ch-12 |
| Book title modern, interior classical (or reverse) | Unify system across title/body/binding/jacket | Unity is the book achievement | ch-12, ch-4 |
| Composition copies abstract art shapes literally | Copy **method** (materials study + contrast), not motifs | Formalism if purpose abandoned | ch-13 |
| Utility satisfied but page lifeless | Require **beauty + tension**, not utilitarianism alone | Spiritual content beyond fitness | ch-3 |
| Symmetry chosen without reason | Allow when tradition/content demand; else asymmetry for hierarchy | Two systems, deliberate choice | ch-4 |

---

## Anti-patterns

| Name | Detection cue | Fix |
|---|---|---|
| **Grey page** | Uniform colour; bold forbidden; no hierarchy | Weight/size contrast by sense |
| **Centred costume** | Everything axial; ornaments for “difference” | Individual asymmetric solution or own decorative system honestly |
| **Block layout** | Text forced into filled rectangle silhouette | Natural endings; sense line lengths; reject box as false order |
| **Predetermined measure fetish** | Design depends on exact word lengths | Flexible sizes/weights; natural line ends |
| **Letter-space fill** | Tracking used to hit width or “elegance” | Intact word shapes; redesign structure |
| **Re-centred asymmetry** | Off-centre group then whole block centred on page | Unequal field margins; true offset |
| **Equal-interval stack** | Rhythm of identical gaps | Unequal distinguishable intervals |
| **Group soup** | Many units, no glance structure | Three-group default |
| **Silhouette monotony** | All blocks same shape/line count | Alternate silhouettes |
| **Size thrash line** | Multiple sizes in one line as habit | Same-size weight emphasis |
| **Font zoo** | Many faces/sizes without plan | One body + one display; ≤3 sizes |
| **Sans–Egyptian mash** | Both in one job | Choose one display strategy |
| **Thick-thin nostalgia** | Shaded rules/borders on modern asymmetric work | Simple one-plane rules |
| **Colour confetti** | Second colour sprinkled | Sparse structural colour |
| **Modern jacket / old book** | Cover contemporary, interior unreconstructed | Full-system unity |
| **Formalism** | Pretty abstract without legibility/purpose | Return to manuscript sense + technique limits |
| **Ornament individuality** | Borders/rules as only brand difference | Structure and type contrast as identity |
| **Right-align LTR lists** | Contents/verse mirrored for “design” | Left align equal lines |

---

## Applicability & exemptions

| Applies strongly | Apply lightly / exempt |
|---|---|
| Editorial, marketing, identity systems, posters, packaging faces, pitch decks with hierarchy | Dense data-product UI chrome already tokenized in eng lexicon |
| Brand layout reviews, campaign systems, publication design | WCAG contrast floors, focus states, responsive engineering |
| Choosing asymmetric vs classical identity language | Legal documents / academic styles mandating tradition — **centred may be correct** |
| Information hierarchy in mixed type+image | Icon grids and component libraries (eng) |
| When “modernist / international style” signal is intended | When heritage/classical signal is the brief — do not force asymmetry |

**Exemptions inside the book’s own logic:**

- Centred table headings when enclosed in rules.
- Narrow columns may force near-centring occasionally.
- Classical book measure/margins largely remain; asymmetry mainly repositions heads/folios/title.
- Black-letter may sit solid.
- Poetry/lists: left alignment is functional, not “old-fashioned centring.”
- Author later accepts symmetry as co-equal system — do not use 1935 polemic to ban all axial work.

**False-positive guard:** “More white space” is not automatically Tschicholdian. White must be **positioned with unequal tension and sense grouping**. Empty luxury margin without hierarchy is not active white space.

**Contra / adjacency:**

- ↔ eng UI-\*: spacing and type scales as product systems — here space/type are **compositional hierarchy**.
- ↔ paula-scher-design: Scher scale drama and big-type identity align with contrast engine; Scher’s eclectic historic mashups may **contra** Tschichold’s mixture bans — keep both as judgment by brief.
- ↔ design-indaba-dialogues: cultural positioning decides *whether* modernist asymmetry is the right signal; this source decides *how* to execute it.

---

## Candidate lexicon rows

| trigger | rule | activating question | tier | phase | src |
|---|---|---|---|---|---|
| layout hierarchy unclear; all blocks equal | **Contrast engine** — define hierarchy via size, weight, position, silhouette tension, not ornament | Can I name the one dominant and what is subdued? | should | layout | asymmetric-typography ch-5 |
| asymmetric composition re-centred on artboard | **Do not centre asymmetry** — unequal L/R margins; field is part of the design | Are left and right margins intentionally different? | blocker | layout | asymmetric-typography ch-6 |
| identical gaps between content groups | **Unequal intervals** — distinguishable spacing aligned to sense coherence | Do intervals create tension while still matching text relatedness? | should | layout | asymmetric-typography ch-6 |
| more than three competing content units at a glance | **Three-group rule** — regroup to sense units absorbable without counting | Can the structure be grasped without counting blocks? | should | layout | asymmetric-typography ch-8 |
| equal-importance lines right-aligned in LTR | **Reading-direction align** — left-align equal lines; eye returns to start | Does the eye know where each line begins? | blocker | layout | asymmetric-typography ch-7 |
| modern cover on classical interior (or reverse) | **Form–content harmony** — one typographic system end-to-end | Does every part of the object share one axial system? | should | identity | asymmetric-typography ch-4 |
| hierarchy depends on borders or decorative frames | **Hierarchy without ornament** — weight/size/position carry meaning | If ornaments vanish, does hierarchy remain? | should | layout | asymmetric-typography ch-2 |
| letter-spacing used to hit a silhouette width | **Intact word shape** — ban lower-case letter-spacing as fill; redesign structure | Is tracking solving a structure problem it should not? | should | type | asymmetric-typography ch-9 |
| second colour or rules used densely | **Thrift of accent** — sparse colour/rules increase force | Is every accent structural, not sprinkle? | judgment | colour | asymmetric-typography ch-11 |
| white space feels leftover or empty luxury | **Active white space / right position** — place type relative to field; white is mass | Does moving the block 10% break or improve tension? | should | layout | asymmetric-typography ch-6 |
| brief allows either classical dignity or modern hierarchy | **Two-system choice** — symmetry valid when content/tradition demand; else asymmetry for differentiated purpose | Which system does the content honestly require? | judgment | layout | asymmetric-typography ch-4 |
| composition copies modernist shapes without message clarity | **Abstract method not motifs** — study materials, forge contrast, stay in purpose | Is this order serving reading, or only looking “Bauhaus”? | should | layout | asymmetric-typography ch-13 |

