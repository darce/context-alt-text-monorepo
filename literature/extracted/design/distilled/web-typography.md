# Web Typography (Richard Rutter) — distilled

> **Source**: Richard Rutter, *Web Typography: A handbook for designing beautiful and effective responsive typography* (Ampersand Type, Brighton, 2017) · extracted from `../web-typography.txt` · distilled 2026-07-09 (spec v1)
> **Contributes**: This lane’s primary **screen typographic system** source. **Measure / line-height / size interlock** (the three-legged stool); **responsive type by reading distance and viewport**; **OpenType feature usage** (numerals, ligatures, small caps, display alternates); **pairing and face selection for screen** (robust texture, skeleton matrix); **tables and numeral roles**; **performance-aware web-font loading** (FOIT/FOUT, subset, display strategy). Named concepts: **readability stool**, **measure**, **typographic colour**, **modular scale**, **active texture**, **FOIT / FOUT**, **lining / old-style / tabular numerals**, **skeleton–flesh–skin**, **workhorse vs personality**, **data-ink ratio** (tables). Where eng owns token scales and a11y floors, this lane owns the **typographic reasoning behind the values**.

## Chapter map

- ch-1 — Scope boundary (type system lane, not eng UI tokens)
- ch-2 — Why web type: duty, mood, relinquish control
- ch-3 — How we read: saccades, immersion, three text roles
- ch-4 — Units: em, rem, ch, reference pixel
- ch-5 — Readability stool: measure, size, line-height
- ch-6 — Alignment, justification, hyphenation
- ch-7 — Responsive paragraphs and display scale
- ch-8 — Hierarchy, modular scale, semantics of structure
- ch-9 — Detail craft: punctuation, ligatures, OpenType
- ch-10 — Numerals and tables
- ch-11 — Tracking, kerning, headlines, vertical rhythm
- ch-12 — Macro composition: margins, white space, grids
- ch-13 — Screen rendering and pragmatic face requirements
- ch-14 — Choosing and pairing faces (body, display, functional)
- ch-15 — Using web fonts: payload and render timing
- pipeline — Type-system decision pipeline
- Decision rules (summary)
- Anti-patterns
- Applicability & exemptions
- Candidate lexicon rows

---

## ch-1 — Scope boundary (type system lane, not eng UI tokens) {#ch-1}

This distillate feeds **design-aesthetics heuristics** for **typographic systems and voice on the web**. It does **not** restate engineering UI mechanics already owned by Refactoring UI / eng lexicon: predefined product type-token tables, 4/8-pt spacing recipes, weight-over-size as default UI hierarchy, shade ramps, elevation, WCAG contrast floors as compliance checklist. Keep the **reasoning, interlock, and craft**; tag borders `↔ eng UI-*`.

| This lane owns | Hand off to eng lexicon |
|---|---|
| Why **45–75 chars / 23–38 em** measure; stool balance | Component `max-width` tokens as implementation |
| **Line-height** from colour, x-height, measure | Default `line-height` token values in UI kits |
| Modular scale **ratios and selection logic** | Generating/exporting scale tokens |
| Face **pairing, voice, optical size, OpenType roles** | Font loading plumbing, fallback stacks as code |
| Table **readability and data-ink** | Table component APIs, responsive table widgets |
| FOIT/FOUT **reading-experience policy** | CDN, caching, build pipeline |

**Era note (2017):** CSS browser-support details age; **numbers, interlocks, and principles do not**. Prefer Can I Use for property support; keep Rutter’s measure/leading/scale and face-selection logic.

↔ eng UI: scales exist in eng as tokens; **this lane owns why those values must move together** when content, face, or viewport changes.

---

## ch-2 — Why web type: duty, mood, relinquish control {#ch-2}

**Duty (Zapf / Ruder):** typography is craft in service of the reader, not self-expression. A site that cannot be read is a product without purpose. Roles beyond bare legibility: invite the reader; honour tone and structure; create conditions for immersion, scanning, or reference as needed.

**Good typography induces a good mood** (Larson & Picard, 2005): little effect on raw speed/comprehension; measurable engagement, perceived shorter reading time, less frowning. Details sum to experience.

**Web is not ink:** the medium is software + hardware under **reader control**. CSS is a peelable layer of **hints**, not absolute print control. **Relinquish control** (Allsopp / Dao of Web Design): designs adapt to environment; reader may override size, font, colour.

