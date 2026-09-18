# AltContext vs Google Photos — Feature Assessment (2026-09-18)

**Status:** Draft for operator review
**Task:** `GPCOMP-1`
**Method:** AltContext features from the codemap route graph (`search_graph label=Route`), the UX maps under `docs/ux-maps/`, and current assessments; prior art via `find_related_prior_work` (semantic) over the handoff; planned features from `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (v11); Google Photos behaviour from Google's public help documentation as of the writing date (not re-verified against a live account — see Open Questions). Canon rules cited by ID from `~/Development/heuristics-canon-research/lexicons/`.

## Summary

Google Photos (GP) and AltContext (ACX) share one core mechanism — detect faces, embed, cluster, let a human name the cluster, then search by that name — and diverge in purpose. GP is a consumer photo library whose output is *browsing*: memories, albums, sharing, edits. ACX is a publisher tool whose output is *published text*: alt text, captions and descriptions written into a WordPress media library, with the named people woven into the prose and every claim inspectable back to a face box.

- **Match (parity, keep):** face grouping, naming, merge and "not the same person" split, hide/dismiss, representative face per person, search by person.
- **Compete (GP ahead, worth taking):** one-card-per-person by default with topology hidden; the "same or different person?" verification prompt; person detail page (cover photo, all photos of the person); cross-modal search (text → image, objects, OCR); pets; a single opt-in switch for face grouping with regional defaults.
- **ACX better at:** accessibility output as a first-class artifact; provenance (which face, which phrase, which policy allowed a name); tenant isolation, purge, export and retention as product features; naming-agreement consent gate before any name appears in text; self-hostable recognition API; roster as a *publishing* entity, not a private label.
- **Do not chase:** Magic Editor, Best Take, Memories, partner sharing, storage. Outside the product's quadrant (portfolio assessment 2026-06-11: Bread-and-Butter/Pearl boundary; video is an Oyster probe, not a plan).

## 1. Feature matrix

| Capability | Google Photos (public docs) | AltContext today (routes / screens) | Verdict |
| --- | --- | --- | --- |
| Face detection + grouping | Automatic "People & Pets" groups; on-device + cloud; off by default in some regions | `POST /recognition/analyze`, `POST /clustering/jobs`, HDBSCAN + representative validation; scan walks the WP media library | **Match** |
| Name a group | Private label per group, only visible to the account | Roster person (`wp_acx_persons`) bound to clusters; `PATCH /clusters/{id}`, `ClusterLabelService`; label unique per tenant | **Match**, but ACX label is a *publishing* entity (goes into alt text) |
| Merge two groups of the same person | "Same or different person?" prompt; merge from person page | `POST /clusters/{id}/merge`, `/merge-candidates`, `PersonMergeService` preview/commit/undo | **Match** in capability; GP ahead in UX (prompted, one click). Current ACX defect: bind-to-person replays a label instead of merging (REL0024-H-06) |
| Split a wrong merge | "Remove result" from a group | `POST /clusters/{id}/split`, `/reassign`, `/revert-merge`, UXW2-3 split action | **Match**; ACX has undo of merge, GP does not expose one |
| Hide / dismiss a person | Hide face group | `POST /clusters/{id}/dismiss` and DELETE to un-dismiss | **Match** |
| Representative / cover face | Choose cover photo per person | `PATCH /clusters/{id}/representatives/{id}/pin`, quality-scored representatives (GPUFLOW-2 svc-rep-recompute) | **Match**; ACX picks by measured quality, GP by user pick |
| Person detail page | Person page: cover, all photos, name, merge, hide | Roster row → workbench filter; representatives and linked media not on one screen (REL0024-M-11) | **Compete — take from GP** |
| Search by person name | Name search, "A and B" conjunctions | Workbench filter by identity; `GET /media/identities?media_ids=` | **Compete**; ACX lacks name-conjunction search |
| Search by content (objects, places, text) | Natural-language and OCR search; Gemini "Ask Photos" | Lexical only: title/filename search and sync-status / confidence-band filters (workbench). Planned: whole-image SigLIP/DINOv2 space (FIR §2b, §10) | **Compete — planned** |
| Alt text persisted in the file | None (metadata stays in the library) | XMP metadata embedding writes alt text into the image file itself | **ACX only** — survives export off WordPress |
| Compare descriptions across providers | None | Side-by-side provider comparison in the public guide | **ACX only** |
| Pets | Pet grouping | None | GP only; out of scope for alt text |
| Suggestions | "Is this X?" prompts, sharing suggestions | `GET /identities/suggestions`, `/clusters/top-unlabeled`, `/roster-candidates`, singleton merge suggestions (WBUX-6) | **Match** at API level; GP surfaces them as interrupts, ACX as a queue |
| Alt text / description for publishing | None. Screen-reader descriptions exist inside the app only | `POST /describe/run`, review queue, Ready-to-apply, writes `<img alt>` and Gutenberg block alt (E20-6); public guide | **ACX only** |
| Names woven into text | N/A | `merge_identities` grounded/positional realizers, naming policy, agreement gate | **ACX only** |
| Provenance per claim | N/A | `naming.realizer`, `naming.status`, phrase spans, face box, `GET /diagnostics/decisions` | **ACX only** |
| Consent / opt-in for recognition | Face grouping toggle; regional defaults | Recognition setting (default off per SECD-12), naming agreement, `GET/PATCH /policy`, presets | **Match on control; ACX ahead on granularity** (naming ≠ grouping) |
| Data lifecycle | Delete photos; turn off grouping deletes face models | `POST /purge`, `POST /export`, `GET /retention/audit`, TTL modes (privacy assessment 2026-06-13) | **ACX ahead** — lifecycle is a product feature with an audit trail |
| Tenancy / hosting | Google account | Tenant-scoped API keys, self-hostable service, no cross-tenant gallery | **ACX ahead** for publishers |
| Cluster diagnostics | None exposed | `/clusters/centroid-health`, `/clusters/events`, `/diagnostics/decisions` | **ACX only** (operator surface) |
| Video | Videos grouped by faces | None; Oyster probe only | GP only; do not chase |
| Editing (Magic Editor, Best Take, Unblur) | Yes | None | Out of scope |

## 2. What ACX is better at

1. **The output is publishable text with named people.** GP names are private and never leave the account. ACX names flow into alt text and captions on a public site, gated by the naming agreement and the per-face policy (`resolve_naming_allowed`). No consumer photo product does this. Canon: A11Y-59, A11Y-07 (one linear, woven description); ATTRIB-02 (carry the confidence of an attribution into the published text).
2. **Every name is traceable.** `naming.status`, realizer mode, phrase span and face box travel with the draft. GP shows a group, not a reason. Canon: HAI-17 (captures stay inspectable), PROV-01.
3. **Consent is layered.** Grouping, naming agreement and per-identity suppression are separate switches. GP has one toggle. Canon: SECD-12 (biometric opt-in default), SECD-13 (necessity gate), MLDATA-13/14 (body-derived data is its own class with a capture-basis column).
4. **Lifecycle is a feature.** Purge, export, retention audit and TTL rows exist as routes and are marketed (privacy assessment). Canon: MLDATA-15.
5. **Undo exists.** Merge revert and person-merge undo. GP's "remove result" is not a revert.
6. **Operator diagnostics.** Centroid health, cluster events, decision diagnostics, quality-scored representatives, sync conflicts and dead-letter queues with retry.
7. **Portable output.** XMP embedding and export/import mean the accessibility text and the curated roster outlive the hosting platform. GP's names and groups are locked to the account.

## 3. What to take from Google Photos

Each item maps to existing code or an already-planned FIR feature; nothing here needs a new subsystem.

| Take | Why GP's version works | ACX landing | Existing code / plan | Canon |
| --- | --- | --- | --- | --- |
| **One card per person, topology hidden** | Users never see "4 face groups"; groups are an implementation detail until something looks wrong | Group by `person_id`, drop the face-group badge from daily view; keep split under "Not the same person?" | `groupIdentitiesByClusters` (IDCHIP-1), `IdentityClusterItem`, split route | NAV-14, GRPH-22, PERC-03 |
| **"Same or different person?" prompt** | A binary question with two thumbnails beats a merge-candidates list | Surface `merge-candidates` above a margin as a yes/no card in the roster; merge via the verified path only | `/clusters/{id}/merge-candidates`, `generate_singleton_merge_suggestions`, `ClusterMergeService` | GRPH-38 (adjudicate + abstain), GRPH-18 (no unguarded auto-merge), HAI-01 |
| **Person page** | Cover, every photo, rename, merge, hide in one place | Roster name click → representatives (pin/unpin) + linked media list | `/clusters/{id}/members`, `/representatives/{id}/pin`, `PersonMergeService` | HAI-17, COG-02 |
| **Name search, incl. "A and B"** | Retrieval by identity is the payoff of naming | Workbench filter accepting multiple person ids; media identities already joinable | `GET /media/identities`, `wp_acx_identity_members` | NAV-14 |
| **Content search** | Objects, places, text without any curation | Second embedding space in the scan walk (SigLIP-B/16 or DINOv2-S), own table, own dim, no identity claims | FIR §2b, §10, §12 (planned) | EMB-01 (one space per modality), IDX-01 |
| **Single opt-in switch with regional defaults** | Compliance is a default, not a policy page | Keep recognition off by default; add jurisdiction preset to `/policy/preset` | `POST /policy/preset`, privacy assessment jurisdiction controls | SECD-12, SECD-13 |
| **Grouping quality under occlusion / small faces** | GP groups people from partial views (body, clothing, context) | Event-scoped torso association within an upload batch; person-first cascade so "person found, face unresolved" is recorded rather than silently missed | FIR §2a (Apple-style torso, event-scoped, never gallery), §11 (RT-DETR/PicoDet cascade, Apache) | MLDATA-13 (torso is biometric-adjacent, TTL rows), EMB-07 |
| **Prompted curation instead of a backlog** | Occasional "is this X?" beats a review queue of 200 | Rank the review queue by high-dimensional uncertainty (soft-assignment entropy, centroid margin); show at most one prompt per session | FIR §17(c) active curation; `/clusters/top-unlabeled` | CAL-11 (quality gate), COG-02 |

**Not taken, with reasons:** Memories/auto-albums (no publishing value); pets (no alt-text policy for animal identity); Magic Editor (edits change the visual facts the description claims — conflicts with the "inspectable visual facts" positioning); partner sharing (cross-account gallery is the exact thing the privacy posture forbids: no cross-tenant recognition).

## 4. Planned FIR features against GP

| FIR item | GP equivalent | Position after landing |
| --- | --- | --- |
| §2b whole-image embeddings → content search | Core GP search | Parity for search; ACX keeps identity and content in separate spaces (GP does not disclose) |
| §2a torso / same-moment association | GP's partial-view grouping | Parity within an event; ACX explicitly refuses cross-event torso identity (GP behaviour undocumented) |
| §11 person-first cascade | Implicit in GP | Better failure reporting: "person found, face unresolved" is a description fact, not a miss |
| §17 UMAP curation atlas | None | ACX-only operator tool; must never gate a decision (projection distances are meaningless) |
| Periocular / mask branch | GP handles masks opaquely | Only a measured experiment; FIR says do not claim occlusion recovery until matched-denominator runs exist |
| §13 proprietary occlusion weights as paid tier | GP is free with storage pricing | Differentiator claim withdrawn in FIR v8 until re-measured; do not quote the 0.865/0.321 pair (CLM-05) |
| Adaptive clustering (reliable cores, provisional attachments, cannot-links) | GP's staged precision/recall (Apple 2021 pattern) | Same design lineage; ACX adds human cannot-links from the split action |

## 5. Risks and cautions

- **Region defaults.** GP ships face grouping off or unavailable in the EU, UK, Illinois and Texas. ACX must keep recognition off by default and expose a jurisdiction preset (privacy assessment: BIPA, GDPR, EU AI Act). SECD-12.
- **Auto-merge temptation.** GP-style silent merging would be an unguarded false edge. Merge only through the verified path with a competing-identity margin. GRPH-18, GRPH-35.
- **Confidence in published text.** A name in alt text is a public claim. Positional naming has no measured accuracy yet; the harness metric exists (`position_accuracy`) and must be run before any two-plus-face ordinal rule ships. CAL-02, ATTRIB-02.
- **Content search is not identity.** The whole-image space must never feed clustering or naming. EMB-01.
- **Torso cues are biometric-adjacent.** Event-scoped, TTL rows, never persisted to the gallery. MLDATA-13, MLDATA-15.

## 6. Recommended sequence

1. Land the GPUFLOW-3 wave already recorded (bind→merge, projection tombstoning, person-first cards, roster person page, thumbnails, naming copy). This alone closes most of the UX gap in §3 rows 1–4.
2. Add multi-person name search on the workbench (small; data already joined).
3. Content search: SigLIP-B/16 second space in the scan walk, behind the paid tier per FIR §13.
4. Prompted curation: one "same person?" card per session from merge-candidates above margin.
5. Torso association and cascade only after the FIR binding sequence's D1 gate passes.

## 7. Open questions (unverified)

- GP regional availability list and the exact "same or different person" flow were taken from public help pages, not re-checked on a live account on 2026-09-18.
- Whether GP exposes any accessibility description export was not confirmed; treated as "in-app only".
- ACX name-conjunction search does not exist today; confirm no workbench filter already accepts multiple person ids before scheduling.

## References

- `docs/assessments/current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md`
- `docs/assessments/current/privacy-trust-and-vlm-fit-investigation-2026-06-13.md`
- `docs/assessments/current/roster-workbench-identity-ux-assessment-20260913.md`
- `docs/assessments/current/identity-prose-merge-design-2026-06-15.md`
- `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (§§2a, 2b, 9–13, 17; adaptive clustering; binding sequence v8)
- Handoff decisions `next_wave_proposal_naming_clusters_apply_20260918`, `naming_realizer_tiering_by_face_count_20260918`, `next_wave_recommended_steps_20260918` (MAINT-RELEASE-0024-20260918)
- Google Photos Help: "Find people & pets", "Turn face grouping on or off", "Merge or hide face groups" (public pages, accessed via prior knowledge)
