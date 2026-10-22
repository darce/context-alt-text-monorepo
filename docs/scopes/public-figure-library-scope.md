# Scope: Public Figure Library (PFL), pre-built face gallery for news and education tenants

**Intake**: 2026-10-21 · task MAINT-public-figure-gallery-scope-20261021 (to be rehomed to PUBFIG-1) · answers recorded in handoff MCP
**Canon**: heuristics canon v0.26.2
**Status**: DRAFT, revised after planning review PR1 (2026-10-21). Phase 1 is decided by the operator and gated on counsel (§ MVP scope): politicians and living celebrities (athletes included), with auto-name. § Implementation task plans is the input for drafting PUBFIG-2..10.

## Problem

News and education tenants keep hand-labelling the same recurring people: politicians, historical figures and celebrities. The proposal is a vendor-curated face gallery that tenants can enable "out of the box", so suggestions arrive without each tenant building that part of their roster.

## Prior art (handoff semantic search + repo)

- **E15-29 blocker 7.** `infra/oci/demo/seed/README.md` requires public-domain or generated faces for the public demo. celebs01 (111 figures) is real-celebrity photography of unknown licence. **celebs01 must not seed the PFL.**
- **VLM-6 decision 2308.** Operator policy: "private personal images = LOCAL, UNPUBLISHED ONLY; public figures = the only publishable identity corpus." The role split already exists.
- **DEMO-UX-1-D-10 (10025, deferred).** Identifiable celebrities enrolled in a face-recognition demo without consent conflicts with the product's ethics positioning (HAI-05, HAI-09). This was raised and left undecided. P3 (decision 18981) answers it by construction, not by consent. Unlike celebs01, P3 is licensed, targeted, opt-out capable (tombstone), tenant opt-in, and auto-names only in `public_role` context. The public demo stays on public-domain or generated faces (E15-29 blocker 7).
- **GUIDE2IMG-1-LIC-01 (13745).** An unlicensed press photo of public figures was published as an accepted risk. That is the same failure class at small scale.
- **SECREV-1 (2734).** `acx_description_allow_person_names` defaults to false. `SettingsForm.tsx` promises roster-only names (MAINT-CAPTIONCTX-DEBT finding 18947).
- **FIR scope** (`docs/scopes/commercial-face-identity-replacement.md`). The prod embedder, InsightFace buffalo_l, has non-commercial weights. The in-house commercial pipeline is still dev-only.
- **Code seams** (verified 2026-10-21; § Implementation task plans lists every change site).
  - `recognition/application/suggestions/roster_candidates.py::list_roster_candidates` ranks labelled roster clusters against a probe, in memory, on demand. Its only caller is `recognition/interface_adapters/http/routers/suggestions.py::get_roster_candidates`. Its `SimilarityBand` is "never a calibrated probability".
  - `embedding_space.py::models_are_same_space` already fails closed across models (FIR23-01).
  - `recognition/infrastructure/repositories/tenant_entitlement_repository.py::SqlAlchemyTenantEntitlementRepository` gates the entitlement. The tenant's opt-in choices are tenant settings, not entitlement.
  - Naming is gated at two sites. Backend: `scene/application/identity_merge/join.py::load_confirmed_faces` (confirmed, non-`cluster-` label) and `scene/application/identity_merge/policy.py::resolve_naming_allowed` (no `roster_id` means never nameable). Plugin: `DescribeMediaService::build_identity_context` (a face without a confirmed person name counts as machine-only).
- **Market.**
  - AWS Rekognition `RecognizeCelebrities` is open per call. Its legal instrument is contractual, not statutory: the AWS Biometric Notice and Consent Terms make the customer give notice and obtain consent "on behalf of AWS". AWS has still been sued under BIPA over Rekognition (Dorian v. AWS).
  - Google Cloud Celebrity Recognition launched in 2019 with limited availability: vetted media and entertainment customers, professionally produced video, no adding people, celebrities could opt out. Google deprecated it on 2024-09-16 and shut it down on 2025-09-16, for both the Vision and Video Intelligence APIs. No reason was given.
  - Azure celebrity recognition has been under Limited Access since July 2022.
  - The pattern is gated access for media customers, or withdrawal. No statute licenses any vendor to do this; each one carries the same legal exposure.
  - General-purpose captioners already name famous people from pixels, for free. On 2026-09-09, imagecaptiongenerator.com (free, no sign-up, 5 captions per image, UI model label Gemini 3.1 Flash Lite) named Trudeau and Perry in all five captions of the Tribeca photo (`docs/assessments/current/public-guide-caption-baseline-2026-09-09.md`). AltText.ai did not name them that day. On 2026-10-21 it named both people in both guided photos, and autoalt.ai (free online generator) named both in the Tribeca photo. Three free alt-text tools now name these celebrities with no context supplied. Naming famous people is therefore table stakes: it does not differentiate, but its absence is a reason not to adopt AltContext. Today AltContext never names an unrostered face (`scene/infrastructure/vlm/gpu_remote_adapter.py::_SYSTEM_PROMPT`: "Never name or guess about anyone the context does not name"; `scene/application/identity_merge/policy.py::resolve_naming_allowed`), so a new tenant gets "a man in a black suit" where a free tool says "Justin Trudeau". The differentiator remains people no model knows.

## How it would work

1. **Global, read-only gallery** in the recognition service, separate from tenant tables.
   - `pf_identity`: canonical name, Wikidata QID, dated public role(s), inclusion tier (P1, P2, P3, historical), living/deceased, opt-out state, review date.
   - `pf_reference`: source, licence, attribution, sha256, **capture basis** (MLDATA-14), retention expiry (MLDATA-15).
   - `pf_template`: vector, `embedding_model`, `gallery_version`.
   - One gallery per embedding contract (EMB-01). Versions are pinned, and the gallery is rebuilt when the contract changes (EMB-05, IDX-02).
