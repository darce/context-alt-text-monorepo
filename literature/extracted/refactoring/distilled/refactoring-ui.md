# Refactoring UI — distilled

> **Source**: Adam Wathan & Steve Schoger, *Refactoring UI*, 2018 · extracted from `../Refactoring-UI.txt` · distilled 2026-07-09 (spec v2)
> **Contributes**: The only source in this directory about **visual design as an engineering discipline**: it converts "make it look designed" into checkable rules over CSS/markup — predefined scales for every visual property (spacing, type, color, shadow), visual-hierarchy mechanics (weight/color over size, de-emphasis over emphasis), HSL color-system construction, light-source-consistent depth, and contrast/accessibility floors. Every rule fires on an observable literal in a stylesheet or template, which makes this the backbone of a "UI & Visual" lexicon section that no architecture or process book supplies.

## Chapter map

- ch-1 — Starting from Scratch: what to design first, personality choices, why every visual property needs a predefined scale
- ch-2 — Hierarchy is Everything: emphasis via size/weight/color, labels, action pyramids, weight-vs-contrast balancing
- ch-3 — Layout and Spacing: white-space defaults, the ≥25% spacing scale, fixed vs fluid widths, ambiguous-spacing rule
- ch-4 — Designing Text: hand-crafted type scale, font selection filters, line length/height, alignment, letter-spacing
- ch-5 — Working with Color: HSL, palette size (greys/primary/accents × shades), fixed shade scales, perceived brightness, WCAG contrast
- ch-6 — Creating Depth: light-from-above, elevation shadow system, two-part shadows, flat-design depth, overlap
- ch-7 — Working with Images: photo quality, text-over-image contrast, intended sizes for icons/screenshots, user-uploaded content
- ch-8 — Finishing Touches: supercharged defaults, accent borders, background decoration, empty states, border alternatives
- ch-9 — Leveling Up: how to keep improving (study unintuitive decisions, rebuild interfaces)

## ch-1 — Starting from Scratch {#ch-1}

**Start with a feature, not a layout.** "Designing the app" usually means designing the shell (nav position, sidebar, logo). But an app is a collection of features, and shell decisions require feature knowledge you don't have yet. Start with one piece of real functionality (flight search: departure field, destination field, dates, search button) — the shell can come later, or never (worked for Google).

**Detail comes later.** In earliest stages, don't decide typefaces, shadows, icons. Low-fidelity trick: sketch on paper with a thick Sharpie — detail obsession is physically impossible. **Hold the color**: design in grayscale first, forcing spacing, contrast, and size to do all hierarchy work; the result is a clearer interface that's easy to enhance with color later. **Don't over-invest**: wireframes are disposable — explore, decide, leave them behind.

**Don't design too much.** Work in short cycles: design a simple version → build it → iterate on the working UI (real edge cases surface there, not in imagination) → design the next feature. **Be a pessimist**: never imply functionality you aren't ready to build (e.g., an attachments section in a comment-system mock delays shipping the whole comment system). Design the smallest useful version; nice-to-haves get designed later.

**Choose a personality.** Personality is determined by concrete factors, not vibes:

| Factor | Choice → feel |
|---|---|
| Typeface | serif → elegant/classic · rounded sans → playful · neutral sans → plain/versatile |
| Color | blue → safe/familiar · gold → expensive/sophisticated · pink → fun/informal |
| Border radius | none → serious/formal · small → neutral · large → playful |
| Language | formal tone → official · casual tone → friendly |

Stay consistent: mixing square and rounded corners in one UI almost always looks worse than committing to either. Choose direction by looking at sites your audience already uses — but don't clone direct competitors.

**Limit your choices — define systems in advance.** Unlimited options make every minor decision torture (12px or 13px? 10% or 15% shadow opacity? 24px or 25px avatar?), because with continuous values there is always more than one right choice. Pre-define constrained scales and pick from them; the hard work of choosing values happens once, not on every element.

**Designing by process of elimination** (works for any systematized property):
1. Guess the best value from the scale (say 16px for an icon).
2. Try the adjacent scale values on either side (12px, 24px).
3. If both neighbors are obviously worse, the middle wins — done.
4. If a neighbor wins, re-center on it and compare again.

Properties to systematize (minimum set — extend whenever a low-level decision recurs):

| | | |
|---|---|---|
| font size | font weight | line height |
| color | margin | padding |
| width | height | box shadow |
| border radius | border width | opacity |

You don't have to define everything up front — approach design with a system-focused mindset and never make the same minor decision twice.

## ch-2 — Hierarchy is Everything {#ch-2}

**Visual hierarchy** — how important elements *appear* relative to one another — is the single biggest factor in making something feel "designed". When everything competes for attention, the UI reads as noise; deliberately de-emphasizing secondary/tertiary content fixes it without touching color scheme, font, or layout.

