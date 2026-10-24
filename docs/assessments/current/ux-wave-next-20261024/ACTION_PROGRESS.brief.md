# ACTION_PROGRESS remote brief

Read COMMON.md + UI-CONTRACTS.md.

## objective

Move existing Describe and its existing run status into one persistent library action surface; preserve run/idempotency and primary ownership. Status hooks/vocabulary/settings are read-only; original GPU_STATUS owns their correctness.

## finding

19859; reuse19714.

## anchors

MediaSelectionRouted162–631 currently places BulkDescribeCta after fulltable at478; BulkDescribeCta841–1039; BulkDescribeProgress1103–1352. Existing status correctness/dormant-toast suppression are READ ONLY here, owned by original GPU_STATUS. Do not repair hooks, vocabulary, or settings in this geometry lane.

## rules

PERC-01 Proximity binds meaning (Designing with the Mind in Mind + Refactoring UI §avoid-ambiguous-spacing); INT-05 Prominent Done, INT-08 Waitstate/cancel (Designing Interfaces3); INT-10 Status–predict–stop (Human-Centered AI); INT-16 Resume preservedstate (Design of Everyday Things ch5).

## accept

0/1/10selection; queued/warming/describing/lostpoll/cancelling/terminal/reload. Exactlyone submit/cancel and relevant announcement; no fabricated CPU/result claims. Headless Chrome rendered tall-row fixture must prove active viewport/focus geometry at1440x1000 and719x960; jsdom membership alone is insufficient.

## owned paths

- apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx
- apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss

## scoped verification on VM

From apps/prototype-wp-alt-context: npm test -- js/admin/pages/workbench/__tests__/MediaSelection.gpuStatus.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.describePollRecovery.test.tsx js/admin/pages/workbench/__tests__/MediaSelection.statusAnnouncement.test.tsx js/admin/hooks/__tests__/useGpuStateToasts.test.tsx
Then npm run typecheck and narrowly added headless acceptance. Install locked dependencies only in assigned remote sandbox if absent. Never use test:agent because it masks failure. Root reconciles exact lane/counter/subject before dispatch.

Owned tests are restricted to scoped MediaSelection action/progress placement/geometry tests. Existing useGpuStateToasts tests may be run as a read-only regression check; hook source/tests stay with original GPU_STATUS. ACTION_PROGRESS does not wait for the hook repair; joined gate verifies the combined result.