**Process order:** choosing a face is **not** typography’s first act. Design essentials for content and structure first; face choice last among foundations—but expect iteration because the face will pull measure, leading, and hierarchy.

**Prepare the ground:** read representative content; know audience, devices, contexts; honour text—do not force copy into a fashionable page silhouette.

---

## ch-3 — How we read: saccades, immersion, three text roles {#ch-3}

**Three roles of text:**

| Role | Intent | Setting priority |
|---|---|---|
| **Display** | Grab attention; set mood; looked at before read | Impact, shape, emotional type |
| **Reference** | Consult discrete facts (tables, lists, glossaries) | Scan, alignment, numeral clarity |
| **Linear** | Continuous reading | Measure–size–leading comfort |

Readers **skim**, **scan with purpose**, then **engage**. Aim for immersive **flow**; bad type can block it even when writing is good.

**Mechanics:** foveal vision ~**4–5 letters** sharp; eyes move in **saccades** with brief **fixations**; occasional regressions; big saccade to next line start. Design task: keep eyes on the line with minimal back-pedalling; make **return sweep** accurate.

**Readability vs legibility:** readability = comfort and comprehension of typeset material; legibility = character clarity (mostly type design, affected by setting). Screens emit light; distance, glare, resolution, bandwidth all fight the reader—type systems must work across hostile conditions.

---

## ch-4 — Units: em, rem, ch, reference pixel {#ch-4}

| Unit | Definition (Rutter) | Prefer for |
|---|---|---|
| **em** | Length = element’s font size (or inherited when sizing font) | **Local** sizing: padding, gaps inside a component that should track that component’s type |
| **rem** | Always relative to root (`html`) / browser default | **Global** type sizes and page-scale relationships |
| **ch** | Width of `0` in current font (~0.5em if unknown) | Widths that should follow face width (display line breaks); not general layout consistency |
| **CSS px** | **Reference pixel** ≈ 1/96" at arm’s length—not hardware pixel | Avoid for text sizing (accessibility history; absolute framing) |

**Rule:** rems for global sizing; ems for local sizing. Example: pull-quote para size in rem; space between those paras in em so enlarging the quote scales its internal rhythm.

**1 em ≈ 2 characters** average → measure range **23–38 em** maps **45–75 characters**.

---

## ch-5 — Readability stool: measure, size, line-height {#ch-5}

**Three-legged stool:** **line spacing + measure + text size**. Change one → rebalance the others.

### Measure (start here)

- Ideal ~**66 characters**; satisfactory range **45–75** (spaces included)—centuries of print practice, not pure lab mandate.
- Screen studies: longer lines (to ~**100**) can speed reading but **readers prefer shorter**; prefer inviting over max speed.
- Mobile-first: default phone ~**~40 cpl** at default size—near lower bound; do not shrink text to cram more characters.
- Desktop unconstrained can hit **~135 cpl**—too long. Cap with liquid layout: `max-width: 38em` (upper end); allow shrink on small viewports; do not fix absolute width that fights the device.
- **ch** varies by face → prefer **em** for measure control.

### Text size

- Start body at **browser default** (usually **16 px**); respect user default changes.
- Screens read farther than books → default feels large vs print side-by-side; still **safer slightly big than small**.
- Reversed-out (light on dark): often needs **slightly larger**.
- **Face-dependent optical size:** match apparent size to a benchmark (Helvetica) by eye or **aspect value** (x-height / font-size). Examples at 16 px Helvetica baseline: Lato ≈ **16.5**, Futura ≈ **20**, Altis ≈ **15.2** (use whole px). Formula: `size₂ = size₁ × aspect₁ / aspect₂`.
- Size text in **rem** (`18px → 1.125rem` when root 16).

### Line-height (leading)

- Prefer **unitless** multipliers so children inherit the multiplier, not a calculated px trap.
- Browser `normal` ≈ **1.0–1.2**—usually tight for screen; start ~**1.4**, then adapt to face and measure.
- **Typographic colour** (density of black texture): even grey, not stripes. More colour (bold, high contrast, large x-height) → slightly **more** leading; less colour (light weight, small x-height) → slightly **tighter**.
- Longer measure → more leading; short measure can tighten.
- Shorthand: `font: 15px/1.5 sans-serif` (order and required fields matter).

**Interlock tests (falsifiable):**