**Size isn't everything.** Relying on font size alone yields primary text too large and secondary text too small. Use weight and color instead:
- Text colors: **dark** for primary content, **grey** for secondary, **lighter grey** for tertiary — two or three colors total.
- Font weights: **400–500** for normal text, **600–700** for emphasis — two weights are usually enough.
- **Never use weights under 400 for UI text** — illegible at small sizes; de-emphasize with lighter color or smaller size instead.

**Don't use grey text on colored backgrounds.** Grey-on-white works because it *reduces contrast*, not because grey is special. On a colored background, literal grey looks wrong, and `white + reduced opacity` looks dull/disabled and lets background images bleed through. Fix: hand-pick a color with the **same hue as the background**, adjusting saturation and lightness until contrast is right.

**Emphasize by de-emphasizing.** When the main element won't pop and there's nothing left to add to it, soften its competitors instead: give inactive nav items a quieter color; if a sidebar competes with the content area, remove its background color entirely and let content sit on the page background.

**Labels are a last resort.** The naive `label: value` format gives every datum equal emphasis and kills hierarchy.
- Format often communicates type without a label: `janedoe@example.com` is an email, `(555) 765-4321` a phone number, `$19.99` a price.
- Context often suffices: "Customer Support" under a name in an employee directory needs no "Department:" label.
- **Combine labels into values** when format/context isn't enough:

  ```
  before: In stock: 12        after: 12 left in stock
  before: Bedrooms: 3         after: 3 bedrooms
  ```
- When labels are genuinely needed (multiple similar data points that must scan, e.g. dashboards), treat them as supporting content: smaller, lower contrast, lighter weight — some combination of all three.
- Exception — when users scan *for the label* (tech-spec pages: they hunt for "depth", not "7.6mm"), emphasize the label: darker label, slightly lighter value. Don't over-de-emphasize the value; it's still the information.

**Separate visual hierarchy from document hierarchy.** Pick heading tags (h1–h6) for semantics, style them for visual hierarchy. Section titles usually act as *labels*, not headings — they should be small; the section's content is the focus. Taken to the extreme: keep the title in markup for accessibility but hide it visually when content speaks for itself.

**Balance weight and contrast.** Bold reads as emphasized because it covers more surface area. Solid icons are "heavy" the same way and over-emphasize themselves next to text — you can't reduce an icon's weight, so reduce its **contrast** (softer color) as a counterbalance. Inverse move: a 1px border too subtle in a soft color turns harsh if darkened — **increase its width** instead to add emphasis while keeping the soft look.

**Semantics are secondary.** Every page action sits in a pyramid:

| Tier | Treatment |
|---|---|
| Primary (one per page) | solid, high-contrast background |
| Secondary | outline or low-contrast background |
| Tertiary | link-style |

**Destructive ≠ big/red/bold.** If the destructive action isn't the page's primary action, give it secondary/tertiary treatment; put the big red styling on the confirmation step, where destruction *is* the primary action.

## ch-3 — Layout and Spacing {#ch-3}

**Start with too much white space.** The default workflow (add margin until it stops looking bad) gives elements only the *minimum* breathing room. Instead start with far too much space and remove until satisfied — "a bit too much" per element reads as "just enough" in a full UI. Dense UIs (dashboards) are legitimate but must be a deliberate choice, because missing white space is far less obvious than excess.

**Establish a spacing and sizing system.** "Everything a multiple of 4px" (a linear scale) doesn't help choose between 120px and 125px. What matters is *relative* difference between adjacent values:
- 12px → 16px = **+33%** — a big, visible jump (icon size, button padding).
- 500px → 520px = **+4%** — imperceptible (card width, hero spacing) — eight times less significant.
- Rule: **no two adjacent values in the scale closer than ~25%.**

Build from a sensible base — **16px** (divides cleanly; default browser font size) — using its factors and multiples, packed at the small end and progressively sparser upward. A practical scale:

```
4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 640, 768
```

Payoff: need space under an element? Grab a scale value; not enough? The next one is probably perfect. Faster decisions, plus a subtle consistency that wasn't there before — especially when designing in the browser, where typing numbers beats dragging.

**You don't have to fill the whole screen.** If 600px is optimal, use 600px — spreading content wide makes it harder to interpret; edge space never hurt anyone. Applies per-section too: content needn't be full-width just because the nav is. Struggling with a small UI on a large canvas? **Shrink the canvas**: design mobile-first at ~400px, then expand and fix only what felt compromised. Narrow-optimal content in a wide layout: split into **columns** (form + supporting text) rather than widening the form.

**Grids are overrated.** A grid = constrained percentage-based fluid widths — but many elements should be **fixed-width**. A 25%-wide sidebar wastes space on wide screens and collapses below usable on narrow ones; give the sidebar a fixed width optimized for its content and let the main area flex. Don't use percentages unless you actually want scaling. **Don't shrink an element until you need to**: grid-fraction sizing can make a login card *wider on medium screens than large ones*; instead give it `max-width` at its optimal size and only shrink when the viewport forces it.

