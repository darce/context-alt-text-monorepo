/**
 * operator115 identity suggestion transport (c82 FIR115).
 *
 * Producer -> confirm -> real mutation -> real HTTP transport. The producer is the real
 * selectClusterSuggestions / resolveClusterMatchFromOptions pair. The confirm chain is the real
 * useClusterConfirmSuggestion -> useClusterMatchAction, the mutation is the real
 * useClusterActionMutations, and the wire is the real identityActionsApi. Only `fetch` (the network
 * boundary) is replaced. The whole-cluster merge route is a spy because it is owned by a sibling lane;
 * every identity write is observed on the wire.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { resetConfigCache } from '../../../../api/config';
import type { ProjectedSuggestion } from '../suggestionProjection';
import type { ClusterGroup } from '../types';
import { useClusterActionMutations } from '../useClusterActionMutations';
import { useClusterConfirmSuggestion } from '../useClusterConfirmSuggestion';
import { resolveClusterMatchFromOptions, selectClusterSuggestions } from '../useClusterSuggestions';

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => false,
}));

const EDITABLE_CLUSTER_ID = '26d1cacb-351d-4e52-a007-f130764ba758';
const TARGET_CLUSTER_ID = '0a6dbdcb-5191-4f63-9d9f-63f375149ee8';
const FIRST_FACE_ID = 'face-first-member';
const SELECTED_FACE_ID = 'adcde572-ce74-446a-86e7-970865e533d8';
const SUGGESTION_ID = '19697519-6950-4743-8305-8105584652f9';
const TARGET_LABEL = 'Bea Burke';
const ACCEPT_SUFFIX = `/${SUGGESTION_ID}/accept`;

const member = (identityId: string, clusterId: string | null): ClusterGroup['members'][number] => ({
  identity_id: identityId,
  representative_id: `rep-${identityId}`,
  media_id: 115,
  cluster_id: clusterId,
  cluster_label: null,
  is_auto_label: false,
  is_pinned: false,
  bbox: { x: 0, y: 0, width: 1, height: 1 },
  confidence: 1,
  similarity: 0.49,
  detected_at: '',
});

/** Identity-keyed producer row: the pending suggestion of SELECTED_FACE_ID, targeting TARGET_CLUSTER_ID. */
const selectedFaceRow = (suggestionId = SUGGESTION_ID): ProjectedSuggestion => ({
  suggestionId,
  identityId: SELECTED_FACE_ID,
  clusterId: TARGET_CLUSTER_ID,
  label: TARGET_LABEL,
  similarity: 0.49,
  identityCount: 2,
});

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

const SUGGESTIONS_ENDPOINT = 'https://example.test/wp-json/alt-context/v1/recognition/suggestions';
const MERGE_SUGGESTIONS_ENDPOINT = 'https://example.test/wp-json/alt-context/v1/recognition/merge-suggestions';

