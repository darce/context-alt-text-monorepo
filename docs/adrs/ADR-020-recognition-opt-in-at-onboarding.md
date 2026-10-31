# ADR-020: Face recognition offered at onboarding, tenant-controlled, with a 30-day limit on unnamed faces and a jurisdiction hold

- **Status:** Proposed (operator direction 2026-10-31; needs operator acceptance, then the release gate below)
- **Date:** 2026-10-31
- **Context task:** BIODEF-1
- **Keeps:** `RecognitionPolicy::DEFAULT = false` from commit `31ef9cbc82` (E4, 2026-09-18). Recognition starts only when the tenant turns it on; this ADR puts that choice in onboarding, where every tenant sees it.
- **Coordinates with:** [public-figure-library-scope.md](../scopes/public-figure-library-scope.md) (PFL; shares the jurisdiction field and held list), [ADR-011](ADR-011-retire-on-device-recognition-remote-only.md) (single remote backend, RLS tenanting), [ADR-019](ADR-019-person-anchored-curation-surfaces.md) (curation surfaces), [E22](../epics/v0.5.0/commercial-face-identity-replacement-epic.md) (commercial face model).
- **Heuristics (Canon v0.26.2):** SECD-05, SECD-08, SECD-09, SECD-11, SECD-12, SECD-13, SECD-14, MLDATA-13, MLDATA-14, MLDATA-15, MLDATA-16, MLDATA-17, CARD-26, CLM-03, RLSE-02, RLSE-09, STRAT-03, A11Y-38.

## Context

Weaving tenant-curated identities into descriptions is the main product proposition (ADR-018, ADR-019), and tenants sign up for ACX to get it. Recognition is off by default today and its switch sits in Settings. A new tenant's first describe run names nobody, and the curation flow that builds the roster (face groups → name a person) never starts unless the tenant finds the setting. Market comparators:

- Apple Photos lets a user name anyone in their own photos and computes the face data on the user's devices. ACX follows the same model: a tenant names people in its own images, which live on its own WordPress site. The difference is that ACX keeps the face templates on its server.
- Free alt-text tools (AltText.ai, autoalt.ai, imagecaptiongenerator.com) name famous people from pixels through the VLM, with no gallery of their own ([PFL scope](../scopes/public-figure-library-scope.md) § Prior art, Market). What the model learned about those faces sits in its weights, and there is no reliable way to remove one person short of retraining. An ACX template is a row the tenant deletes.
- DBGallery and PhotoShelter PeopleID apply a named face across the collection ([pricing strategy](../gtm/pricing-2026-10-08/strategy.md) § Facial recognition).

ACX already has protections most comparators lack:

- Postgres RLS isolates every tenant, so a face is only ever compared inside the library it came from, and nobody can use ACX to find a person across other tenants' collections (ADR-011). This is the pictured person's main protection.
- `POST /recognition/retention/purge` with `scope=all` lets a tenant delete all of its face data at any time.
- There is no public or cross-tenant face search.

Gaps this ADR closes:

- **Retention is unbounded today.** `RecognitionSettings.default_retention_mode` defaults to `retain_all`, so every unnamed face's template is kept until the tenant purges (MLDATA-15).
- **Face data doesn't follow its image.** Deleting an image in WordPress leaves its face templates on the server: the plugin has no attachment-delete handler and the service has no media-delete route.
- **Templates carry no capture basis** (MLDATA-14).
- **Some statutes apply to whoever holds a face template, wherever the image lives.** Illinois BIPA (written release), Texas CUBI, Washington, GDPR Art. 9 in the EU/EEA and UK, Quebec, and the OPC's express-consent position for facial biometrics (PIPEDA Findings #2021-001) require consent, or another legal basis, before a face template is created. ACX keeps the templates on its server, so these reach ACX and its tenants even though the images live on the tenant's site. Rule 4 asks for an attestation in those jurisdictions until counsel clears them (Q-R1, Q-R4).

## Decision

Recognition stays **off until the tenant turns it on**, and onboarding asks every new tenant to decide (rule 5). A tenant that turns it on gets face groups and roster suggestions from its first describe run. From then on the tenant controls it: one switch, and delete-all at any time.

### Rule 1. Three objects