2. **Off by default** (SECD-12). Turning it on needs an entitlement plus a tenant admin opt-in.
   - Entitlement: `SqlAlchemyTenantEntitlementRepository`. Opt-in: a new tenant table `tenant_pfl_settings(tenant_id, enabled_tiers, autoname_tiers, purpose_statement, updated_by, updated_at)`.
   - The admin picks enabled tiers and records a purpose/necessity statement (SECD-13).
   - The tenant gets a subject-facing notice line for their privacy page (SECD-11).
3. **Matching** is one shared core, `list_pfl_candidates(tenant_id, probe, embedding_model)` over `PflGalleryRepository`. Three callers use it (PR1-01).
   - The core applies, in order:
     1. Same-space templates only (`models_are_same_space`).
     2. The active `gallery_version` only.
     3. Tier ∈ the tenant's `enabled_tiers`.
     4. Not minor-flagged, tombstoned or denylisted.
     5. Licence and capture basis non-null.
     6. Not suppressed for the tenant.
   - It returns capped bands. Below the floor the result is unknown (CAL-02). The tenant roster wins at equal band.
   - **Curate, on demand.** `get_roster_candidates` merges PFL candidates into its response with `source: pfl` and `pf_qid`.
   - **Curate, proactive.** A post-clustering job after `cluster_unclustered_identities` writes one existing `name_suggestions` row per (cluster, QID), with `source='pfl'`, `pf_qid` and `suggested_name` as the canonical display name for the review UI. The tenant sees suggestions without asking.
   - **Describe, per image.** After the VLM returns `setting`, the naming step calls the core for each unlinked detected face. This is the only place auto-name can be decided, because the context gate needs `setting`.
   - **Auto-name (operator decision 2026-10-21, decision 18958).** A strong-band match names the person with no acceptance step, but only when all of these hold: the tenant enabled auto-name for that tier; the tier has calibration evidence (criterion 12); the QID is not suppressed for the tenant; and this image's `setting` is `public_role`. Otherwise the match is a suggestion (review reason `pfl_suggestion`). The strong-band ceiling is set for precision (AIPX-07) from FPIR at the served gallery size on news imagery, not from 1:1 FMR.
   - An auto-name is computed per describe and **persists nothing to identity tables** (PR1-08). It records `pfl_auto:<QID>@<gallery_version>` and its band in `naming_provenance`. A later image is decided again on its own context, and a `gallery_version` change cannot leave a stale link.
   - **"Not this person"** writes `pfl_name_suppressions(tenant_id, qid, cluster_id NULL|id)` (PR1-03). A row with no cluster unnames the QID across the tenant; a row with a cluster stops that cluster being suggested or auto-named as the QID. `NamingPolicy` gains `suppressed_qids`, and the matching core filters on both forms. It is written by `reject_name_suggestion` (source `pfl`) and by the describe review action.
4. **Link-on-accept (revised 2026-10-21, decision 18960).** A human accept is the only way a tenant cluster links to a QID. That covers accepting a suggestion, and accepting the name on an auto-named face.
   - `accept_name_suggestion` (source `pfl`) sets `IdentityCluster.pf_qid`, `user_confirmed = true` and `confirmation_source = ConfirmationSource.PFL_ACCEPT`. `label` stays NULL. A tenant's own non-PFL label is never overwritten; that accept is refused.
   - The tenant keeps its face membership, which is its own data, so the curated-accuracy flywheel still accrues to the tenant. The name string is never copied into the tenant roster.
   - Nothing a tenant does writes to PFL tables (PROV-11, PROV-12).
5. **Naming is a separate gate from matching.**
   - Descriptions name a linked identity only when `allow_person_names` is on (CLM-03 keeps the settings promise true).
   - **Every PFL-derived name, linked or auto, needs `setting = public_role` on that image** (PR1-09). Otherwise the face stays generic with review reason `pfl_private_context`. A tenant's own roster persons keep today's behaviour, with no context gate.
   - The reviewer confirms whether the image context is the person's public role (ATTRIB-02, § public/private line).
6. **Opt-out and deletion.** Tombstoning an identity drops its templates, rebuilds the served index (PROV-10), and stops the name resolving for every tenant's later descriptions. Alt text already published stays the tenant's content. A P2 tier exit deletes templates only: the name entry stays, so existing tenant links still resolve.
7. **Audit.** Every PFL query logs tenant, gallery_version and candidate count. This is the controller audit SECD-11 asks for.
8. **Curation is targeted, never scraped.**
   - Build per identity from licensed sources: public-domain historical images, official government portraits, CC images via Wikidata P18 with recorded attribution, or a contracted agency feed. P3 celebrities have no official portraits, so their references come from Commons CC/PD images or an agency feed whose licence explicitly permits biometric templating.
   - Untargeted scraping to build a face-recognition database is prohibited under EU AI Act Art. 5(1)(e).
   - Every reference is human-verified.

### Serving architecture (recommended, 2026-10-21)

