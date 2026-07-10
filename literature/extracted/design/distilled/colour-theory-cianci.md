# Colour Theory: Understanding and Working with Colour (Lisa Cianci) — distilled

> **Source**: Dr Lisa Cianci, *Colour Theory: Understanding and Working with Colour* (RMIT Open Press, 2023; CC BY-NC 4.0) · extracted from `../colour-theory-cianci.txt` · distilled 2026-07-09 (spec v1)
> **Contributes**: This lane’s primary **colour systems + meaning** source. **Harmony structures** (mono / analogous / complementary / split-comp / triadic / tetradic); **properties** (hue, saturation/chroma, value, tint/shade/tone, colour bias); **temperature and warm–cool pigment pairs** as mix and spatial tools; **simultaneous / relational colour** (Chevreul → Albers/Itten); **cultural and brand symbolism** (not universal psychology); **language and naming** as thought tools; **additive vs subtractive** and **gamut/media shifts** (RGB/screen ↔ CMYK/print, metamerism); **palette from concept** (brief, symbol, medium, bias) rather than picker roulette. Named concepts: **additive / subtractive colour**, **colour gamut / colour space**, **metamerism**, **simultaneous contrast / relative colour**, **opponent pairs**, **hue–value–chroma**, **tint / shade / tone**, **colour bias**, **harmony schemes**, **spot vs process colour**, **colour grading vs correction**, **accessible colour** (meaning + contrast intent — floors live in eng).

## Chapter map

- ch-1 — Scope boundary (colour meaning lane, not eng shade scales)
- ch-2 — Colour as description: hue, value, saturation/chroma
- ch-3 — Historical systems that still structure design thinking
- ch-4 — Properties toolkit: tints, shades, tones, bias
- ch-5 — Harmony structures (wheel schemes as decision menus)
- ch-6 — Temperature, warm–cool pairs, spatial effect
- ch-7 — Colour interaction: simultaneous contrast and afterimage
- ch-8 — Cultural symbolism and brand colour meaning
- ch-9 — Language, naming, and taxonomies
- ch-10 — Psychology claims vs marketing evidence
- ch-11 — Additive vs subtractive: which system owns the job
- ch-12 — Gamut, media shift, and colour management intent
- ch-13 — Metamerism: same-spec colours that fail in context
- ch-14 — Palette from concept (not from the picker)
- ch-15 — Image colour: grading, skin bias, style as meaning
- ch-16 — Accessibility as colour-system constraint (not eng floors)
- pipeline — Colour decision pipeline (testable checks)
- Decision rules (summary)
- Anti-patterns
- Applicability & exemptions
- Candidate lexicon rows

---

## ch-1 — Scope boundary (colour meaning lane, not eng shade scales) {#ch-1}

This distillate feeds **design-aesthetics heuristics** for **colour systems and meaning**. It does **not** restate engineering UI mechanics already owned by Refactoring UI / eng lexicon: shade-scale generation, step counts, elevation tints, WCAG contrast formula floors, token storage, component state palettes as implementation recipes. Keep the **why a palette exists**, **what hues mean**, **how colours interact**, and **which medium/gamut** — tag borders `↔ eng UI-*`.

| This lane owns | Hand off to eng lexicon |
|---|---|
| Harmony structure choice (mono, analogous, complementary…) | Generating 50–900 shade ramps / `UI-07` |
| Cultural/brand meaning of hue families | CSS variables, design-token files |
| Temperature, bias, relational contrast | Default UI grey/primary ramp recipes |
| Concept → palette process | Component state colour matrices |
| Screen vs print gamut *intent* and proof culture | Build pipeline colour profiles as infra |
| Accessible *palette planning* (hue+value pairs that survive CVD) | WCAG ratio tables and automated a11y gates |

**↔ eng UI-07 (shade scales):** eng owns *how* to store and step values; this source owns *why* a hue family exists, which harmony structure binds the set, and whether tints/shades/tones serve meaning or only UI chrome.

**Textbook note:** Open educational resource — breadth over single-school dogma. Prefer **falsifiable design rules** extracted from history, culture, perception, and media practice; skip quiz/activity scaffolding and pure chemistry curiosities unless they change a design decision.

---

## ch-2 — Colour as description: hue, value, saturation/chroma {#ch-2}

**Colour** (intro definition): visible features of an object described by **hue**, **lightness/value**, and **saturation**. In physics: wavelengths of the **visible spectrum**. Design decisions always act on at least one of these three axes — never “pick a nice hex” without knowing which property is doing the work.

