# IDCHIP-1. Identity chips grouped by person, representative avatar, roster merge and click-through

> Source: `docs/assessments/current/roster-workbench-identity-ux-assessment-20260913.md` (decision 11143).
> Branch `feature/idchip-1`. Lane manifest `config/lane-orchestration/IDCHIP-1.json`.

## Objective

On demo workbench page 2 every media row shows the same person as several identity chips, each with a different face. Fix both defects and the roster gaps the assessment traced to the same cause: chips and roster rows expose cluster topology instead of the person.

## Contract (layer 0, committed first on `feature/idchip-1`)

`DetectedIdentity` gains `person_id?: string | null` (stringified `acx_persons.id` bound to the identity's cluster) and `representative_face?: RepresentativeFace | null` (`identity_id`, `media_id`, `media_url`, `attachment_url?`, `bbox`, resolved server-side from the cluster's `representative_id`). `ClusterGroup` gains `personId?` and `clusterIds?`. All fields optional so the backend-proxy path (python recognition service, unchanged in this task) degrades to today's cluster grouping.

## Slices

1. **payload** (PHP): `IdentityMembersReadRepository::list_for_media_ids` selects `c.person_id` and resolves each distinct `c.representative_id` to its member row's `attachment_id`/`bbox_json`; `MemberResponseMapper::map_cluster_identity` emits `person_id` (string or null) and `representative_face` via the existing `resolve_face_source_fields`. Proxy normalizer passes both through when present, never fabricates them (rg-015). Contract doc `workbench-media-api.md` updated.
2. **group** (TS): `groupIdentitiesByClusters` keys on `person_id ?? cluster_id ?? identity-<id>`, sets `personId`, `clusterIds` (ordered, distinct), `label` from the first labelled member. Existing behaviour unchanged when `person_id` is absent.
3. **avatar** (TS): `ClusterPreview` renders `representative_face` when it has `media_url`+`bbox`, else the current item's face (today's path). `IdentityClusterItem` shows an "N face groups" badge when `clusterIds.length > 1` and keeps the member `+N` count. Vocabulary in `representativeVocabulary.ts`.
4. **roster-nav** (TS): roster row name and avatar open `PersonWorkspacePanel` for that entry; rename is reached only through the pencil icon; the Face groups cell becomes a button into the same panel. Keyboard reachable, accessible names on both controls.
5. **person-merge-api** (PHP): `PersonMergeService::preview(survivor_id, loser_id)` returns survivor/loser names, tag union, cluster counts and conflicts; `commit()` runs inside `run_transactional` (sr-009): rebind loser's clusters to survivor, union tags, delete loser row, record an undo token holding the prior bindings; `undo(token)` restores. Never triggered by name matching (finding 9307). Routes under `acx/v1/roster/persons/merge` (`preview`, `commit`, `undo`).
6. **uxmap** (docs): `workbench-identity-chips.uxmap.json` (states: single cluster, N face groups, representative vs current face, merge affordance, undo banner) and roster-people additions; rendered by `render_ux_maps.py`, nothing hand-written below `## Screens`.
7. **person-merge-ui** (TS, after 4 and 5): merge affordance on roster rows, `PersonMergeDialog` preview, commit, `MergeUndoBanner`-style undo; invalidates roster.entries, clusters.all, clusters.labels, media.identities (finding 3864).

## DAG

```
layer 0  contract commit (coordinator)
layer 1  payload | group | avatar | roster-nav | person-merge-api | uxmap      (6 parallel)
layer 2  person-merge-ui  <- roster-nav, person-merge-api
layer 3  astra LOW integration review of feature/idchip-1 (cross-slice consistency only)
```

Conflict graph (concurrent writes): `RosterEntriesTable.tsx` is written by roster-nav then person-merge-ui (edge, not parallel). `IdentityClusterItem.tsx` is owned by avatar only; group owns `utils.ts` and `IdentityClusterList.tsx`. No other shared files.

## Canon checks

- HAI-01 evidence before label: collapsing chips keeps the face-group count visible.
- HAI-17 render the store's reference image: representative crop, current face as fallback only.
- INT-07 preview before commit, INT-09 reversible: person merge has preview and undo, same as cluster merge.
- Release It! stable contracts: new fields optional, absent means unresolved, never invented (rg-015).
- DDIA schema evolution: additive optional fields, consumers tolerate absence.
- Small-batch review: one Luna MAX review per lane delta, narrow Astra LOW integration pass.

## Verification

- Lane tests per manifest `test_commands`; coordinator runs `npx tsc --noEmit` and the full vitest suite on `feature/idchip-1` after each integration.
- PHPUnit: `vendor/bin/phpunit` full run before the merge-candidate gate.
- Demo proof after release: workbench page 2 rows show one chip per person with the representative face.
