import { describe, expect, it } from 'vitest';

import { DATA_SOURCE, PROJECTION_STATUS, parseDataSource, parseProjectionStatus } from '../types/dataSource';
import type { PendingMergeSuggestionsResponse, PendingSuggestionsResponse } from '../types';
import { mapPendingSuggestions, mapPendingMergeSuggestions } from '../identitySuggestionMappers';
import { fetchMediaIdentities } from '../identityQueriesApi';

const asPendingSuggestionsResponse = (value: Record<string, unknown>): PendingSuggestionsResponse =>
  value as unknown as PendingSuggestionsResponse;

const asPendingMergeSuggestionsResponse = (value: Record<string, unknown>): PendingMergeSuggestionsResponse =>
  value as unknown as PendingMergeSuggestionsResponse;

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
    const response: PendingSuggestionsResponse = {
      suggestions: [
        {
          id: 's1',
          identity_id: 'i1',
          suggested_cluster_id: 'c1',
          representative_similarity: 0.9,
          resolution: 'pending',
        },
      ],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.BACKEND_PROXY,
    };

    const mapped = mapPendingSuggestions(response);
    // COR-3 (rg-015): no authoritative total is forwarded by the boundary.
    expect('total' in mapped).toBe(false);
    expect(mapped.limit).toBe(25);
    expect(mapped.offset).toBe(0);
    expect(mapped.data_source).toBe('backend_proxy');
  });

  it('throws when data_source is invalid', () => {
    const response = asPendingSuggestionsResponse({
      suggestions: [],
      total: 0,
      limit: 25,
      offset: 0,
      data_source: 'invented',
    });

    expect(() => mapPendingSuggestions(response)).toThrow('valid data_source');
  });

  it('throws when limit is not a number', () => {
    const response = asPendingSuggestionsResponse({
      suggestions: [],
      total: 0,
      limit: 'twenty-five',
      offset: 0,
      data_source: DATA_SOURCE.BACKEND_PROXY,
    });

    expect(() => mapPendingSuggestions(response)).toThrow('numeric limit');
  });
});

// ---------------------------------------------------------------------------
// mapPendingMergeSuggestions — envelope metadata provenance
// ---------------------------------------------------------------------------

describe('mapPendingMergeSuggestions', () => {
  it('preserves envelope metadata from a valid response', () => {
    const response: PendingMergeSuggestionsResponse = {
      suggestions: [{ id: 'm1', cluster_a_id: 'a', cluster_b_id: 'b', similarity: 0.85, status: 'pending' }],
      limit: 10,
      offset: 0,
      data_source: DATA_SOURCE.BACKEND_PROXY,
    };

    const mapped = mapPendingMergeSuggestions(response);
    // COR-3 (rg-015): no authoritative total is forwarded by the boundary.
    expect('total' in mapped).toBe(false);
    expect(mapped.limit).toBe(10);
    expect(mapped.data_source).toBe('backend_proxy');
  });

  it('throws when data_source is missing', () => {
    const response = asPendingMergeSuggestionsResponse({
      suggestions: [],
      total: 0,
      limit: 10,
      offset: 0,
    });

    expect(() => mapPendingMergeSuggestions(response)).toThrow('valid data_source');
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