1. At max measure (**38em**), can the eye rejoin next line without skipping?
2. At phone width (~40 cpl), is body still ≥ default comfort (no artificial shrink for “more words”)?
3. If face x-height changes, was size **and** leading re-judged?

↔ eng UI: eng may ship a type scale; **stool balance is design judgment when face or content column changes**.

---

## ch-6 — Alignment, justification, hyphenation {#ch-6}

| Choice | Rule |
|---|---|
| Default continuous prose | **Left-align (ragged right)** |
| Justify | Only if hyphenation on; browsers often use **greedy** word-spacing → rivers |
| Final line of justified block | Stay left (never full-justify last line of continuous text) |
| Centre | Short display / classical intros OK; **never long body** |
| Hyphenate without justify | OK (reduces rag); **justify without hyphenate** = harm |

**Hyphenation craft (English rules of thumb):**

- `hyphens: auto` + set **`lang`** (region matters: `en-GB` vs `en`)
- Max consecutive hyphens ~**2** (ladders)
- Word min length **6**; min **3** before / **2** after break (`hyphenate-limit-chars: 6 3 2`)
- Hyphenation zone ~**8%** as start (wider zone → fewer hyphens, more rag)
- No orphaned hyphen stub as last line (`hyphenate-limit-last: always` when available)
- Soft hyphens for odd words; `<wbr>` for long URLs without visible hyphen
- Prefer no auto-hyphen on proper names / all-caps abbrs after first appearance

**Cultural note:** German readers tolerate more ladders; agglutinative languages need hyphenation more.

---

## ch-7 — Responsive paragraphs and display scale {#ch-7}

Responsive type = **best compromise**, not one perfect setting.

**Reading-distance approximations** (perceived ~**30 arcminutes** like 10 pt book at 35 cm):

| Context | Distance (approx) | Target body |
|---|---|---|
| Phone | ~30 cm | **1rem** (~16 px default) |
| Laptop/tablet | ~45 cm | **~1.125rem** (~18 px) from ~**60em** width |
| Large desktop | ~60 cm | **~22 px** scale—Rutter example uses **120em** width breakpoint (verify optical result; keep stool) |

Use **em-based breakpoints** so layout responds to **type size + viewport**, not device names. Include **min-height** with min-width for large type so ultra-wide shallow windows don’t crop huge heads.

**Tablet problem (Mod):** bed / knee / breakfast distances—undetectable; test manually.

**Display as picture of type:** large type (≥ **~3× body**) sets mood before reading. Perceived impact can exist on phones (~**48 px** ≈ magazine impact at close distance vs ~**98 px** on desktop for same arcminutes).

**Viewport units for display:**

- `vw` / `vh` / `vmin` / `vmax` (1 = 1% of dimension)
- Prefer **`vmin`** over `vw` for orientation-stable impact
- Hybrid supporting text: e.g. `calc(0.5rem + 2.5vmin)` so subheads don’t race main head
- White space for display: can use **vh**; large display + huge margins only when **width and height** both allow (rule of thumb: min-height ≈ **half** min-width for 16:9-ish)

**Prototype rule:** design type in a **browser with real/unfamiliar content**; squinting hierarchy is not a readability test. Change sample text each iteration.

---

## ch-8 — Hierarchy, modular scale, semantics of structure {#ch-8}

**Differentiation palette:** size, weight, style (italic/caps), face, colour, spacing, proximity. **Change one attribute at a time.** Importance ≠ always largest—**contrast** is the goal.

**Always size from a scale.** Classic typographic scale (pt heritage still in software presets):

`6 7 8 9 10 11 12 14 16 18 21 24 36 48 60 72`

- Recurring **2:1** octave; **interval 5** between doubles (with historical anomalies).
- Limit simultaneous sizes—**three** is a good start; many sizes = melody noise, not a chord.
- Pick **smallest size first** so small print stays legible; never trap body small then need smaller still.

**Modular scale equation:** \(f_i = f_0 \times r^{n/i}\) (base, ratio, interval). Classic: base **12**, ratio **2**, interval **5**. Alternatives: musical ratios (**3:2** perfect fifth, **4:3** perfect fourth) when photography/screens share those aspects; golden ratio φ ≈ **1.618** is pleasant but often unrelated to content proportions.

**Responsive hierarchy:** keep **one scale**; pick **larger steps** from it at wider (and taller) breakpoints—example perfect-fourth ladder **12…78** with different h1–h4 picks at phone / 60em / 120em.

