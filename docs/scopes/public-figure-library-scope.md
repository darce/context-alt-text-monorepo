# Scope: Public Figure Library (PFL), pre-built face gallery for news and education tenants

**Intake**: 2026-10-21 · task MAINT-public-figure-gallery-scope-20261021 (to be rehomed to PUBFIG-1) · answers recorded in handoff MCP
**Canon**: heuristics canon v0.26.2
**Status**: DRAFT, revised after planning review PR1 (2026-10-21), then revised for **public figures on by default** (operator direction 2026-10-21, § How it would work item 2), then revised after review gate 1 (2026-10-22: one eligibility gate for linked and unlinked paths, PUBFIG-8/9 in the release gate, API contract owners, FM-14 warrant). Phase 1 is decided by the operator and its release is gated on counsel (§ MVP scope): politicians and living celebrities (athletes included), with auto-name. Every operator call is decided (§ Operator calls). § Implementation task plans is the input for drafting PUBFIG-2..11.

## Problem

News and education tenants keep hand-labelling the same recurring people: politicians, historical figures and celebrities. The proposal is a vendor-curated face gallery that tenants can enable "out of the box", so suggestions arrive without each tenant building that part of their roster.

## Prior art (handoff semantic search + repo)

- **E15-29 blocker 7.** `infra/oci/demo/seed/README.md` requires public-domain or generated faces for the public demo. celebs01 (111 figures) is real-celebrity photography of unknown licence. **celebs01 must not seed the PFL.**
- **VLM-6 decision 2308.** Operator policy: "private personal images = LOCAL, UNPUBLISHED ONLY; public figures = the only publishable identity corpus." The role split already exists.
- **DEMO-UX-1-D-10 (10025, deferred).** Identifiable celebrities enrolled in a face-recognition demo without consent conflicts with the product's ethics positioning (HAI-05, HAI-09). This was raised and left undecided. P3 (decision 18981) answers it by construction, not by consent. Unlike celebs01, P3 is licensed, targeted, opt-out capable for the subject (tombstone) and for the tenant (one switch), and auto-names only in `public_role` context. The public demo stays on public-domain or generated faces (E15-29 blocker 7).
- **GUIDE2IMG-1-LIC-01 (13745).** An unlicensed press photo of public figures was published as an accepted risk. That is the same failure class at small scale.
- **SECREV-1 (2734).** `acx_description_allow_person_names` defaults to false. `SettingsForm.tsx` promises roster-only names (MAINT-CAPTIONCTX-DEBT finding 18947).
- **FIR scope** (`docs/scopes/commercial-face-identity-replacement.md`). The prod embedder, InsightFace buffalo_l, has non-commercial weights. The in-house commercial pipeline is still dev-only.
- **Code seams** (verified 2026-10-21; § Implementation task plans lists every change site).
  - `recognition/application/suggestions/roster_candidates.py::list_roster_candidates` ranks labelled roster clusters against a probe, in memory, on demand. Its only caller is `recognition/interface_adapters/http/routers/suggestions.py::get_roster_candidates`. Its `SimilarityBand` is "never a calibrated probability".
  - `embedding_space.py::models_are_same_space` already fails closed across models (FIR23-01).
  - `recognition/infrastructure/repositories/tenant_entitlement_repository.py::SqlAlchemyTenantEntitlementRepository` gates the entitlement. The tenant's PFL choices (the switch, tiers, auto-name) are tenant settings, not entitlement.
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
2. **Public figures on by default; private recognition stays opt-in** (operator direction 2026-10-21: the market now names public figures by default). The canon reading is a partition by object and by sequence, recorded as a contextual judgment (§ Canon validation, SECD-12 row):
   - **Object: private faces keep SECD-12.** The tenant roster, clustering and `acx_recognition_enabled` stay off until the tenant opts in (`apps/prototype-wp-alt-context/src/settings/class-recognition-policy.php::RecognitionPolicy::DEFAULT` stays `false`).
   - **Object: PFL tiers default on.** SECD-12 binds "when choice is product-real". The operator ruled that a product without public-figure names is disqualified (decisions 18949, 18981), so an off default is not a real choice for this object. The tenant opt-in never protected the pictured person, who has no choice either way. The person's protections are kept: tier bounds (MLDATA-16), subject opt-out (item 6), the `public_role` gate (item 5), the subject notice and audit (SECD-11), and editor review before publish (SECD-14).
   - **Sequence: the system default stays deny** (SECD-05). A server setting `PFL_ENABLED` defaults to `false` and stays off until the release gate passes (§ Implementation task plans). Every failure path fails to no PFL name: the flag is off, the gallery is unreachable, the version is stale, or the jurisdiction is held or unknown.
   - **Surface: held jurisdictions stay off.** `tenant_pfl_settings.jurisdiction` is an ISO 3166-2 code captured at onboarding (e.g. `US-IL`, `CA-QC`). A config list `pfl_held_jurisdictions` turns PFL off there, and an unknown jurisdiction counts as held. The list starts with every jurisdiction that has a biometric statute or special-category regime: US-IL, US-TX, US-WA, EU/EEA, UK and CA-QC. It shrinks only on a counsel answer (§ Operator calls, call 4).
   - **Tenant control.** `tenant_pfl_settings(tenant_id, jurisdiction, enabled_tiers, autoname_tiers, updated_by, updated_at)`. With no row, every released tier is enabled with auto-name on. One switch turns PFL off and is as easy as turning it on (SECD-08), with per-tier detail behind it. The first PFL-named draft a tenant sees carries a one-time notice naming the switch, so turning it off is never a hunt.
   - **Entitlement.** Every plan, trial included, grants PFL by default through `SqlAlchemyTenantEntitlementRepository`. It is bundled, never an upsell (§ Not doing).
   - **One eligibility decision gates every PFL path** (SECD-05, SEC-01). `recognition/application/pfl/eligibility.py::resolve_pfl_eligibility(tenant_id)` returns `PflEligibility(open, enabled_tiers, autoname_tiers)`.
     - It is open only when `PFL_ENABLED` is on, the tenant is entitled, its jurisdiction is neither held nor unknown, and the tenant has not switched PFL off. `enabled_tiers` is the released tiers (criterion 12) ∩ the tenant's tiers. Any read failure returns closed.
     - It is evaluated per request and never cached. A describe-cache hit evaluates it again, as name realization does (item 5).
     - Every PFL path reads it: unlinked matching (the core, item 3), linked naming (item 5), on-demand candidates and the proactive job (item 3), and listing or accepting pending `pfl` suggestions (item 4). Closed means no PFL candidate and no PFL name, linked or auto; pending `pfl` suggestions are hidden and cannot be accepted.
     - A linked identity is nameable only while its recorded tier is in `enabled_tiers`. A P2 tier exit keeps the tier and the name entry (item 6), so an exited P2 link still resolves while P2 is enabled. A tombstone, an opt-out or turning P2 off stops it.
   - **Purpose (SECD-13).** The vendor sets the default, so the vendor holds the necessity record in the DPIA. Tenant terms bind use to captioning the tenant's own library (MLDATA-16). There is no per-tenant purpose statement.
   - **Notice (SECD-11).** The vendor publishes a subject-facing notice page: the tiers, the sources, and an opt-out request route that feeds tombstoning (item 6). Tenants also get a notice line for their privacy page.
   - **Probe retention is zero when private recognition is off** (MLDATA-15). Describe then detects and embeds faces in-request through `recognition/application/embedding/detector.py::FaceDetectorProtocol.detect`, matches the PFL, and discards every probe vector. It writes no `media_identity` row. The curate paths in item 3 need clusters, so they run only for tenants with private recognition on.