beforeEach(() => {
  // The real identityActionsApi reads its endpoint and nonce from the localized admin config.
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

interface ChainOptions {
  members: ClusterGroup['members'];
  editableClusterId: string | null;
  canSearchForMatch: boolean;
  rows: ProjectedSuggestion[];
}

/** Real producer -> real confirm -> real mutation -> real API. Only merge is a spy (sibling-owned route). */
const renderChain = ({ members, editableClusterId, canSearchForMatch, rows }: ChainOptions) => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const onError = vi.fn();
  const onAbort = vi.fn();
  const invalidateQueries = vi.fn();
  const merge = vi.fn();
  const actions = renderHook(
    () => useClusterActionMutations({ clusterId: TARGET_CLUSTER_ID, onError, onAbort, invalidateQueries }),
    { wrapper },
  ).result;
  const options = selectClusterSuggestions({
    identityProjection: rows,
    namingOptions: [],
    editableClusterId,
    labelInput: '',
  });
  const saveAbortRef = { current: null as AbortController | null };
  const requestConfirm = vi.fn().mockResolvedValue(true);
  const confirm = renderHook(() =>
    useClusterConfirmSuggestion({
      members,
      editableClusterId,
      canEdit: true,
      canSearchForMatch,
      options,
      saveStatus: 'idle',
      mutations: {
        isPending: false,
        merge,
        assignToCluster: (identityId, targetClusterId, signal, suggestionId) =>
          actions.current.assignToCluster(identityId, targetClusterId, signal, suggestionId),
      },
      requestConfirm,
      cancelEditing: vi.fn(),
      setError: vi.fn(),
      queueSaveStatus: vi.fn(),
      resetSaveStatus: vi.fn(),
      saveAbortRef,
    }),
  ).result;
  return { confirm, merge, onError, options };
};

describe('identity suggestion transport (producer -> confirm -> mutation -> fetch)', () => {
  it('issues exactly one identity accept for the selected second member and never merges or touches the first', async () => {
    const { confirm, merge, onError, options } = renderChain({
      members: [member(FIRST_FACE_ID, EDITABLE_CLUSTER_ID), member(SELECTED_FACE_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
      rows: [selectedFaceRow()],
    });

    // Producer: the Suggested option carries the source face of its suggestion row.
    const match = resolveClusterMatchFromOptions(options, TARGET_LABEL);
    expect(match?.suggestionProvenance).toEqual({ kind: 'identity', identityId: SELECTED_FACE_ID });

    await act(async () => {
      await confirm.current.handleConfirmSuggestion(
        match?.id ?? '',
        TARGET_LABEL,
        match?.suggestionId,
        match?.suggestionProvenance,
      );
    });

    await waitFor(() => expect(acceptCalls()).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST');
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
    expect(merge).not.toHaveBeenCalled();
    expect(mergeCalls()).toEqual([]);
    expect(requestUrls().join('\n')).not.toContain(FIRST_FACE_ID);
    expect(onError).not.toHaveBeenCalled();
  });

  it('keeps a manual whole-cluster merge atomic: one merge, no identity accept', async () => {
    const { confirm, merge } = renderChain({
      members: [member(FIRST_FACE_ID, EDITABLE_CLUSTER_ID), member(SELECTED_FACE_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
      rows: [],
    });

    await act(async () => {
      await confirm.current.handleConfirmSuggestion(TARGET_CLUSTER_ID, TARGET_LABEL, undefined);
    });

    expect(merge).toHaveBeenCalledExactlyOnceWith(TARGET_CLUSTER_ID, TARGET_LABEL, expect.any(AbortSignal), undefined);
    expect(acceptCalls()).toEqual([]);
  });

  it('routes a genuine cluster-merge suggestion to the atomic merge path, not identity accept', async () => {
    const { confirm, merge } = renderChain({
      members: [member(FIRST_FACE_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
      rows: [],
    });

    await act(async () => {
      await confirm.current.handleConfirmSuggestion(TARGET_CLUSTER_ID, TARGET_LABEL, 'merge-suggestion-1', {
        kind: 'cluster_merge',
      });
    });

    expect(merge).toHaveBeenCalledExactlyOnceWith(
      TARGET_CLUSTER_ID,
      TARGET_LABEL,
      expect.any(AbortSignal),
      'merge-suggestion-1',
    );
    expect(acceptCalls()).toEqual([]);
  });

  it('assigns only the source face in an unassigned group and never loops the members', async () => {
    const { confirm, merge, options } = renderChain({
      members: [member(FIRST_FACE_ID, null), member(SELECTED_FACE_ID, null)],
      editableClusterId: null,
      canSearchForMatch: true,
      rows: [selectedFaceRow()],
    });

    const match = resolveClusterMatchFromOptions(options, TARGET_LABEL);
    await act(async () => {
      await confirm.current.handleConfirmSuggestion(
        match?.id ?? '',
        TARGET_LABEL,
        match?.suggestionId,
        match?.suggestionProvenance,
      );
    });

    await waitFor(() => expect(acceptCalls()).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestUrls().join('\n')).not.toContain(FIRST_FACE_ID);
    expect(merge).not.toHaveBeenCalled();
  });

  it('lets a superseded confirm reach fetch with an aborted signal, one write per confirm', async () => {
    fetchMock.mockImplementationOnce(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    const { confirm, options } = renderChain({
      members: [member(FIRST_FACE_ID, null), member(SELECTED_FACE_ID, null)],
      editableClusterId: null,
      canSearchForMatch: true,
      rows: [selectedFaceRow()],
    });
    const match = resolveClusterMatchFromOptions(options, TARGET_LABEL);

    act(() => {
      void confirm.current.handleConfirmSuggestion(
        match?.id ?? '',
        TARGET_LABEL,
        match?.suggestionId,
        match?.suggestionProvenance,
      );
    });
    await waitFor(() => expect(acceptCalls()).toHaveLength(1));

    await act(async () => {
      await confirm.current.handleConfirmSuggestion(
        match?.id ?? '',
        TARGET_LABEL,
        match?.suggestionId,
        match?.suggestionProvenance,
      );
    });

    await waitFor(() => expect(acceptCalls()).toHaveLength(2));
    const [superseded, current] = acceptCalls().map(([, init]) => init?.signal);
    expect(superseded?.aborted).toBe(true);
    expect(current?.aborted).toBe(false);
  });

  it('a 404 on identity accept surfaces one error: no merge fallback and no repeated write', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ code: 'not_found', message: 'Suggestion not found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const { confirm, merge, onError, options } = renderChain({
      members: [member(FIRST_FACE_ID, EDITABLE_CLUSTER_ID), member(SELECTED_FACE_ID, EDITABLE_CLUSTER_ID)],
      editableClusterId: EDITABLE_CLUSTER_ID,
      canSearchForMatch: false,
      rows: [selectedFaceRow()],
    });
    const match = resolveClusterMatchFromOptions(options, TARGET_LABEL);

    await act(async () => {
      await confirm.current.handleConfirmSuggestion(
        match?.id ?? '',
        TARGET_LABEL,
        match?.suggestionId,
        match?.suggestionProvenance,
      );
    });

    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
    expect(onError).toHaveBeenCalledWith(expect.any(String));
    expect(acceptCalls()).toHaveLength(1);
    expect(mergeCalls()).toEqual([]);
    expect(merge).not.toHaveBeenCalled();
  });
});