| Property | Definition (keep) | Decision use |
|---|---|---|
| **Hue** | Classification name (“red”, “magenta”, “greenish-yellow”); in physics a wavelength class. Black, white, grey are **not** hues but may be “colours” in practice | Identity family; cultural symbol; harmony position on wheel |
| **Value** (lightness/darkness) | Closeness to white or black; dark green has lower value than pale green | Hierarchy, legibility, 3D form reading, spatial depth |
| **Saturation** | Intensity / colourfulness relative to grey; B&W = zero saturation | Energy vs restraint; trend “muted” vs “vivid” |
| **Chroma** | Absolute colour of the object (CIE framing); high chroma needs strong saturated reflectance | Spec language for materials; do not collapse casually into “saturation” in briefs |

**Rule:** when a mockup “feels wrong,” name the broken axis first — wrong *hue family*, wrong *value structure*, or wrong *chroma energy* — before swapping hexes.

**Munsell frame (still industry-relevant):** colours classified by **hue + value + chroma** with a numbering system spanning art and science. Useful when designers need shared language beyond brand-name poetry (“Elephant’s breath”).

---

## ch-3 — Historical systems that still structure design thinking {#ch-3}

Do not treat colour history as trivia. Each major system encodes a **different primary set** and a **different claim about harmony**.

| Era / author | Claim that still fires | Design implication |
|---|---|---|
| Greek elemental (white/black/red/yellow) | Limited earthy palette as default material reality | Ochre/earth systems as cultural baseline, not “primitive” |
| Ibn al-Haytham / optics | Light required for colour (not eye-rays) | Colour is illumination-dependent — see metamerism |
| Da Vinci / Alberti | Practical primaries for pigment craft | Mixing skills ≠ pure spectral primaries |
| Newton (ROYGBIV, prism) | Spectrum as ordered hue circle seed | Modern wheel geometry |
| Goethe | Colour as **subjective / psychological** experience | Aesthetics and mood as legitimate design material (not only physics) |
| Le Blon | Three-colour print → path to CMYK | Print is subtractive craft from the start |
| Chevreul | Relational colour; side-by-side perception | **Simultaneous contrast** as law of adjacency |
| Maxwell | RGB better light primaries; early colour photo | Screen/digital additive standard |
| Rood | Small dots blend at distance; complementary contrast | Optical mixture / pointillist lesson for UI “dots” and image grain |
| Munsell | Hue–value–chroma solid | Spec and education system |
| Ostwald | Search for scientific **harmony** (pleasant vs not) | Bauhaus / De Stijl influence; harmony as research object |
| CIE / CIELAB | Device-independent perceptual space; human gamut reference | Gamut comparison: LAB ⊃ RGB ⊃ CMYK (typical) |

**Traditional RYB wheel** still appears in arts education and Bauhaus lineage (Itten, Albers). **Modern practice** for screen work uses **RGB** (additive) or **CMY** (subtractive print) as scientifically preferred primaries because they maximise mixture gamut.

**Rule:** when teaching or specifying “primaries,” state **which system** (RYB art-school, RGB light, CMY/K print, or psychological opponent pairs). Mixing systems mid-argument produces false “red+blue=purple always” myths — pigments often yield brown mud.

---

## ch-4 — Properties toolkit: tints, shades, tones, bias {#ch-4}

Operational definitions for palette construction (not eng ramp generation):

| Term | Construction | Effect on purity |
|---|---|---|
| **Tint** | Hue + white | Value toward white; chroma/purity drops |
| **Shade** | Hue + black | Value toward black; chroma/purity drops |
| **Tone** | Hue + grey | Saturation drops; softer, more “designed” neutrals |

**Colour bias:** many “primary” pigments are not pure spectrum hues — a red may bias **orange** or **purple**. Bias explains muddy mixes and is a deliberate palette tool: choose biased partners that share a temperature family.

**Saturation placement on a wheel UI:** intensity often maps as distance from centre (interactive wheel model in the text). Value often has a separate control (shade slider). Treat that as a **mental model**: hue angle + radial chroma + value axis — same three properties, different UI.

**Rule:** a brand “neutral” is usually a **tone** or low-chroma biased grey, not pure `#808080`. Specify bias (warm grey / cool grey) as identity.

↔ eng UI-07: building a 10-step shade scale is eng; deciding that the brand neutral is a **warm tone of umber** rather than pure grey is this lane.

---

## ch-5 — Harmony structures (wheel schemes as decision menus) {#ch-5}

**Colour relationships / schemes** — structural choices for multi-colour palettes. Author definitions (verbatim structure):