```
 OFFLINE BUILD (operator-run)            Postgres schema `pfl` (pgvector HNSW)
 Wikidata QIDs + tiers ─┐                 pf_identity · pf_reference · pf_template
 licensed refs + sha256 ┼─► embed with ─► identity_name · denylist · active_version
 human verify, outliers ┘   PROD model    serving role: SELECT only
   artifact pfl-<model>-<ver> ── load job (blue/green) ──┘
                                              │
              shared core: list_pfl_candidates(tenant, probe, model)
              same-space · active version · enabled tiers · minors/denylist
              · licence+capture basis · tenant suppressions · capped bands
          ┌───────────────────────────┼───────────────────────────────┐
 CURATE (on demand)        CURATE (after clustering)        DESCRIBE (per image, language)
 get_roster_candidates     job → name_suggestions           VLM → caption + setting
 merges source=pfl         (source=pfl, pf_qid)             load_confirmed_faces:
          │                           │                       roster label  → name
          └──── human accept ─────────┘                       pf_qid link   → identity_name[QID, lang]
                     │                                      unlinked face → core → strong band
     IdentityCluster.pf_qid (label NULL,                      + gate passes → pfl_auto (provenance only)
     PFL_ACCEPT); reject → pfl_name_suppressions            every PFL name needs setting=public_role
                                                            → merge_identities → named_draft
```

- **The gallery is a build artifact, not live tables.** An offline pipeline produces `pfl-<embedding_model>-<version>`: identity manifest, provenance, vectors and a sha256. A loader inserts it into a new `gallery_version` and flips `active_version`. Model change means re-embed from stored reference provenance (EMB-01, EMB-05, IDX-02).
- **Isolation is a grant, not discipline.** The serving DB role has SELECT only on `pfl`; tenant code paths cannot write it (PFL-SC-07). Takedown deletes the rows immediately (pgvector HNSW supports deletes) and adds the QID to a denylist the query also checks (PFL-SC-09). Tenant-side PFL state is tenant tables only: `IdentityCluster.pf_qid`, `name_suggestions` rows, `pfl_name_suppressions` and `tenant_pfl_settings`.
- **Matching runs where the data is (PR1-01).** Every path reuses embeddings already stored on `media_identity` (`MediaIdentity.embedding`, `embedding_model`). Describe reads them by the `identity_id`s that `join.py::load_detected_faces` already returns. Each call is one HNSW query per face, milliseconds, with no extra GPU. Nothing about a match is stored at describe time.
- **Two naming sites change together (PR1-02, PR1-05).** The E20-10 guardrail ("machine-only faces are never named") is enforced in the backend and in the plugin. Both change in the same task plan, PUBFIG-6, or one side vetoes or mis-flags what the other names:
  - Backend: `load_confirmed_faces` loads a face confirmed with `pf_qid` (label NULL) and resolves its name from the registry for the request language. `ConfirmedFace` gains `pf_qid`. `resolve_naming_allowed` gains a QID branch: nameable when `agreement_enabled`, the QID is not in `suppressed_qids`, and `setting == public_role`.
  - Plugin: the cluster projection selects `pf_qid` (`ClusterProjectionWriter::upsert_projection_cluster`, `IdentityMembersReadRepository::list_for_media_ids`). `build_identity_context` counts a `pf_qid` face as neither named nor machine-only, so it raises no `identity_unconfirmed`. It adds no item to `IdentityContext.identities`, whose `name` is required. The backend realizes PFL names after the VLM call, through `named_draft`.
  - The VLM prompt rule in `_SYSTEM_PROMPT` stays: the VLM never names anyone unprompted. Both class docblocks record the scoped exception.
- **Names are centrally controlled and localized per language** (operator correction 2026-10-21). The tenant roster stores the QID link, never the name.
  - `pfl.identity_name(qid, language, display_name, source, verified_by, verified_at)` holds one verified form per language, including that language's title convention: Pope Leo XIV / Papa León XIV; Pope John Paul II / Papa Juan Pablo II.
  - Wikidata labels seed it, and an editor verifies each form. Crowd-sourced labels are not an authority (FM-14); Wikidata's Spanish label is "Juan Pablo II", without "Papa".
  - At describe time the name is resolved for the description language: exact locale (es-MX), then base language (es), then the canonical form.
  - A central correction or rename reaches every tenant's next description with no tenant action. Example: Robert Prevost became Pope Leo XIV. One authority owns the name, and every tenant renders from it (DATA-14, REF-45).
  - Gap: describe has no language input today. The plugin sends no locale, and the description service has no language parameter.
  - **English only at launch, built for a quick language add** (operator decision 2026-10-21, decision 18963):
    - Language is an end-to-end parameter from Phase 1 (PR1-06). It is `ContextPack.language`, a BCP 47 tag.
      - The backend field lands first. `ContextPack` is `extra="forbid"`, so a plugin that sent it earlier would get a 422.
      - The plugin's `DescribeMediaService::build_context_pack` then sends it: the WPML/Polylang post language, else the WordPress locale.
      - Because it is inside the context pack, `scene/application/hashing.py::compute_context_hash` covers it. The describe cache (`description_repository.py::get_by_cache_key`, `context_hash`) and the plugin's F-10 predicate (`DescribeMediaService::matches_generated_provenance`, `context_hash`) therefore separate `en` from `fr` with no new key.
      - The resolved language is recorded in `naming_provenance`.
    - `supported_languages = ["en"]` is config. A disabled or unknown language resolves to `en`.
    - The registry is keyed by BCP 47 from day one; launch ships `en` rows only.
    - Adding a language is data plus config: editor-verified rows for every served identity, then one `supported_languages` entry. No code, schema or migration change.
    - Coverage gate: a language is enabled only when every served identity has a verified row, even if it is identical to the canonical form ("Justin Trudeau"). Without the gate, a Spanish sentence gets "Pope Leo XIV". Most rows bulk-confirm from Wikidata; titled roles (popes, monarchs, clergy, nobility) get editor review.
  - A registry edit must reach the next description even on a describe-cache hit. Name realization runs after the cache lookup and reads the registry live (criterion 17 tests this on a cache hit).