| Object | What is stored | Cleared jurisdiction | Held / unknown jurisdiction |
| --- | --- | --- | --- |
| **A. Roster match**: faces matched to a person the tenant named | Template of a named person, linked to that person | On once the tenant turns recognition on | On once turned on with the attestation (rule 4) |
| **B. Face grouping**: unnamed faces clustered so the tenant can name them | Templates of unnamed people, for at most 30 days unless named | On once turned on; unnamed faces expire (rule 2) | On once turned on with the attestation |
| **C. Public Figure Library** | Vendor gallery; tenant probes discarded when A and B are off | Per PFL scope (on by default) | Off (PFL held list) |

- Before the tenant chooses, A and B process nothing (SECD-12). C follows the PFL scope.
- A and B share one switch in the product. They are separate rows here because their retention and capture basis differ.

### Rule 2. Unnamed faces expire, and face data follows its image (MLDATA-15)

- New setting `unnamed_face_retention_days`, default **30**, max 90, validated at load (rg-008).
- A face template that no human has confirmed or named within that window is deleted with its cluster membership. A daily disposal job enforces it, and the deletion reaches pgvector indexes and backups within the backup TTL (PROV-10).
- A face becomes long-lived only when a human names or confirms the group (a capture-basis transition, rule 3). A named person's templates are kept until the tenant deletes the person or the image, purges, or the subscription ends plus 30 days.
- Rejected faces ("not a person I name", strangers deliberately left unnamed per ADR-018) are deleted on rejection, not at TTL.
- Deleting an image deletes that image's templates and cluster memberships, named or not. This is new: a plugin `delete_attachment` handler calls a new service route.
- `default_retention_mode` drops `retain_all` as the default. The per-tenant retention presets stay.

### Rule 3. Capture basis is a column (MLDATA-14) and face data is its own class (MLDATA-13)

- `media_identity.capture_basis` (StrEnum, sr-007): `tenant_library_unreviewed` (B), `tenant_named` (A, cleared jurisdiction), `tenant_named_attested` (A, held jurisdiction after the attestation), `pfl_licensed` (C).
- The match path refuses a null or unrecognised basis. A `tenant_library_unreviewed` row past its TTL, or any row whose image was deleted, is never served, even if the disposal job lags.
- Greenfield: the column goes into `001_identity_schema.py` directly.
- The body-derived data class gets its own rules: no vectors in logs or error payloads, export behind its own permission, no soft delete, and the backup TTL is recorded in the inventory.

### Rule 4. Jurisdiction hold (SECD-05)

- One tenant-level `jurisdiction` (ISO 3166-2), captured at sign-up from the billing address or an admin answer. It is shared with the PFL and replaces `tenant_pfl_settings.jurisdiction`, so there is one write (DATA-14).
- Config `recognition_attestation_jurisdictions` starts as the PFL held list: **US-IL, US-TX, US-WA, EU/EEA, UK, CA-QC**. An unknown jurisdiction counts as held. The list shrinks only on a counsel answer.
- In a held jurisdiction, **Turn on** (rule 5) also asks for an attestation: "I have the consent or legal basis required in my jurisdiction for the people I name." A and B then write `tenant_named_attested` / `tenant_library_unreviewed`. In CA-QC the tenant notice also covers Quebec's biometric-database disclosure to the CAI. Counsel confirms that duty and its timing (Q-R3).
- Every failure fails closed to off: settings unreachable, a held jurisdiction without an attestation, or a failed policy read.

### Rule 5. Offered at onboarding, one switch, and deleting is as easy as enabling (SECD-08, SECD-12)

- **Onboarding.** The plugin's first-run setup shows one step after the site connects: **Identify people in your images**. It says what is stored, that face data stays in this site's account, that unnamed faces are deleted after 30 days, and that everything can be deleted at any time. The plugin has no onboarding flow today, so this is new.
- Two buttons of equal weight, nothing pre-selected: **Turn on** and **Not now**. **Not now** leaves recognition off, and the People page then shows a turn-on card, so the choice stays one click away (rg-003). In a held or unknown jurisdiction, **Turn on** also asks for the rule 4 attestation.
- The step is an accessible dialog that wires `onOpenChange` (rg-004), and Escape means **Not now**. Every string goes through `wp.i18n` (sr-012). It runs once per tenant; greenfield, so no existing tenant needs a backfill.
- **After onboarding**, Settings → People identification holds the same switch. Turning it off warns that alt text will stop naming the people this site has identified (A11Y-38, ATAG B.4.1.3), stops all new face processing on the next request, and offers two buttons of equal weight: **Keep named people** (unnamed faces still expire under rule 2) and **Delete all face data now** (calls the existing purge route with `scope=all`).
- "Delete all face data" is also on the People page at all times, not only behind the switch.

