import { describe, expect, it } from 'vitest';
import type { RosterEntry, RosterEntryCluster, RosterEntryRepresentativeIdentity } from '../roster-entry';
import { selectRepresentativeIdentity } from '../../../pages/roster/RosterEntriesTable';

const makeEntry = (clusters: RosterEntryCluster[]): RosterEntry => ({
  id: 1,
  person_uuid: '11111111-1111-1111-1111-111111111111',
  name: 'Alice',
  tags: [],
  cluster_count: clusters.length,
  clusters,
  queue_memberships: [],
  updated_at: '2026-05-07T14:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T14:00:00Z',
});

const makeCluster = (
  cluster_id: string,
  identity_count: number,
  identity_id: string,
  representative_quality: number | null,
): RosterEntryCluster => ({
  cluster_id,
  identity_count,
  representative_identity: {
    identity_id,
    media_id: 1,
    media_url: null,
    bbox: null,
    similarity: null,
    representative_quality,
  } satisfies RosterEntryRepresentativeIdentity,
  instances: [],
});

describe('roster representative projection', () => {
  it('chooses the highest projected representative quality before identity count', () => {
    const entry = makeEntry([
      makeCluster('cluster-a', 8, 'identity-count-winner', 0.31),
      makeCluster('cluster-b', 2, 'quality-winner', 0.94),
    ]);

    expect(selectRepresentativeIdentity(entry)?.identity_id).toBe('quality-winner');
  });

  it('falls back to identity count when projected quality is unavailable', () => {
    const entry = makeEntry([
      makeCluster('cluster-b', 2, 'smaller-cluster', null),
      makeCluster('cluster-a', 8, 'identity-count-winner', null),
    ]);

    expect(selectRepresentativeIdentity(entry)?.identity_id).toBe('identity-count-winner');
  });
});