- **Size (PR1-07).** N is an output of the FPIR budget, not an input: false positive identification rate grows with gallery size, so call 6 fixes the served N per tier.
  - P1 + P2 is in the low thousands.
  - P3 at a 12-month Wikimedia pageview threshold is plausibly 10–30k identities. At ~5 templates each, that is 50–150k vectors, about 100–300 MB at 512-d float32.
  - HNSW from day one.
  - Pageviews are stored per Wikimedia project (en, fr, es…), so regional notability (fr.wikipedia for Quebec) is a config change.
- **Auto-name (decided 2026-10-21).** Strong-band matches that pass the auto-name gate (§ How it would work, item 3) are named for that describe only, with `pfl_auto` provenance. No link is written (PR1-08). This is an explicit, scoped change to the E20-10 guardrail ("machine-only faces are never named", the `DescribeMediaService` class docblock) and to the SEC-01 describe path, at both naming sites.
- **Context gate.** The describe VLM call also returns `setting: public_role | private | unclear`: a new field on the VLM JSON contract in `gpu_remote_adapter.py::_SYSTEM_PROMPT`, carried on `scene/application/description_adapter.py::AdapterResult`. A missing or invalid value is `unclear`. Only `public_role` allows any PFL name, auto or linked. `private` and `unclear` leave the face generic with a review reason. Example: the Tribeca red carpet allows auto-name; the Coachella noodles photo does not. The gate carries the most weight for P3: a performance, red carpet, premiere, match or press event is the public role, while street, family, beach and home photos are private even for a celebrity (Campbell).
- **Legal gate before Phase 1.** BIPA has no public-figure exception, and GDPR Art. 9 applies to templates of public figures. Counsel decides the population and geography bounds before any template is built. For P3, counsel also covers the right of publicity (naming in alt text is not endorsement or commercial use, but confirm per jurisdiction).

## The public/private line (distilled corpus)

Sources:
- Berle, *Face Recognition Technology: Compulsory Visibility*, ch. 7 §7.6 and ch. 11 §11.6: Campbell v MGN, von Hannover v Germany, Murray v Express.
- `benchmarks/reports/fir-gtm-legal-research-20260723.json`.
- Dutch DPA Clearview decision on Art. 9(2)(e).
- OPC Canada PIPEDA Findings #2021-001.

The core distinction is that **there are two separate questions, and fame answers only the second.**

1. **May we hold a biometric template of this person?** This is a data-protection question, and fame barely helps.
   - GDPR Art. 9 treats face templates as special-category data whoever the person is.
   - The Dutch DPA rejected "manifestly made public" (Art. 9(2)(e)) for online photos, especially photos posted by third parties.
   - The OPC (Clearview, 2021) held that publicly accessible images are not "publicly available" for the consent exception, and that facial biometrics need express consent.
   - BIPA has no public-figure exemption.
   - The journalism exemption (Art. 85) is set by each member state and attaches to the controller doing journalism, not to a vendor building a gallery for everyone.
   - **Exception that matters:** GDPR does not apply to deceased persons (Recital 27). PIPEDA permits disclosure 20 years after death or 100 years after the record. Counsel should verify both.
2. **May this caption name this person in this image?** This is a publication question.
   - von Hannover criteria: contribution to a debate of general interest, notoriety, prior conduct, content, form and consequences of the publication, and the circumstances of the photo.
   - Campbell (Hale, ¶154–155): celebrities "are not anonymous, but their personal lives are private". Context turned a street photo into private information.
   - Murray: a public figure's child is not a public figure.

**The line, operationalised:**

| Axis | Public (may be in PFL / may be named) | Private (never in PFL / never auto-named) |
| --- | --- | --- |
| Who (inclusion tier) | Deceased historical figures. **Politicians in the current news cycle** (operator decision 2026-10-21): (P1) current national heads of state/government, cabinet ministers, national legislators, governors/premiers and big-city mayors in supported countries, via Wikidata P39 with no end date; (P2) any adult current or former officeholder or declared candidate whose trailing-30-day news salience is above a threshold, e.g. Trudeau, a former PM who is still in the news. **Living celebrities** (operator decision 2026-10-21, decision 18981, table stakes): (P3) living adults famous through a voluntary public career (entertainment, music, film/TV, sport, arts, media, business) above a notability threshold, e.g. Katy Perry. Notability is Wikimedia pageviews over a trailing 12 months (decision 18983); the threshold value comes from the call-6 FPIR budget. Athletes above the threshold are P3 (decision 18983); team rosters cover the rest. | Minors, including child performers. Relatives of public figures without independent notability. Involuntary or one-time newsmakers (victims, bystanders, viral subjects). Anyone who opted out. |
| What (image context) | The image depicts the public role: podium, chamber, official event, performance, archival record. | Family, medical, home, holiday, religious or recovery settings (Campbell, von Hannover), even if the person is famous. |
| Why (tenant purpose) | News, education, archive captioning of the tenant's own media library, with a recorded purpose (SECD-13, MLDATA-16). | People search, open "who is this" lookups, marketing, monitoring. |
| When (decay) | Role is current, salience is current (P2 enters on threshold and exits after 90 days below it), notability is current (P3 is re-checked at each editorial review date), or historical and deceased. | Limited-purpose fame that has faded. A weekly salience job removes P2 identities that have exited and deletes their templates (data minimisation). The name entry and existing tenant QID links stay. |

## GTM fit verdict

**Parity requirement for news and education, not a differentiator.** (Revised 2026-10-21, decision 18952; the earlier verdict was "partial fit, not a launch feature".)

- **Parity.** Free alt-text tools name famous people out of the box (see Prior art). A news or education evaluator who uploads a photo of a head of government or a famous entertainer and gets no name will choose the free tool. The operator ruled that missing celebrities disqualifies the product (decision 18981). Table-stakes items get built even when they add no margin (PROD-15).

