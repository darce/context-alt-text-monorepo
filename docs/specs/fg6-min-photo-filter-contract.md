# FG6 optional minimum-photo listing contract

Selected bounded implementation: MCP20817, 2026-10-30. This contract governs
FG6/case 13 only. It supersedes the documentation-only restriction in the
[original request](../scopes/facegroup-0-training-free-face-grouping-request.md)
for this selected slice; that request's other proposed capabilities retain their
separate gates. The supplied scope-refresh report is advisory, not deployment
or operator acceptance evidence.

## Read API

Authenticated `GET /recognition/clusters` accepts optional `min_photos`.
Omission retains the current membership, search, labeled, paging and outlier
behavior, including real stored clusters with no members. A supplied value must
be a decimal integer from 1 through 2147483647 inclusive. Non-integers, empty
values, zero, negatives and overflow return HTTP 400. No matches returns HTTP
200 with `[]`.

Every real row returned by this listing has a derived nonnegative integer
`photo_count`. Other `ClusterResponse` producers that have not computed the
count, including top-unlabeled, return `photo_count: null`. Unknown is distinct
from a computed zero. Representatives and stored `identity_count` cannot stand
in for this value. The domain field is appended for positional compatibility;
there is no persisted counter or migration.

## Population and SQL

For the authenticated tenant, count distinct `MediaIdentity.media_id` values
reachable through `IdentityMember.identity_id = MediaIdentity.id`, grouped by
`IdentityMember.cluster_id`. Constrain both joined tables to that tenant, as well
as the outer stored cluster query. Duplicate faces from one photo count once.
The existing tenant/media-ID namespace remains authoritative: equal media IDs
are the same photo within that tenant. Do not add an embedding-space, run,
representative, label-inference or image-content population.

The current listing and member read producers do not add a `disposed_at` or
`dismissed_at` predicate to this population. This slice preserves that behavior;
physical membership/identity deletion removes its contribution on the next
read. Snapshot/export visibility predicates belong to different producers and
are not transplanted here. No access scope is broadened by the aggregate.

Compute counts in SQL with one tenant-constrained grouped aggregate joined to
the existing listing. Keep zero-member clusters using an outer join and a
computed zero. Apply the requested threshold before SQL `limit`/`offset`, along
with the existing escaped case-insensitive label search and labeled-only
conditions (`label IS NOT NULL` and `user_confirmed IS TRUE`). Eager relation
loading remains bounded by batches; no per-cluster count query is allowed.

Filtered requests order by `created_at DESC, id ASC`. This is deterministic
for a fixed dataset, including timestamp ties. Omitted-filter requests retain
`created_at DESC`. Offset pagination offers no stability guarantee across
writes. Existing post-pagination hiding of stored outliers can shorten a page;
this slice does not rewrite that behavior.

## Outliers

With `min_photos` present, omit the synthetic unassigned pseudo-group even when
`include_outliers=true`. It is not a persisted person group and must not get a
fabricated count. Do not build it in that path. Existing real stored outliers
are still included only when requested and meet the SQL threshold like other
stored rows. With the filter omitted, retain the existing synthetic producer
and stored-outlier behavior, including its existing non-UUID pseudo-ID behavior;
this contract does not repair that separate legacy response issue.

## Evidence and limits

Source path verified directly (native graph tools unavailable in this worker):
HTTP `clusters_snapshot.list_clusters` → `ClusterService.list_clusters` →
`curation.cluster_queries.list_clusters` →
`SqlAlchemyClusterRepository.get_by_tenant` → `IdentityCluster` →
`ClusterResponse`. Each edge carries `min_photos` or the derived `photo_count`.
Actual source takes precedence over dated request anchors. SQL member/identity
joins, tenant columns, eager loading, paging and the top-unlabeled manual
response producer were inspected.

Focused tests cover duplicate photos, threshold boundaries, both adversarial
tenant joins, zero members, filtering before offset with timestamp ties,
search/labeled intersections, stored/synthetic outliers, query budget,
nullable legacy responses, API validation, and API serialization through the
real SQL repository and service. SQLite tests verify query behavior only.
Recorded execution results and sandbox limitations belong to the external
worker report; test presence is not evidence of a passing execution.

For a later actual-Postgres check, use the existing migrated scratch-database
fixture, not production credentials or a production database. The opt-in
`test_min_photos_on_ephemeral_postgres` requires `FG6_POSTGRES_CHECK=1`, explicit
loopback `IDENTITY_PG_TEST_URL` / `IDENTITY_PG_ADMIN_URL`, and `fg6_scratch` in the
test database basename. Supply an already provisioned disposable local
pgvector server with an unprivileged test role and a scratch-DB admin role.
The existing fixture creates, migrates and drops a PID-suffixed isolated
scratch database and checks that the test role cannot bypass RLS. No new
credentials are created by this slice. Run through the shared two-slot runner:

```sh
# Set the two IDENTITY_PG_* URLs to that disposable local server first.
python3 /home/gate/workbay-sandbox/acx-nextwaves-20261030/common/run_check.py \
  bash -lc 'cd apps/prototype-description-service && LC_ALL=C PYTHONPATH=. FG6_POSTGRES_CHECK=1 IDENTITY_PG_REQUIRED=1 /home/gate/src/context-alt-text-monorepo/.venv/bin/python -m pytest recognition/tests/integration/test_cluster_min_photos.py -k ephemeral_postgres -q -p no:cacheprovider'
```

This is a bounded query check, not concurrency, query-plan/latency, production
Postgres RLS, deployment or live acceptance proof. No services are started by
the FG6 worker. Existing fixture migration requirements can independently block
this opt-in check.

## Canon rationale

Heuristics Canon **v0.26.2**, pinned published copy with all 53 manifest digests
verified. [DATA-14], **No dual writes**, *Designing Data-Intensive Applications*,
ch. 11: member/identity rows remain the single authority; counts are derived,
not copied into another persisted counter. The dual-write trigger is avoided.
[REF-27], **Don't program by coincidence**, *The Pragmatic Programmer*, ch. 7:
the photo namespace, visibility population, query ordering and fixed-dataset
assumption are explicit above. [WEB-08], **Authorize the object, not just the
route**, *The Web Application Hacker's Handbook*: preserve authenticated tenant
resolution and constrain both sides of the join, tested with corrupt
cross-tenant memberships. Existing RLS is retained; SQLite is not its proof.
[DATA-03], **Schema evolution compat**, *Designing Data-Intensive Applications*,
ch. 4: response additions are optional for legacy producers. [TEST-06],
**Watch it fail once / predict the failure**, *Modern Software Engineering*,
ch. 8: record expected and actual RED separately from infrastructure failures.
[GRPH-32], **An edge exists only where data moves**, practice label `bootstrap`:
the source chain names its actual fields; FG6 has no data dependency on the
independent W1 train. Applicable principle siblings and matched reasoning cards
were checked; training/UI correction siblings have no trigger in this read-only
slice. Canon source: <https://github.com/darce/heuristics-canon/tree/v0.26.2>.

No FG1–5/8 activation, FG7 job, UI/default change, privacy activation,
ADR017/018 acceptance, inference/scan, payment/configuration/account/service
mutation, or general FACEGROUP acceptance follows from this implementation.