### Rule 6. Notice (SECD-11)

- The plugin registers suggested privacy-policy text through `wp_add_privacy_policy_content()`: "This site uses AltContext to suggest names for people in images it publishes. Face data stays in this site's private AltContext account and is never shared with other sites. Unnamed faces are deleted after 30 days, and deleting an image deletes its face data." The tenant edits it.
- A vendor notice page (shared with the PFL) explains the processing and gives a subject request route. A subject's request reaches the tenant as controller. For PFL identities it reaches the tombstone path.
- The existing retention audit (`GET /recognition/retention/audit`) logs identity queries, as SECD-11 requires.

### Rule 7. Naming stays a draft (SECD-14)

Nothing changes in the naming gates: a name reaches published alt text only when an editor applies the draft (ADR-018, E20-10). A false match is caught at apply time.

### Rule 8. Necessity record (SECD-13)

- **Need:** recurring people in the tenant's own library (faculty, staff, students in a programme, sources) are the information a screen-reader user can't get from the pixels. Typing each name per image is the cost this removes.
- **Alternatives:**
  - Typing names, which is the baseline.
  - IPTC/XMP person metadata (PFL Phase 0).
  - VLM-native naming of famous people (PFL Alternative 4).
  - Named-only matching with no grouping (object A alone). Rejected because no roster ever forms without B, and a roster is how a tenant names anyone.
  - On by default with no onboarding choice. Rejected: it deviates from SECD-12, and onboarding reaches the same tenants with an explicit choice.
- **Scope:** the tenant's own library. No cross-tenant matching, no search API, no export of vectors to the tenant (MLDATA-16).
- **Effectiveness metric:** the share of tenants who turn it on at onboarding; the accepted-name rate and the false-name rate at apply time, per tenant; and the share of unnamed faces that expire unnamed. A high expiry share means B collects more than it serves.
- **Review date:** 2027-04-30.

## Release gate (RLSE-02)

The onboarding step ships only when all of these are merged on `main` and verified:

1. Rule 2 disposal job and image-delete path, with tests showing that an unnamed template past TTL, or any template whose image was deleted, is neither served nor present afterwards.
2. Rule 3 column, with a test showing the match path refuses a null basis.
3. Rule 4 jurisdiction capture and held-list resolution, with a test showing that an unknown jurisdiction requires the attestation.
4. Rule 5 onboarding step, the People-page turn-on card, the switch, both off-buttons and the always-visible delete.
5. Rule 6 privacy-policy text and vendor notice page.
6. Counsel answers to Q-R1–Q-R4.
7. E22: a commercial-licensed face model in prod, which the in-house FIR work delivers. Prod runs InsightFace buffalo_l today, whose weights are non-commercial (CARD-26), and FIR stays in dev until it is declared ready.

Until then recognition stays as it is today: off, with the switch in Settings.

## Counsel questions (RLSE-09, STRAT-03)

Each question needs a yes or no, per jurisdiction where it applies:

- **Q-R1.** Is recognition lawful for a tenant's own library when the tenant turns it on at onboarding, with a one-switch off, delete-all, a 30-day limit on unnamed faces, face data deleted with its image and the rule 6 notice? Ask for: CA federal (PIPEDA), Ontario public-sector institutions (FIPPA) for universities, the US states outside the held list, and each jurisdiction on it. In a held jurisdiction, is the tenant's attestation enough, and can rule 2 serve as the published retention schedule BIPA requires?
- **Q-R2.** Is ACX the processor and the tenant the controller for objects A and B? If not, which duties fall on ACX?
- **Q-R3.** In CA-QC, does the biometric-database disclosure to the CAI fall on the tenant or on ACX, and how far ahead of go-live must it be filed?
- **Q-R4.** Does any answer change because ACX works like a personal photo library (the tenant names people in its own images, which live on its own site), given that the templates sit on ACX's server rather than on the tenant's devices? If it does, the held list shrinks accordingly.