- **Against.**
  - The launch ICP is professors working on lecture diagrams. `pricing-2026-10-08/strategy.md` says recognition "is not the central value proposition" there.
  - The same doc requires identity to stay "optional, scoped to a customer-authorized roster, and subject to review". A vendor gallery is not customer-authorized unless the tenant explicitly opts in to scoped tiers.
  - A shared gallery is a commodity that AWS sells per call, not the moat. The moat in the launch plan (§2) is tenant-curated labels.
  - The ~$83/mo time-saved math does not carry a standalone add-on, so this must be bundled, not upsold.
- **For.**
  - It removes the empty-roster cold start for news (100–1,500 images/mo), archives, and history/civics course material.
  - Link-on-accept turns gallery hits into tenant roster faces; the name stays central.
  - It fits "Roster → Recognize & Flag → Curate" if framed as a *starter roster from a licensed library*.
- **Positioning risk.**
  - "Celebrity recognition" invites the Clearview question that DEMO-UX-1-D-10 already raised.
  - Copy must say "suggests names from a licensed public-figure library for your review", never "identifies anyone" (CLM-01, CLM-02).
- **Validate before inventory.** Curating and licensing the gallery is inventory. Micro-test the offer and land 2–3 same-segment reference customers first (GTM-02, GTM-14, CARD-06).

## Alternatives considered (SECD-13)

1. **Source-metadata naming, with no biometrics.** Wire and agency photos often carry IPTC "Person Shown" or caption names. The plugin today only *writes* IPTC ImageRegion XMP (`src/media/class-xmp-image-region-packet-builder.php`, `class-image-xmp-writer.php`; VLM-6 bridge). It has no reader, so Phase 0 needs one (PR1-13). This honours the source's identity decision (ATTRIB-05). **Measure its coverage before building a gallery.**
2. **Wrap AWS RecognizeCelebrities.**
   - Rejected for core use: it sends tenant images to a new subprocessor and uses a separate embedding space, so it cannot rank alongside the tenant roster.
   - It is also open-ended celebrity scope and priced per call.
3. **Status quo: manual tenant roster.** This is the baseline the PFL must beat on net identification time.
4. **VLM-native suggestion, then roster enrolment (recommended first cut).** This is how the free tools do it: the VLM already knows famous faces.
   - Relax our own VLM prompt rule ("Never name or guess about anyone the context does not name", `gpu_remote_adapter.py::_SYSTEM_PROMPT`) for a suggestion channel only. The model proposes a name with a `model_suggested_identity` review reason, and the name is never published unconfirmed.
   - One confirmation links the face to a registry QID, so later photos are named by the existing roster match. A VLM-proposed name that does not resolve to a registry QID is not used: names stay centrally controlled (FM-14).
   - It needs no vendor gallery, no licensing inventory and no new subprocessor. The only templates stored are the tenant's own roster, which exists today.
   - Risks: misnaming lookalikes and uneven accuracy across skin tones. Confirm-before-publish and the PFL-SC-12 fairness slices still apply.
   - **First disconfirmer (STRAT-02):** does AltContext's own VLM name Trudeau and Perry in the two guided photos once that prompt rule is relaxed? Unverified. If it does not, only option 1 or the PFL gallery gives parity.

## MVP scope (phased; PROD-18, PROD-45)

Reordered 2026-10-21 (decision 18958): politicians are the parity gap, so they come first.

- **Phase 0. Metadata-first naming.** No biometrics. It ships in parallel and is no longer a go/no-go gate.
  - Add an IPTC/XMP person-name reader (`Iptc4xmpExt:PersonInImage`, ImageRegion names), then surface those names as suggestions.
- **Phase 1. Public Figures Library: politicians (P1 + P2) and living celebrities (P3), with auto-name.**
  - Living current and former officeholders and candidates in the news cycle, built from official portraits and licensed sources.
  - Living celebrities above the notability threshold (decision 18981). This is table stakes: without it the Tribeca photo names Trudeau and leaves Perry generic, while free tools name both.
  - Restricted to verified news and education tenants. Auto-name is per tenant and per tier, behind calibration evidence.
  - Gated on counsel memos: EU AI Act Art. 6 classification (the Commission lists "facial recognition for media archives" under Annex III 1(a)), a DPIA, BIPA/CUBI geo-policy, Quebec biometric-database disclosure, and right of publicity for P3.
- **Phase 2. Historical Figures Library.** Deceased persons, public-domain references, curriculum and archive identities. Same pipeline; lower legal exposure (GDPR Recital 27).

## Assumptions

- The commercial embedding model will be the production space before any PFL ships. Shipping a commercial gallery on buffalo_l weights is the risk to avoid (CARD-26).
- Wikidata QID is the identity key. Tier assignment is a human editorial decision recorded per identity with a review date.
- The tenant is the controller of its own media and its QID links. The vendor is the controller of the PFL and the name registry.

## Success criteria

Each criterion maps to an eval case in `public-figure-library-evals.json`.

