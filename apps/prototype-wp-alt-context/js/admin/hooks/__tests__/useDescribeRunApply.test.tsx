import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { describeRunItemsQueryKey, useDescribeRunApply } from '../useDescribeRunApply';
import { mediaStatsMissingQueryKey, mediaStatsTotalQueryKey } from '../useMediaStats';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunItemsResponse } from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';

vi.mock('../../api/describeApi', () => ({
  fetchDescribeRunItems: vi.fn(),
  applyDescribeRunDrafts: vi.fn(),
}));

const fetchItemsMock = vi.mocked(describeApi.fetchDescribeRunItems);
const applyMock = vi.mocked(describeApi.applyDescribeRunDrafts);

const itemsResponse: DescribeRunItemsResponse = {
  run_id: 'run-abc',
  items: [
    { media_id: 71, status: 'completed', alt_text_draft: 'A flower.', caption: 'A flower.', provenance: null, existing_alt: false },
    { media_id: 70, status: 'completed', alt_text_draft: 'A bridge.', caption: 'A bridge.', provenance: null, existing_alt: true },
    { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
    { media_id: 73, status: 'completed', alt_text_draft: '   ', caption: null, provenance: null, existing_alt: true },
  ],
};

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
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71, 70],
      partial: [],
      skipped_existing: [],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });

    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(buildClient()),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([70]);

    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    expect(applyMock).toHaveBeenCalledWith('run-abc', [70]);
    expect(result.current.apply.data?.applied).toEqual([71, 70]);
  });

  it('invalidates run items and the missing-alt stats probe after a successful apply [BR-125]', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71, 70],
      partial: [],
      skipped_existing: [],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });

    const client = buildClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(client),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([70]);
    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: describeRunItemsQueryKey('run-abc') });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: mediaStatsMissingQueryKey });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.workbench() });
    // Not the total probe (media count unchanged) and not media.all (BR-77).
    expect(
      invalidateSpy.mock.calls.some(
        (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: mediaStatsTotalQueryKey }),
      ),
    ).toBe(false);
    expect(
      invalidateSpy.mock.calls.some(
        (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: queryKeys.media.all }),
      ),
    ).toBe(false);
  });

  it('refreshes stats after a partial apply — some alts landed so counters are stale [BR-125]', async () => {
    // HTTP success with mixed buckets: applied + failed. onSuccess still runs;
    // some writes landed so dashboard coverage must ask the server again.
    fetchItemsMock.mockResolvedValue(itemsResponse);
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [],
      skipped_existing: [],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [70],
    });

    const client = buildClient();
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useDescribeRunApply('run-abc'), {
      wrapper: createWrapper(client),
    });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([70]);
    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    expect(result.current.apply.data?.applied).toEqual([71]);
    expect(result.current.apply.data?.failed).toEqual([70]);

    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: mediaStatsMissingQueryKey });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.workbench() });
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
