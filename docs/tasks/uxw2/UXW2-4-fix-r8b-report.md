# UXW2-4-R7E-01 — `label_state` is a half-wired column

## Result

Closed. Cluster reads now SELECT the same three-valued `label_state` as identity-members. `ClusterResponseMapper` emits it on list, detail, and top-unlabeled. Contract names the field.

`projected_cluster_label_select_sql()` is **not** a faithful swap on clusters-read: it aliases `AS cluster_label` (mapper reads `label`), and labeled-only WHERE at `:64` / `:81` interpolates the value CASE. SELECT sites append `projected_cluster_label_state_sql() AS label_state` beside `as label`. WHERE is unchanged.

Private `resolve_label_state()` renamed to `resolve_label_flags()` (booleans). String authority is `resolve_emitted_label_state()`: SQL column when present, else `resolve_cluster_label_state()`.

`file:line` cites below were re-derived with `sed -n '<N>p' <file>` after the last code commit.

## Closure

| Gap | Commit subject | Test | Verbatim mutant RED | GREEN selected/total |
| --- | --- | --- | --- | --- |
| Sibling repo omits `label_state` | `fix(php): emit cluster label_state on reads and REST` | `testClusterReadsAgreeWithIdentityMembersOnLabelStateShape` | `Failed asserting that 'SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, CASE WHEN p.name IS NOT NULL AND p.name <> '' THEN p.name WHEN c.label IS NULL OR c.label = '' OR (LOWER(c.label) LIKE 'cluster-%%' OR LOWER(c.label) LIKE 'cluster\_%%') THEN c.label ELSE NULL END as label\n FROM \`wp_acx_clusters\` c\n LEFT JOIN \`wp_acx_persons\` p ON c.person_id = p.id\n WHERE c.tenant_id = '33380427-1819-5ad2-922b-cdd246fac3a0'\n ORDER BY c.updated_at DESC, c.cluster_uuid ASC\n LIMIT 10 OFFSET 0' [ASCII](length: 489) contains "AS label_state" [ASCII](length: 14).` | **1 / 1** `OK (1 test, 46 assertions)` |
| Dropped before REST | same `fix(php)` commit | `testMapClusterListAndTopUnlabeledEmitLabelState` | `Failed asserting that an array has the key 'label_state'.` | **1 / 1** `OK (1 test, 6 assertions)` |
| SQL arm authority (person vs unbound row) | trait already present; exercised by `test(php): prove cluster label_state path` | `testProjectedLabelStateSqlClassifiesBoundPersonVersusUnboundHumanOnRealRows` | `Failed asserting that two strings are identical.` / expected `'unbound'` / actual `'unlabeled'` | **1 / 1** `OK (1 test, 4 assertions)` |
| Undocumented | `docs(contracts): document cluster label_state` | `git grep -n label_state docs/workbay/contracts` now hits clustering-api.md | no required mutant | — |

Each mutant restored after RED. Production `git diff` after restore was the intended change only. Same filters were **1 / 1** on the unmutated tree before the mutant (non-zero).

### Mutant RED (verbatim)

**M1** `testProjectedLabelStateSqlClassifiesBoundPersonVersusUnboundHumanOnRealRows` — swap `unbound`/`unlabeled` arms in `projected_cluster_label_state_sql`:

```
Failed asserting that two strings are identical.
--- Expected
+++ Actual
@@ @@
-'unbound'
+'unlabeled'
```

**M2** `testMapClusterListAndTopUnlabeledEmitLabelState` — drop `label_state` from both mapper emit arrays:

```
Failed asserting that an array has the key 'label_state'.
```

**M3** `testClusterReadsAgreeWithIdentityMembersOnLabelStateShape` — revert clusters-read SELECT change:

