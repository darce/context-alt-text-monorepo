# ROSTER_EVIDENCE remote brief

Read COMMON.md + UI-CONTRACTS.md.

## objective

Enlarge person evidence and expose existing person photo collection without a second roster/media API.

## finding

19861.

## anchors

DIRECTORY_THUMB_SIZE31=32; EditableRow149–377 already opens workspace from avatar/name/facegroupcount. listPersonMedia168–188 calls rosterPersons/personId/media GET with limit/offset/with_person_ids. Existing Photos section. cluster_count counts groups, not photos.

## rules

NAV-11 Deep links encode place/state (Designing Interfaces3); PERC-01 Proximity binds meaning (Designing with the Mind in Mind + Refactoring UI §avoid-ambiguous-spacing); DATA-14 No dualwrites (Designing Data-Intensive Applications ch11).

## accept

Neutral populatedfixture (audited site0people);64px directory/96px header proposals checked narrow/desktop. Explicit Viewphotos reaches same stablepersonID/existing paginated Photos; keyboard and brokenimagefallback work. Rename/merge/delete/correction remain distinct; no inferred name-based deduplication.

## owned paths

- apps/prototype-wp-alt-context/js/admin/pages/roster/RosterEntriesTable.tsx
- apps/prototype-wp-alt-context/js/admin/pages/roster/PersonWorkspacePanel.tsx
- apps/prototype-wp-alt-context/js/admin/styles/components/_roster.scss

## scoped verification on VM

From apps/prototype-wp-alt-context: npm test -- js/admin/pages/roster/__tests__/RosterEntriesTable.clickthrough.test.tsx js/admin/pages/roster/__tests__/RosterEntriesTable.enterToSave.test.tsx js/admin/pages/roster/__tests__/PersonWorkspacePanel.test.tsx js/admin/pages/roster/__tests__/PersonWorkspacePanel.alsoWith.test.tsx
Then npm run typecheck and narrowly added headless acceptance. Install locked dependencies only in assigned remote sandbox if absent. Never use test:agent because it masks failure. Root reconciles exact lane/counter/subject before dispatch.