| Scheme | Structure | Prefer when |
|---|---|---|
| **Monochrome** | One hue + tints/shades/tones | Strong identity hue; calm systems; photography-forward UIs; fashion/season cohesion |
| **Analogous** | Main hue + neighbours on either side (± further adjacents for 5-colour) | Soft harmony, nature/brand “related family,” low clash risk |
| **Complementary** | Two hues opposite on wheel | Maximum contrast, sports/energy, call-to-action vs field, poster punch |
| **Split-complementary** | Dominant hue + two hues flanking its complement | High contrast with less raw opposition than pure complementary |
| **Triadic** | Three hues equally spaced (triangle) | Balanced multicolour systems (flags, kids brands, festival) — needs value control |
| **Tetradic** | Four hues as rectangle on wheel | Complex multi-product systems; risk of chaos without hierarchy |
| **Quadratic** | Four hues as square (even spacing) | More even tetradic case |

**Harmony is not automatic beauty.** Ostwald sought scientific pleasantness; designers still **assign roles**: dominant, support, accent, neutral. A triadic set with three equal-chroma equals will fight; one low-chroma field + one high-chroma accent is still “triadic-structured” but readable.

**Rule:** pick the **scheme before the hex**. Document: “analogous cool blues–teals with one complementary coral accent at low area ratio.”

**Optical mixture (Rood / Impressionists):** small patches of distinct hues blend at distance into a new perceived colour. Use for texture, data viz dither, and image direction — not as excuse for illegible micro-contrast text.

---

## ch-6 — Temperature, warm–cool pairs, spatial effect {#ch-6}

### Temperature as meaning and mix tool

Association table (author; bidirectional, not universal):

| Family | Common associations (positive/negative both valid) |
|---|---|
| Red | heat, activity, anger, danger, passion, energy |
| Orange | warning, warmth, fun, youth, optimism, excitement |
| Yellow | happiness, warmth, positivity, cheerfulness, compassion |
| Green | calm, serenity, renewal, envy, wealth, abundance |
| Blue | cold/coolness, stability, loyalty, trust, peace, envy |
| Purple | wisdom, power, spirituality, royalty, mystery |
| Pink | love, affection, softness, kindness |
| Brown | practicality, honesty, simplicity, dependability |
| Gold | wealth, luxury, triumph, glamour |
| White | purity, cleanliness, innocence, spirituality |
| Black | elegance, drama, power, death, evil |
| Grey | stability, authority, modernity, mundane, sadness |

**Warm–cool pigment pairing (practical mix kit):** a basic set includes **two reds** (e.g. cadmium = opaque yellowish; alizarin = transparent bluish), **two blues** (Prussian = dark cool transparent; cobalt = intense warm opaque), and warm/cool yellows and greens. Temperature is a **mixing axis**, not only a mood word.

**Rule:** when a mix goes muddy, check **temperature conflict** (warm red + cool blue without shared bias) before blaming “bad art.”

### Spatial / form reading

- **Value** is primary for 3D form: light and shadow tell the brain position in space.
- **Warm vs cool** associations (heat advance / cool recede are traditional craft heuristics) reinforce depth when paired with value — warm high-chroma accents step forward; cool low-chroma fields recede.
- **Relative colour** (next chapter) can invert perceived depth if adjacency is ignored.

**Language bias note:** many languages differentiate warm hues more finely than cool — designers naming systems may over-specify reds and underspecify blues unless deliberate.

---

## ch-7 — Colour interaction: simultaneous contrast and afterimage {#ch-7}

### Relational colour (Chevreul → Albers)

Chevreul’s industrial dye work established that colours **change appearance by adjacency**. Albers: colour changes continually with light, shape, placement, quantity (area or recurrence), and mood/receptiveness.

**Simultaneous contrast / relative colour:** the same patch can read as different hues or values against different grounds (author animation: fixed square, pink→green background shifts perception). The viral dress (blue-black vs white-gold) is the same class of phenomenon under ambiguous illumination.

**Design rules:**

1. **Never approve a brand colour only on white.** Test on product photography, dark mode field, UI chrome grey, and competitor adjacency.
2. **Accent area ratio matters.** A complementary accent at 5% area differs from 40% field fight.
3. **Quantity is a design parameter** (Albers): recurrence of a small hue can equal a large field in perceived importance.

### Opponent process and afterimage

Cone/opponent framing: modern complementary pairs map approximately **red–cyan, green–magenta, blue–yellow** (not only schoolbook red–green / blue–yellow). Staring fatigue produces **afterimages** in opponent colours — useful for understanding why high-chroma full-bleed reds exhaust and why complementary UI accents “vibrate.”