**Relative sizing doesn't scale.** Encoding "headline = 2.5em of body" breaks across screen sizes:

```
desktop: 18px body → 45px headline   (2.5×)
mobile:  14px body → 20–24px headline (1.5–1.7×)
```

Same elements, totally different ratio — meaning there was no real relationship to encode. General law: **elements that are large on large screens must shrink faster than elements that are already small**; the size spread compresses at small screen sizes. The same independence applies within a component: button padding defined in em of font-size makes size variants look like zoom artifacts; a large button needs disproportionately *more* padding and a small button disproportionately *less* to actually feel large/small. Fine-tune properties independently per context.

**Avoid ambiguous spacing.** When groups aren't separated by borders/backgrounds, spacing alone signals grouping — so **space around a group must exceed space within it**. Failure cases:
- Stacked form: margin below a label equals margin below its input — labels float ambiguously between fields; at worst users type data into the wrong field.
- Article headings with as much space above as below — the heading should hug the content it introduces.
- Bulleted lists where item spacing equals the line-height of a wrapped item.
- Horizontal component rows where the intra-group gap equals the inter-group gap (e.g. icon+text pairs in a toolbar).

Interfaces that are hard to parse always look worse — this rule is usability and aesthetics at once.

## ch-4 — Designing Text {#ch-4}

