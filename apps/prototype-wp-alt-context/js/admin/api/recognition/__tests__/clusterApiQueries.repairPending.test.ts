import { describe, expect, it } from 'vitest';

import { normalizeTopUnlabeledClustersResponse } from '../clusterApiQueries';
import { DATA_SOURCE } from '../types/dataSource';

const envelope = (overrides: Record<string, unknown> = {}) => ({
  clusters: [],
  limit: 20,
  total: 0,
  truncated: false,
  singleton_count: 0,
  has_clusters: false,
  data_source: DATA_SOURCE.LOCAL_PROJECTION,
  ...overrides,
});

describe('normalizeTopUnlabeledClustersResponse repair_pending', () => {
  it('R3-03: maps repair_pending true from a raw envelope and false when absent', () => {
    expect(normalizeTopUnlabeledClustersResponse(envelope({ repair_pending: true })).repair_pending).toBe(
      true,
    );
    expect(normalizeTopUnlabeledClustersResponse(envelope()).repair_pending).toBe(false);
  });
});