**Chimerical colours** (stygian, self-luminous, hyperbolic): fatigue-induced “impossible” colours outside normal object colours — art/experiment territory; for product design, treat as warning that extreme chroma + afterimage can produce unintended glow or dirtiness.

**Rule:** if two brand colours “hum” or look dirty only when adjacent, you have interaction failure — fix by shifting value, reducing shared saturation, inserting a neutral separator, or changing scheme — not by blaming the monitor alone.

---

## ch-8 — Cultural symbolism and brand colour meaning {#ch-8}

### Symbolism is contextual, not universal

- Element systems (e.g. traditional Chinese: red–fire, yellow–earth, white–metal, black–water, blue–wood) bind colour to cosmology.
- **Rarity → prestige:** Tyrian purple (expensive snail dye) → imperial status; ultramarine (lapis, worth more than gold) → sacred Virgin cloak and celestial meaning.
- **Flags** encode nation/history; Aboriginal flag: black people, red earth, yellow sun; Torres Strait: green mainlands, black people, blue waters, white Dhari/peace, star/navigation.
- **Pride flags** use colour as identity taxonomy — multiple legitimate systems, evolving.
- **Australian Indigenous practice:** ochre material systems; meanings vary by language group; some knowledge restricted. Wider acrylic/digital palettes post-1970s can still map to land intensity — do not flatten to one “Aboriginal colour meaning” chart.

**Rule:** for any identity colour, ask **to whom** and **in which tradition** before locking brand guidelines. Export of a local symbol as global “universal psychology” is a failure mode.

### Brand and logo control

- Colour communicates brand meaning and desired customer perception.
- Iconic product colours (Coca-Cola red, Facebook blue, Cadbury purple…) work by **consistent monopoly of a hue**, not by secret universal emotion maps.
- **Style / brand guides** must specify logo colours, allowed backgrounds, clear space, scale, placement — and **incorrect usage** (RMIT examples: wrong colour versions banned).
- Fast-food red+yellow is cited as appetite stimulation — treat as **marketing pattern**, not physiology law.

**Rule:** identity colour is a **controlled asset**. If a logo may appear in arbitrary gradients or seasonal recolors without strategy, you no longer have identity colour — you have decoration.

---

## ch-9 — Language, naming, and taxonomies {#ch-9}

- Linguistic research: languages differ in colour term inventories (e.g. single blue-green term vs Russian dark/light blue split). Learning a language can alter colour discrimination tasks.
- Gladstone’s “Homeric Greeks had no blue” is **linguistics, not optics** — they saw the spectrum; naming and metaphor differed (“wine-looking sea”).
- **Colour atlases** (Werner / Syme): named colours by natural referents for naturalists when spectral pigment matching was hard — concept still useful: **name by referent** (“storm cloud”, “dry grass”) for cross-team alignment.
- Domain naming: painters (“Prussian Blue”), fashion (“khaki”, “fuchsia”), marketing (“Velvet dream”) — different jobs.
- Idioms (“seeing red”, “green thumb”) carry **figurative** meaning that may not travel across languages.

**Rule:** brand colour names in guidelines should be **stable codes + perceptual description + cultural caveat**, not only poetic marketing labels. Poetic names sell paint; they do not ship products.

---

## ch-10 — Psychology claims vs marketing evidence {#ch-10}

| Claim type | Stance in source | Design use |
|---|---|---|
| Some emotion–colour links may be widely shared | Tentative research; not hard law | Soft priors only |
| Cultural group differences | Explicit | Localise meaning |
| Anecdotal “colour psychology” blogs | Unreliable | Do not cite in brand strategy |
| Marketing / purchase attraction | Stronger evidence base | Competitor colour maps, category codes |
| Jung colour–personality / Myers-Briggs colour types | Pseudoscience / no evidence for career use | Ban from professional rationale |
| Chromotherapy as medical cure | Rejected / fraudulent historically | Do not sell as product claim |
| Evidence-based phototherapy (e.g. neonatal blue light) | Real medical, wavelength-specific | Not brand metaphor |

**Rule:** separate **(a)** cultural symbol, **(b)** category convention, **(c)** perceptual interaction, **(d)** medical physics. Only (b)+(c) plus tested (a) belong in a design decision record.

---

## ch-11 — Additive vs subtractive: which system owns the job {#ch-11}