3. **Matching** is one shared core, `list_pfl_candidates(tenant_id, probe, embedding_model)` over `PflGalleryRepository`. Three callers use it (PR1-01).
   - The core applies, in order:
     1. `resolve_pfl_eligibility` is open (item 2).
     2. Same-space templates only (`models_are_same_space`).
     3. The active `gallery_version` only.
     4. Tier ∈ the eligibility's `enabled_tiers` (released and enabled by the tenant; default: every released tier).
     5. Not minor-flagged, tombstoned or denylisted.
     6. Licence and capture basis non-null.
     7. Not suppressed for the tenant.
   - It returns capped bands. Below the floor the result is unknown (CAL-02). The tenant roster wins at equal band.
   - **Curate, on demand.** `get_roster_candidates` merges PFL candidates into its response with `source: pfl`, `pf_qid`, `cluster_id` null, and the `suggestion_id` of the pending (cluster, QID) `name_suggestions` row when one exists. A candidate without a row is shown but not committable, like an unmapped roster candidate today.
   - **Curate, proactive.** A post-clustering job after `cluster_unclustered_identities` writes one existing `name_suggestions` row per (cluster, QID), with `source='pfl'`, `pf_qid` and `suggested_name` as the canonical display name for the review UI. It also runs once per tenant over existing unlinked clusters when a new `gallery_version` goes active, so clusters made before the gallery get suggestions. The tenant sees suggestions without asking.
   - **Describe, per image.** After the VLM returns `setting`, the naming step calls the core for each unlinked detected face. This is the only place auto-name can be decided, because the context gate needs `setting`.
   - **Auto-name (operator decision 2026-10-21, decision 18958).** A strong-band match names the person with no acceptance step, but only when all of these hold: auto-name is on for that tier (the default; the tenant can turn it off); the tier has calibration evidence (criterion 12); the QID is not suppressed for the tenant; and this image's `setting` is `public_role`. Otherwise the match is a suggestion (review reason `pfl_suggestion`). The strong-band ceiling is set for precision (AIPX-07) from FPIR at the served gallery size on news imagery, not from 1:1 FMR (call 6).
   - **An auto-name lands only in a draft.** The plugin has no publish-without-review path: an editor applies every description. That apply step is the human review SECD-14 requires for a high-harm false match, so the draft marks each PFL name with its source. A future no-review publish path must not carry PFL names.
   - An auto-name is computed per describe and **persists nothing to identity tables** (PR1-08). It records `pfl_auto:<QID>@<gallery_version>` and its band in `naming_provenance`. A later image is decided again on its own context, and a `gallery_version` change cannot leave a stale link.
   - **"Not this person"** writes `pfl_name_suppressions(tenant_id, qid, cluster_id NULL|id)` (PR1-03). A row with no cluster unnames the QID across the tenant; a row with a cluster stops that cluster being suggested or auto-named as the QID. `NamingPolicy` gains `suppressed_qids`, and the matching core filters on both forms. It is written by `reject_name_suggestion` (source `pfl`) and by the describe review action.
4. **Link-on-accept (revised 2026-10-21, decision 18960).** A human accept is the only way a tenant cluster links to a QID. That covers accepting a suggestion, and accepting the name on an auto-named face. With private recognition off there is no cluster to link, so accepting an auto-name only keeps it in that draft.
   - `accept_name_suggestion` (source `pfl`) sets `IdentityCluster.pf_qid`, `user_confirmed = true` and `confirmation_source = ConfirmationSource.PFL_ACCEPT`. `label` stays NULL. A tenant's own non-PFL label is never overwritten; that accept is refused. It is also refused while PFL eligibility is closed (item 2).
   - The tenant keeps its face membership, which is its own data, so the curated-accuracy flywheel still accrues to the tenant. The name string is never copied into the tenant roster.
   - Nothing a tenant does writes to PFL tables (PROV-11, PROV-12).
5. **Naming is a separate gate from matching.**
   - Descriptions name a linked identity only when `allow_person_names` is on (CLM-03 keeps the settings promise true).
   - A linked QID is named only while PFL eligibility is open for this request and the identity's tier is in `enabled_tiers` (item 2). An accepted link never outlives the switch, the flag, the entitlement or the jurisdiction.
   - **Every PFL-derived name, linked or auto, needs `setting = public_role` on that image** (PR1-09). Otherwise the face stays generic with review reason `pfl_private_context`. A tenant's own roster persons keep today's behaviour, with no context gate.
   - The reviewer confirms whether the image context is the person's public role (ATTRIB-02, § public/private line).