**Semantics:**

- Indent **or** space between paragraphs—**never both**
- Indent ≥ **1em**, ideally = line-height; **never** indent first para after title/heading/interrupt
- Blank gap between paras ≤ **1em**; half line-height often enough for scanning web chunks
- Indent suits long-form immersion; spaced paras suit chunked/skimmable web writing
- Block quotes: inset like para indent; same size or slightly smaller **or** italic—not both; hang opening quotes
- Lists: half-line offset; short items no inter-item gap; long items use para-like gap; hang numbers when possible
- Links: clear, unobtrusive; default blue underline is loud; if colour-only, WCAG link contrast + non-colour cue on focus
- True bold/italic—not faux; `font-synthesis` off only when decoration-only and failure won’t hide meaning
- Weights **100–900** (400 regular, 700 bold); map names loosely

**Openers:** white space before first prose; optional **run-in** small caps / bold first line; **drop caps** only if baseline + cap-height alignment accurate (`initial-letter`)—bad drops worse than none.

↔ eng UI: weight-over-size hierarchy recipe is eng default for chrome; **content hierarchy still uses the multi-attribute contrast engine**.

---

## ch-9 — Detail craft: punctuation, ligatures, OpenType {#ch-9}

**Orthotypography:** punctuation is notation, not decoration (except intentional display).

| Wrong | Right |
|---|---|
| Hyphen for ranges / parentheticals | **En dash** (ranges; spaced en for British parentheticals) |
| Double hyphen | **Em dash** (US parentheticals; hair spaces often) |
| Hyphen as minus / x as multiply | **−** minus, **×** multiply, **÷** divide |
| Neutral quotes | Curly quotes; nest per locale (UK single-out, US double-out; guillemets elsewhere) |
| Three dots | Ellipsis … |
| Straight primes for feet/inches | ′ ″ primes; ° for degrees |
| Missing diacritics in names | Honour accents; face must contain glyphs |

Spaces: non-breaking for “Page 2”, dates, initials; thin (**~1/6 em**), hair (**~1/24 em**); narrow no-break for initials/units.

**Ligatures:** keep **common ligatures** on (`liga`); discretionary/historical for display only. Prefer `font-variant-*` with `@supports`; `font-feature-settings` overrides wholly—repeat tags when stacking.

**Small caps:** true drawn small caps for abbreviations in running text; not for Title Case headings; avoid faux small-caps shrink.

**OpenType feature cheat (common tags):** `liga`, `dlig`, `hist`, `smcp`/`c2sc`, `onum`/`lnum`, `tnum`/`pnum`, `subs`/`sups`, `kern`, `swsh`, `ss01+`, `salt`.

---

## ch-10 — Numerals and tables {#ch-10}

### Numeral roles

| Context | Numeral form | OpenType |
|---|---|---|
| Running text | **Old-style / text** | `oldstyle-nums` / `onum` |
| Headings with caps / Title Case | **Lining** | `lining-nums` / `lnum` |
| Columns of comparable numbers | **Tabular lining** | `lining-nums tabular-nums` / `lnum`+`tnum` |
| Prose phone/serial strings | Letterspace digits ~**5%** | tracking + lining/old-style as context |

Helvetica-era lining-only faces are poor body defaults when numbers appear often. Prefer proper **sub/sup** figures; neutralize browser `vertical-align`/`font-size` when real OT figures exist.

**Footnotes:** superscript markers in text; full-size numbers in notes; on web, prefer **in-place reveal** near the reference over distant endnotes when possible.

### Tables as text to be read

**Tschichold / Tufte:** maximise **data-ink**; remove frames, zebra-by-default, full-width stretch “as image.”

| Do | Don’t |
|---|---|
| Column width from content (let browser algorithm work) | Force equal columns / stretch to column width for looks |
| Left-align text; right-align numbers; match header alignment | Centre everything |
| Same decimal precision when scanning magnitudes | Mixed precision that looks like magnitude |
| Align to decimal when precision varies | Pretend right-align fixes mixed decimals |
| Collapse borders; padding asymmetrical (less top); line-height can go ~**1** in short cells | Spreadsheet grid cages |
| Group rows by **proximity**; rules only if alignment fails—one direction, light | Net of rules around every cell |
| Condensed **or** slightly smaller for cramped—not both | Cram + decorate |

**Responsive tables (purpose-first):**