| System | Primaries | Mix direction | Owns |
|---|---|---|---|
| **Additive** | RGB light | More light → toward white | Screens, pixels, stage light, XR |
| **Subtractive** | CMY (+ K black in print); traditional RYB in art teaching | More material → darker / muddier | Ink, paint, dye, print |

**Memory hook:** additive = mix **light**; subtractive = mix **materials**.

**Cross-link:** mixing two additive primaries yields a subtractive primary (and vice versa) — confusion clears when primaries are chosen for **maximum gamut**, not tradition.

**K in CMYK:** black added because CMY inks do not make a good black; black ink is also cheaper. Extended gamut print may add **OGV** (orange, green, violet).

**Rule:** choose palette **in the medium of delivery**. A neon RGB identity that only lives on OLED will break on CMYK packaging unless you plan dual specs (screen primaries + print/spot fallbacks).

---

## ch-12 — Gamut, media shift, and colour management intent {#ch-12}

**Gamut / colour space:** complete range of colours a device, app, or process can produce or record.

Typical containment (author diagram language): **CIELAB (human-oriented)** larger than **RGB spaces**, which are larger than **CMYK** — conversion loses colour.

| Space | Role | Design note |
|---|---|---|
| **sRGB** | Web/default displays, many games | Safe shared assumption for product UI |
| **Adobe RGB / opRGB** | Wider, especially cyan-greens; print-oriented RGB | Photo/print pipelines |
| **DCI-P3** | Cinema; ~25% more than sRGB; red-yellow rich | Film/HDR-aware image direction |
| **CIELAB** | Device-independent perceptual | Reference / difference detection, not a paint-by-number UI model |
| **CMYK process** | Four-colour print | Photos and continuous tone |
| **Spot / Pantone** | Premixed solid inks | Logos, packaging, metallics, fluorescents, exact brand matches |

**Practical conversion rules:**

- Home printers may auto-convert RGB→CMYK poorly; pro workflows convert with control.
- Edit photographs in **RGB**, not CMYK, for on-screen accuracy and tool support; convert for output.
- **Spot vs process:** process = tiny dots mixing (good photos, bad exact logo sometimes); spot = solid Pantone-like matches; jobs may combine both.
- Hard-copy **Pantone swatches** beat on-screen Pantone previews; refresh physical books as pigments age.
- **Double colour management** (app + printer both “correcting”) can pink the reds — one controlled pipeline.
- **Paper stock** changes appearance — proof on the real stock.
- Screen **calibration** and device variance: you cannot guarantee every user’s display; test multiple devices and older screens.

**Colour depth context:** 24-bit ~16.7M colours common; higher bit depths help extremes of light/dark — secondary to gamut choice for most identity work.

**Hex:** base-16 encoding of RGB for the web — a **notation**, not a separate colour physics.

**Rule:** any brand system that ships **print + screen** needs dual recipes and a proof ritual, not a single hex exported everywhere.

---

## ch-13 — Metamerism: same-spec colours that fail in context {#ch-13}

**Metamerism:** colours match under one illuminant but not another (**illuminant metameric failure**). Matching pairs under those conditions are **metamers**. Different chemistry can look identical under one light (two orange paints: mixed vs single pigment) and diverge under another.

**Observer metameric failure:** colour vision difference / CVD as person-dependent matching failure.

**High-risk colours:** whites, greys, beiges, blacks, pinks, mauves — “all black outfit” fails outdoors when blacks carry different red/green/blue biases.

**Prevention rituals:**

| Domain | Test |
|---|---|
| Fashion / soft goods | Swatch zip, thread, fabric, binding under multiple lights |
| Interiors | Paint pots + carpet samples on site, day and night |
| Digital | Multiple devices; encourage calibrated viewing when colour-critical; accept residual variance |

**Rule:** brand “match” is **illuminant-qualified**. Specify critical viewing conditions for physical products; for digital, design with **tolerance** (value hierarchy and shape still work if hue drifts).

---

## ch-14 — Palette from concept (not from the picker) {#ch-14}

Author flow for trends + aesthetics + wheel tools, inverted into a decision sequence:

### Pipeline: concept → structure → properties → medium → proof

