import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import * as recognitionApi from '../../../../api/recognition';
import type { ProjectedSuggestion } from '../suggestionProjection';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';
import { useSuggestionReviewMutations } from '../useSuggestionReviewMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', () => ({
  acceptSuggestion: vi.fn(),
  rejectSuggestion: vi.fn(),
  acceptMergeSuggestion: vi.fn(),
  rejectMergeSuggestion: vi.fn(),
  acceptNameSuggestion: vi.fn(),
  rejectNameSuggestion: vi.fn(),
  bulkAcceptSuggestions: vi.fn(),
}));

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);

const makeItem = (overrides: Partial<ProjectedSuggestion> & Pick<ProjectedSuggestion, 'suggestionId'>): ProjectedSuggestion => ({
  identityId: `identity-${overrides.suggestionId}`,
  clusterId: 'cluster-1',
  label: 'Alice',
  similarity: 0.9,
  ...overrides,
});

const makePage = (items: ProjectedSuggestion[]): SuggestionReviewPage => ({
  items,
  dataSource: DATA_SOURCE.LOCAL_PROJECTION,
});

describe('useSuggestionReviewMutations', () => {
  let queryClient: QueryClient;
  let bulkActionRef: { current: boolean };

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const renderMutations = () =>
    renderHook(() => useSuggestionReviewMutations({ queryClient, bulkActionRef }), { wrapper });

  beforeEach(() => {
    vi.clearAllMocks();
    bulkActionRef = { current: false };
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
  });

  it('rolls back the reviewPage cache when accept fails after optimistic remove', async () => {
    // TEST-06 predicted first failure (before implementation):
    // "expected { items: […2 items], … } to be { items: […2 items], … }" — previous page not restored
    // (or "expected [item-a] to deeply equal [item-a, item-b]" if only optimistic path ran).
    const itemA = makeItem({ suggestionId: 'sugg-a', similarity: 0.95 });
    const itemB = makeItem({ suggestionId: 'sugg-b', similarity: 0.85, clusterId: 'cluster-2', label: 'Bob' });
    const previousPage = makePage([itemA, itemB]);
    queryClient.setQueryData(reviewPageKey, previousPage);

    // Defer rejection so the optimistic cache window is observable before onError restores it.
    let rejectAccept!: (error: Error) => void;
    const pendingAccept = new Promise<never>((_resolve, reject) => {
      rejectAccept = reject;
    });
    vi.mocked(recognitionApi.acceptSuggestion).mockReturnValue(pendingAccept);

    const { result } = renderMutations();

    act(() => {
      result.current.mutations.accept.mutate('sugg-a');
    });

    await waitFor(() => {
      const optimistic = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
      expect(optimistic?.items.map((item) => item.suggestionId)).toEqual(['sugg-b']);
    });

    await act(async () => {
      rejectAccept(new Error('accept failed'));
      await pendingAccept.catch(() => undefined);
    });

    await waitFor(() => {
      expect(result.current.mutations.accept.isError).toBe(true);
    });

    const restored = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
    // TanStack structural sharing may rewrite the root object; content must match the pre-mutate page.
    expect(restored).toEqual(previousPage);
    expect(restored?.items).toEqual(previousPage.items);
    expect(restored?.dataSource).toBe(previousPage.dataSource);
  });

  it('removes the item on reject success and invalidates projection + clusters.all', async () => {
    // TEST-06 predicted first failure (before implementation):
    // "expected invalidateQueries to have been called with { queryKey: ['suggestions','projection'] }"
    // (still targeting pending()) and/or "expected items to have length 1" if suggestionId filter missed.
    const itemA = makeItem({ suggestionId: 'sugg-a', similarity: 0.95 });
    const itemB = makeItem({ suggestionId: 'sugg-b', similarity: 0.85, clusterId: 'cluster-2', label: 'Bob' });
    queryClient.setQueryData(reviewPageKey, makePage([itemA, itemB]));

    vi.mocked(recognitionApi.rejectSuggestion).mockResolvedValue({
      suggestion_id: 'sugg-a',
      resolution: 'rejected',
      identity_id: 'identity-sugg-a',
      cluster_id: null,
      message: 'ok',
    });

    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderMutations();

    act(() => {
      result.current.mutations.reject.mutate('sugg-a');
    });

    await waitFor(() => {
      expect(recognitionApi.rejectSuggestion).toHaveBeenCalledWith('sugg-a', expect.anything());
    });

    await waitFor(() => {
      const page = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
      expect(page?.items.map((item) => item.suggestionId)).toEqual(['sugg-b']);
    });

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.suggestions.projection.all });
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.clusters.all });
    });
  });
});