1. Default-off. Without entitlement and opt-in, zero PFL candidates are returned.
2. Same-space. Mismatched `embedding_model` yields zero PFL candidates, fail-closed.
3. A null or unrecognised capture basis or licence is never served.
4. Out-of-tier, minor-flagged or opted-out identities are never served.
5. Below the floor returns unknown. The possible band is suggestion-only. The strong band auto-names only when the auto-name gate passes (tenant setting, tier enabled, tier calibrated, `public_role` context); otherwise it is a suggestion.
6. The tenant roster outranks the PFL at equal band, and a PFL name never overwrites a tenant's own (non-PFL) person label.
7. No tenant probe, accept or edit writes to PFL tables, and nothing crosses tenants.
8. Link-on-accept stores the QID and provenance on the tenant cluster, never a name string.
9. Tombstone or opt-out removes the identity's templates from the served index and stops its name resolving in later descriptions for every tenant.
10. Linked PFL identities are not named when `allow_person_names` is false. In the plugin, a `pf_qid` face is not counted as machine-only and carries no name in the context pack.
11. Every PFL query is audit-logged.
12. FMR/FNMR per skin-tone slice is within the parity bound on the gallery population and on news imagery before a tier is enabled (FAIR-07, FAIR-08, COL-10). This is offline, on the VM.
13. A served `gallery_version` matches the active model contract, and stale versions are refused.
14. Every auto-named face carries `pfl_auto` provenance (QID, gallery_version, band) and writes nothing to identity tables. `private`/`unclear` context never yields a PFL name, linked or auto.
15. "Not this person" writes a `pfl_name_suppressions` row. A tenant-wide row unnames the QID in the tenant's later descriptions; a cluster row stops that cluster being suggested or auto-named as the QID.
16. P2 news-cycle lifecycle: entry above the salience threshold, exit after 90 days below it, and templates deleted on exit; P1 membership follows Wikidata P39 end dates.
17. Names resolve from the registry for the description language (exact locale, then base language, then canonical). A registry edit changes the next description for every linked tenant, including on a describe-cache hit.
18. Adding a language needs only registry rows and a `supported_languages` entry; no code or schema change. A language below full verified coverage cannot be enabled, and a disabled language resolves to `en`.
19. P3 celebrity tier: a living adult, athletes included, above the 12-month Wikimedia pageview threshold with a voluntary public career is served. Minors, relatives without independent notability, and involuntary newsmakers are never served, even above the threshold. A P3 auto-name requires `public_role` context like every tier.

## Not doing

- Influencers, entertainers or athletes below the P3 notability threshold. They come via tenant or team rosters.
- Minors, relatives of public figures, one-time newsmakers.
- An open "who is this person" API, or search over images outside the tenant's library.
- Non-English description text. This scope adds the `language` parameter and the name half only; the VLM output language is a separate i18n scope that reuses the same parameter.
- Auto-naming below the strong band, in `private`/`unclear` context, or for an uncalibrated tier. Confidence shown as probability.
- Writing tenant data back into the global gallery, or cross-tenant learning.
- Seeding from celebs01 or any scraped or unlicensed set.
- Pricing it as a standalone recognition upsell.
- Video.

## Canon validation (v0.26.2)

| ID | Rule | Verdict for this design |
| --- | --- | --- |
| SECD-12 | Biometric opt-in default | Off by default plus a tenant opt-in (§2). |
| SECD-13 | Necessity-proportionality gate | Purpose statement, alternatives (§Alternatives), tiered scope, review date. |
| SECD-11 | Compulsory-visibility notice | Tenant notice line plus PFL query audit. |
| MLDATA-14 | Capture basis is a column | `pf_reference.capture_basis`. Null is refused on the match path. |
| MLDATA-15 | Every identity store carries a retention maximum | Expiry plus disposal on `pf_reference`. |
| MLDATA-16 | Bound face-search scope | Tiers plus the "Who" axis define the population. P3 is bounded by a notability threshold and the voluntary-career test, not by occupation lists alone. |
| MLDATA-17 | Removing names does not de-identify a face | Tombstone drops templates, not just names. |
| PROV-10, PROV-11, PROV-12 | Deletion reaches rebuilt artifacts; a derived copy inherits access controls; consumers are scoped to purpose | No write-back. Link-on-accept. Purpose bound per tenant. |
| DATA-14, REF-45 | No dual writes; one authored source, rendered per consumer | One name registry. Tenants hold QID links and render per language. |
| FM-14 | Literary warrant before admit | Every localized form is editor-verified; Wikidata labels only seed it. |
| EMB-01, EMB-05, IDX-02 | One space, pinned versions, rebuild on contract change | One gallery per model contract, versioned. |
| CAL-02, CARD-03, AIPX-07 | Unknown is valid; precision-first | Capped bands, abstain below the floor. |
| HITL-14 | Familiar is not unfamiliar | Reviewer guidance: familiarity is not verification. |
| FAIR-07, FAIR-08, COL-10 | Subgroup monitoring; know your algorithm; inclusive grade test | Success criterion 12 before any tier goes on. |
| ATTRIB-02, ATTRIB-05 | Captions explain or falsify identity; honour source identity decisions | Naming gate. Metadata-first Phase 0. |
| CLM-01, CLM-02, CLM-03 | Claims are products; cost asymmetry; the policy is a contract | "Suggests from a licensed library" copy; the settings promise holds. |
| CARD-26 | Licence provenance is transitive | Per-reference licence row. No buffalo_l commercial gallery. |
| GTM-02, GTM-14, CARD-06 | Micro-test the offer; reference customers first; evidence before commitment | Calibration evidence per tier before auto-name is enabled for it. |
| STRAT-03 | Circle of competence | Legal questions go to counsel (§8), not agent judgement. |

**Canon gap:** no row distinguishes public from private figures, or biometric processing from publication. Candidate row for the maintainer: "Fame licenses publication, not templating", sourced from Berle ch. 7.

## Open operator calls