1. Horizontal scroll inside figure (`overflow-x: auto`)—readable beats fully-on-screen illegible
2. Linearise simple directories to labelled stacks at narrow breakpoints
3. Hide non-essential columns with toggle when **comparison** of remaining fields matters
4. Oblique headers only as space tactic for short data / long labels

---

## ch-11 — Tracking, kerning, headlines, vertical rhythm {#ch-11}

**Kerning:** pairwise; leave on (`font-kerning: normal`); many free fonts lack tables. **Tracking:** global letter-spacing—rare.

| Tracking rule | Detail |
|---|---|
| Lowercase running text | Do **not** letterspace without cause (Goudy warning); if needed, question the face |
| Strings of caps | Add ~**0.05em** (5%); more for light display caps |
| Long digit strings | ~**5%** |
| Big bold wide display | Gently tighten (e.g. **−0.03em**); Univers body sometimes **−0.01em** |
| Letterspace on | Turn **ligatures off** (browsers still ligate incorrectly) |
| Centred + tracked | Compensate trailing letter-space with negative margin |

**Headlines:** prevent **widows** (nbsp between last two words); tighten leading for large type (often **1** solid; all-caps try **~0.75**); watch **clash**; alternate line lengths for known display copy; hang / optically centre punctuation; OpenType **swashes/alternates** with surgical markup—not whole-word feature dumps.

**Vertical rhythm:** basic unit = body **line-height** (e.g. 16/21 → **21 px** unit). Margins and other line-heights as **factors of that unit**. Browser default 1em para margin breaks the beat—set explicitly. When size changes, recompute so block height stays on the module. **Asymmetrical** heading margins OK if sum is multiple of unit. Embedded media may **break** the grid—restart rhythm after; don’t crop photos to fit maths. **Baseline grid ≠ vertical rhythm** on the web (text centres in line boxes); don’t fake print baseline religion.

---

## ch-12 — Macro composition: margins, white space, grids {#ch-12}

**Content-out, mobile-first:** no fixed canvas; force priority on a single column. Continuous fluid response > device silhouettes.

**Scan design (F-pattern on large screens):** inviting linear experience; clear subheads; strong **left edge** as visual banister.

**Margins:** frame + rail; when wide enough, park asides (example: body **38em** + **10em** note + gutters → float aside from ~**60em**).

**Active white space:** intentional framing/emphasis (vs passive inter-letter/line space). More surrounding space → more emphasis. Use ems inside text; **% / viewport** for environmental emptiness.

**Gestalt for composition:** proximity, similarity, focal points, common regions.

**Grids:** hierarchical (mobile natural), columnar, modular (canvas-heavy—weak on web). Prefer **compound** hierarchical+columnar. Prefer **odd** column counts for tension/hierarchy over framework “divisible by 12” convenience. CSS multi-columns: prefer `column-width`; gate multi-col on **min-height** so readers don’t scroll up between columns.

↔ asymmetric-typography: active white space and odd tension align; Rutter adds **responsive fluid** constraints Tschichold’s paper canvas didn’t have.

---

## ch-13 — Screen rendering and pragmatic face requirements {#ch-13}

**Hostile screen:** low ppi vs print; emitted light; divergent rasterisers. Accept difference across platforms—goal is good, not identical (Schwartz).

| Platform tendency | Implication |
|---|---|
| Windows + hinting | Clarity over contour fidelity at low res |
| Apple/others | Contour fidelity; may look softer at low res |
| Mobile | Greyscale AA often (rotation); no TrueType hint use on many stacks |
| Hi-res | Differences collapse |

Don’t disable subpixel AA except **reversed-out large text** on low-res macOS (`-webkit-font-smoothing` sparingly). Test Windows low-res early. Autohinted web fonts common; unhinted cheap fonts can be unusable.

**Pragmatic shortlist gate (before aesthetics):**

1. Required **characters** (languages, names, chemistry, currency)—no tofu / silent fallback face mix
2. Required **styles** (italic, bold, condensed, display weights)—no faux as plan
3. Required **OpenType** (old-style, tabular, small caps, math)
4. **Rendering** OK on target devices
5. **File size / connection** budget
6. Licence model (service vs self-host; no illegal desktop→web convert)
7. Brand face unfit for body → confine to display and pair a real text face

Free fonts: some excellent (Source Serif, Lato, Fira…); many incomplete—budget testing effort.

---

## ch-14 — Choosing and pairing faces (body, display, functional) {#ch-14}