```
Failed asserting that 'SELECT COUNT(*) OVER() AS total_count, c.*, p.person_uuid, CASE WHEN p.name IS NOT NULL AND p.name <> '' THEN p.name WHEN c.label IS NULL OR c.label = '' OR (LOWER(c.label) LIKE 'cluster-%%' OR LOWER(c.label) LIKE 'cluster\_%%') THEN c.label ELSE NULL END as label
 FROM `wp_acx_clusters` c
 LEFT JOIN `wp_acx_persons` p ON c.person_id = p.id
 WHERE c.tenant_id = '33380427-1819-5ad2-922b-cdd246fac3a0'
 ORDER BY c.updated_at DESC, c.cluster_uuid ASC
 LIMIT 10 OFFSET 0' [ASCII](length: 489) contains "AS label_state" [ASCII](length: 14).
```

## Contract delta

`clustering-api.md`:

- List example gains `"label_state": "person"`. Top-unlabeled example gains `"label_state": "unlabeled"`.
- Notes: `person \| unlabeled \| unbound`; `is_auto_label` / `is_labeled` cannot express `unbound`; FE must not synthesize `cluster-<hex>` from a null label.
- Label-authority bullet names the field, endpoints (list, detail, top-unlabeled via `ClusterResponseMapper`), and the members SELECT-but-not-emitted residue.

## Gate

From `apps/prototype-wp-alt-context`:

**Baseline** (before first code commit):

```
OK (1847 tests, 8933 assertions)
```

**After**:

```
OK (1851 tests, 8994 assertions)
```

Delta: **+4 tests, +61 assertions**.

Targeted `--filter` GREEN (selected / total), each **1 / 1** before the mutant and after restore:

| Filter | Result |
| --- | --- |
| `testProjectedLabelStateSqlClassifiesBoundPersonVersusUnboundHumanOnRealRows` | **1 / 1** `OK (1 test, 4 assertions)` |
| `testMapClusterListAndTopUnlabeledEmitLabelState` | **1 / 1** `OK (1 test, 6 assertions)` |
| `testClusterReadsAgreeWithIdentityMembersOnLabelStateShape` | **1 / 1** `OK (1 test, 46 assertions)` |

## file:line

| Claim | `sed -n` |
| --- | --- |
| State SQL `person` / `unlabeled` / `unbound` | `trait-detects-system-defined-labels.php:54` |
| Members SELECT helper (`AS cluster_label` + `AS label_state`) | `:57-59` |
| PHP fallback | `:62` `resolve_cluster_label_state` |
| Clusters-read SELECT `as label` + `AS label_state` | `class-clusters-read-repository.php:61`, `:78`, `:94`, `:111`, `:244`, `:322` |
| Labeled-only WHERE still value CASE (not `label_state`) | `:64`, `:81` |
| Top-unlabeled emit | `class-cluster-response-mapper.php:110` |
| List/detail emit | `:158` |
| Boolean helper renamed | `:329` `resolve_label_flags` |
| String helper (SQL column, else trait) | `:348` `resolve_emitted_label_state` → `:367` `resolve_cluster_label_state` |
| Contract examples | `clustering-api.md:207`, `:266` |
| Contract notes + authority | `:242-243`, `:449` |
| Members still SELECT (not edited) | `class-identity-members-read-repository.php:57`, `:75`, `:136`, `:217` |

## Undone

- **FE.** `js/` and `docs/ux-maps/` untouched (sibling lane). `npx vitest run` not run.
- **Member mapper.** Identity-members SELECTs still compute `label_state`; `MemberResponseMapper` does not copy it onto member / media-identities rows. Not owned this round.
- **Shared-contract schemas.** `packages/shared-contracts/schemas/recognition-cluster-*-response.schema.json` do not yet list `label_state` (no `additionalProperties: false`; extra key is valid). Not owned.
- **Goldens.** Six local-projection fixtures under `tests/fixtures/clusters-read/` regenerated (`UPDATE_CLUSTERS_READ_FIXTURES=1`) so characterization matches the new key. Forced by `composer test`; listed because they sit outside the owned-path set.
- **Handoff.** Isolated lane clone has no MCP `workbay-handoff-mcp` tools; integrator records the decision after transplant.