1. ~~Pilot segment~~ Decided 2026-10-21: news-cycle politicians first (decision 18958).
2. The gallery licence source for Phase 1: official portraits only, or a contracted agency feed. P3 has no official portraits, so it needs Commons CC/PD or an agency feed whose licence permits biometric templating.
3. Engage EU/US/CA privacy counsel now; it gates Phase 1.
4. Launch jurisdictions, and whether to geo-gate IL/TX.
5. P3 half decided 2026-10-21: notability is Wikimedia pageviews over a trailing 12 months, and athletes are included (decision 18983). The threshold value is bound to call 6. Still open: the P2 salience source and threshold. Recommended: Wikimedia pageviews over a trailing 30 days, one pipeline for both tiers. GDELT news mentions are the alternative.
6. The FPIR bound that sets the auto-name ceiling per tier. P3 enlarges the served gallery, so the ceiling is computed at the served N.
7. ~~Whether living entertainers (Perry) get a tier~~ Decided 2026-10-21: living celebrities are P3 in Phase 1, table stakes (decision 18981).
8. ~~Launch languages~~ Decided 2026-10-21: English only, with i18n built in (decision 18963).
9. Whether a tenant may override a language form for its style guide (e.g. "León XIV" without "Papa"). Recommended: no in Phase 1. If allowed, overrides are tenant-side rows keyed by (tenant, QID, language) and never write the registry.

## Implementation task plans

Each plan below becomes one `docs/tasks/` plan under PUBFIG-1. Paths are relative to `apps/prototype-description-service/` unless they start with `apps/`. The evals file maps every case to its plan (`task_plan`). Each plan runs RED then implementation (§ Dispatch), with slices of 1–3 files.

**Dependency order:**
1. PUBFIG-2.
2. PUBFIG-3, PUBFIG-5 and PUBFIG-8, in parallel.
3. PUBFIG-4.
4. PUBFIG-6.
5. PUBFIG-7 and PUBFIG-9.

PUBFIG-10 waits for curation. PUBFIG-11 runs in parallel throughout.

**Release gate:** PFL stays off for every tenant until PUBFIG-6 and PUBFIG-7 are both merged, criterion 12 passes for the tier, and the counsel memos exist. Default-off (criterion 1) makes intermediate merges safe.

### PUBFIG-2. Gallery schema, enums, repository, artifact loader

- **Change sites.**
  - New `db/models/pfl.py`: schema `pfl` with `PfIdentity`, `PfReference`, `PfTemplate`, `PfIdentityName`, `PfDenylist`, `PfGalleryVersion` (`active` flag), and per-project pageview columns on `PfIdentity`.
  - New `db/models/pfl_tenant.py`: `TenantPflSettings` and `PflNameSuppression`.
  - `db/models/identity.py::IdentityCluster`: add `pf_qid` (nullable). Replace the free `confirmation_source` strings with a `ConfirmationSource` StrEnum that adds `PFL_ACCEPT`, and extend `valid_confirmation_source`.
  - `db/models/constraints.py::NameSuggestion`: add `pf_qid` (nullable). Add a `NameSuggestionSource` StrEnum that adds `PFL`, and extend the source CHECK.
  - `db/migrations/versions/001_identity_schema.py`: all of the above, plus an HNSW index on `pf_template.vector` and a SELECT-only grant on `pfl` for the serving role.
  - New `recognition/infrastructure/repositories/pfl_gallery_repository.py::PflGalleryRepository` (read).
  - New `scripts/pfl/load_gallery_artifact.py`: verify the sha256 and manifest, insert a new `gallery_version`, flip `active`.
- **Criteria.** 3 (null licence or capture basis is not loadable), 7 (the grant), 13 (one active version per model).
- **Proof.**
  - Schema tests.
  - The loader rejects a bad sha256 or a null licence.
  - An INSERT as the serving role is denied.

### PUBFIG-3. Matching core, opt-in gate, audit

- **Change sites.**
  - New `recognition/application/pfl/candidates.py::list_pfl_candidates(tenant_id, probe, embedding_model)`. It applies the § How it would work item 3 filter order and returns capped bands, using `embedding_space.py::models_are_same_space` and `SimilarityBand`.
  - Opt-in reads `TenantPflSettings`; entitlement reads `SqlAlchemyTenantEntitlementRepository`.
  - Each query writes one `db/models/observability.py::AuditEvent` row: tenant, gallery_version, candidate count.
- **Criteria.** 1, 2, 3, 4, 11, 13, and 19 (the serving-exclusion half).
- **Proof.** `recognition/tests/unit/test_pfl_candidates.py`, `test_pfl_audit.py`, `recognition/tests/api/test_pfl_isolation.py`.
- **Depends on** PUBFIG-2.

### PUBFIG-4. Curate: suggestions, link-on-accept, suppression

- **Change sites.**
  - `recognition/interface_adapters/http/routers/suggestions.py::get_roster_candidates`: merge `list_pfl_candidates` results with `source: pfl` and `pf_qid`. The tenant roster wins at equal band.
  - New `recognition/application/pfl/suggest_job.py`: after `orchestration/clustering/orchestrator.py::cluster_unclustered_identities`, write `name_suggestions` rows with `source=PFL`, `pf_qid` and the canonical name.
  - `recognition/infrastructure/services/suggestion_extension_service.py::accept_name_suggestion`: the `pfl` branch sets `pf_qid`, `user_confirmed` and `PFL_ACCEPT`, and leaves the label NULL. It refuses if the cluster has a non-PFL label.
  - `reject_name_suggestion`: the `pfl` branch writes `PflNameSuppression`.
- **Criteria.** 6, 7 (no PFL write on accept or reject), 8, and 15 (the write half).
- **Proof.** `recognition/tests/api/test_pfl_accept.py`.
- **Depends on** PUBFIG-3.

### PUBFIG-5. Name registry, language parameter, coverage gate

- **Change sites.**
  - New `scene/application/identity_merge/pfl_names.py::resolve_pfl_name(session, qid, language)`: exact locale, then base language, then canonical.
  - `supported_languages` config. A language is enabled only at full verified coverage; a disabled or unknown language resolves to `en`.
  - `scene/interface_adapters/http/schemas/requests.py::ContextPack`: add `language` with BCP 47 validation. This lands first.
  - Then `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php::DescribeMediaService::build_context_pack` sends it: the WPML/Polylang post language, else `get_locale()`.