6. **Opt-out and deletion.** Tombstoning an identity drops its templates, rebuilds the served index (PROV-10), and stops the name resolving for every tenant's later descriptions. Alt text already published stays the tenant's content. A P2 tier exit deletes templates only: the name entry and tier stay, so existing tenant links still resolve while P2 is enabled (item 2).
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
              resolve_pfl_eligibility(tenant): per request, fails closed,
              gates every path below (unlinked, linked, curate, accept)
              shared core: list_pfl_candidates(tenant, probe, model)
              same-space · active version · enabled tiers · minors/denylist
              · licence+capture basis · tenant suppressions · capped bands
          ┌───────────────────────────┼───────────────────────────────┐
 CURATE (on demand)        CURATE (after clustering)        DESCRIBE (per image, language)
 get_roster_candidates     job → name_suggestions           VLM → caption + setting
 merges source=pfl         (source=pfl, pf_qid)             load_confirmed_faces:
          │                           │                       roster label  → name
          └──── human accept ─────────┘                       pf_qid link + eligible, tier on → identity_name[QID, lang]
                     │                                      unlinked face → core → strong band
     IdentityCluster.pf_qid (label NULL,                      + gate passes → pfl_auto (provenance only)
     PFL_ACCEPT); reject → pfl_name_suppressions            every PFL name needs setting=public_role
                                                            recognition off → in-request probe, vectors discarded
                                                            → merge_identities → named_draft
