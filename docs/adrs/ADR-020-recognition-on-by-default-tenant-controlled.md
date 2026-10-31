# ADR-020: Face recognition on by default for the tenant's own library, with bounded retention, a jurisdiction hold and one off switch

- **Status:** Proposed (operator direction 2026-10-31; needs operator acceptance, then counsel answers before the default flips)
- **Date:** 2026-10-31
- **Context task:** BIODEF-1
- **Supersedes (when accepted):** the `RecognitionPolicy::DEFAULT = false` posture landed in commit `31ef9cbc82` (E4, 2026-09-18), and the "private recognition stays opt-in" half of [public-figure-library-scope.md](../scopes/public-figure-library-scope.md) § How it would work, item 2.
- **Coordinates with:** [public-figure-library-scope.md](../scopes/public-figure-library-scope.md) (PFL; shares the jurisdiction field and held list), [ADR-011](ADR-011-retire-on-device-recognition-remote-only.md) (single remote backend, RLS tenanting), [ADR-019](ADR-019-person-anchored-curation-surfaces.md) (curation surfaces).
- **Heuristics (Canon v0.26.2):** SECD-05, SECD-08, SECD-09, SECD-11, SECD-12, SECD-13, SECD-14, MLDATA-13, MLDATA-14, MLDATA-15, MLDATA-16, MLDATA-17, CARD-26, CLM-03, RLSE-02, RLSE-09, STRAT-03, A11Y-38.

## Context

Weaving tenant-curated identities into descriptions is the main product proposition (ADR-018, ADR-019). With recognition off by default, a new tenant's first describe run names nobody, and the curation flow that builds the roster (face groups → name a person) never starts unless the tenant finds the setting. Market comparators:

- Apple Photos labels people on the device. Templates never leave it.
- Free alt-text tools (AltText.ai, autoalt.ai, imagecaptiongenerator.com) name famous people from pixels through the VLM, with no stored gallery ([PFL scope](../scopes/public-figure-library-scope.md) § Prior art, Market).
- DBGallery and PhotoShelter PeopleID apply a named face across the collection ([pricing strategy](../gtm/pricing-2026-10-08/strategy.md) § Facial recognition).

ACX already has protections most comparators lack:

- Postgres RLS isolates every tenant, so one tenant's gallery can't match faces in another tenant's library (ADR-011).
- `POST /recognition/retention/purge` with `scope=all` lets a tenant delete all of its face data at any time.
- There is no public or cross-tenant face search.

What that doesn't cover:

