import { beforeEach, describe, expect, it, vi } from 'vitest';

import { acceptMergeSuggestion } from '../identityActionsApi';
import type { HTTPOptions } from '../../../utils/http';

/**
 * FEBT1-LD-01: the atomic merge+accept envelope.
 *
 * The service merges and stamps ACCEPTED under one transaction, so this one
 * response must carry the authoritative survivor/retired pair and the exact set
 * of identities the transaction moved. The client validates all three explicitly
 * (sr-005) — an un-revertable merge must fail here, not surface later as a
 * silently missing undo.
 */

const mockConfig = {
  nonce: 'nonce-123',
  endpoints: {
    recognitionMergeSuggestions: 'https://example.com/merge-suggestions',
  } as Record<string, string>,
};

vi.mock('../../config', () => ({
  getEndpoint: vi.fn((primary: string) => mockConfig.endpoints[primary] ?? `https://example.com/${primary}`),
  getConfig: vi.fn(() => mockConfig),
  isDevMode: vi.fn(() => false),
}));

const fetchMock = vi.fn<(endpoint: string, options?: HTTPOptions) => Promise<unknown>>();

vi.mock('../../../utils/http', () => ({
  fetchApi: (endpoint: string, options?: HTTPOptions) => fetchMock(endpoint, options),
  fetchRequiredApi: (endpoint: string, options?: HTTPOptions) => fetchMock(endpoint, options),
  stripTrailingSlash: (value: string) => (value.endsWith('/') ? value.slice(0, -1) : value),
}));

const SUGGESTION_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const CLUSTER_A = '11111111-1111-1111-1111-111111111111';
const CLUSTER_B = '22222222-2222-2222-2222-222222222222';
const MOVED = ['33333333-3333-3333-3333-333333333333', '44444444-4444-4444-4444-444444444444'];

const acceptPayload = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  id: SUGGESTION_ID,
  cluster_a_id: CLUSTER_A,
  cluster_b_id: CLUSTER_B,
  similarity: 0.91,
  status: 'accepted',
  source_cluster_id: CLUSTER_A,
  target_cluster_id: CLUSTER_B,
  moved_identity_ids: MOVED,
  ...overrides,
});

const requestOptions = (callIndex = 0): HTTPOptions | undefined => fetchMock.mock.calls[callIndex]?.[1];

describe('acceptMergeSuggestion', () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(acceptPayload());
  });

  it('returns the revert set and the authoritative merge topology in one response', async () => {
    const result = await acceptMergeSuggestion(SUGGESTION_ID);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.moved_identity_ids).toEqual(MOVED);
    expect(result.source_cluster_id).toBe(CLUSTER_A);
    expect(result.target_cluster_id).toBe(CLUSTER_B);
    expect(result.status).toBe('accepted');
  });

  it('sends no body when the operator did not choose a survivor', async () => {
    await acceptMergeSuggestion(SUGGESTION_ID);

    expect(requestOptions()?.body).toBeUndefined();
  });

  it('forwards the operator-chosen survivor', async () => {
    await acceptMergeSuggestion({ suggestionId: SUGGESTION_ID, targetClusterId: CLUSTER_A });

    expect(requestOptions()?.body).toEqual({ target_cluster_id: CLUSTER_A });
  });

  it('FEBT2-LD2-NEW-02: forwards the caller signal so the accept is cancellable', async () => {
    // Predicted first failure without the fix: `signal` is undefined here,
    // because the request object destructure dropped it before fetch.
    const controller = new AbortController();

    await acceptMergeSuggestion({ suggestionId: SUGGESTION_ID, signal: controller.signal });

    expect(requestOptions()?.signal).toBe(controller.signal);
  });

  it('FEBT2-LD2-NEW-02: the bare-id call passes no signal rather than a fabricated one', async () => {
    await acceptMergeSuggestion(SUGGESTION_ID);

    expect(requestOptions()?.signal).toBeUndefined();
  });

  it('posts to the accept path for the given suggestion', async () => {
    await acceptMergeSuggestion(SUGGESTION_ID);

    expect(fetchMock.mock.calls[0]?.[0]).toContain(`/merge-suggestions/${SUGGESTION_ID}/accept`);
    expect(requestOptions()?.method).toBe('POST');
  });

  it('rejects a response with no moved_identity_ids array', async () => {
    fetchMock.mockResolvedValue(acceptPayload({ moved_identity_ids: undefined }));

    await expect(acceptMergeSuggestion(SUGGESTION_ID)).rejects.toThrow(/moved_identity_ids array/);
  });

  it('rejects a response whose moved_identity_ids holds a non-string entry', async () => {
    fetchMock.mockResolvedValue(acceptPayload({ moved_identity_ids: [MOVED[0], 42] }));

    await expect(acceptMergeSuggestion(SUGGESTION_ID)).rejects.toThrow(/moved_identity_ids\[1\]/);
  });

  it('rejects a response whose moved_identity_ids holds an empty string', async () => {
    fetchMock.mockResolvedValue(acceptPayload({ moved_identity_ids: [''] }));

    await expect(acceptMergeSuggestion(SUGGESTION_ID)).rejects.toThrow(/moved_identity_ids\[0\]/);
  });

  it('rejects a response missing the authoritative survivor', async () => {
    fetchMock.mockResolvedValue(acceptPayload({ target_cluster_id: null }));

    await expect(acceptMergeSuggestion(SUGGESTION_ID)).rejects.toThrow(/target_cluster_id/);
  });

  it('rejects a response missing the authoritative retired cluster', async () => {
    fetchMock.mockResolvedValue(acceptPayload({ source_cluster_id: null }));

    await expect(acceptMergeSuggestion(SUGGESTION_ID)).rejects.toThrow(/source_cluster_id/);
  });

  it('accepts an empty revert set without inventing one', async () => {
    fetchMock.mockResolvedValue(acceptPayload({ moved_identity_ids: [] }));

    const result = await acceptMergeSuggestion(SUGGESTION_ID);

    expect(result.moved_identity_ids).toEqual([]);
  });
});