```

- **The gallery is a build artifact, not live tables.** An offline pipeline produces `pfl-<embedding_model>-<version>`: identity manifest, provenance, vectors and a sha256. A loader inserts it into a new `gallery_version` and flips `active_version`. Model change means re-embed from stored reference provenance (EMB-01, EMB-05, IDX-02).
- **Isolation is a grant, not discipline.** The serving DB role has SELECT only on `pfl`; tenant code paths cannot write it (PFL-SC-07). Takedown deletes the rows immediately (pgvector HNSW supports deletes) and adds the QID to a denylist the query also checks (PFL-SC-09). Tenant-side PFL state is tenant tables only: `IdentityCluster.pf_qid`, `name_suggestions` rows, `pfl_name_suppressions` and `tenant_pfl_settings`.
- **Matching runs where the data is (PR1-01).** Every path reuses embeddings already stored on `media_identity` (`MediaIdentity.embedding`, `embedding_model`). Describe reads them by the `identity_id`s that `join.py::load_detected_faces` already returns. Each call is one HNSW query per face, milliseconds, with no extra GPU. Nothing about a match is stored at describe time.
  - Exception: a tenant with private recognition off has no stored embeddings. Describe then runs the shared face pipeline in-request (`FaceDetectorProtocol.detect`, admitted through `face_pipeline_adapter.py::FacePipelineAdmissionGate`) and discards the vectors (§ How it would work, item 2). That costs one detect-and-embed per described image; criterion 20 proves nothing persists.
- **Two naming sites change together (PR1-02, PR1-05).** The E20-10 guardrail ("machine-only faces are never named") is enforced in the backend and in the plugin. Both change in the same task plan, PUBFIG-6, or one side vetoes or mis-flags what the other names:
  - Backend: `load_confirmed_faces` loads a face confirmed with `pf_qid` (label NULL) and resolves its name from the registry for the request language. `ConfirmedFace` gains `pf_qid` and the identity's tier. `resolve_naming_allowed` gains a QID branch: nameable when this request's PFL eligibility is open, the identity's tier is in its `enabled_tiers`, `agreement_enabled` holds, the QID is not in `suppressed_qids`, and `setting == public_role`. Eligibility is evaluated after the describe-cache lookup, like the registry read.
  - Plugin: the cluster projection selects `pf_qid` (`ClusterProjectionWriter::upsert_projection_cluster`, `IdentityMembersReadRepository::list_for_media_ids`). `build_identity_context` counts a `pf_qid` face as neither named nor machine-only, so it raises no `identity_unconfirmed`. It adds no item to `IdentityContext.identities`, whose `name` is required. The backend realizes PFL names after the VLM call, through `named_draft`.
  - The VLM prompt rule in `_SYSTEM_PROMPT` stays: the VLM never names anyone unprompted. Both class docblocks record the scoped exception.
- **Names are centrally controlled and localized per language** (operator correction 2026-10-21). The tenant roster stores the QID link, never the name.
  - `pfl.identity_name(qid, language, display_name, source, warrant_sources, verified_by, verified_at)` holds one verified form per language, including that language's title convention: Pope Leo XIV / Papa León XIV; Pope John Paul II / Papa Juan Pablo II.
  - **Literary warrant (FM-14).** A row is verified only when `warrant_sources` cites at least three published authoritative sources that use that form, in that language, for that person. Qualifying sources: a national-library or VIAF/ISNI name authority record, the person's official or office page, and a published reference work, style guide or major news outlet in that language. Each source must refer to the same person (the authority record links the QID, or the editor confirms it); a spelling match for someone else is rejected.
  - Wikidata labels and Wikidata's external identifiers (authority IDs, official website) seed the candidate form and its candidate sources. They are not a warrant source themselves: crowd-sourced labels are not an authority, and Wikidata's Spanish label is "Juan Pablo II", without "Papa". An editor confirms each row against its cited sources.
  - An identity without a verified canonical (`en`) row is not served, so warrant coverage bounds the served N like the 3-reference rule (call 2).
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
    - Adding a language is data plus config: verified, warranted rows for every served identity, then one `supported_languages` entry. No code, schema or migration change.
    - Coverage gate: a language is enabled only when every served identity has a verified row (three warrant sources), even if it is identical to the canonical form ("Justin Trudeau"). Without the gate, a Spanish sentence gets "Pope Leo XIV". Seeding pre-fills the form and candidate sources from Wikidata; titled roles (popes, monarchs, clergy, nobility) get closer editor review.
  - A registry edit must reach the next description even on a describe-cache hit. Name realization runs after the cache lookup and reads the registry live (criterion 17 tests this on a cache hit).
- **Size (PR1-07).** N is an output of the FPIR budget, not an input: false positive identification rate grows with gallery size, so call 6 fixes the served N per tier.
  - P1 + P2 is in the low thousands.
  - P3 at a 12-month Wikimedia pageview threshold is plausibly 10–30k identities. At ~5 templates each, that is 50–150k vectors, about 100–300 MB at 512-d float32.
  - HNSW from day one.
  - Pageviews are stored per Wikimedia project (en, fr, es…), so regional notability (fr.wikipedia for Quebec) is a config change.
- **Auto-name (decided 2026-10-21).** Strong-band matches that pass the auto-name gate (§ How it would work, item 3) are named for that describe only, with `pfl_auto` provenance. No link is written (PR1-08). This is an explicit, scoped change to the E20-10 guardrail ("machine-only faces are never named", the `DescribeMediaService` class docblock) and to the SEC-01 describe path, at both naming sites.
- **Context gate.** The describe VLM call also returns `setting: public_role | private | unclear`: a new field on the VLM JSON contract in `gpu_remote_adapter.py::_SYSTEM_PROMPT`, carried on `scene/application/description_adapter.py::AdapterResult`. A missing or invalid value is `unclear`. Only `public_role` allows any PFL name, auto or linked. `private` and `unclear` leave the face generic with a review reason. Example: the Tribeca red carpet allows auto-name; the Coachella noodles photo does not. The gate carries the most weight for P3: a performance, red carpet, premiere, match or press event is the public role, while street, family, beach and home photos are private even for a celebrity (Campbell).
- **Legal gate before release.** BIPA has no public-figure exception, and GDPR Art. 9 applies to templates of public figures. Counsel decides the population bounds and the held-jurisdiction list before `PFL_ENABLED` flips (§ Operator calls, call 3). Building templates for the calibration benchmark is part of that question. For P3, counsel also covers the right of publicity (naming in alt text is not endorsement or commercial use, but confirm per jurisdiction).

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
| Why (tenant purpose) | News, education, archive captioning of the tenant's own media library, with use bound by tenant terms and the vendor's recorded necessity case (SECD-13, MLDATA-16). | People search, open "who is this" lookups, marketing, monitoring. |
| When (decay) | Role is current, salience is current (P2 enters on threshold and exits after 90 days below it), notability is current (P3 is re-checked at each editorial review date), or historical and deceased. | Limited-purpose fame that has faded. A weekly salience job removes P2 identities that have exited and deletes their templates (data minimisation). The name entry and existing tenant QID links stay. |

## GTM fit verdict

**Parity requirement for news and education, not a differentiator.** (Revised 2026-10-21, decision 18952; the earlier verdict was "partial fit, not a launch feature".)

- **Parity.** Free alt-text tools name famous people out of the box (see Prior art). A news or education evaluator who uploads a photo of a head of government or a famous entertainer and gets no name will choose the free tool. The operator ruled that missing celebrities disqualifies the product (decision 18981). Table-stakes items get built even when they add no margin (PROD-15).

- **Against.**
  - The launch ICP is professors working on lecture diagrams. `pricing-2026-10-08/strategy.md` says recognition "is not the central value proposition" there.
  - The same doc required identity to stay "optional, scoped to a customer-authorized roster, and subject to review". Default-on PFL keeps it optional (one switch) and subject to review (editor apply), but it is vendor-authorized, not customer-authorized. This branch amends that sentence (`strategy.md` § recognition) so the policy and the product never contradict (CLM-03).
  - A shared gallery is a commodity that AWS sells per call, not the moat. The moat in the launch plan (§2) is tenant-curated labels.
  - The ~$83/mo time-saved math does not carry a standalone add-on, so this must be bundled, not upsold.
- **For.**
  - It removes the empty-roster cold start for news (100–1,500 images/mo), archives, and history/civics course material.
  - Link-on-accept turns gallery hits into tenant roster faces; the name stays central.
  - It fits "Roster → Recognize & Flag → Curate" if framed as a *starter roster from a licensed library*.
- **Positioning risk.**
  - "Celebrity recognition" invites the Clearview question that DEMO-UX-1-D-10 already raised.
  - Copy must say "suggests names from a licensed public-figure library for your review", never "identifies anyone" (CLM-01, CLM-02).
- **Validate before inventory.** Phase 1 buys no inventory: references come from Commons and official portraits (call 2). Bought feeds wait until 2–3 same-segment reference customers name a gap (GTM-02, GTM-14, CARD-06).

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
  - On by default for every tenant in a cleared jurisdiction, on every plan including trial. The tenant can turn it off (§ How it would work, item 2). A tier serves only after its calibration evidence passes (criterion 12).
  - Release gated on counsel memos: EU AI Act Art. 6 classification (the Commission lists "facial recognition for media archives" under Annex III 1(a)), a DPIA, BIPA/CUBI geo-policy, Quebec biometric-database disclosure, and right of publicity for P3.
- **Phase 2. Historical Figures Library.** Deceased persons, public-domain references, curriculum and archive identities. Same pipeline; lower legal exposure (GDPR Recital 27).

## Assumptions

- The commercial embedding model will be the production space before any PFL ships. Shipping a commercial gallery on buffalo_l weights is the risk to avoid (CARD-26).
- Wikidata QID is the identity key. Tier assignment is a human editorial decision recorded per identity with a review date.
- The tenant is the controller of its own media and its QID links. The vendor is the controller of the PFL, the name registry and the default.
- Onboarding can capture a tenant jurisdiction (ISO 3166-2), from the billing address or an admin answer. Until it does, the tenant counts as held.

## Success criteria

Each criterion maps to an eval case in `public-figure-library-evals.json`.

1. Default-on, fail-safe. Zero PFL candidates are returned when `PFL_ENABLED` is off, the tenant is not entitled, its jurisdiction is held or unknown, or the tenant switched PFL off. Otherwise a tenant with no settings row gets candidates from every released tier, and turning the switch off takes effect on the next request.
2. Same-space. Mismatched `embedding_model` yields zero PFL candidates, fail-closed.
3. A null or unrecognised capture basis or licence is never served.
4. Out-of-tier, minor-flagged or opted-out identities are never served.
5. Below the floor returns unknown. The possible band is suggestion-only. The strong band auto-names only when the auto-name gate passes (auto-name on for the tier, tier calibrated, QID not suppressed, `public_role` context); otherwise it is a suggestion.
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
18. Adding a language needs only registry rows and a `supported_languages` entry; no code or schema change. A language below full verified coverage cannot be enabled, and a disabled language resolves to `en`. A row counts toward coverage only with ≥3 cited `warrant_sources` (FM-14), and an identity with no verified canonical row is not served.
19. P3 celebrity tier: a living adult, athletes included, above the 12-month Wikimedia pageview threshold with a voluntary public career is served. Minors, relatives without independent notability, and involuntary newsmakers are never served, even above the threshold. A P3 auto-name requires `public_role` context like every tier.
20. With private recognition off and PFL on, describe can still auto-name a public figure, but it writes no `media_identity` row and persists no probe vector.
21. Linked paths obey the same gate as matching. A cluster already linked to a QID is not named, and pending `pfl` suggestions are neither listed nor acceptable, when `PFL_ENABLED` is off, the tenant is not entitled, its jurisdiction is held or unknown, the tenant switched PFL off, or the identity's tier is not enabled. This holds on a describe-cache hit, and an eligibility read failure means no PFL name. An exited P2 link still resolves while P2 is enabled.
22. A `pfl` suggestion survives the existing API. `SuggestedLabelSource.PFL` and `pf_qid` round-trip from a `name_suggestions` row through list, serialize and accept. `NameSuggestionResponse` carries `source='pfl'` and `pf_qid`. A roster-candidates response carries a gallery candidate with `source='pfl'`, `pf_qid`, `cluster_id` null and its pending `suggestion_id`, and exactly one of `cluster_id` and `pf_qid` is set. The plugin passes the candidate through without a roster mapping.

## Not doing

- Influencers, entertainers or athletes below the P3 notability threshold. They come via tenant or team rosters.
- Minors, relatives of public figures, one-time newsmakers.
- An open "who is this person" API, or search over images outside the tenant's library.
- Non-English description text. This scope adds the `language` parameter and the name half only; the VLM output language is a separate i18n scope that reuses the same parameter.
- Auto-naming below the strong band, in `private`/`unclear` context, or for an uncalibrated tier. Confidence shown as probability.
- Writing tenant data back into the global gallery, or cross-tenant learning.
- Seeding from celebs01 or any scraped or unlicensed set.
- Pricing it as a standalone recognition upsell, or gating it to a higher plan.
- PFL in a held or unknown jurisdiction, or before `PFL_ENABLED` flips.
- Persisting probe vectors for a tenant whose private recognition is off.
- Any publish path that carries a PFL name without an editor applying the draft.
- Video.

## Canon validation (v0.26.2)

| ID | Rule | Verdict for this design |
| --- | --- | --- |
| SECD-12 | Biometric opt-in default | Partitioned by object (§ How it would work, item 2). Private faces stay opt-in. PFL tiers default on, a contextual judgment: the rule binds "when choice is product-real", and the operator ruled an off default disqualifies the product (decisions 18949, 18981). Counter-case: the pictured person gets no choice either way, so their protections (tier bounds, opt-out, context gate, notice, editor review) are all kept. |
| SECD-05 | Fail-safe defaults | `PFL_ENABLED` defaults to false. Held or unknown jurisdiction, stale version or unreachable gallery all mean no PFL name. One per-request eligibility decision gates linked and unlinked paths alike and fails closed (criterion 21). |
| SECD-08 | Make the safe path the easy path | One switch turns PFL off. A first-run notice on the first PFL-named draft names it. The switch (PUBFIG-9) is a release prerequisite. |
| SECD-14 | FP/FN harm polarity for face decisions | FPIR bound per tier at the served N (call 6). An auto-name lands only in a draft an editor applies. |
| SECD-13 | Necessity-proportionality gate | Vendor DPIA necessity record (the vendor sets the default), alternatives (§Alternatives), tiered scope, review date. Tenant terms bind purpose. |
| SECD-11 | Compulsory-visibility notice | Vendor subject notice page with an opt-out route, tenant notice line, PFL query audit. The tombstone path behind the opt-out route (PUBFIG-8) is a release prerequisite. |
| MLDATA-14 | Capture basis is a column | `pf_reference.capture_basis`. Null is refused on the match path. |
| MLDATA-15 | Every identity store carries a retention maximum | Expiry plus disposal on `pf_reference`. |
| MLDATA-16 | Bound face-search scope | Tiers plus the "Who" axis define the population. P3 is bounded by a notability threshold and the voluntary-career test, not by occupation lists alone. |
| MLDATA-17 | Removing names does not de-identify a face | Tombstone drops templates, not just names. |
| PROV-10, PROV-11, PROV-12 | Deletion reaches rebuilt artifacts; a derived copy inherits access controls; consumers are scoped to purpose | No write-back. Link-on-accept. Purpose bound by tenant terms. |
| DATA-14, REF-45 | No dual writes; one authored source, rendered per consumer | One name registry. Tenants hold QID links and render per language. |
| FM-14 | Literary warrant before admit | A localized form counts as verified only with ≥3 cited published sources for that form and person in `identity_name.warrant_sources`. Wikidata only seeds candidates. The coverage gate (criterion 18) counts only verified rows. |
| EMB-01, EMB-05, IDX-02 | One space, pinned versions, rebuild on contract change | One gallery per model contract, versioned. |
| CAL-02, CARD-03, AIPX-07 | Unknown is valid; precision-first | Capped bands, abstain below the floor. |
| HAI-14 | Disclose the synthetic hand | Each PFL name in a draft carries its source mark until the editor applies it. |
| HITL-14 | Familiar is not unfamiliar | Reviewer guidance: familiarity is not verification. |
| FAIR-07, FAIR-08, COL-10 | Subgroup monitoring; know your algorithm; inclusive grade test | Success criterion 12 before any tier goes on. |
| ATTRIB-02, ATTRIB-05 | Captions explain or falsify identity; honour source identity decisions | Naming gate. Metadata-first Phase 0. |
| CLM-01, CLM-02, CLM-03 | Claims are products; cost asymmetry; the policy is a contract | "Suggests from a licensed library" copy; the settings promise holds. |
| CARD-26 | Licence provenance is transitive | Per-reference licence row. No buffalo_l commercial gallery. |
| GTM-02, GTM-14, CARD-06 | Micro-test the offer; reference customers first; evidence before commitment | Calibration evidence per tier before auto-name is enabled for it. No agency-feed contract before demand is measured (call 2). |
| PROD-15 | HPC triage | Table stakes is built even without margin. Bundled in every plan. |
| FM-12 | Concept ID, not preferred string | P2 salience is keyed by QID through Wikipedia sitelinks, not by name strings (call 5). |
| RLSE-02 | Gates are not suggestions | Market urgency does not move the release gate. |
| RLSE-09 | Plain-English expert gate | Counsel gets yes/no questions with quoted strings (call 3). |
| STRAT-03 | Circle of competence | Legal questions go to counsel (call 3), not agent judgement. |

**Canon gaps** (for the maintainer):
- No row distinguishes public from private figures, or biometric processing from publication. Candidate row: "Fame licenses publication, not templating", sourced from Berle ch. 7.
- RLSE-09 glosses RLSE-02 as "CONDITIONAL is red: proximity makes the shipping team the worst judge". RLSE-02's row says "Gates are not suggestions". No row states the reviewer-independence rule the gloss describes.

## Operator calls (all decided 2026-10-21)

1. **Pilot segment.** News-cycle politicians first (decision 18958).
2. **Gallery licence source.** No agency feed in Phase 1. Buying a feed before demand is measured is inventory before a micro-test (GTM-02).
   - P1 and P2: official portraits whose licence permits reuse (US federal works are public domain; any other source records its licence per reference), plus Commons CC0, PD, CC BY and CC BY-SA images via Wikidata P18.
   - P3: Commons CC0, PD, CC BY and CC BY-SA only.
   - Disconfirmer (STRAT-02): a P3 identity serves only with 3 or more verified licensed references. Identities below that drop out of the served N. An agency feed is reconsidered only when paying reference customers name a gap (GTM-14).
   - Whether a CC licence permits deriving a template is counsel question Q5.
3. **Counsel.** Engage EU, US and CA privacy counsel now. Counsel gates the release (`PFL_ENABLED`) and the templates PUBFIG-10 builds. It does not gate task-plan drafting or the RED and implementation lanes, which ship dark behind the flag. The brief follows RLSE-09: quoted strings, yes/no answers, and a "not your problem" section covering the engineering mechanisms.
   - Q1. May AltContext build and store face templates of the P1–P3 population (the "Who" axis), from the call-2 sources, for captioning a tenant's own library, in each launch jurisdiction? Yes/no per jurisdiction.
   - Q2. Per jurisdiction: is PFL lawful on by default with a one-switch off, lawful only after a tenant opt-in, or barred?
   - Q3. Do these strings meet the notice duties? Tenant: "AltContext names public figures from its licensed public-figure library. You can turn this off in Settings." Subject: the vendor notice page, including Quebec's biometric-database disclosure duty. Yes/no each.
   - Q4. Does naming a P3 person in alt text, in `public_role` context, create right-of-publicity exposure? Yes/no per jurisdiction.
   - Q5. Do CC BY and CC BY-SA permit deriving a biometric template from the image? Yes/no.
   - Q6. Asked only before EU/EEA leaves the held list: does the PFL fall under EU AI Act Annex III 1(a)? Yes/no.
4. **Launch jurisdictions.** Launch only where counsel answers Q1 yes and Q2 "on by default". The starting held list is US-IL, US-TX, US-WA, EU/EEA, UK and CA-QC, and an unknown jurisdiction counts as held (SECD-05). The list is config (`pfl_held_jurisdictions`), so a counsel answer is a config change. Where Q2 is "opt-in", the tenant switch starts off there.
5. **Salience and notability sources.** One pipeline, Wikimedia pageviews, keyed by QID through Wikipedia sitelinks (FM-12). GDELT keys on name strings and needs entity resolution, so it is not used.
   - P2: trailing-30-day pageviews. Entry at or above the threshold, exit after 90 days below it.
   - P3: trailing-12-month pageviews (decision 18983).
   - Both thresholds are set by the call-6 N budget, per Wikimedia project.
6. **FPIR bound.** This is a contextual judgment; canon requires a stated bound (SECD-14) but sets no number.
   - **Strong band (auto-name):** FPIR ≤ 1×10⁻³ per non-mated probe at the served N. It uses the 95% upper bound, on news imagery, and is checked per skin-tone slice; the worst slice sets the bound (FAIR-07).
   - **Sample size:** at least 3,000 non-mated probes per slice (rule of three: 0 false matches in 3,000 bounds FPIR at 1×10⁻³).
   - **Suggestion band:** FPIR ≤ 1×10⁻² at the same N.
   - If a tier misses the bound, its served N shrinks by notability rank until it passes. FNIR is reported but not bounded, because a miss leaves the face generic (AIPX-07, CAL-02).
7. **Living entertainers.** Living celebrities are P3 in Phase 1, as table stakes (decision 18981).
8. **Launch languages.** English only, with i18n built in (decision 18963).
9. **Tenant language-form override.** Not in Phase 1. One authored source renders per consumer (DATA-14, REF-45). A style-guide variant is a registry correction request.
10. **Default posture.** Public figures are on by default and private recognition stays opt-in (§ How it would work, item 2).

**Operator actions.** These are actions, not open decisions:
- Engage counsel with Q1–Q6.
- Run the curation workstream (§ Dispatch).
- Publish the vendor notice page before `PFL_ENABLED` flips.

## Implementation task plans

Each plan below becomes one `docs/tasks/` plan under PUBFIG-1. Paths are relative to `apps/prototype-description-service/` unless they start with `apps/`. The evals file maps every case to its plan (`task_plan`). Each plan runs RED then implementation (§ Dispatch), with slices of 1–3 files.

**Dependency order:**
1. PUBFIG-2.
2. PUBFIG-3, PUBFIG-5 and PUBFIG-8, in parallel.
3. PUBFIG-4.
4. PUBFIG-6.
5. PUBFIG-7 and PUBFIG-9.

PUBFIG-10 waits for curation. PUBFIG-11 runs in parallel throughout.

**Release gate:** `PFL_ENABLED` stays `false` until all of these hold:
- PUBFIG-6, PUBFIG-7, PUBFIG-8 and PUBFIG-9 are merged.
- Acceptance evidence exists on the merged `main` for each subject and tenant control the defaults rely on:
  - the switch: turning PFL off yields no PFL candidate or name, linked or auto, on the next request (criteria 1, 21);
  - "Not this person": the UI action writes the suppression and the QID is unnamed in the next description (criterion 15);
  - tombstone: a request through the notice-page opt-out route removes the identity's templates and stops its name resolving (criterion 9).
- Criterion 12 passes for the tier.
- Counsel has answered Q1–Q5 for the launch jurisdictions.
- The vendor notice page is live, with its opt-out route wired to the tombstone path.

The flag's false default (criterion 1) makes intermediate merges safe. Market pressure does not move this gate (RLSE-02).

### PUBFIG-2. Gallery schema, enums, repository, artifact loader

- **Change sites.**
  - New `db/models/pfl.py`: schema `pfl` with `PfIdentity`, `PfReference`, `PfTemplate`, `PfIdentityName` (with `warrant_sources`, a list of cited sources), `PfDenylist`, `PfGalleryVersion` (`active` flag), and per-project pageview columns on `PfIdentity`.
  - New `db/models/pfl_tenant.py`: `TenantPflSettings` (`jurisdiction`, `enabled_tiers`, `autoname_tiers`; no row means the defaults in § How it would work item 2) and `PflNameSuppression`.
  - `recognition/config/settings.py::RecognitionSettings`: `pfl_enabled` (env `PFL_ENABLED`, default `false`) and `pfl_held_jurisdictions` (the call-4 list), validated at load (rg-008).
  - `db/models/identity.py::IdentityCluster`: add `pf_qid` (nullable). Replace the free `confirmation_source` strings with a `ConfirmationSource` StrEnum that adds `PFL_ACCEPT`, and extend `valid_confirmation_source`.
  - `db/models/constraints.py::NameSuggestion`: add `pf_qid` (nullable), and add `'pfl'` to the `name_suggestion_valid_source` CHECK.
  - `recognition/domain/suggestion.py::SuggestedLabelSource`: add `PFL = "pfl"`. It stays the one canonical source enum (sr-007); a schema test asserts the CHECK list equals its values. `recognition/domain/suggestion.py::NameSuggestion`: add `pf_qid: str | None`.
  - `db/migrations/versions/001_identity_schema.py`: all of the above, plus an HNSW index on `pf_template.vector` and a SELECT-only grant on `pfl` for the serving role.
  - New `recognition/infrastructure/repositories/pfl_gallery_repository.py::PflGalleryRepository` (read).
  - New `scripts/pfl/load_gallery_artifact.py`: verify the sha256 and manifest, insert a new `gallery_version`, flip `active`.
- **Criteria.** 3 (null licence or capture basis is not loadable), 7 (the grant), 13 (one active version per model), 18 (the warrant column) and 22 (the enum and domain model).
- **Proof.**
  - Schema tests, including CHECK-equals-enum.
  - The loader rejects a bad sha256 or a null licence.
  - An INSERT as the serving role is denied.

### PUBFIG-3. Matching core, default-on gate, audit

- **Change sites.**
  - New `recognition/application/pfl/eligibility.py::resolve_pfl_eligibility(tenant_id) -> PflEligibility`. It reads `PFL_ENABLED`, `pfl_held_jurisdictions`, `TenantPflSettings` (absent row = every released tier on) and `SqlAlchemyTenantEntitlementRepository`. Any read failure returns closed (SECD-05). No caching across requests.
  - New `recognition/application/pfl/candidates.py::list_pfl_candidates(tenant_id, probe, embedding_model)`. It calls `resolve_pfl_eligibility` first, then applies the § How it would work item 3 filter order and returns capped bands, using `embedding_space.py::models_are_same_space` and `SimilarityBand`.
  - Each query writes one `db/models/observability.py::AuditEvent` row: tenant, gallery_version, candidate count.
- **Criteria.** 1, 2, 3, 4, 11, 13, 19 (the serving-exclusion half) and 21 (the eligibility decision, including read failure).
- **Proof.** `recognition/tests/unit/test_pfl_candidates.py`, `test_pfl_audit.py`, `recognition/tests/api/test_pfl_isolation.py`.
- **Depends on** PUBFIG-2.

### PUBFIG-4. Curate: suggestions, link-on-accept, suppression

- **Change sites.**
  - `recognition/interface_adapters/http/routers/suggestions.py::get_roster_candidates`: merge `list_pfl_candidates` results with `source: pfl`, `pf_qid`, `cluster_id` null and the pending `suggestion_id`. The tenant roster wins at equal band.
  - `recognition/interface_adapters/http/schemas/responses.py`:
    - `RosterCandidateResponse`: add `source: Literal["roster", "pfl"]` (default `roster`), `pf_qid: str | None` and `suggestion_id: str | None`. `cluster_id` becomes `str | None`, UUID-validated when set. A model validator requires exactly one of `cluster_id` and `pf_qid`. Update the docstring: PHP maps `cluster_id` to `roster_entry_id` only for `source="roster"`.
    - `NameSuggestionResponse`: `source` accepts `pfl`, and add `pf_qid: str | None`.
    - `suggested_label_source` on `ClusterResponse`, `SuggestionResponse` and `ClusterSnapshotClusterResponse` accepts `pfl`. Each of these Literals derives from `SuggestedLabelSource`, so the next value cannot drift.
  - `recognition/infrastructure/services/suggestion_extension_service.py::_to_name_suggestion` and `_to_name_suggestion_with_representatives`: map `pf_qid`. `SuggestedLabelSource(model.source)` then accepts `pfl`.
  - New `recognition/application/pfl/suggest_job.py`: after `orchestration/clustering/orchestrator.py::cluster_unclustered_identities`, write `name_suggestions` rows with `source=PFL`, `pf_qid` and the canonical name. It also runs over existing unlinked clusters when a new `gallery_version` goes active.
  - `recognition/infrastructure/services/suggestion_extension_service.py::accept_name_suggestion`: the `pfl` branch sets `pf_qid`, `user_confirmed` and `PFL_ACCEPT`, and leaves the label NULL. It refuses if the cluster has a non-PFL label, or if `resolve_pfl_eligibility` is closed.
  - `suggestion_extension_service.py::list_name_suggestions` omits `source=pfl` rows while eligibility is closed.
  - `reject_name_suggestion`: the `pfl` branch writes `PflNameSuppression`.
- **Criteria.** 6, 7 (no PFL write on accept or reject), 8, 15 (the write half), 21 (the list and accept half) and 22 (the API half).
- **Proof.** `recognition/tests/api/test_pfl_accept.py`: list, serialize and accept a real `pfl` row; a roster-candidates response with a gallery candidate; list and accept refused while eligibility is closed.
- **Depends on** PUBFIG-3.

### PUBFIG-5. Name registry, language parameter, coverage gate

- **Change sites.**
  - New `scene/application/identity_merge/pfl_names.py::resolve_pfl_name(session, qid, language)`: exact locale, then base language, then canonical.
  - `supported_languages` config. A language is enabled only at full verified coverage, where verified means ≥3 cited `warrant_sources`; a disabled or unknown language resolves to `en`. `resolve_pfl_name` returns no name for a row without that warrant.
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
  - `scene/application/identity_merge/merge.py::ConfirmedFace`: add `pf_qid` and the identity's tier.
  - `join.py::load_confirmed_faces`: load `pf_qid` faces and name them via `resolve_pfl_name`.
  - `policy.py::NamingPolicy`: add `suppressed_qids`, `setting` and `pfl_eligibility`. `resolve_naming_allowed` gets the QID branch, which requires eligibility open and the face's tier in `enabled_tiers` (§ Serving architecture, two naming sites).
  - `policy.py::NamingProvenance` / `InjectedName`: add `pf_qid`, `gallery_version`, `band` and the resolved language.
  - `naming_preview_service.py::load_fusion_naming_inputs`: call `eligibility(tenant_id)` once per request, after the describe-cache lookup, and put it on `NamingPolicy`. Closed skips every PFL name, linked or auto. Then load QID suppressions and run auto-name for unlinked faces. Both go through a scene-side `PflCandidateSource` Protocol with `eligibility(tenant_id)` and `candidates(tenant_id, probe, embedding_model)`. The describe router wires recognition's `resolve_pfl_eligibility` and `list_pfl_candidates` into it; scene/application does not import recognition.
  - Review reasons `pfl_suggestion` and `pfl_private_context` go on `scene/application/fusion/reconcile.py::ReviewReason`.
  - `scene/interface_adapters/http/routers/describe.py::describe_image_multipart`: today `recognition_enabled` false skips `_load_fusion_naming_inputs` entirely. Add the PFL-only branch: with recognition off and the PFL gate open, detect and embed faces in-request through `FaceDetectorProtocol.detect`, pass the probes to the `PflCandidateSource`, and drop them. Tenant roster faces stay unloaded (SEC-01 unchanged).
- **Criteria.** 5, 10, 14, 15 (the naming half), 17 (cache-hit half), 19 (the auto-name half), 20 and 21 (the linked-naming half, including on a cache hit).
- **Proof.** `scene/tests/test_pfl_naming.py`, with one linked-cluster case per closed state of criterion 21.
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
  - The PFL panel: one on/off switch (on by default, as easy to turn off as on), per-tier and per-tier auto-name detail behind it, the jurisdiction field, and the notice line to copy.
  - The one-time first-run notice on the first PFL-named draft, naming the switch.
  - A source mark on each PFL name in the draft (SECD-14).
  - A source chip on `pfl` suggestions.
  - The "Not this person" action.
  - The `SettingsForm.tsx` naming copy, which must stay true (CLM-03).
  - Every string through `wp.i18n` (sr-012).
- **API consumers** (rg-015; the plugin must not drop or invent the new fields):
  - `apps/prototype-wp-alt-context/src/api/class-suggestions-controller.php::attach_roster_entry_ids`: map `cluster_id` to `roster_entry_id` only for `source="roster"`. Pass `source="pfl"` candidates through with `pf_qid`, `suggestion_id` and `roster_entry_id` null, and do not dedupe them into roster people.
  - `apps/prototype-wp-alt-context/js/admin/api/recognition/rosterCandidatesApi.ts::RosterCandidate`: add `source`, `pf_qid` and `suggestion_id`; `cluster_id` becomes `string | null`.
  - The `suggested_label_source` and suggestion `source` unions in `js/admin/api/recognition/types/suggestion.ts`, `types/cluster.ts` and `identitySuggestionMappers.ts`: add `'pfl'` and `pf_qid`.
  - Accept and "Not this person" on a `pfl` candidate call the existing name-suggestion accept and reject routes by `suggestion_id`.
- **Criteria.** 22 (the plugin half). Acceptance is otherwise a ux-map pass (map, render, critique, target ASCII) before the ADR, plus the switch and "Not this person" evidence the release gate names.
- **Proof.** `apps/prototype-wp-alt-context/tests/Unit/SuggestionsControllerPflTest.php`; a vitest case for the `RosterCandidate` mapping.
- **Depends on** PUBFIG-3 and PUBFIG-4.

### PUBFIG-10. Offline fairness benchmark

- **Change sites.** A VM/GPU benchmark under `benchmarks/`: FMR/FNMR per skin-tone slice, at the served N, on news imagery.
- **Criteria.** 12. Its output sets the call-6 FPIR ceiling and N per tier.
- **Depends on** PUBFIG-2 and a curated gallery.

### PUBFIG-11. Phase 0 metadata names (parallel)

- **Change sites.**
  - A plugin IPTC/XMP person-name reader beside `src/media/class-image-xmp-writer.php`.
  - Names surface as suggestions with source `metadata`. This needs a `SuggestedLabelSource` value and the matching CHECK entry, so it lands after PUBFIG-2 or adds both itself.
- **Criteria.** None in this suite. It gets its own small eval when planned.
- **Gate.** Measure coverage on news imagery first (Alternatives, item 1).

## Dispatch (per task plan, after operator calls)

1. **RED lane** `pubfig-<n>-red`.
   - Owned paths: that plan's test files only, from `recognition/tests/{unit,api}/test_pfl_*.py`, `scene/tests/test_pfl_*.py`, `apps/prototype-wp-alt-context/tests/Unit/*Pfl*Test.php` and `apps/prototype-wp-alt-context/js/**/__tests__/*Pfl*.test.ts`.
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