1. **Concept / brief** — product category, audience cultures, competitor map, emotion *targets as hypotheses* not laws.
2. **Symbol audit** — what hues already mean in those cultures and categories; what is taboo or over-owned.
3. **Harmony structure** — monochrome / analogous / complementary / split / triadic / tetradic (ch-5); assign roles (dominant / support / accent / neutral).
4. **Temperature + bias** — warm or cool system; pick biased pigments/hex families that mix cleanly (ch-6).
5. **Value architecture** — light/dark hierarchy for type, UI, or image before chroma thrills (ch-2, ch-6).
6. **Chroma energy** — one high-chroma accent vs overall muted; trends (Pantone CotY etc.) are **optional seasonality**, not identity foundations.
7. **Medium dual-spec** — sRGB web + CMYK/spot print + physical materials; plan losses (ch-11–12).
8. **Interaction test** — adjacent pairs, dark/light grounds, image overlays (ch-7).
9. **Metamerism / multi-device test** (ch-13).
10. **Accessibility pass** — CVD-safe combinations, value contrast intent (ch-16); eng runs ratio gates.
11. **Lock in brand guide** — allowed/forbidden usages (ch-8).

**Trend tools** (Coolors, Adobe Color, Canva, Colormind…): valid for **exploration**, not authority. Image-extracted palettes inherit the image’s concept — good when the concept *is* that image direction.

**Artists’ palettes as systems:** limited sets force relationships; digital analysis of master paintings teaches structure. Prefer **constrained sets** over infinite picker freedom.

**Rule:** if the only rationale for a hex is “the generator liked it,” the palette is not designed.

---

## ch-15 — Image colour: grading, skin bias, style as meaning {#ch-15}

| Term | Meaning |
|---|---|
| **Colour correction** | Fix capture problems; match scenes; remove defects |
| **Colour grading** | Deliberate mood/style: hue, saturation, contrast, shadows, highlights |

Genre conventions exist (teal-orange blockbusters, cold thriller blues…). **Moonlight** example: chapter-wise grades emulating different film stocks (Fuji for skin, Agfa cyan push, modified Kodak) — grade as narrative structure.

**Racial bias in capture standards:** historical Kodak “Shirley cards” optimised light skin; darker skin and even dark product browns were poorly served until market pressure. Modern grading can preserve skin detail under stylised looks — **identity image direction must include diverse skin rendering tests**.

**Rule:** image systems (photography, film stills, product shots) are part of the colour system. Brand guidelines that specify logo hex but ignore grade and skin rendering are incomplete.

---

## ch-16 — Accessibility as colour-system constraint (not eng floors) {#ch-16}

**Accessible colour** = greatest number of people can perceive communicated meaning. Relevant for text, maps, charts, infographics, signage, exhibitions.

Design-methodology frames:

| Frame | Focus |
|---|---|
| **Universal design** | Accessible to everyone by default |
| **Inclusive design** | Explicitly include groups otherwise excluded |
| **Equity-focused design** | Ongoing co-design with minority / specialised communities |

**Colour-system checklist (meaning layer):**

- Value contrast between text and ground (intent; eng measures ratios).
- Hue combinations that remain distinguishable under common **CVD** types (protan/deutan/tritan anomalies and dichromacies; monochromacy rare).
- Space around colour-coded elements — colour alone is not the only channel.
- Size/weight of type as co-channel (type lane + eng).
- Warnings for seizure-risk flashing colour.

**CVD design implication:** red/green coding as sole state channel fails a large male-skewed population. Encode status with value, shape, label, position — colour reinforces.

**Rule:** accessibility is a **palette architecture** constraint from step 1 of ch-14, not a final hex nudge. ↔ eng owns automated WCAG gates; this lane owns not choosing a complementary red/green status system as brand “cleverness.”

---

## pipeline — Colour decision pipeline (testable checks) {#pipeline}

Use on brand identity, campaign, packaging, product UI theme, or image direction reviews:

| # | Check | Pass signal |
|---|---|---|
| 1 | Medium named | Additive screen / subtractive print / pigment / multi |
| 2 | Concept sentence | Non-colour words first (“clinical calm for…”) then colour |
| 3 | Harmony structure named | One scheme + role map |
| 4 | Temperature/bias stated | Warm/cool system + neutral bias |
| 5 | Value hierarchy independent of hue | Greyscale mock still ranks elements |
| 6 | Interaction tested | Accents on real grounds, not only white |
| 7 | Cultural audit | Audience-specific meaning + taboos noted |
| 8 | Dual-spec if needed | Screen + print/spot recipes |
| 9 | Metamerism / multi-device | Physical swatches or multi-screen notes |
| 10 | CVD / non-colour channels | Status not hue-only |
| 11 | Brand lock | Allowed/forbidden documented |
| 12 | No pseudoscience rationale | Claims are culture, category, or perception |

---

## Decision rules (summary)