**Establish a type scale.** Unsystematized UIs end up using every pixel size from 10–24px somewhere — inconsistent designs, slow workflow. **Modular scales** (ratio-based: 4:5 "major third", 2:3 "perfect fifth", golden 1:1.618) look mathematically pure but fail for UI work twice over:
1. Fractional pixels (16px base × 4:5 → 31.25px, 39.063px, 48.828px) — browsers round subpixels inconsistently; if you must use one, round the values yourself when defining the scale.
2. Too few sizes where UI needs them (rounded 3:4 gives 12, 16, 21, 28 — you'll want something between 12 and 16, and between 16 and 21).

Prefer a **hand-crafted scale**, picked by eye, aligned with the spacing scale:

```
12, 14, 16, 18, 20, 24, 30, 36, 48, 60, 72   (px)
```

**Avoid em for scale definitions**: em is relative to the *current* font size, so nested elements compound — 0.875em inside a 1.25em (20px) parent computes to 17.5px, a value that exists nowhere in your scale. **px or rem only** is the sole guarantee of scale adherence.

**Use good fonts.**
- Safe default: neutral sans-serif, or the system stack: `-apple-system, Segoe UI, Roboto, Noto Sans, Ubuntu, Cantarell, Helvetica Neue`.
- Filter font directories to **≥5 weights** (10+ styles counting italics) — a care-and-quality proxy that cuts ~85% of Google Fonts.
- Optimize for legibility: avoid condensed, short-x-height (headline-purpose) faces for body/UI text.
- Sort by popularity (crowd wisdom) and inspect fonts on well-designed sites you admire.

**Keep your line length in check.** 45–75 characters per line; in CSS, paragraph width of **20–35em** lands in range. When mixing text with wider images/components, keep paragraphs capped even inside the wider content area — mixed widths look more polished, not less.

**Baseline, not center.** Mixed font sizes on one line: align to the shared **baseline**, not vertical centers — baseline is the reference the eye already perceives; centering offsets baselines awkwardly, worst when sizes are close.

**Line-height is proportional.** Line-height exists so eyes can find the next line after the return sweep, therefore: wider content → taller line-height (narrow ~1.5, wide up to ~2); and **line-height is inversely proportional to font size** — small text needs extra leading, large headlines are fine at 1.

**Not every link needs a color.** Paragraph links amid plain text: full treatment (color, maybe underline). Link-dense UIs: full treatment is overbearing — emphasize with heavier weight or darker color. Ancillary links: no default emphasis at all; underline/color on hover only.

**Align with readability in mind.** Text aligns with its language's reading direction — nearly everything left-aligned (for English). Center only headlines/independent blocks of ≤2–3 lines; if a centered block runs long, shorten the copy or left-align. **Right-align numbers in tables** so decimals line up for comparison. Justified text (print-mimicking contexts only) requires **hyphenation enabled** to avoid word-gap rivers.

**Use letter-spacing effectively.** Default: trust the typeface designer. Two exceptions: (1) tighten letter-spacing when using a legibility-optimized font (e.g. Open Sans) for large headlines, mimicking purpose-built headline faces — but never the reverse (headline fonts don't work small even with added spacing); (2) **increase letter-spacing on all-caps text** — uniform-height capitals lack the ascender/descender variety that makes lowercase legible at default spacing.

## ch-5 — Working with Color {#ch-5}

**Ditch hex for HSL.** Hex/RGB make visually related colors look unrelated in code. HSL encodes what the eye perceives:

| Component | Range | Meaning |
|---|---|---|
| Hue | 0–360° | position on the color wheel: 0° red, 120° green, 240° blue |
| Saturation | 0–100% | 0% grey (hue irrelevant) → 100% vivid |
| Lightness | 0–100% | 0% black · 50% pure hue · 100% white |

**HSL ≠ HSB.** In HSB, 100% brightness is only white at 0% saturation (at 100% saturation it equals HSL's 50% lightness). Design tools usually show HSB; **browsers only understand HSL** — for the web, work in HSL.

**You need more colors than you think.** Five-hex palette generators can't build real UIs. Three categories:
- **Greys** — most of any interface (text, backgrounds, panels, form controls): 8–10 shades. Avoid true black (unnatural); start from very dark grey.
- **Primary color(s)** — 1–2 brand/action colors, 5–10 shades each (ultra-light = tinted alert backgrounds; dark = text).
- **Accents** — eye-grabbing highlight colors (yellow/pink/teal) plus semantic states: red destructive, yellow warning, green positive; 5–10 shades each, used sparingly. Categorized data (graph lines, calendar events, tags) needs more. A complex UI commonly needs ~10 colors × 5–10 shades.

**Define your shades up front.** Never generate shades with on-the-fly `lighten()`/`darken()` — that's how you end up with 35 slightly-different blues that all look the same. Fix a scale in advance; **nine shades** divides nicely (100 lightest … 500 base … 900 darkest). Process:
1. **Base (500)**: no science — rule of thumb, a shade that would work as a button background.
2. **Edges**: darkest (900) chosen for its text use; lightest (100) for tinted-background use (an alert component exercises both). Keep the base hue, tune saturation/lightness by eye.
3. **Gaps**: pick 700 and 300 as perceptual midpoints between their neighbors, then 800/600/400/200 the same way.
4. **Greys**: same process, edges first (darkest = darkest text in the project, lightest = subtle off-white background); base matters less.

It's not a science — trust eyes over numbers and tweak shades as real usage reveals problems, but **resist adding off-scale shades**: an undisciplined palette is no system at all.

**Don't let lightness kill your saturation.** Saturation's visual impact weakens as lightness approaches 0% or 100% — so **increase saturation as lightness moves away from 50%** or light/dark shades look washed out.

**Perceived brightness** (per hue, at equal HSL lightness): brightness ≈ √(0.299R² + 0.587G² + 0.114B²). It is non-linear around the wheel — local maxima at yellow 60°, cyan 180°, magenta 300°; minima at red 0°, green 120°, blue 240°. Exploit it when saturation is already maxed: **to lighten, rotate hue toward the nearest bright hue; to darken, rotate toward the nearest dark hue** (e.g. yellow's darker shades rotate toward orange to stay warm/rich instead of dull brown). Keep rotation **≤20–30°** or it reads as a different color; combine with lightness adjustment for best results.

**Greys don't have to be grey.** Practical "greys" are often noticeably saturated — blue for cool temperature, yellow/orange for warm. Remember to increase that saturation at the light/dark ends of the grey scale, or those shades drift back toward neutral and look washed out.

**Accessible doesn't have to mean ugly.** WCAG floors: **4.5:1** contrast for normal text (<~18px), **3:1** for large text. White text on a colored background needs a surprisingly dark background to pass — which then dominates the page. **Flip the contrast**: dark colored text on a light tinted background of the same hue — passes easily, color still present, far less shouty. Colored-on-colored text (secondary text in a dark panel): rather than approaching pure white, **rotate the hue toward a brighter hue** (cyan/magenta/yellow) to gain contrast while staying colorful.

**Don't rely on color alone.** Red/green deltas are invisible to red-green colorblind users — pair color with an icon, label, or shape. Multi-line graphs: differentiate by **light/dark contrast** rather than distinct hues. Color supports what the design already says; it is never the sole channel.

## ch-6 — Creating Depth {#ch-6}

**Emulate a light source — light comes from above.** The door-panel intuition: a raised panel's top edge is lighter (angled toward the sky), its bottom edge darker; an inset panel is shadowed at the top (the lip blocks light) with a lighter bottom edge. Mimic that and the brain does the rest:

| Effect | Edge highlight | Shadow |
|---|---|---|
| **Raised** (button) | lighter top edge: top border or inset shadow, small positive-y offset | small dark drop shadow below, slight vertical offset, *tight* blur (a couple of px — think wall-outlet shadow) |
| **Inset** (well, text input, checkbox) | lighter bottom edge: bottom border or inset shadow, negative-y offset | small dark *inset* shadow at the top, slight positive-y offset |

- Hand-pick the lighter edge color — a semi-transparent white overlay sucks the saturation out of the underlying color.
- **Don't get carried away**: photo-realism makes interfaces busy and unclear; borrow cues from the real world, don't simulate it.

**Use shadows to convey elevation.** Shadow size = virtual z-position = attention (the closer to the user, the more focus it attracts):

| Shadow | Elevation | Typical elements |
|---|---|---|
| small, tight blur | slightly raised | buttons — noticed, not dominant |
| medium | floating above the UI | dropdowns, popovers |
| large, big blur | closest to the user | modals, dialogs |

Define a **fixed elevation system of ~5 shadows**: smallest and largest first, middle filled with a fairly linear size increase. Then never pick shadows aesthetically — ask *where on the z-axis should this element sit?* and assign the matching level. Shadows also signal interaction: enlarge on drag (item pops forward, clearly grabbable), shrink or remove on press (button pushes into the page).

**Shadows can have two parts.** Inspect a really nice shadow and you'll usually find two, each with a job:
1. **Cast shadow** — larger vertical offset, large blur: what a direct light source throws behind the object.
2. **Ambient-occlusion shadow** — small offset, small blur, darker: the area right under the object that even ambient light can't reach.

Two shadows give independent control — keep the big one subtle while the tight one keeps edges defined. **Account for elevation**: the ambient shadow fades as the object rises (try it with anything on your desk) — quite distinct at your lowest elevation level, nearly or completely invisible at the highest.

**Even flat designs can have depth.** Without any shadows: **lighter than the background reads raised, darker reads inset**. Or use a **solid shadow** — short vertical offset, zero blur radius — flat aesthetic preserved, depth communicated.

**Overlap elements to create layers.** Offset a card across the boundary between two background colors; make an element taller than its parent so it overlaps both sides; overlap small controls (carousel arrows) over their content. Overlapping *images*: give each an **invisible border** matching the page background so adjacent images can't color-clash.

## ch-7 — Working with Images {#ch-7}

**Use good photos.** Bad photos ruin otherwise good designs. Either hire a professional or use quality stock (e.g. Unsplash — free). **Never** design around polished placeholder photos expecting to swap in smartphone shots later — it never works.

**Text needs consistent contrast.** Photos have both light and dark regions, so no single text color survives on a raw image. Reduce the image's dynamics (techniques combine):
- **Semi-transparent overlay** — black overlay for light text, white overlay for dark text.
- **Lower the image contrast** itself; adjust brightness to compensate.
- **Colorize**: lower contrast → desaturate → solid fill in *multiply* blend mode (also harmonizes images with brand colors).
- **Text shadow** as subtle glow — large blur, **no offset** — preserves more image dynamics; still pair with mild contrast reduction.

**Everything has an intended size.**
- Scaling bitmaps up → fuzzy. Scaling *vector* icons up doesn't blur but 16–24px-drawn icons blown to 3–4× look chunky and unprofessional (no detail). Fix: keep the icon near intended size, **enclosed in a colored shape** to fill the larger slot.
- Scaling screenshots down ~70% turns 16px UI text into ~4px mush. Fix: screenshot at a smaller layout (tablet), use a partial screenshot, or draw a simplified line-art version (text as bars).
- Scaling detailed icons/logos *down* (favicon case): browser-mushed detail. Redraw a simplified version at the target size so you control the compromises.

**Beware user-uploaded content.** You can't tune what users upload:
- **Control shape and size**: center images in fixed containers and crop (`background-size: cover`) instead of honoring intrinsic aspect ratios that break the layout.
- **Prevent background bleed** (user image background ≈ UI background): use a **subtle inner box shadow**, not a border — borders clash with image colors; a semi-transparent inner border also works if the inset look bothers you.

## ch-8 — Finishing Touches {#ch-8}

**Supercharge the defaults.** Add polish without new elements: bullets → icons (checkmarks/arrows, or domain-specific like padlocks); testimonial quote marks promoted to large colored graphics; links with thick colorful custom underlines partially overlapping the text; custom checkboxes/radios in brand color for selected states.

**Add color with accent borders.** A colored rectangle requires zero graphic-design talent and reads as "designed": across a card's top, under active nav items, along an alert's left edge, as a short underline beneath a headline, or across the top of the whole layout.

**Decorate your backgrounds** (keep contrast with content low in all cases): change a section's background color, or use a slight gradient (**two hues ≤30° apart**); subtle repeating pattern (whole background or one edge); a lone geometric shape or pattern fragment placed in a corner.

**Don't overlook empty states.** For user-generated-content features, the empty state is the user's *first* interaction — a priority, not an afterthought. Include an image/illustration plus an emphasized call-to-action; **hide supporting UI** (tabs, filters) that does nothing until content exists.

**Use fewer borders.** Too many borders = busy and cluttered. Alternatives for separation: **box shadow** (subtler outline), **different background colors** on the adjacent elements (usually sufficient alone), or **extra spacing**. Already have both different backgrounds *and* a border? Delete the border first — you probably don't need it.

**Think outside the box.** Component conventions are habits, not laws: dropdowns can have sections, columns, icons, supporting text; table columns that don't sort can merge related data with internal hierarchy, plus images and color; important radio groups become selectable cards. Ask what the component must *do*, not what it usually looks like.

## ch-9 — Leveling Up {#ch-9}

Two durable practices: (1) in designs you admire, hunt specifically for **decisions you wouldn't have made** (inverted datepicker background, button inside a text input, two-tone headline) — that's where new tools come from; (2) **rebuild favorite interfaces from scratch without dev tools** — diffing your version against the original surfaces the micro-decisions (heading line-height, all-caps letter-spacing, combined shadows) that produce polish.

## Decision rules (summary)

| Trigger (observable in code/diff/plan) | Rule | Rationale | Src |
|---|---|---|---|
| New-app design starts with nav/shell decisions | Design a real feature first | Shell decisions need feature knowledge you don't have yet | ch-1 |
| High-fidelity mock includes features not scheduled to build | Design the smallest shippable version | Implied features block shipping what already works | ch-1 |
| First design pass picks colors | Grayscale first | Forces hierarchy via spacing/contrast/size; color layers on cleanly later | ch-1 |
| Mixed `border-radius` conventions in one UI | Commit to one corner style | Square+rounded mixed almost always looks worse | ch-1 |
| Diff adds a one-off literal (size/space/shadow/radius/opacity) | Pick from a predefined scale | Unlimited values = decision fatigue + inconsistency | ch-1 |
| Hierarchy attempted via font-size alone | Use weight (600–700) and grey steps instead | Size-only ⇒ oversized primary, unreadable secondary | ch-2 |
| `font-weight` < 400 on UI text | Ban sub-400 weights | Illegible small; de-emphasize via color/size | ch-2 |
| Grey or `rgba(255,255,255,.x)` text on colored background | Same-hue hand-picked color, adjusted S/L | Opacity looks disabled and bleeds background through | ch-2 |
| Primary element "won't pop", more styling being added | De-emphasize competitors instead | Softening neighbors creates contrast without noise | ch-2 |
| `Label: value` rendering of data | Drop, or fold label into value ("3 bedrooms") | label:value flattens hierarchy; format/context often suffice | ch-2 |
| Heading styled large because it's an `h1` | Style for hierarchy, tag for semantics | Section titles are labels; content is the focus | ch-2 |
| Solid icon next to text at full contrast | Soften icon color | Icons are weight-heavy; contrast counterbalances | ch-2 |
| Thin border darkened for emphasis | Widen it instead | Width adds emphasis without harshness | ch-2 |
| Destructive button styled as red primary in-page | Secondary/tertiary in-page; red primary on confirm step | Hierarchy over semantics | ch-2 |
| Cramped layout being patched with minimum margins | Start with too much white space, remove | Minimum-to-not-look-bad is below great | ch-3 |
| Spacing scale with adjacent steps <~25% apart | Enforce ≥25% relative steps (16px base) | 12→16 is +33%; 120→125 is noise | ch-3 |
| Element stretched to container just to match | Use `max-width` at optimal size | Unneeded width hurts interpretation | ch-3 |
| Sidebar/panel width as a grid percentage | Fixed width for fixed-purpose elements; flex the content | Fluid sidebars waste or collapse | ch-3 |
| Headline/padding defined as em of body size | Scale properties independently per context | Ratios don't survive screen-size changes | ch-3 |
| Intra-group spacing ≥ inter-group spacing | More space around groups than within | Ambiguous grouping ⇒ misread UI | ch-3 |
| Font sizes off the type scale creeping in | Hand-crafted px/rem scale (12…72) | Modular scales give fractional px, missing sizes | ch-4 |
| `em` used in type-scale definitions | px or rem only | em compounds in nesting, breaks scale | ch-4 |
| Paragraph width unconstrained in wide container | 45–75 chars (20–35em) even inside wider areas | Long lines break the return sweep | ch-4 |
| Mixed font sizes vertically centered on one line | Align baselines | Baseline is the perceived reference | ch-4 |
| One global line-height | Proportional: wide/small-text taller (→2), headlines →1 | Line-height ∝ line length, ∝ 1/font-size | ch-4 |
| Every link fully colored in link-dense UI | Weight/darker color; hover-only for ancillary | Full treatment overbears when everything is a link | ch-4 |
| Numeric table column left-aligned | Right-align numbers | Aligned decimals enable comparison | ch-4 |
| All-caps text at default letter-spacing | Increase letter-spacing | Uniform caps lack distinguishing features | ch-4 |
| New shade via `lighten()`/`darken()`/ad-hoc hex | Fixed shade scale (9 steps, 100–900) defined up front | On-the-fly shades ⇒ 35 near-identical blues | ch-5 |
| Light/dark shades looking washed out | Raise saturation as lightness leaves 50% | Saturation impact decays toward 0/100% L | ch-5 |
| Need lighter/darker at 100% saturation | Rotate hue ≤20–30° toward bright (60/180/300°) or dark (0/120/240°) hue | Perceived brightness varies by hue | ch-5 |
| Text contrast below 4.5:1 (normal) / 3:1 (large) | Meet WCAG; if white-on-color gets too dark, flip to dark-text-on-light-tint | Accessibility floor without hierarchy damage | ch-5 |
| Status/trend communicated by color only | Pair with icon/label; graphs use light-dark contrast | Red/green invisible to colorblind users | ch-5 |
| Shadow implies light from below / inconsistent light | Light top edges + shadow below (raised); dark top inset (inset) | One light source, from above | ch-6 |
| Per-component ad-hoc `box-shadow` values | ~5-step elevation system; choose by z-position | Elevation is meaning, not decoration | ch-6 |
| Single-shadow element looks flat/muddy | Two shadows: soft cast + tight ambient; ambient fades with elevation | Each shadow does one job | ch-6 |
| Icon scaled 3–4× drawn size / full screenshot scaled to ~30% | Keep imagery near intended size (icon in colored shape; partial/smaller-layout screenshot) | Vectors lack detail scaled up; 16px text → 4px mush scaled down | ch-7 |
| User-uploaded images at intrinsic ratio / bleeding into background | Fixed container + `cover` crop; inner box shadow, not border | Layout stability; borders clash with image colors | ch-7 |
| UGC feature shipped with unstyled empty list | Designed empty state: illustration + CTA; hide dead controls | Empty state is the first impression | ch-8 |
| Borders as the default separator everywhere | Try shadow, background change, or spacing first | Border-dense UIs read busy | ch-8 |

## Anti-patterns

- **Designing the shell first** — detection: first mocks/tickets are nav bar, sidebar, logo placement before any feature screen exists. (ch-1)
- **Hand-picked magic values** — detection: diff introduces `13px`, `margin: 18px`, `opacity: .12` matching no project scale/token. (ch-1)
- **Size-only hierarchy** — detection: stylesheet varies only `font-size` across text roles; single weight, single color. (ch-2)
- **`label: value` dumping** — detection: template renders DB fields as `<label>: <value>` rows with uniform styling. (ch-2)
- **Reduced-opacity white on color** — detection: `color: rgba(255,255,255,.6)` (or grey) over a colored/image background. (ch-2)
- **Big red delete everywhere** — detection: destructive buttons styled as primary on list/detail pages, not just confirmations. (ch-2)
- **Grid slavery** — detection: fixed-purpose elements (sidebars, cards) sized in column percentages; element shrinks although space exists. (ch-3)
- **Proportional-scaling faith** — detection: component size variants derived purely by multiplying one base (em padding, `2.5em` headlines). (ch-3)
- **Ambiguous spacing** — detection: computed margin within a group equals or exceeds margin between groups (label/input, list items, headings). (ch-3)
- **Modular-scale purity** — detection: type scale with fractional px values (31.25px) or visible gaps where sizes are needed. (ch-4)
- **`lighten()`/`darken()` on the fly** — detection: preprocessor/`color-mix()` calls generating shades at use-sites instead of referencing a palette. (ch-5)
- **Five-hex palette** — detection: theme defines ~5 colors with no shade scales; greys count < 8. (ch-5)
- **Color-only signaling** — detection: success/failure or chart series distinguished exclusively by hue, no icon/label/contrast channel. (ch-5)
- **Photo-realism creep** — detection: stacked gradients/bevels/multi-shadow ornamentation beyond a raised/inset cue. (ch-6)
- **Aesthetic shadow-picking** — detection: shadow values unique per component, no shared elevation tokens. (ch-6)
- **Scaled-out-of-intent imagery** — detection: 16px-drawn icon rendered at 64px; full-page screenshot at 30% width; 128px logo as favicon. (ch-7)
- **Placeholder-photo optimism** — detection: design approved with pro stock imagery where production will receive ad-hoc user/smartphone photos. (ch-7)
- **Border-as-only-separator** — detection: nested borders everywhere, including where backgrounds already differ. (ch-8)
- **Afterthought empty state** — detection: no zero-content design; full tab/filter chrome shown over an empty list. (ch-8)

## Applicability & exemptions

- **Domain scope**: web/product UI design for non-designers building applications. Not print, not brand/marketing design, not game UI; typography advice assumes Latin scripts and left-to-right languages (alignment rule explicitly follows reading direction).
- **Dense UIs are legitimate** (dashboards, data tools): the white-space and "start too spacious" rules yield to deliberate density — the requirement is that density be a *choice*, not a default. Don't flag compact data grids per se.
- **Label emphasis flips** on spec/reference pages where users scan for the label ("depth", "RAM"): emphasizing labels there is correct, not a violation of "labels are a last resort".
- **Weights <400** are acceptable for very large headings — the ban applies to body/UI-size text.
- **em units** are wrong for *type-scale definitions* but explicitly right for *paragraph width* (20–35em tracks font size) — don't over-fire on every `em`.
- **Justified/centered text** are legitimate in print-mimicking or short-block contexts; the rules bound them, not ban them.
- **Grids/fluid widths** are fine for content that genuinely should scale — the rule targets fixed-purpose elements only.
- **Scale discipline** presumes a scale exists; in a codebase with design tokens, "off-scale literal" = not using the token set. Greenfield with no tokens yet → the finding is "define the scale", not "wrong value".
- **Aesthetic-preference rules** (personality table, background decoration, supercharged defaults) are generators for designers, not review criteria — a reviewing agent should not flag their absence.
- The authors repeatedly note "it's not a science" (shade-filling, base-color choice): numeric anchors here (25% spacing steps, 9 shades, 20–30° hue rotation) are strong defaults with eyes-over-math final say — except WCAG contrast, which is a hard floor.

## Candidate lexicon rows

| new CSS declares a raw literal for spacing, font-size, radius, shadow, or color where the project has tokens/scales | **Predefined scales only** — hand-picked one-off values accumulate into inconsistency and re-litigate the same decision every time | Is this value drawn from the project scale/tokens, and if no scale exists, should this diff define one? | should | write | src: refactoring-ui ch-1 |
| text hierarchy in a diff varies only `font-size` across primary/secondary/tertiary roles | **Size isn't everything** — weight (400–500 vs 600–700) and a 2–3-step grey ramp communicate importance better than size alone | Could this hierarchy use weight or text color instead of another font size? | should | review | src: refactoring-ui ch-2 |
| `font-weight` below 400 applied to body- or UI-sized text | **No sub-400 UI weights** — thin weights are unreadable at small sizes; de-emphasis belongs to color or size | Is this thin weight on large display text (fine) or on UI text (replace with lighter color/smaller size)? | should | write | src: refactoring-ui ch-2 |
| grey text, or white/black text with reduced opacity, over a colored or image background | **Same-hue de-emphasis** — grey works on white only because it reduces contrast; on color, opacity looks disabled and lets backgrounds bleed through — hand-pick a same-hue color with adjusted saturation/lightness | Is de-emphasized text sitting on a non-white background via grey or alpha? | should | review | src: refactoring-ui ch-2 |
| template renders data as `Label: value` pairs with uniform styling | **Labels are a last resort** — format or context usually identifies data; fold labels into values ("3 bedrooms") and style any required label as supporting content | Does the user need this label, and if so is it visually subordinate to the data? | judgment | review | src: refactoring-ui ch-2 |
| destructive action styled as the big red primary button on a normal page | **Hierarchy over semantics** — destructive ≠ prominent; in-page it gets secondary/tertiary treatment, and red-primary styling moves to the confirmation step | Is delete/destroy competing with the page's true primary action? | should | review | src: refactoring-ui ch-2 |
| margin within a group equals or exceeds margin between groups (label/input pairs, list items, headings) | **Unambiguous spacing** — spacing signals grouping, so space around a group must exceed space within it or users mis-associate elements | Is every intra-group gap strictly smaller than the surrounding inter-group gap? | should | review | src: refactoring-ui ch-3 |
| fixed-purpose element (sidebar, card, form) sized as a fluid percentage or stretched full-width | **Optimal width, not grid width** — give it a fixed width or `max-width` at its optimal size and shrink only when the viewport forces it | Does this element actually need to scale with the container, or does it have an intended width? | should | write | src: refactoring-ui ch-3 |
| `em` units used to define font sizes in a type scale or nested components | **px/rem for type scales** — em compounds through nesting, producing computed sizes that exist nowhere in the scale | Would this font-size compute off-scale inside a parent with a non-default size? | should | write | src: refactoring-ui ch-4 |
| shade generated at the use-site via `lighten()`/`darken()`/`color-mix()` or a new near-duplicate hex | **Define shades up front** — a fixed 9-step scale (100–900 around a base) per color; on-the-fly derivation breeds dozens of near-identical variants | Does this shade exist in the palette, or is it being invented inline? | should | write | src: refactoring-ui ch-5 |
| state, trend, or chart series distinguished by hue alone; or text contrast below 4.5:1 normal / 3:1 large | **Never color alone, never below WCAG** — pair color with an icon/label or light-dark contrast, and if white-on-color must go too dark to pass, flip to dark text on a light same-hue tint | Does every color-coded signal have a second channel, and does all text meet its contrast floor? | blocker | review | src: refactoring-ui ch-5 |
| `box-shadow` values invented per component instead of referencing shared elevation tokens | **Elevation system** — a fixed ~5-shadow scale mapped to z-meaning (button < dropdown < modal), chosen by where the element sits, not by taste | Which elevation level is this element, and does its shadow come from the shared scale? | should | write | src: refactoring-ui ch-6 |
