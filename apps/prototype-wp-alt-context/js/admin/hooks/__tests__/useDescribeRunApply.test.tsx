import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useDescribeRunApply } from '../useDescribeRunApply';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunItemsResponse } from '../../api/describeApi';

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

const wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useDescribeRunApply', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not fetch items when no run id is provided', () => {
    renderHook(() => useDescribeRunApply(null), { wrapper });
    expect(fetchItemsMock).not.toHaveBeenCalled();
  });

  it('fetches items for a run and buckets drafts by existing_alt and draft presence', async () => {
    fetchItemsMock.mockResolvedValue(itemsResponse);

    const { result } = renderHook(() => useDescribeRunApply('run-abc'), { wrapper });

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
    applyMock.mockResolvedValue({ run_id: 'run-abc', applied: [71, 70], skipped_existing: [], skipped_no_draft: [72], skipped_invalid: [], failed: [] });

    const { result } = renderHook(() => useDescribeRunApply('run-abc'), { wrapper });
    await waitFor(() => expect(result.current.itemsQuery.isSuccess).toBe(true));

    result.current.apply.mutate([70]);

    await waitFor(() => expect(result.current.apply.isSuccess).toBe(true));
    expect(applyMock).toHaveBeenCalledWith('run-abc', [70]);
    expect(result.current.apply.data?.applied).toEqual([71, 70]);
  });

  it('is a no-op apply when no run id is set', async () => {
    const { result } = renderHook(() => useDescribeRunApply(null), { wrapper });

    result.current.apply.mutate([]);

    await waitFor(() => expect(result.current.apply.isError).toBe(true));
    expect(applyMock).not.toHaveBeenCalled();
  });
});
