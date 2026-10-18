/**
 * operator115 identity suggestion routing at the UI (c82 FIR115).
 *
 * UI producer -> real mutation -> real HTTP transport. The producer is the rendered
 * IdentityClusterItem and its inline "Is this X?" Yes control. The mutation is the real
 * useClusterMutations, the wire is the real identityActionsApi, and only `fetch` is replaced.
 * The suggestion-match query hook is stubbed as data (no network); no mutation hook is stubbed.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import { IdentityClusterItem } from '../IdentityClusterItem';
import type { ProjectedSuggestion } from '../suggestionProjection';
import type { ClusterGroup } from '../types';

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

vi.mock('../useClusterSuggestions', () => ({
  useClusterSuggestions: () => ({
    options: [],
    isLoading: false,
    collisionsByLabel: new Map(),
    findClusterByLabel: vi.fn(() => Promise.resolve(null)),
    atRestTotal: 0,
    atRestTruncated: false,
    isAtRestMode: false,
  }),
}));

const CLUSTER_ID = '26d1cacb-351d-4e52-a007-f130764ba758';
const TARGET_CLUSTER_ID = '0a6dbdcb-5191-4f63-9d9f-63f375149ee8';
const SELECTED_FACE_ID = 'adcde572-ce74-446a-86e7-970865e533d8';
const SUGGESTION_ID = '19697519-6950-4743-8305-8105584652f9';
const TARGET_LABEL = 'Bea Burke';
const ACCEPT_SUFFIX = `/${SUGGESTION_ID}/accept`;
const SUGGESTIONS_ENDPOINT = 'https://example.test/wp-json/alt-context/v1/recognition/suggestions';
const MERGE_SUGGESTIONS_ENDPOINT = 'https://example.test/wp-json/alt-context/v1/recognition/merge-suggestions';

const member = (identityId: string): ClusterGroup['members'][number] => ({
  identity_id: identityId,
  representative_id: `rep-${identityId}`,
  media_id: 115,
  cluster_id: CLUSTER_ID,
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 0.49,
  detected_at: '',
});

/** Unlabeled singleton face: the inline "Is this X?" prompt only renders for a singleton (isSingleton). */
const unlabeledSingletonCluster = (): ClusterGroup => ({
  key: 'unlabeled',
  clusterId: CLUSTER_ID,
  label: null,
  isAutoLabel: false,
  clusteringPending: false,
  members: [member(SELECTED_FACE_ID)],
});

const inlineMatch: ProjectedSuggestion = {
  suggestionId: SUGGESTION_ID,
  identityId: SELECTED_FACE_ID,
  clusterId: TARGET_CLUSTER_ID,
  label: TARGET_LABEL,
  similarity: 0.49,
  identityCount: 2,
};

const acceptedResponse = (): Response =>
  new Response(JSON.stringify({ status: 'accepted' }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>();

const urlOf = (input: RequestInfo | URL): string =>
  typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
const requestUrls = (): string[] => fetchMock.mock.calls.map(([input]) => urlOf(input));
const acceptCalls = () => fetchMock.mock.calls.filter(([input]) => urlOf(input).endsWith(ACCEPT_SUFFIX));
const mergeCalls = () => fetchMock.mock.calls.filter(([input]) => urlOf(input).includes('merge'));

beforeEach(() => {
  window.AltContextAdmin = {
    nonce: 'test-nonce',
    endpoints: {
      recognitionSuggestions: SUGGESTIONS_ENDPOINT,
      recognitionMergeSuggestions: MERGE_SUGGESTIONS_ENDPOINT,
    },
  } as unknown as typeof window.AltContextAdmin;
  resetConfigCache();
  fetchMock.mockReset();
  fetchMock.mockImplementation(() => Promise.resolve(acceptedResponse()));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetConfigCache();
  delete window.AltContextAdmin;
});

const renderUnlabeledItem = (inlineSuggestionMatch: ProjectedSuggestion | undefined = inlineMatch) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <IdentityClusterItem
        cluster={unlabeledSingletonCluster()}
        canLabel
        canMutate
        inlineSuggestionMatch={inlineSuggestionMatch}
      />
    </QueryClientProvider>,
  );
};

describe('IdentityClusterItem inline identity suggestion (UI -> mutation -> fetch)', () => {
  it('renders without writing; the inline Yes sends exactly one identity accept and no merge', async () => {
    const { container } = renderUnlabeledItem();

    // A render (or a retry of it) must never accept a suggestion on its own.
    expect(fetchMock).not.toHaveBeenCalled();

    const yes = container.querySelector<HTMLButtonElement>('.acx-inline-suggestion__yes');
    if (!yes) {
      throw new Error('inline Yes control was not rendered');
    }
    fireEvent.click(yes);

    // The inline match carries no member count, so the operator confirms first (FIX-3). This
    // identity suggestion assigns this selected face, so the dialog action is 'assign' (copy: "Assign").
    fireEvent.click(await screen.findByRole('button', { name: 'Assign' }));

    await waitFor(() => expect(acceptCalls()).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST');
    expect(mergeCalls()).toEqual([]);
    expect(requestUrls().join('\n')).not.toMatch(/\/merge/);
  });

  it('without an inline suggestion, rendering the unlabeled face writes nothing', async () => {
    renderUnlabeledItem(undefined);

    await new Promise((resolve) => setTimeout(resolve, 25));
    expect(acceptCalls()).toEqual([]);
    expect(mergeCalls()).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