| Trigger (observable in mockup/brief/asset) | Rule | Rationale | Src |
|---|---|---|---|
| Palette justified only by generator/hex pick | **Concept-first palette** — structure from brief, symbol, medium | Picker output is exploration, not identity | ch-14 |
| Multiple equal-chroma brand colours fight | **Harmony + roles** — scheme then dominant/support/accent/neutral | Structure without hierarchy is noise | ch-5 |
| Brand colour approved only on white | **Relational proof** — test adjacency, image grounds, dark fields | Simultaneous contrast changes hue/value reading | ch-7 |
| Logo recolored arbitrarily | **Controlled identity colour** — guide locks usage | Consistency builds recognition more than “emotion science” | ch-8 |
| Single hex for web and packaging | **Dual medium spec** — RGB/sRGB + CMYK/spot | Gamuts differ; conversion loses colour | ch-11, ch-12 |
| Status encoded only as red vs green | **Non-colour co-channels** — value/shape/label | CVD and interaction failures | ch-16 |
| Neutrals are pure grey by default | **Biased neutrals** — warm/cool tones as identity | Pure grey is a choice, not a neutral fact | ch-4, ch-6 |
| Muddy mixed accents | **Temperature-matched bias** — warm with warm, cool with cool | Pigments are biased, not spectral pure | ch-6, ch-3 |
| Physical materials “match” in one room only | **Metamerism ritual** — multi-illuminant swatch test | Chemistry + light shift matches | ch-13 |
| Psychology blog cited in brand deck | **Evidence triage** — culture, category, perception only | Anecdote and chromotherapy-class claims fail | ch-10 |
| Image grade ignores darker skin | **Inclusive rendering test** — grade across skin types | Historical capture bias is documented | ch-15 |
| “Primaries” argued without system | **Name the primary system** — RGB/CMY/RYB/opponent | Cross-system myths break mixing and UI | ch-3, ch-11 |
| Accent everywhere | **Quantity as parameter** — limit high-chroma area/recurrence | Albers: amount changes perception | ch-7 |
| Trend CotY becomes permanent brand core | **Trend ≠ identity** — seasonal layers over stable structure | Trends move; recognition needs constancy | ch-8, ch-14 |
| Greyscale mock loses hierarchy | **Value architecture first** | Form and reading order live in value | ch-2, ch-6 |
| Print reds shift pink / double correction | **Single colour-management path** + real stock proof | Double CMS and paper alter output | ch-12 |
| Chart uses rainbow hue legend only | **Accessible encoding** — pattern/label + CVD-safe set | Colour-only legends exclude | ch-16 |
| Palette has no named scheme | **Scheme before hex** | Wheel structures are decision menus | ch-5 |
| Brand claims universal emotion for a hue | **Audience-bound meaning** | Symbolism is cultural and historical | ch-8 |
| Designers debate saturation vs chroma loosely | **Property precision** — hue/value/sat/chroma named | Fixes the wrong axis wastes cycles | ch-2 |

---

## Anti-patterns

| Anti-pattern | Detection cue | Fix |
|---|---|---|
| **Picker roulette** | Hexes chosen without scheme/roles | Run concept→harmony pipeline |
| **White-room brand** | All specs on `#fff` only | Relational and photo-ground tests |
| **Gamut denial** | One RGB hex forced to all print | Dual-spec + spot where needed |
| **Psychology astrology** | Jung/MBTI/chromotherapy in rationale | Cut; use culture + category + perception |
| **Red/green only status** | Error/success solely hue-coded | Add value, icon, text |
| **Equal-loud triadic** | Three full-chroma primaries equal area | Role hierarchy; mute supports |
| **Temperature mud** | Warm/cool clash in mixes or UI accents | Align bias families |
| **Metamer black stack** | “Black” materials diverge in daylight | Multi-light match ritual |
| **Double CMS** | App + printer both colour-manage | One controlled path; proof |
| **Shirley default** | Image system only tested on light skin | Inclusive grade tests |
| **Trend core swap** | Annual CotY rebrands the company | Stable core + seasonal accents |
| **Hex as physics** | Treat hex as medium-proof truth | Hex is RGB notation only |
| **RYB absolutism** | Teach only school red-yellow-blue for screens | Name system; use RGB/CMY for media |
| **Accent confetti** | Brand colour sprinkled on every control | Quantity discipline |
| **Universal flag theft** | Sacred/political colours used naively globally | Cultural audit |
| **Shade-scale cosplay** | Design debate only about step count | Return to meaning/harmony; leave steps to eng |

---

## Applicability & exemptions