- **Criteria.** 17 (the resolver half), 18.
- **Proof.**
  - `scene/tests/test_pfl_name_resolution.py`.
  - A context-hash test shows `en` ≠ `fr`.
  - A PHPUnit test for the context-pack language.
- **Depends on** PUBFIG-2.

### PUBFIG-6. Describe naming, backend

- **Change sites.**
  - VLM `setting`: `scene/infrastructure/vlm/gpu_remote_adapter.py::_SYSTEM_PROMPT` and its JSON parsing, and `scene/application/description_adapter.py::AdapterResult.setting`. Missing means `unclear`. The prompt's never-name rule is unchanged.
  - `scene/application/identity_merge/merge.py::ConfirmedFace`: add `pf_qid`.
  - `join.py::load_confirmed_faces`: load `pf_qid` faces and name them via `resolve_pfl_name`.
  - `policy.py::NamingPolicy`: add `suppressed_qids` and `setting`. `resolve_naming_allowed` gets the QID branch.
  - `policy.py::NamingProvenance` / `InjectedName`: add `pf_qid`, `gallery_version`, `band` and the resolved language.
  - `naming_preview_service.py::load_fusion_naming_inputs`: load QID suppressions, then run auto-name for unlinked faces through a scene-side `PflCandidateSource` Protocol. The describe router wires recognition's `list_pfl_candidates` into it; scene/application does not import recognition.
  - Review reasons `pfl_suggestion` and `pfl_private_context` go on `scene/application/fusion/reconcile.py::ReviewReason`.
- **Criteria.** 5, 10, 14, 15 (the naming half), 17 (cache-hit half), and 19 (the auto-name half).
- **Proof.** `scene/tests/test_pfl_naming.py`.
- **Depends on** PUBFIG-3, PUBFIG-4 and PUBFIG-5.

### PUBFIG-7. Describe naming, plugin guardrail

- **Change sites.**
  - `apps/prototype-wp-alt-context/src/sovereign/repositories/class-cluster-projection-writer.php::ClusterProjectionWriter::upsert_projection_cluster` and `class-identity-members-read-repository.php::IdentityMembersReadRepository::list_for_media_ids`: project and select `pf_qid`.
  - `DescribeMediaService::build_identity_context`: a `pf_qid` face is neither named nor machine-only.
  - The `DescribeMediaService` class docblock and the `policy.py` module docstring: record the scoped E20-10 exception.
- **Criteria.** 10 (the PHP case).
- **Proof.** `apps/prototype-wp-alt-context/tests/Unit/DescribeMediaServicePflTest.php`.
- **Depends on** PUBFIG-2 (the column) and PUBFIG-6 (the semantics).

### PUBFIG-8. Lifecycle and curation tooling

- **Change sites.** New `scripts/pfl/`:
  - `tombstone.py`: delete templates, add to the denylist, drop names from resolution.
  - `sync_p1.py`: Wikidata P39 with no end date.
  - `salience_p2.py`: weekly; entry above the threshold, exit after 90 days below, templates deleted on exit.
  - `notability_p3.py`: 12-month Wikimedia pageviews per project; living, adult, voluntary-career flags; editorial review date.
  - `pf_reference` retention expiry sweep.
  - Timers in `systemd/`.
- **Criteria.** 9, 16, and 19 (the membership half).
- **Proof.** `recognition/tests/unit/test_pfl_lifecycle.py`.
- **Depends on** PUBFIG-2.

### PUBFIG-9. Admin settings and review UI

- **Change sites.** `apps/prototype-wp-alt-context/js/admin/`:
  - The PFL opt-in panel: tiers, auto-name per tier, purpose statement, the notice line to copy.
  - A source chip on `pfl` suggestions.
  - The "Not this person" action.
  - The `SettingsForm.tsx` naming copy, which must stay true (CLM-03).
  - Every string through `wp.i18n` (sr-012).
- **Criteria.** No new criterion. Acceptance is a ux-map pass (map, render, critique, target ASCII) before the ADR.
- **Depends on** PUBFIG-3 and PUBFIG-4.

### PUBFIG-10. Offline fairness benchmark

- **Change sites.** A VM/GPU benchmark under `benchmarks/`: FMR/FNMR per skin-tone slice, at the served N, on news imagery.
- **Criteria.** 12. Its output sets the call-6 FPIR ceiling and N per tier.
- **Depends on** PUBFIG-2 and a curated gallery.

### PUBFIG-11. Phase 0 metadata names (parallel)

- **Change sites.**
  - A plugin IPTC/XMP person-name reader beside `src/media/class-image-xmp-writer.php`.
  - Names surface as suggestions with source `metadata`. This needs a `NameSuggestionSource` value, so it waits for PUBFIG-2's enum or adds it.
- **Criteria.** None in this suite. It gets its own small eval when planned.
- **Gate.** Measure coverage on news imagery first (Alternatives, item 1).

## Dispatch (per task plan, after operator calls)

1. **RED lane** `pubfig-<n>-red`.
   - Owned paths: that plan's test files only, from `recognition/tests/{unit,api}/test_pfl_*.py`, `scene/tests/test_pfl_*.py` and `apps/prototype-wp-alt-context/tests/Unit/*Pfl*Test.php`.
   - It writes the failing tests for that plan's evals cases.
   - It is done when the tests collect and fail.
2. **Implementation lane** `pubfig-<n>-impl`, dispatched after the RED commit.
   - It owns that plan's change sites only and may not edit RED tests.
3. **Curation workstream** (data, not code):
   - The P1 QID list.
   - The P2 salience inputs.
   - The P3 notability list: living, adult, voluntary public career, above the 12-month pageview threshold.
   - Licence vetting.
   - Editorial tier review.
   - `en` registry rows.