## Change sites (for the task plan)

- `apps/prototype-wp-alt-context/src/settings/class-recognition-policy.php::RecognitionPolicy`: unchanged. `DEFAULT` stays `false`; the onboarding step writes the option through `set()`.
- `apps/prototype-description-service/recognition/config/settings.py::RecognitionSettings`: add `unnamed_face_retention_days` and `recognition_attestation_jurisdictions`; change the `default_retention_mode` default.
- `db/migrations/versions/001_identity_schema.py` and `db/models/identity.py`: `capture_basis`, tenant `jurisdiction`.
- New disposal job plus a `systemd/` timer, beside the retention router's purge path.
- Image-delete path: a plugin `delete_attachment` handler and a service route that deletes that image's templates and cluster memberships. An ended subscription runs the purge with `scope=all` after 30 days.
- Admin UI (`apps/prototype-wp-alt-context/js/admin/`): the onboarding step, the attestation, the People-page turn-on card, the switch, both off-buttons and the always-visible delete. Every string goes through `wp.i18n` (sr-012).
- The plugin's privacy-policy content registration.
- `infra/oci/demo/bootstrap-wp.sh`: the explicit demo opt-in stays.

## Canon

| ID | Verdict |
| --- | --- |
| SECD-12 | **Met.** A and B process nothing until the tenant turns recognition on, and onboarding puts that choice in front of every tenant, so there is no post-hoc opt-out. Default-on was considered and rejected (rule 8). |
| SECD-05 | Unknown jurisdiction, unreadable settings and a stale basis all fail closed to off or not served. |
| SECD-08 | Equal-weight buttons at onboarding and at switch-off; deleting is as easy as enabling and always visible. |
| SECD-09 | Purge revokes templates; a leak plan re-enrols only from fresh captures. Templates are never treated as resettable. |
| SECD-11 | Rule 6 privacy-policy text, vendor notice page, retention audit. |
| SECD-13 | Rule 8. |
| SECD-14 | Rule 7: editor apply is the human gate for a false match. |
| MLDATA-13, -14, -15, -16, -17 | Rules 2, 3 and 8. MLDATA-15's maximum is 30 days for an unnamed face; a named face lasts until the tenant deletes the person or the image, purges, or 30 days after the subscription ends. The disposal job, the image-delete path and the subscription-end purge enforce it, and the inventory covers pgvector indexes and backups. Deleting a name never down-classifies a face; the template is deleted. |
| CARD-26 | Release gate 7 (E22). |
| CLM-03 | Onboarding copy, settings copy and privacy text must match rules 2–6 word for word. |
| A11Y-38 | Pulls against SECD-12; partitioned. Object: alt-text generation, the content support feature, stays on by default, and only face identity processing waits for the tenant's opt-in. Sequence: onboarding asks every tenant, so off is never an unchosen default (canon Principle 6). Settings and the People-page card reactivate it (B.4.1.2), switching off warns (B.4.1.3, rule 5), and the onboarding step keeps it prominent (B.4.1.4). |
| RLSE-02, RLSE-09, STRAT-03 | Release gate; counsel gets yes/no questions; legal judgement isn't made here. |

## Consequences

- Every new tenant decides at onboarding. A tenant that turns recognition on gets face groups and roster suggestions from its first describe run, so weaving (ADR-018) has a roster to weave from.
- Unnamed faces are bounded: each lives at most 30 days, in one tenant's account, and is never compared across tenants.
- Tenants in held jurisdictions (Illinois, Texas, Washington, EU/EEA, UK, Quebec) can turn it on with the attestation. Counsel can remove the attestation jurisdiction by jurisdiction.
- The Mozilla HSAI application can describe recognition as the tenant's explicit choice at onboarding, with the 30-day limit on unnamed faces and delete-all (see the HSAIFIT-1 assessment).
- Paid recognition can't ship before E22, so in practice onboarding lands with the in-house FIR model.