| Applies strongly | Apply lightly / exempt |
|---|---|
| Brand identity, packaging, campaign systems, marketing sites | Dense product chrome already tokenized in eng |
| Cross-media (screen + print + physical) systems | Single-medium throwaway experiments |
| Image direction, film stills, photography guidelines | Pure data-viz statistical palettes (still use CVD rules) |
| Cultural positioning of colour in product markets | Medical phototherapy device design (different domain) |
| Naming systems for design ops + brand | Eng shade ramp generation recipes |

**Exemptions / limits:**

- **WCAG numeric floors** always bind via eng/a11y process; this text supplies planning intent, not ratio math.
- **Art-only experimental work** may pursue chimerical colour, vibration, and fatigue effects deliberately — still label risk for public product UI.
- **Restricted cultural knowledge** (e.g. some Indigenous meanings) — do not invent universal charts; consult authority holders.
- **Pseudoscience sections** in the source are historical warnings, not techniques to apply.
- **Animal vision / chemistry fireworks** chapters: out of scope for product design rules unless biomimetic brief.

**Contra / adjacency:**

- ↔ eng UI-07 shade scales: eng = *how to step and store*; this = *why the hue family and structure exist*.
- ↔ eng UI contrast/a11y: eng = measurable floors; this = CVD-aware structure and non-colour channels.
- ↔ asymmetric-typography: thrift of accent colour as composition; here full meaning + gamut systems.
- ↔ paula-scher-design / design-indaba: cultural positioning of identity; Cianci supplies colour mechanics inside that positioning.
- ↔ dictionary-of-color-combinations (if distilled later): combinatorial recipes; Cianci supplies theory + media physics.

---

## Candidate lexicon rows

| trigger | rule | activating question | tier | phase | src |
|---|---|---|---|---|---|
| palette from generator without brief structure | **Concept-first palette** — scheme and roles before hex | Can I state the concept without naming colours? | should | colour | colour-theory-cianci ch-14 |
| brand colour only mocked on white | **Relational proof** — adjacency and grounds change colour | Does the hue still hold on photo and dark UI? | blocker | colour | colour-theory-cianci ch-7 |
| one hex for screen and print identity | **Dual-medium colour spec** — plan gamut loss and spot | Where does this colour die in CMYK? | blocker | colour | colour-theory-cianci ch-12 |
| success/error only red/green hue | **Co-channel status** — never hue-only for critical state | Would CVD users still parse state? | blocker | colour | colour-theory-cianci ch-16 |
| equal-chroma multi-colour set | **Harmony roles** — dominant/support/accent/neutral | Which one colour is the identity anchor? | should | colour | colour-theory-cianci ch-5 |
| brand deck cites colour personality tests | **No pseudo colour-psychology** — culture and perception only | Is the claim testable in market or culture? | should | brand | colour-theory-cianci ch-10 |
| physical “matching” colours diverge on site | **Metamerism ritual** — multi-illuminant swatches | Did we check daylight and store light? | should | colour | colour-theory-cianci ch-13 |
| muddy secondary mixes or muddy UI accents | **Temperature-matched bias** — warm/cool families | Are paired hues sharing bias? | should | colour | colour-theory-cianci ch-6 |
| greyscale of mock loses hierarchy | **Value architecture first** — rank without hue | Does hierarchy survive desaturation? | should | colour | colour-theory-cianci ch-2 |
| image system untested on dark skin | **Inclusive grade test** — preserve detail across skin | Whose skin was the pipeline built for? | should | image | colour-theory-cianci ch-15 |
| neutrals default to pure grey | **Biased identity neutrals** — warm/cool tones | Is the grey intentionally temperature-free? | judgment | colour | colour-theory-cianci ch-4 |
| sacred or political colours used as decoration | **Audience-bound symbolism** — audit meaning by culture | To whom does this hue already speak? | should | brand | colour-theory-cianci ch-8 |

---

## Source pairing note

| Adjacent source | Relationship |
|---|---|
| **eng Refactoring UI** | Shade scales, spacing, WCAG floors — cite `↔ eng`; do not duplicate ramps here |
| **Asymmetric Typography** | Colour as sparse compositional accent; Cianci expands full meaning systems |
| **Paula Scher / Design Indaba** | Identity voice and cultural stance; Cianci supplies harmony, gamut, interaction mechanics |
| **Web Typography (Rutter)** | Type colour (density) as grey value of text block — adjacent “colour” metaphor, different object |

Use **Cianci** when deciding **what colour means, how colours interact, and which medium can hold the system**; use **eng** when implementing **tokens, ramps, and contrast gates**.
