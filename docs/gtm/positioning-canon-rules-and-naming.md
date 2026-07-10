# Positioning: Canon Rules (distilled) + AltContext Naming

> **Two deliverables:** (1) three new positioning rules distilled from the positioning literature, formatted for the [heuristics-canon](https://github.com/darce/heuristics-canon) `business-marketing.md` §4 Go-to-Market; (2) how "name your method" applies to AltContext, and whether it's the marketing tagline.
> **Authored:** 2026-07-09.

---

## Part 1 — Canon contribution: positioning rules (GTM-14..16)

**Gap identified** (from the Bidar review): the canon has `[STRAT-05]` (compete from private knowledge) and `[GTM-07]` (name = emotional first line) but **no rule for choosing a positioning frame or owning a named category/method** — the concept the Bidar blog gestured at ("The Framework Formula") but did not originate. The proper sources are the positioning literature. Distilled below in canon row format (`ID | Trigger | Rule | Answers | T·P | Src`).

| ID | Trigger | Rule | Answers | T·P | Src |
| --- | --- | --- | --- | --- | --- |
| GTM-14 | product described by what it *is* (feature list), inheriting a category a competitor defined | **Positioning is a chosen context** — deliberately select the competitive-alternative frame and the best-fit customers for whom your unique attributes are the obvious winning value; positioning is a decision, not destiny | In what frame is our strongest attribute the thing that obviously matters, and to whom? | B·g | obviously-awesome ch-6 |
| GTM-15 | competing on feature-comparison inside a category a rival named | **Design and name the category/method** — name the problem *and* the approach so you set the buying criteria; the category's namer ("king") takes the majority of its economics, not the best feature set | What named category/method can only we own, and does it make our advantage the default criterion? | S·g | play-bigger ch-2 |
| GTM-16 | launch plan advertises a merely-good product to the middle market | **Remarkable or invisible** — build something a niche of early adopters will remark on unprompted; safe-and-boring can't be bought into spread with ad budget; put the marketing *in* the product | What makes an early adopter tell a peer without being asked? | S·g | purple-cow ch-2 |

**Add to canon §8 (cross-source tensions):**
- **Fit-the-frame vs create-the-category**: `[GTM-14]` (Dunford: position inside a context buyers already understand) ↔ `[GTM-15]` (Play Bigger: name a *new* category). Resolution by sequence: position within an understood frame first for comprehension; once you have proof, condition the market toward the new category you name. Premature category-creation with no proof is vanity `[STRAT-08]`.
- `[GTM-16]` (remarkable) reinforces `[GTM-08]` (novelty beats craft on first exposure) and `[STRAT-05]` (private knowledge) — the remark *is* the novelty carried by word of mouth.

**Tier rationale:** GTM-14 is `B` (blocker) — Dunford's thesis is that wrong positioning silently kills good products, an existential/irreversible-if-ignored failure. GTM-15/16 are `S` (strong defaults with judgment exemptions).

### Admission path (important — respects canon governance)
These are **book-sourced**, so under the canon's `DISTILLATION_SPEC` they must be distilled from the source before formal inclusion — the `Src` slugs (`obviously-awesome`, `play-bigger`, `purple-cow`) do **not** yet exist in `distilled/business/`. Two valid routes:
1. **Proper distillation (preferred for durability):** distill the three books into `distilled/business/<slug>.md` per the spec, then PR these rows into `lexicons/business-marketing.md`. This is offload-appropriate grunt work once the source texts are available.
2. **Provisional project use now:** cite `[GTM-14..16]` in *this* project's planning as provisional (marked so), and upstream them after distillation. Do **not** merge un-distilled rows into canon `main` — that would violate the source-faithful contract.

> Recommendation: use provisionally here now; queue the three-book distillation as a separate offload batch before the canon PR.

---

## Part 2 — "Name your method" for AltContext

### The short answer to your question
**No — the named method should NOT be the marketing tagline.** They are two different assets that fail if merged:
- **Tagline / H1** = the *outcome*, in one emotional line a stranger repeats after one read `[GTM-07]`. Leading with a method name is leading with *mechanism over outcome* — the classic conversion mistake (`[AIPX]` outcome-over-output; `[GTM-08]` novelty/benefit first).
- **Named method** = the *ownable, repeatable framework* you teach and repeat everywhere else (How-it-works, docs, content, sales, build-in-public). It's the `[GTM-15]` category/`[STRAT-05]` private-knowledge asset — the thing a code-clone can't claim credibly.

### Applying the three rules to AltContext

**GTM-14 (choose the frame):**
- Competitive alternative buyers currently use: *generic AI captioners* + *manual/empty alt text*.
- Best-fit customer who cares: image-heavy WordPress owners who publish photos of **known people** and carry **accuracy/compliance** stakes (galleries, event orgs, publishers, membership sites, agencies).
- Unique attributes that win *in that frame*: roster recognition, honest confidence, the curation loop that compounds.
- **Frame to claim:** not "AI alt-text generator" (a category rivals own) but **"verified, roster-aware alt text."**

**GTM-15 (name the category + method):**
- **Category to own:** **"Verified Alt Text."** It sets a buying criterion generic captioners fail: *Does your captioner verify **who** is in the photo, and tell you when it's **unsure**?* Every competitor answers "no."
- **Named method (the framework asset):** **The Curated-Accuracy Method** — a 3-step loop:
  1. **Roster** — teach it the people who matter, once.
  2. **Recognize & Flag** — it names them, and honestly flags what it isn't sure of (never bluffs).
  3. **Curate** — your corrections compound; accuracy climbs on *your* library, month over month.
  This *is* the moat narrative (plan §2.1–2.3) turned into an ownable, teachable name.

**GTM-16 (remarkable hook):** the remark you want early adopters to make, unprompted, is *"this one actually knew who was in my photos — and told me when it wasn't sure."* Lead build-in-public with the wrong-caption-caught-by-honest-confidence stories (plan §10, Move 2).

### Concrete copy (drop-in)

```
H1 (unchanged — outcome, emotional):     Alt text that knows who's in the photo.
Sub-head (adds the category frame):      Verified, roster-aware alt text for WordPress —
                                          accurate, accessible, and audit-ready.
Method line (in How-it-works, not H1):   Powered by the Curated-Accuracy Method:
                                          Roster → Recognize & Flag → Curate.
Method block (3 steps, trust section):   1 Roster: teach it your people once.
                                          2 Recognize & Flag: it names them, and says
                                            "not sure" instead of guessing.
                                          3 Curate: your corrections compound — it gets
                                            more accurate on your library over time.
```

### Where the method name earns its keep (not the H1)
- **How-it-works** section (§8 wireframe) — rename the 3 steps to the method.
- **Docs + onboarding** — "the Curated-Accuracy Method" as the mental model.
- **Build-in-public content** (§10) — every accuracy-improvement post is "the Curate step, working."
- **Sales / concierge** — a named method makes the concierge pitch repeatable.
- **The accuracy changelog** (LS-2) — literally the Method's Curate loop, made public.

### Naming hygiene
- Treat "Curated-Accuracy Method" and "Verified Alt Text" as **positioning marks** (use `™`-style, lowercase-in-prose) — not legal claims; a trademark search is a later, cheap step before you lean on them hard. Not legal advice.
- Don't over-invest before proof — naming is a `[GTM-15]` asset, but the persona's failure mode is *rebranding instead of shipping*. Name it once, ship, and let the Curate stories prove it; don't re-litigate the name.

### Plan integration
- Add **D10** to the launch-plan decision log: *category = "Verified Alt Text"; method = "The Curated-Accuracy Method"; method is a supporting asset, not the H1.*
- Feeds: §2 (moat narrative gets a name), §8 (sub-head + How-it-works copy), §10 (content spine), §11 (readme.txt positioning).
