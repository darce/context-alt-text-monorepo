import { describe, expect, it } from 'vitest';

import {
  mapPendingMergeSuggestion,
  mapPendingSuggestions,
} from '../identitySuggestionMappers';
import type { PendingSuggestionsResponse } from '../types';
import { DATA_SOURCE } from '../types/dataSource';

const IDENTITY_ATTACHMENT_URL = 'https://example.test/identity-attachment.jpg';
const REPRESENTATIVE_ATTACHMENT_URL = 'https://example.test/representative-attachment.jpg';
const CLUSTER_A_ATTACHMENT_URL = 'https://example.test/cluster-a-attachment.jpg';
const CLUSTER_B_ATTACHMENT_URL = 'https://example.test/cluster-b-attachment.jpg';

const suggestionEnvelope = (
  suggestion: Record<string, unknown>,
): PendingSuggestionsResponse => ({
  suggestions: [
    {
      id: 's1',
      identity_id: 'i1',
      suggested_cluster_id: 'c1',
      representative_similarity: 0.9,
      ...suggestion,
    },
  ],
  limit: 25,
  offset: 0,
  data_source: DATA_SOURCE.BACKEND_PROXY,
});

const mergePayload = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: 'm1',
  cluster_a_id: 'cluster-a',
  cluster_b_id: 'cluster-b',
  similarity: 0.84,
  status: 'pending',
  ...overrides,
});

describe('mapPendingSuggestions', () => {
  it('passes identity_attachment_url and representative_attachment_url through when present', () => {
    const mapped = mapPendingSuggestions(
      suggestionEnvelope({
        identity_attachment_url: IDENTITY_ATTACHMENT_URL,
        representative_attachment_url: REPRESENTATIVE_ATTACHMENT_URL,
      }),
    );
    const suggestion = mapped.suggestions[0];

    expect(suggestion).toHaveProperty('identity_attachment_url', IDENTITY_ATTACHMENT_URL);
    expect(suggestion).toHaveProperty('representative_attachment_url', REPRESENTATIVE_ATTACHMENT_URL);
    expect(suggestion.identity_attachment_url).toBe(IDENTITY_ATTACHMENT_URL);
    expect(suggestion.representative_attachment_url).toBe(REPRESENTATIVE_ATTACHMENT_URL);
  });

  it('normalizes omitted attachment URLs to null instead of dropping them', () => {
    const mapped = mapPendingSuggestions(suggestionEnvelope({}));
    const suggestion = mapped.suggestions[0];

    expect('identity_attachment_url' in suggestion).toBe(true);
    expect('representative_attachment_url' in suggestion).toBe(true);
    expect(suggestion).toHaveProperty('identity_attachment_url', null);
    expect(suggestion).toHaveProperty('representative_attachment_url', null);
    expect(suggestion.identity_attachment_url).toBeNull();
    expect(suggestion.representative_attachment_url).toBeNull();
    expect(suggestion.identity_attachment_url).not.toBeUndefined();
    expect(suggestion.representative_attachment_url).not.toBeUndefined();
  });
});

describe('mapPendingMergeSuggestion', () => {
  it('passes cluster representative attachment URLs through when present', () => {
    const mapped = mapPendingMergeSuggestion(
      mergePayload({
        cluster_a_representative_attachment_url: CLUSTER_A_ATTACHMENT_URL,
        cluster_b_representative_attachment_url: CLUSTER_B_ATTACHMENT_URL,
      }),
    );

    expect(mapped).toHaveProperty('cluster_a_representative_attachment_url', CLUSTER_A_ATTACHMENT_URL);
    expect(mapped).toHaveProperty('cluster_b_representative_attachment_url', CLUSTER_B_ATTACHMENT_URL);
    expect(mapped.cluster_a_representative_attachment_url).toBe(CLUSTER_A_ATTACHMENT_URL);
    expect(mapped.cluster_b_representative_attachment_url).toBe(CLUSTER_B_ATTACHMENT_URL);
  });

  it('normalizes omitted merge attachment URLs to null instead of dropping them', () => {
    const mapped = mapPendingMergeSuggestion(mergePayload());

    expect('cluster_a_representative_attachment_url' in mapped).toBe(true);
    expect('cluster_b_representative_attachment_url' in mapped).toBe(true);
    expect(mapped).toHaveProperty('cluster_a_representative_attachment_url', null);
    expect(mapped).toHaveProperty('cluster_b_representative_attachment_url', null);
    expect(mapped.cluster_a_representative_attachment_url).toBeNull();
    expect(mapped.cluster_b_representative_attachment_url).toBeNull();
    expect(mapped.cluster_a_representative_attachment_url).not.toBeUndefined();
    expect(mapped.cluster_b_representative_attachment_url).not.toBeUndefined();
  });
});