### Body

- Remove friction; reader shouldn’t notice the face.
- **Robust for screen:** high x-height, low contrast, open counters, sturdy terminals—newspaper **Scotch** / **humanist slab** / signage-leaning **humanist sans** territory.
- **Active texture + even colour:** not dull monoline soup, not high-contrast dazzle; leading finishes colour.
- **Clothes words wear** (Warde): match **nature of writing**, not only topic keywords; no neutral face—quiet is still a choice.
- History/culture of face should not fight content; research foundry intent + Fonts In Use.
- Specimen with real content, all needed styles, client name, multi-device judgment.
- Shortlist by pragmatism; final pick may be taste among non-wrong options.

### Display

- **Seduction** and amygdala-level association; can shift mood/expectation (Hyndman-type effects as caution: face sets expectations).
- **Workhorses** (Helvetica/Futura/Proxima class): flexible, ubiquitous, hard to make exceptional.
- **Personalities:** more character out of box; less malleable—prefer for distinctiveness on a homogeneous web.
- Prefer true **optical display styles** (higher contrast, finer detail at large size; text styles coarser/looser at small).
- Superfamily condensed/extra for wide screens without over-wide words.
- Reinforce text face structure (same skeleton column) when no optical sibling.

### Functional (UI chrome, captions, microcopy)

- Distinguish by context/position/colour; size ≥ **~75% of body** (print 6–8 pt captions don’t translate).
- Short lines/tighter leading OK for glanceable scraps.
- Open, **distinguishable** glyphs (I/l/1); generous built-in spacing; avoid light weights that dissolve.
- Signage/UI-designed faces; caption optical cuts; system UI stacks (`message-box` / `-apple-system` patterns) when native chrome match matters.

### Pairing

- Use few faces (**2–3** default) unless strict role map and consistency.
- **Anchor** (usually body) → complements.
- **Skeleton matrix** (dynamic / rational / geometric × contrast × serif|slab|sans): same **column** pairs well; adjacent columns hard; **diagonal** for strong contrast; serif+sans same skeleton is classic.
- Also: superfamilies, same designer thumbprint, same foundry recommendations, shared x-height/colour with size tweaks.
- Similarity ≠ compatibility; geometry kinship (Bodoni + Eurostile) can trump era.

**Skeleton–flesh–skin description** (Kupferschmidt-style): stress/form → contrast + serif presence → x-height and local details. Use to brief clients and hunt pairs.

---

## ch-15 — Using web fonts: payload and render timing {#ch-15}

**Web font** = same font, network-delivered. Optimise **payload** and **timing**.

### Payload

- Limit families/weights actually needed
- Prefer **WOFF2** (+ WOFF fallback); ~**30%** smaller than WOFF
- **Subset** language/features—not so hard that glyphs missing mid-name
- Variable fonts (OpenType 1.8): one file, axes (`wght`, `wdth`, `opsz`, …)—payload + responsive axis potential; progressive with static fallbacks

### Timing (FOIT vs FOUT)

| Strategy | Behaviour | Use |
|---|---|---|
| FOIT (block) | Invisible text until font | Only tiny text where brand face is required for sense |
| FOUT (swap) | Fallback then swap | Important short text |
| **fallback** | Brief wait, then fallback; may freeze fallback if late | **Body default** |
| optional | Use only if already there / bandwidth OK | Nice-to-have faces |

`font-display: fallback` (preferred body policy). **Preload one** critical face (usually body)—more preloads delay first paint. Font Loading API / `wf-active` classes for progressive enhancement and metric-matched fallbacks.

**Fallback stack craft:** match **x-height**, width economy, and key glyphs (G, W, a, y, g) per OS; order by best metric match; `font-size-adjust` or wf-class size/leading compensation to reduce reflow.

**Services vs self-host:** services → licence, CDN, subsetting, UA-tuned files; self-host → control, one-off fee, you own subsetting/ethics/CDN.

Never plan on **faux bold** to save a weight download.

---

## pipeline — Type-system decision pipeline {#pipeline}

Use as ordered checks on a mockup, prototype, or brand type proposal:

