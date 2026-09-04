import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDescribeRunApply } from '../useDescribeRunApply';
import { mediaStatsMissingQueryKey, mediaStatsTotalQueryKey } from '../useMediaStats';
import { MEDIA_PAGE_SIZE_OPTIONS } from '../useWorkbenchFilters';
import * as describeApi from '../../api/describeApi';
import type { ApplyDescribeRunResponse, DescribeRunItemsResponse } from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';

vi.mock('../../api/describeApi', () => ({
  fetchDescribeRunItems: vi.fn(),
  applyDescribeRunDrafts: vi.fn(),
}));

const fetchItemsMock = vi.mocked(describeApi.fetchDescribeRunItems);
const applyMock = vi.mocked(describeApi.applyDescribeRunDrafts);

const itemsResponse: DescribeRunItemsResponse = {
  run_id: 'run-abc',
  items: [
    { media_id: 71, status: 'completed', alt_text_draft: 'A flower.', caption: 'A flower.', provenance: null, tier: 'final_gpu', result_generation: 1, existing_alt: false },
    { media_id: 70, status: 'completed', alt_text_draft: 'A bridge.', caption: 'A bridge.', provenance: null, tier: 'final_gpu', result_generation: 1, existing_alt: true },
    { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, tier: 'final_gpu', result_generation: 1, existing_alt: false },
    { media_id: 73, status: 'completed', alt_text_draft: '   ', caption: null, provenance: null, tier: 'final_gpu', result_generation: 1, existing_alt: true },
  ],
};

const defaultPerPage = MEDIA_PAGE_SIZE_OPTIONS[0];
const largePerPage = MEDIA_PAGE_SIZE_OPTIONS[MEDIA_PAGE_SIZE_OPTIONS.length - 1];

const workbenchListPageKeys = [
  ...MEDIA_PAGE_SIZE_OPTIONS.map((perPage) =>
    queryKeys.media.workbenchPage({ page: 1, perPage, status: 'missing' }),
  ),
  queryKeys.media.workbenchPage({
    page: 1,
    perPage: defaultPerPage,
    status: 'missing',
    search: 'ada',
  }),
  queryKeys.media.workbenchPage({
    page: 1,
    perPage: largePerPage,
    status: 'missing',
    search: '',
  }),
];

const emptyPage: WorkbenchMediaResponse = { items: [], total: 0, totalPages: 0 };

const seedWorkbenchCache = (client: QueryClient): void => {
  for (const key of workbenchListPageKeys) {
    client.setQueryData(key, emptyPage);
  }
  client.setQueryData(mediaStatsTotalQueryKey, { items: [], total: 10, totalPages: 10 });
  client.setQueryData(mediaStatsMissingQueryKey, { items: [], total: 3, totalPages: 3 });
};

const expectListPagesInvalidated = (client: QueryClient, invalidated: boolean): void => {
  for (const key of workbenchListPageKeys) {
    expect(client.getQueryState(key)?.isInvalidated).toBe(invalidated);
  }
};

const applyResponse = (overrides: Partial<ApplyDescribeRunResponse> = {}): ApplyDescribeRunResponse => ({
  run_id: 'run-abc',
  applied: [71, 70],
  partial: [],
  skipped_existing: [],
  skipped_no_draft: [72],
  skipped_invalid: [],
  failed: [],
  ...overrides,
});

const buildClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

const createWrapper = (client: QueryClient) => {
  const Wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

describe('useDescribeRunApply', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not fetch items when no run id is provided', () => {
    renderHook(() => useDescribeRunApply(null), { wrapper: createWrapper(buildClient()) });
    expect(fetchItemsMock).not.toHaveBeenCalled();
  });

  it('fetches items for a run and buckets drafts by existing_alt and draft presence', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);

    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(buildClient()),
    });

    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));
    expect(fetchItemsMock).toHaveBeenCalledWith('run-abc');

    // Draft present, no existing alt → safe to auto-apply.
    expect(result.current.buckets.withoutAlt.map((i) => i.media_id)).toEqual([71]);
    // Draft present, existing alt → needs explicit overwrite.
    expect(result.current.buckets.withExistingAlt.map((i) => i.media_id)).toEqual([70]);
    // Blank/absent draft (failed or empty) → informational, never applied.
    expect(result.current.buckets.noDraft.map((i) => i.media_id).sort()).toEqual([72, 73]);
  });

  it('applies drafts with the operator overwrite list and exposes the result', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue(applyResponse());

    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(buildClient()),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([70]);

    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    expect(applyMock).toHaveBeenCalledWith('run-abc', [70]);
    expect(result.current.apply.data?.applied).toEqual([71, 70]);
  });

  it('invalidates list pages and missing stats, not the total probe, after a successful apply [BR-125][S6-F1]', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue(applyResponse());

    const client = buildClient();
    seedWorkbenchCache(client);
    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(client),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    expectListPagesInvalidated(client, false);
    expect(client.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).not.toBe(true);
    expect(client.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).not.toBe(true);

    const itemsFetchesBefore = fetchItemsMock.mock.calls.length;
    result.current.apply.mutate([70]);
    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    await waitFor(() => expect(fetchItemsMock.mock.calls.length).toBeGreaterThan(itemsFetchesBefore));

    expectListPagesInvalidated(client, true);
    expect(client.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(true);
    // Prefix workbench() invalidation would also mark the perPage:1 total probe.
    expect(client.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
  });

  it('refreshes list pages and missing stats after a partial apply — some alts landed [BR-125]', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue(
      applyResponse({
        applied: [71],
        failed: [70],
      }),
    );

    const client = buildClient();
    seedWorkbenchCache(client);
    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(client),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([70]);
    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    expect(result.current.apply.data?.applied).toEqual([71]);
    expect(result.current.apply.data?.failed).toEqual([70]);

    expectListPagesInvalidated(client, true);
    expect(client.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
  });

  it('still invalidates list pages when only partial writes landed [S6-F4]', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue(
      applyResponse({
        applied: [],
        partial: [71],
        skipped_no_draft: [72],
      }),
    );

    const client = buildClient();
    seedWorkbenchCache(client);
    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(client),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([]);
    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));

    expectListPagesInvalidated(client, true);
    expect(client.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
  });

  it('skips workbench and stats invalidation when a 200 apply landed nothing [S6-F4]', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue(
      applyResponse({
        applied: [],
        partial: [],
        skipped_existing: [70],
        skipped_no_draft: [72],
        skipped_invalid: [],
        failed: [],
      }),
    );

    const client = buildClient();
    seedWorkbenchCache(client);
    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(client),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    const itemsFetchesBefore = fetchItemsMock.mock.calls.length;
    result.current.apply.mutate([]);
    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    await waitFor(() => expect(fetchItemsMock.mock.calls.length).toBeGreaterThan(itemsFetchesBefore));

    // History buckets still refresh; library rows and dashboard counters do not.
    expectListPagesInvalidated(client, false);
    expect(client.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(false);
    expect(client.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
  });

  it('is a no-op apply when no run id is set', async () => {
    const { result } = renderHook(() => useDescribeRunApply(null), {
      wrapper: createWrapper(buildClient()),
    });

    result.current.apply.mutate([]);

    await waitFor(() => expect(result.current.apply.isError).toBe(true));
    expect(applyMock).not.toHaveBeenCalled();
  });
});
