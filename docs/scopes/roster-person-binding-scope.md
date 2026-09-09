# Scope note: roster person-binding (wp_acx_persons empty) — deferred, rides E22

Date: 2026-07-16 · Intake: /scope (ALTQ/VLM curation session) · Status: **deferred by decision**

## Finding

`wp_acx_persons` is empty on the 10018 curation tenant while 133 confirmed cluster labels
exist. Investigated end-to-end:

- **Non-breaking today**: production name-injection reads `IdentityCluster.label`
  (`recognition/interface_adapters/http/deps/stores.py:173-225` — `list_by_media_ids`
  selects `cluster_label` + `user_confirmed`), NOT the roster. The workbench label flow
  and describe/media-identities responses work without any person rows.
- **The contract supports binding** (`docs/workbay/contracts/curation-sync-api.md` L99:
  binding sets `identity_clusters.roster_id = person_uuid` and derives the label from
  `person_name`) — the workbench label flow simply never creates/binds persons; the WP
  roster surface (`/roster/persons` CRUD, `RosterEntryProjectionRepository`) is only fed
  by legacy import or manual roster management.
- **Real (latent) debt — identity safety, not behavior**: the same human across N
  clusters is N duplicate strings. Evidence: the 2026-07-16 export shows **133 labeled
  clusters but 130 distinct names** (3 people already split). Renames don't propagate;
  merges aren't identity-safe; cross-cluster analytics can't group by person.

## Decision (intake answers, 2026-07-16)

- **Defer**: labels suffice for the bake-off/demo. Confirmed: the ALTQ interleave path
  consumes the label-sourced export (`curated-identities-20260716.json`, 530 attachments)
  and never touches `wp_acx_persons` — deferral has zero impact on GPU/CPU bake-off work.
- **Ownership: rides E22 / FIR (commercial face pipeline)** — identity storage is already
  in that epic's blast radius; doing roster binding standalone risks rework.

## Acceptance criteria to carry into E22 (apply when the work happens)

1. **Backfill parity**: `wp_acx_persons` rows == distinct confirmed names; every labeled
   cluster carries `roster_id`; zero orphan labels.
2. **Rename propagation**: renaming a person updates all bound clusters' labels and
   downstream `media/identities` responses in one operation (test-pinned).
3. **Dedupe the splits**: duplicate-label people become one person UUID spanning their
   clusters (as of 2026-07-16: 3 cases; re-run the export to verify 130 persons / 133
   bindings).

## Not-doing (now)

- No auto-bind-on-confirm write path, no backfill, no person-management UI outside E22.
- No change to the bake-off/interleave pipeline — it stays label-sourced.