1. **Content & roles** — Map display / linear / reference / functional; read samples; mobile priority order.
2. **Measure** — Body column **45–75 cpl** (**23–38em**); liquid max **38em**; no desktop river of 100+ cpl.
3. **Size** — Default-root body; optical adjust for face; rem; distance breakpoints in **em**.
4. **Leading** — Unitless; start ~**1.4**; rebalance for colour, x-height, measure; tighten display.
5. **Scale** — Smallest size first; modular steps; ≤ few sizes; larger steps from same scale on large viewports.
6. **Structure semantics** — One attribute change per level; indent XOR gap; hang quotes; true styles.
7. **Numerals & tables** — OT numeral roles; data-ink tables; purpose-based responsive behaviour.
8. **Face shortlist** — Characters, styles, OT, render, licence, budget **before** vibe.
9. **Pair** — Anchor + skeleton column / superfamily; display optical or personality with intent.
10. **Load** — Subset + WOFF2; `font-display`; one preload; metric fallbacks; no faux plan.
11. **Verify** — Read unfamiliar text on real devices; Windows low-res + phone + wide shallow; check stool after any face swap.

---

## Decision rules (summary)

| Trigger | Rule | Rationale | Src |
|---|---|---|---|
| Body column unbounded on large screens | Cap measure **38em** / ~**75 cpl** liquid | Return sweep fails on long lines | ch-5 |
| Changing size or face | Rebalance **measure + leading** | Three-legged stool | ch-5 |
| New face looks “small” at 1rem | Optical-size via **x-height/aspect** | Metrics ≠ perceived size | ch-5 |
| line-height set in px/% on parent | Prefer **unitless** multipliers | Inheritance traps | ch-5 |
| Justified body without hyphens | Align left or enable hyphenation | Rivers from greedy justify | ch-6 |
| Breakpoints in device px only | Prefer **em** width (+ height) | Type-relative response | ch-7 |
| Display scales with `vw` only | Prefer **vmin** or hybrid calc | Orientation inconsistency | ch-7 |
| Hierarchy by size jumps alone | Change **one** attribute; use scale | Messy multi-signal systems | ch-8 |
| Smallest type undecided | Choose **smallest first** | Avoid illegible fine print trap | ch-8 |
| Numbers in paragraphs | **Old-style** numerals | Lining shouts in prose | ch-10 |
| Numeric comparison tables | **Tabular lining** + align | Vertical scan of magnitudes | ch-10 |
| Table styled like spreadsheet | Strip furniture; **data-ink** | Decoration harm reading | ch-10 |
| Letterspaced lowercase body | Stop; rechoose face | Destroys word shape | ch-11 |
| Vertical spacing random | Module from body **line-height** | Rhythm guides descent | ch-11 |
| Face chosen on day one | Design system first; face last among foundations | Face isn’t typography | ch-2, ch-14 |
| Pairing two “nice” fonts | Same **skeleton column** or strong diagonal contrast | Dissonant adjacents | ch-14 |
| UI microcopy in thin geometric | Open, distinct, ≥**75%** body | Glanceability | ch-14 |
| FOIT on body copy | `font-display: fallback` (+ progressive) | Invisible text blocks reading | ch-15 |
| Many weights “just in case” | Load only used styles; subset | Payload | ch-15 |
| Missing accent in names | Face must contain glyph; no silent stack mix | Ethnocentric broken rendering | ch-9, ch-13 |

---

## Anti-patterns

| Anti-pattern | Detection cue | Fix |
|---|---|---|
| **Measure flood** | Full-bleed prose on desktop | `max-width` ~38em liquid |
| **Stool one-leg tweak** | Only font-size changed after redesign | Re-check cpl and leading |
| **Pixel text religion** | Body in px “for control” | rem + user default |
| **Justify vanity** | Justified CMS blog, no hyphens | Left-align or full hyphen pipeline |
| **Centre essay** | Long centred articles | Centre only short display |
| **Scale free-for-all** | 11 unrelated sizes in inspector | Modular scale; fewer steps |
| **Faux emphasis** | Synthetic bold/italic | Real faces or redesign without |
| **Lining spam** | Years/prices shout in serif body | `onum` in text |
| **Spreadsheet table** | Full-width grid, zebra, centred nums | Data-ink + alignment rules |
| **Tracked Garamond** | Spaced old-style lowercase | Tracking off |
| **Drop-cap stumble** | Misaligned decorative initial | Fix `initial-letter` or remove |
| **Brand body abuse** | Display brand face at 16px for articles | Pair text face |
| **FOIT brand purity** | Blank page until fonts load | fallback/optional strategies |
| **Subset tofu** | Mixed fallback mid-word | Widen subset / face |
| **Device costume breakpoints** | “iPad CSS” only | Fluid em breaks |

