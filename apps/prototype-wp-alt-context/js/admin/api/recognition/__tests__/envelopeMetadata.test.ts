import { describe, expect, it } from 'vitest';

import {
  DATA_SOURCE,
  PROJECTION_STATUS,
  parseDataSource,
  parseProjectionStatus,
} from '../types/dataSource';
import { mapPendingSuggestions, mapPendingMergeSuggestions } from '../identitySuggestionMappers';
import { fetchMediaIdentities } from '../identityQueriesApi';

// ---------------------------------------------------------------------------
// parseDataSource
// ---------------------------------------------------------------------------

describe('parseDataSource', () => {
  it('returns the value for each valid data source', () => {
    expect(parseDataSource('local_projection')).toBe(DATA_SOURCE.LOCAL_PROJECTION);
    expect(parseDataSource('backend_proxy')).toBe(DATA_SOURCE.BACKEND_PROXY);
    expect(parseDataSource('unavailable')).toBe(DATA_SOURCE.UNAVAILABLE);
  });

  it('returns null for invalid values', () => {
    expect(parseDataSource('invented_source')).toBeNull();
    expect(parseDataSource('')).toBeNull();
    expect(parseDataSource(null)).toBeNull();
    expect(parseDataSource(undefined)).toBeNull();
    expect(parseDataSource(42)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// parseProjectionStatus
// ---------------------------------------------------------------------------

describe('parseProjectionStatus', () => {
  it('returns the value for each valid projection status', () => {
    expect(parseProjectionStatus('available')).toBe(PROJECTION_STATUS.AVAILABLE);
    expect(parseProjectionStatus('bootstrapping')).toBe(PROJECTION_STATUS.BOOTSTRAPPING);
    expect(parseProjectionStatus('unavailable')).toBe(PROJECTION_STATUS.UNAVAILABLE);
  });

  it('returns null for invalid values', () => {
    expect(parseProjectionStatus('stale')).toBeNull();
    expect(parseProjectionStatus('')).toBeNull();
    expect(parseProjectionStatus(null)).toBeNull();
    expect(parseProjectionStatus(undefined)).toBeNull();
  });
});


// ---------------------------------------------------------------------------
// mapPendingSuggestions — envelope metadata provenance
// ---------------------------------------------------------------------------

describe('mapPendingSuggestions', () => {
  it('preserves envelope metadata from a valid response', () => {
    const response = {
      suggestions: [{ id: 's1', identity_id: 'i1', cluster_id: 'c1', rep_similarity: 0.9, status: 'pending' }],
      total: 1,
      limit: 25,
      offset: 0,
      data_source: 'backend_proxy',
    };

    const mapped = mapPendingSuggestions(response as any);
    expect(mapped.total).toBe(1);
    expect(mapped.limit).toBe(25);
    expect(mapped.offset).toBe(0);
    expect(mapped.data_source).toBe('backend_proxy');
  });

  it('throws when total is missing', () => {
    const response = {
      suggestions: [],
      limit: 25,
      offset: 0,
      data_source: 'backend_proxy',
    };

    expect(() => mapPendingSuggestions(response as any)).toThrow('numeric total');
  });

  it('throws when data_source is invalid', () => {
    const response = {
      suggestions: [],
      total: 0,
      limit: 25,
      offset: 0,
      data_source: 'invented',
    };

    expect(() => mapPendingSuggestions(response as any)).toThrow('valid data_source');
  });

  it('throws when limit is not a number', () => {
    const response = {
      suggestions: [],
      total: 0,
      limit: 'twenty-five',
      offset: 0,
      data_source: 'backend_proxy',
    };

    expect(() => mapPendingSuggestions(response as any)).toThrow('numeric limit');
  });
});

// ---------------------------------------------------------------------------
// mapPendingMergeSuggestions — envelope metadata provenance
// ---------------------------------------------------------------------------

describe('mapPendingMergeSuggestions', () => {
  it('preserves envelope metadata from a valid response', () => {
    const response = {
      suggestions: [{ id: 'm1', source_cluster_id: 'a', target_cluster_id: 'b', similarity: 0.85, status: 'pending' }],
      total: 1,
      limit: 10,
      offset: 0,
      data_source: 'backend_proxy',
    };

    const mapped = mapPendingMergeSuggestions(response as any);
    expect(mapped.total).toBe(1);
    expect(mapped.limit).toBe(10);
    expect(mapped.data_source).toBe('backend_proxy');
  });

  it('throws when data_source is missing', () => {
    const response = {
      suggestions: [],
      total: 0,
      limit: 10,
      offset: 0,
    };

    expect(() => mapPendingMergeSuggestions(response as any)).toThrow('valid data_source');
  });
});

// ---------------------------------------------------------------------------
// fetchMediaIdentities — empty-array guard
// ---------------------------------------------------------------------------

describe('fetchMediaIdentities', () => {
  it('throws on empty media IDs instead of inventing a data_source', async () => {
    await expect(fetchMediaIdentities([])).rejects.toThrow('requires at least one media ID');
  });
});