- **The pictured person still doesn't choose.** Off-by-default doesn't protect them either; a tenant ticking a box isn't the subject's consent. What protects the subject is what is stored about them, for how long, where, and whether anyone tells them. This ADR therefore moves the protection from the default to those four places.
- **Retention is unbounded today.** `RecognitionSettings.default_retention_mode` defaults to `retain_all`, so every detected bystander's template is kept until the tenant purges (MLDATA-15).
- **Templates carry no capture basis** (MLDATA-14).
- **Some statutes put a consent duty on the controller for the pictured person.** Tenants sign up for ACX to get this feature, so the tenant's choice isn't in question. The person in the photo is. The tenant is the controller of its library (PFL scope § Assumptions). In some jurisdictions the controller needs that person's consent, or another legal basis, before a template is created: Illinois BIPA (written release), Texas CUBI, Washington, GDPR Art. 9 in the EU/EEA and UK, Quebec, and the OPC's express-consent position for facial biometrics (PIPEDA Findings #2021-001). Rule 4 keeps those jurisdictions opt-in, with an attestation.

## Decision

Recognition is **on by default** for a tenant in a cleared jurisdiction, and **opt-in** in a held or unknown jurisdiction. The default is safe because it is split by what gets stored.

### Rule 1. Three objects, three defaults

| Object | What is stored | Default (cleared jurisdiction) | Default (held / unknown) |
| --- | --- | --- | --- |
| **A. Roster match**: faces matched to a person the tenant named | Template of a named person, linked to that person | On | Off until opt-in with attestation (rule 4) |
| **B. Face grouping**: unnamed faces clustered so the tenant can name them | Templates of unnamed people, for a bounded time | On, with the unnamed-face retention limit (rule 2) | Off until opt-in with attestation |
| **C. Public Figure Library** | Vendor gallery; tenant probes discarded when A and B are off | Per PFL scope (on, held list) | Off (PFL held list) |

- **Cold start.** A tenant with recognition on and an empty roster still processes faces under B. That is the deviation from SECD-12, recorded in § Canon.
- A and B share one switch in the product. They are separate rows here because their retention differs.

### Rule 2. Unnamed faces expire (MLDATA-15)

- New setting `unnamed_face_retention_days`, default **30**, max 90, validated at load (rg-008).
- A face template that no human has confirmed or named within that window is deleted with its cluster membership. A daily disposal job enforces it, and the deletion reaches pgvector indexes and backups within the backup TTL (PROV-10).
- A face becomes long-lived only when a human names or confirms the group (a capture-basis transition, rule 3). A named person's templates are kept until the tenant deletes the person, purges, or the subscription ends plus 30 days.
- Rejected faces ("not a person I name", strangers deliberately left unnamed per ADR-018) are deleted on rejection, not at TTL.
- `default_retention_mode` drops `retain_all` as the default. The per-tenant retention presets stay.

### Rule 3. Capture basis is a column (MLDATA-14) and face data is its own class (MLDATA-13)

- `media_identity.capture_basis` (StrEnum, sr-007): `tenant_library_unreviewed` (B), `tenant_named` (A, cleared jurisdiction), `tenant_named_attested` (A, held jurisdiction after opt-in), `pfl_licensed` (C).
- The match path refuses a null or unrecognised basis. A `tenant_library_unreviewed` row past its TTL is never served, even if the disposal job lags.
- Greenfield: the column goes into `001_identity_schema.py` directly.
- The body-derived data class gets its own rules: no vectors in logs or error payloads, export behind its own permission, no soft delete, and the backup TTL is recorded in the inventory.

### Rule 4. Jurisdiction hold (SECD-05)

- One tenant-level `jurisdiction` (ISO 3166-2), captured at onboarding from the billing address or an admin answer. It is shared with the PFL and replaces `tenant_pfl_settings.jurisdiction`, so there is one write (DATA-14).
- Config `recognition_optin_jurisdictions` starts as the PFL held list: **US-IL, US-TX, US-WA, EU/EEA, UK, CA-QC**. An unknown jurisdiction counts as held. The list shrinks only on a counsel answer.
- In a held jurisdiction, turning recognition on asks for an attestation: "I have the consent or legal basis required in my jurisdiction for the people I name." A and B then write `tenant_named_attested` / `tenant_library_unreviewed`. In CA-QC the tenant notice also covers Quebec's biometric-database disclosure to the CAI. Counsel confirms that duty and its timing (Q-R3).
- Every failure fails closed to off: settings unreachable, jurisdiction unknown, or the service default unreadable.

### Rule 5. One switch, and deleting is as easy as enabling (SECD-08)

- Settings → People identification: one switch, on by default where rule 4 allows. Turning it off stops all new face processing on the next request.
- Turning it off offers two buttons of equal weight: **Keep named people** (unnamed faces still expire under rule 2) and **Delete all face data now** (calls the existing purge route with `scope=all`).
- "Delete all face data" is also on the People page at all times, not only behind the switch.
- The first describe run that names or groups a face shows a one-time notice that names the switch and the delete button.

### Rule 6. Notice (SECD-11)

- The plugin registers suggested privacy-policy text through `wp_add_privacy_policy_content()`: "This site uses AltContext to suggest names for people in images it publishes. Face data stays in this site's private AltContext account, is never shared with other sites, and unnamed faces are deleted after 30 days." The tenant edits it.
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
  - Named-only matching with no grouping (object A alone). It is rejected as the default because no roster ever forms without B, and a roster is how a tenant names anyone.
- **Scope:** the tenant's own library. No cross-tenant matching, no search API, no export of vectors to the tenant (MLDATA-16).
- **Effectiveness metric:** the accepted-name rate and the false-name rate at apply time, per tenant, plus the share of unnamed faces that expire unnamed. A high expiry share means B collects more than it serves.
- **Review date:** 2027-04-30.

## Release gate (RLSE-02)

The default flips (`RecognitionPolicy::DEFAULT` resolves on) only when all of these are merged on `main` and verified:

1. Rule 2 disposal job, with a test showing that an unnamed template past TTL is neither served nor present after the job runs.
2. Rule 3 column, with a test showing the match path refuses a null basis.
3. Rule 4 jurisdiction capture and held-list resolution, with a test showing that unknown resolves to off.
4. Rule 5 switch, both off-buttons, and the always-visible delete.
5. Rule 6 privacy-policy text and vendor notice page.
6. Counsel answers to Q-R1–Q-R3 for every jurisdiction where the default is on.
7. A commercial-licensed face embedder in prod. Today prod runs InsightFace buffalo_l, whose weights are non-commercial (CARD-26; E22). This already blocks paid recognition; default-on widens the exposure from opted-in tenants to every tenant.

Until then the default stays `false`.

## Counsel questions (RLSE-09, STRAT-03)

Answer yes or no for each jurisdiction:

- **Q-R1.** Is recognition lawful on by default for a tenant's own library, with a one-switch off, a 30-day limit on unnamed faces and the rule 6 notice? Ask for: CA federal (PIPEDA), Ontario public-sector institutions (FIPPA) for universities, the US states outside the held list, and each state on it.
- **Q-R2.** Is ACX the processor and the tenant the controller for objects A and B? If not, which duties fall on ACX?
- **Q-R3.** In CA-QC, does the biometric-database disclosure to the CAI fall on the tenant or on ACX, and how far ahead of go-live must it be filed?

## Change sites (for the task plan)

- `apps/prototype-wp-alt-context/src/settings/class-recognition-policy.php::RecognitionPolicy`: a missing option row resolves from the service-reported effective default (rule 4) instead of the `DEFAULT` constant. It fails closed to `false` when that read fails. Stored `'1'`/`'0'` still wins.
- `apps/prototype-description-service/recognition/config/settings.py::RecognitionSettings`: add `unnamed_face_retention_days` and `recognition_optin_jurisdictions`; change the `default_retention_mode` default.
- `db/migrations/versions/001_identity_schema.py` and `db/models/identity.py`: `capture_basis`, tenant `jurisdiction`.
- New disposal job plus a `systemd/` timer, beside the retention router's purge path.
- Admin UI (`apps/prototype-wp-alt-context/js/admin/`): the switch, the attestation, both off-buttons, the always-visible delete and the first-run notice. Every string goes through `wp.i18n` (sr-012).
- The plugin's privacy-policy content registration.
- `infra/oci/demo/bootstrap-wp.sh`: the explicit demo opt-in stays, since the demo tenant's jurisdiction is set.

## Canon

| ID | Verdict |
| --- | --- |
| SECD-12 | **Deviation, recorded.** S-tier: a strong default with named exemptions. Object A at cold start does no identity processing (empty roster), but B does, so this is an opt-out design for face grouping, which the row's "avoid post-hoc opt-out only" names. The case for deviating: tenants sign up for ACX to get identity weaving, so signing up is the tenant's affirmative choice (operator, 2026-10-31). A second opt-in inside the product protected the tenant's choice twice and the subject's not at all. The subject's protections are rules 2, 3, 4 and 6. Held jurisdictions keep opt-in. A canon gap goes to the maintainer: the row doesn't separate "who chooses" (tenant vs subject) from "what is stored". |
| SECD-05 | Unknown jurisdiction, unreadable settings and a stale basis all fail closed to off or not served. |
| SECD-08 | One switch; deleting is as easy as enabling and always visible. |
| SECD-09 | Purge revokes templates; a leak plan re-enrols only from fresh captures. Templates are never treated as resettable. |
| SECD-11 | Rule 6 privacy-policy text, vendor notice page, retention audit. |
| SECD-13 | Rule 8. |
| SECD-14 | Rule 7: editor apply is the human gate for a false match. |
| MLDATA-13, -14, -15, -16, -17 | Rules 2, 3 and 8. Deleting a name never down-classifies a face; the template is deleted. |
| CARD-26 | Release gate 7. |
| CLM-03 | Settings copy and privacy text must match rules 2–6 word for word. |
| A11Y-38 | Supporting context: an authoring-tool aid that is off by default goes unused. It doesn't override SECD-12; it explains why the default matters to the product. |
| RLSE-02, RLSE-09, STRAT-03 | Release gate; counsel gets yes/no questions; legal judgement isn't made here. |

## Consequences

- New tenants in cleared jurisdictions get face groups and roster suggestions on their first describe run. Weaving (ADR-018) has a roster to weave from.
- Bystanders are bounded: an unnamed face lives at most 30 days, in one tenant's account.
- Held-jurisdiction tenants (Illinois, Texas, Washington, EU/EEA, UK, Quebec) keep opt-in until counsel clears them.
- The Mozilla HSAI application must describe this posture accurately. "On by default" reads against the Intentional principle, so the application leads with tenant control, the 30-day limit and delete-all (see the HSAIFIT-1 assessment).
- The default can't flip before E22, so in practice it lands with the commercial embedder.