---

## Applicability & exemptions

| Applies strongly | Exempt / weak fit |
|---|---|
| Long-form, editorial, docs, marketing sites | Single-line app chrome (hand most to eng UI) |
| Responsive content sites | Fixed canvas print PDF export (still use craft) |
| Multilingual Latin/European text | Complex scripts (Arabic, Indic, CJK)—out of book scope |
| Data tables and numeric UI | Charts/graphs (Tufte applies; different mechanics) |
| Custom brand web fonts | Strict system-font-only performance mode (still use measure/leading) |

**Exemptions:**

- **Accessibility floors** (contrast, zoom, reflow) always bind; beautiful measure does not excuse unreadable contrast or disabled zoom.
- **App UI density:** stool still informs readable panes; pure control labeling may use functional-text loosening (short lines, tighter leading).
- **Deliberate display rule-breaking:** allowed when text is picture-first and remains ultimately legible.
- **Agglutinative / German** hyphenation norms differ—don’t force English ladder limits globally.
- **2017 CSS support notes** are historical; principles and numbers remain.

**Contra notes:**

- ↔ eng UI type scales: eng owns token tables; **Rutter owns interlock and content-column reasoning**.
- ↔ asymmetric-typography: shared white-space/hierarchy craft; Rutter insists on **reader-controlled fluid medium**.
- ↔ pure baseline-grid print practice: web **vertical rhythm ≠** forced shared baselines.
- ↔ “longer lines are faster on screens”: preference and invitation beat pure speed metrics.

---

## Candidate lexicon rows

| Trigger | Rule | Activating question | Tier | Phase | Src |
|---|---|---|---|---|---|
| prose column >~75 cpl on desktop | **Measure cap** — liquid max ~38em / 45–75 cpl | Can the eye rejoin the next line without hunting? | blocker | type | src: web-typography ch-5 |
| size/face/measure changed in isolation | **Readability stool** — rebalance size, measure, leading together | Did all three legs move when one did? | blocker | type | src: web-typography ch-5 |
| body leading still browser normal | **Screen leading floor** — start ~1.4 unitless; tune to colour | Is colour even, not striped or sparse? | should | type | src: web-typography ch-5 |
| justified article body | **Hyphenate or ragged** — never justify without hyphens | Are there rivers or ladders? | blocker | type | src: web-typography ch-6 |
| type locked to device breakpoints only | **Em-based type response** — breaks track root size + distance | Does layout still work if user enlarges default text? | should | type | src: web-typography ch-7 |
| many ad-hoc font sizes | **Modular scale discipline** — few steps; smallest first | Are sizes from one harmonic ladder? | should | type | src: web-typography ch-8 |
| numbers in running prose use lining defaults | **Old-style in text** — lining for caps heads; tabular in tables | Do figures shout louder than words? | should | type | src: web-typography ch-10 |
| data table full-width with grid fills | **Table data-ink** — align, group, strip furniture | Is every rule earning its pixels? | should | type | src: web-typography ch-10 |
| pairing display + body by trend only | **Skeleton pairing** — same form column or deliberate diagonal | Do faces share structure or only vibe? | should | type | src: web-typography ch-14 |
| brand face used for long reading | **Text face duty** — robust screen text; brand for display | Would you read 3000 words in this face? | blocker | type | src: web-typography ch-14 |
| web fonts block first paint of body | **FOUT-friendly body** — font-display fallback + metric fallbacks | Is text readable before webfont arrives? | blocker | type | src: web-typography ch-15 |
| font files include unused languages/weights | **Payload subset** — load only needed glyphs/styles | What bytes are never painted? | should | type | src: web-typography ch-15 |

---

## Source pairing note

| Adjacent source | Relationship |
|---|---|
| **Asymmetric Typography (Tschichold)** | Composition, active white space, table austerity—print ideology; Rutter supplies **web fluid + CSS mechanics** |
| **Paula Scher** | Display voice and identity drama; Rutter supplies **body readability stool** and performance loading |
| **eng Refactoring UI** | Token scales, spacing, a11y floors; cite `↔ eng`—do not duplicate token recipes here |

Use Rutter when deciding **how type behaves as a system on screens**; use eng when implementing **product chrome tokens**; use Tschichold/Scher when composition or brand voice dominates over continuous reading.
