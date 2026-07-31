import React from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCorrectMediaAlt } from '../useCorrectMediaAlt';
import {
  mediaStatsMissingQueryKey,
  mediaStatsTotalQueryKey,
  useMediaStats,
} from '../useMediaStats';
import * as describeApi from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';
import * as workbenchMediaApi from '../../api/workbenchMediaApi';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';

vi.mock('../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/describeApi')>('../../api/describeApi');
  return {
    ...actual,
    correctDescriptionHistoryItem: vi.fn(),
  };
});

vi.mock('../../api/workbenchMediaApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/workbenchMediaApi')>(
    '../../api/workbenchMediaApi',
  );
  return {
    ...actual,
    fetchWorkbenchMedia: vi.fn(),
  };
});

const correctMock = vi.mocked(describeApi.correctDescriptionHistoryItem);
const fetchWorkbenchMock = vi.mocked(workbenchMediaApi.fetchWorkbenchMedia);

const PARTIAL_MESSAGE =
  'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';

const partialError = (
  message = PARTIAL_MESSAGE,
  data: Record<string, unknown> = { status: 500, stored_alt_text: 'Partial-saved alt' },
): Error =>
  new Error(
    `Request to /correction failed (500): ${JSON.stringify({
      code: 'description_correction_partial',
      message,
      data,
    })}`,
  );

const totalFailureError = (
  message = 'Could not save the alt text correction.',
): Error =>
  new Error(
    `Request to /correction failed (500): ${JSON.stringify({
      code: 'description_correction_failed',
      message,
      data: { status: 500 },
    })}`,
  );

const successHistoryItem = (
  mediaId: number,
  altText: string,
  title = 'Item',
  isDecorative = false,
): describeApi.DescriptionHistoryItem => ({
  media_id: mediaId,
  title,
  mime_type: 'image/jpeg',
  current_alt_text: altText,
  generated_alt_text: 'Generated',
  provenance: null,
  human_edit: { alt_text: altText, edited_at: '2026-07-28 12:00:00', user_id: 7 },
  run_status: null,
  is_decorative: isDecorative,
});

const seedWorkbench = (
  client: QueryClient,
  altText: string | null = null,
  overrides: Partial<WorkbenchMediaResponse> = {},
): WorkbenchMediaResponse => {
  const page: WorkbenchMediaResponse = {
    items: [
      {
        id: 42,
        title: 'Bridge',
        status: 'missing',
        thumbnailUrl: null,
        altText,
        isDecorative: false,
        editUrl: null,
        tags: [],
      },
      {
        id: 99,
        title: 'Other',
        status: 'missing',
        thumbnailUrl: null,
        altText: null,
        isDecorative: false,
        editUrl: null,
        tags: [],
      },
    ],
    total: 2,
    totalPages: 1,
    ...overrides,
  };
  client.setQueryData(queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' }), page);
  return page;
};

const missingPageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
const PER_PAGE = 20;

/**
 * Envelope honesty for workbench pages after targeted row patches.
 *
 * The pin-splice defect grew `items` while leaving `total` alone (or left
 * total=0 with items>0). Asserting only `total === expectedTotal` and
 * `items.length <= PER_PAGE` cannot see that growth: total:2 with three items
 * would pass. Callers pass the seeded page length so a phantom splice fails
 * the helper alone [BR-122][TEST-15][rg-015].
 */
const assertEnvelopeHonest = (
  cached: WorkbenchMediaResponse | undefined,
  expectedTotal: number,
  expectedItemCount: number = expectedTotal,
): void => {
  expect(cached).toBeDefined();
  // total is server seed — never fabricated upward to match a spliced items array.
  expect(cached!.total).toBe(expectedTotal);
  // Exact seeded length — not an upper bound that swallows phantom growth [BR-122].
  expect(cached!.items.length).toBe(expectedItemCount);
  expect(cached!.items.length).toBeLessThanOrEqual(PER_PAGE);
  // Pin-splice signature was items grown while total stayed (or total=0 with items>0).
  if (cached!.total === 0) {
    expect(cached!.items.length).toBe(0);
  }
};

const buildClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const createWrapper = (client: QueryClient) => {
  const Wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

const statsEnvelope = (total: number): WorkbenchMediaResponse => ({
  items: [],
  total,
  totalPages: Math.max(1, total),
});

describe('useCorrectMediaAlt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('assertEnvelopeHonest fails when items grow while total stays (phantom splice) [BR-122][TEST-15]', () => {
    // Standalone proof that the helper alone catches growth: splice a phantom row,
    // leave total alone, and show the helper fails without other id-list asserts.
    const honest: WorkbenchMediaResponse = {
      items: [
        {
          id: 42,
          title: 'Bridge',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
        {
          id: 99,
          title: 'Other',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
      ],
      total: 2,
      totalPages: 1,
    };
    expect(() => assertEnvelopeHonest(honest, 2)).not.toThrow();

    const withPhantom: WorkbenchMediaResponse = {
      ...honest,
      items: [
        ...honest.items,
        {
          id: 777,
          title: 'Phantom',
          status: 'missing',
          thumbnailUrl: null,
          altText: 'spliced',
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
      ],
    };
    // total still 2; old helper (items.length <= PER_PAGE only) would pass.
    expect(withPhantom.total).toBe(2);
    expect(withPhantom.items.length).toBe(3);
    expect(() => assertEnvelopeHonest(withPhantom, 2)).toThrow();
  });

  it('refetches the missing-alt stats probe after a successful correction [BR-101]', async () => {
    // Assert on observed query state / fetch count for the real stats key — not
    // merely that invalidateQueries was called (which would pass for a wrong key).
    correctMock.mockResolvedValue(successHistoryItem(42, 'Saved alt', 'Bridge'));
    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(7));
      }
      if (params.status === 'all' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(20));
      }
      return Promise.resolve(statsEnvelope(0));
    });

    const client = buildClient();
    seedWorkbench(client, null);
    const wrapper = createWrapper(client);
    const { result: statsResult } = renderHook(() => useMediaStats(), { wrapper });
    const { result: correctResult } = renderHook(() => useCorrectMediaAlt(), { wrapper });

    await waitFor(() => expect(statsResult.current.isLoading).toBe(false));
    expect(statsResult.current.stats.missing).toBe(7);
    expect(statsResult.current.stats.total).toBe(20);
    const missingFetchesBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;
    const totalFetchesBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'all' && call[0].perPage === 1,
    ).length;
    expect(missingFetchesBefore).toBeGreaterThanOrEqual(1);

    // Next missing probe returns a lower total — only a real refetch of the
    // correct key can move stats.missing.
    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(6));
      }
      if (params.status === 'all' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(20));
      }
      return Promise.resolve(statsEnvelope(0));
    });

    correctResult.current.mutate({ mediaId: 42, altText: 'Saved alt' });
    await waitFor(() => expect(correctResult.current.isSuccess).toBe(true));

    await waitFor(() => expect(statsResult.current.stats.missing).toBe(6));
    const missingFetchesAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;
    const totalFetchesAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'all' && call[0].perPage === 1,
    ).length;
    expect(missingFetchesAfter).toBeGreaterThan(missingFetchesBefore);
    // status:'all' probe is not invalidated — alt correction does not change media count.
    expect(totalFetchesAfter).toBe(totalFetchesBefore);
    // Cache entry under the exported key holds the new server total.
    expect(client.getQueryData<WorkbenchMediaResponse>(mediaStatsMissingQueryKey)?.total).toBe(6);
    // List page still has honest envelope — we did not fabricate totals [rg-015].
    assertEnvelopeHonest(client.getQueryData<WorkbenchMediaResponse>(missingPageKey), 2);
  });

  it('does not refresh stats counters on a failed correction [BR-101]', async () => {
    correctMock.mockRejectedValueOnce(totalFailureError());
    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(7));
      }
      if (params.status === 'all' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(20));
      }
      return Promise.resolve(statsEnvelope(0));
    });

    const client = buildClient();
    seedWorkbench(client, null);
    const wrapper = createWrapper(client);
    const { result: statsResult } = renderHook(() => useMediaStats(), { wrapper });
    const { result: correctResult } = renderHook(() => useCorrectMediaAlt(), { wrapper });

    await waitFor(() => expect(statsResult.current.isLoading).toBe(false));
    const missingFetchesBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;

    correctResult.current.mutate({ mediaId: 42, altText: 'Would-be alt' });
    await waitFor(() => expect(correctResult.current.isError).toBe(true));

    // Give any accidental invalidate a chance to schedule a refetch.
    await new Promise((resolve) => setTimeout(resolve, 50));
    const missingFetchesAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;
    expect(missingFetchesAfter).toBe(missingFetchesBefore);
    expect(statsResult.current.stats.missing).toBe(7);
    expect(client.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).not.toBe(true);
  });

  it('does not refresh stats counters on a partial correction [BR-101]', async () => {
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt', is_decorative: false }),
    );
    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(7));
      }
      return Promise.resolve(statsEnvelope(20));
    });

    const client = buildClient();
    seedWorkbench(client, null);
    const wrapper = createWrapper(client);
    const { result: statsResult } = renderHook(() => useMediaStats(), { wrapper });
    const { result: correctResult } = renderHook(() => useCorrectMediaAlt(), { wrapper });

    await waitFor(() => expect(statsResult.current.isLoading).toBe(false));
    const missingFetchesBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;

    correctResult.current.mutate({ mediaId: 42, altText: 'Partial-saved alt' });
    await waitFor(() => expect(correctResult.current.isError).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));

    const missingFetchesAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].status === 'missing' && call[0].perPage === 1,
    ).length;
    expect(missingFetchesAfter).toBe(missingFetchesBefore);
    expect(statsResult.current.stats.missing).toBe(7);
  });

  it('patches the corrected row from the server response and does not invalidate media.all', async () => {
    correctMock.mockResolvedValue(successHistoryItem(42, 'Saved alt', 'Bridge'));
    const client = buildClient();
    seedWorkbench(client, null);
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Saved alt' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('Saved alt');
    // Sibling untouched; both rows still present (no list drop on success).
    expect(cached?.items.find((item) => item.id === 99)?.altText).toBeNull();
    expect(cached?.items).toHaveLength(2);
    assertEnvelopeHonest(cached, 2);

    // The BR-77 root cause: media.all invalidation. Must not fire.
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: queryKeys.media.all });
    expect(
      invalidateSpy.mock.calls.some(
        (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: queryKeys.media.all }),
      ),
    ).toBe(false);
    // BR-101: only the missing stats probe (not the list page, not media.all).
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: mediaStatsMissingQueryKey });
    expect(
      invalidateSpy.mock.calls.some(
        (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: mediaStatsTotalQueryKey }),
      ),
    ).toBe(false);
  });

  it('full success with non-empty alt patches status to complete [WBUX-5-BR-112]', async () => {
    // Discrimination: before the fix only altText was patched; status stayed 'missing'.
    correctMock.mockResolvedValue(successHistoryItem(42, 'Saved alt', 'Bridge'));
    const client = buildClient();
    seedWorkbench(client, null, { total: 5, totalPages: 3 });
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Saved alt' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBe('Saved alt');
    expect(row?.status).toBe('complete');
    expect(row?.isDecorative).toBe(false);
    // Envelope counts are server seed — never recomputed from one row [rg-015].
    expect(cached?.total).toBe(5);
    expect(cached?.totalPages).toBe(3);
    assertEnvelopeHonest(cached, 5, 2);
  });

  it('full success with decorative:true patches isDecorative true + complete + null alt [WBUX-5]', async () => {
    // Server is_decorative true must land on the cached row — status alone is not
    // enough (altText null + complete is the same shape as a refetch race).
    correctMock.mockResolvedValue(successHistoryItem(42, '', 'Bridge', true));
    const client = buildClient();
    seedWorkbench(client, 'Prior alt', { total: 5, totalPages: 2 });
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '', decorative: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.status).toBe('complete');
    expect(row?.isDecorative).toBe(true);
    assertEnvelopeHonest(cached, 5, 2);
  });

  it('two-arg mutation (no decorative) calls correctDescriptionHistoryItem with two args only [A-02]', async () => {
    // Existing Accept/Save paths omit decorative. Pre-fix and post-fix both
    // must produce a literal two-argument API call — tests pin no third arg.
    // [TEST-15]: goes RED if mutationFn always passes a third options object.
    correctMock.mockResolvedValue(successHistoryItem(42, 'Saved alt', 'Bridge'));
    const client = buildClient();
    seedWorkbench(client, null);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Saved alt' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, 'Saved alt');
    expect(correctMock.mock.calls[0]).toHaveLength(2);
  });

  it('mutation with decorative:false posts options with false [A-02][INT-09]', async () => {
    // Un-mark: decorative must be defined so the API sends explicit false.
    // [TEST-15]: goes RED if mutationFn only forwards when decorative === true.
    correctMock.mockResolvedValue(successHistoryItem(42, '', 'Bridge', false));
    const client = buildClient();
    seedWorkbench(client, null);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '', decorative: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(correctMock).toHaveBeenCalledWith(42, '', { decorative: false });
  });

  it('PARTIAL path never plants isDecorative when server reports false even if request was decorative [WBUX-5][A-03]', async () => {
    // Marker was not stored this write. Server is_decorative:false is authoritative;
    // empty PARTIAL must not invent isDecorative:true from request intent [A-03][rg-015].
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, {
        status: 500,
        stored_alt_text: '',
        is_decorative: false,
      }),
    );
    const client = buildClient();
    const page = seedWorkbench(client, 'Prior alt', { total: 3, totalPages: 1 });
    page.items[0] = { ...page.items[0], status: 'complete', altText: 'Prior alt', isDecorative: false };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '', decorative: true });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.status).toBe('missing');
    expect(row?.isDecorative).toBe(false);
  });

  it('PARTIAL decorative with server is_decorative true keeps marker complete [WBUX-5-R2-02][WBUX-5-D-01][A-03]', async () => {
    // Server reports marker still present (empty non-decorative / plant already
    // on disk). Seed false so only server truth (not prior cache) can flip true.
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, {
        status: 500,
        stored_alt_text: '',
        is_decorative: true,
      }),
    );
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 3, totalPages: 1 });
    page.items[0] = {
      ...page.items[0],
      status: 'missing',
      altText: null,
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '', decorative: true });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.isDecorative).toBe(true);
    expect(row?.status).toBe('complete');
  });

  it('non-empty non-decorative correction clears a prior isDecorative true [WBUX-5-D-01][WBUX-5-R2-02]', async () => {
    // Kills sticky `decorative || item.isDecorative` — describing a decorative
    // image must flip isDecorative false and status complete with alt set.
    correctMock.mockResolvedValue(successHistoryItem(42, 'Now described', 'Bridge', false));
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 5, totalPages: 2 });
    page.items[0] = {
      ...page.items[0],
      altText: null,
      status: 'complete',
      isDecorative: true,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Now described' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBe('Now described');
    expect(row?.status).toBe('complete');
    expect(row?.isDecorative).toBe(false);
  });

  it('empty non-decorative correction uses server is_decorative true [WBUX-5-D-01][A-03][TEST-15]', async () => {
    // Two-click repro: Edit→Save blank on a decorative row posts alt_text:'' with
    // no decorative flag. Server still has the marker — is_decorative:true on the
    // success envelope is the only honest source [A-03][rg-015].
    // Seed prior FALSE so sticky `decorative || prior` and collapsed
    // `decorative === true` both leave false — only reading server flips true.
    correctMock.mockResolvedValue(successHistoryItem(42, '', 'Bridge', true));
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 4, totalPages: 1 });
    page.items[0] = {
      ...page.items[0],
      altText: null,
      status: 'missing',
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.isDecorative).toBe(true);
    expect(row?.status).toBe('complete');
  });

  it('whitespace-only non-decorative correction uses server is_decorative true [C-02][rg-015][A-03][TEST-15]', async () => {
    // Server rule: '' !== trim($alt_text). Whitespace-only is empty for has_alt and
    // preserves a prior decorative marker — server reports is_decorative:true.
    // Prior false: sticky/collapsed client re-derive cannot invent true [TEST-15].
    correctMock.mockResolvedValue(successHistoryItem(42, '   ', 'Bridge', true));
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 4, totalPages: 1 });
    page.items[0] = {
      ...page.items[0],
      altText: null,
      status: 'missing',
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '   ' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.isDecorative).toBe(true);
    expect(row?.status).toBe('complete');
  });

  it('PARTIAL non-empty stored alt follows server is_decorative over client re-derive [WBUX-5-R3-01][A-03][TEST-15]', async () => {
    // Clear-failed PARTIAL can report non-empty stored alt with is_decorative:true
    // (marker survived). Client "non-empty → clear marker" would set false; sticky
    // prior false stays false. Only server truth flips true.
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, {
        status: 500,
        stored_alt_text: 'Partial-saved alt',
        is_decorative: true,
      }),
    );
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 6, totalPages: 2 });
    page.items[0] = {
      ...page.items[0],
      altText: null,
      status: 'missing',
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Partial-saved alt' });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBe('Partial-saved alt');
    expect(row?.status).toBe('complete');
    expect(row?.isDecorative).toBe(true);
  });

  it('cache patch follows server is_decorative even when it contradicts request intent [A-03][TEST-15]', async () => {
    // Discrimination: old nextIsDecorative(alt, decorativeIntent=true, prior) was
    // always true. Server reports is_decorative:false (plant refused / marker
    // absent) — client must patch false, not re-derive true from request [rg-015].
    correctMock.mockResolvedValue(successHistoryItem(42, '', 'Bridge', false));
    const client = buildClient();
    const page = seedWorkbench(client, 'Prior alt', { total: 4, totalPages: 1 });
    page.items[0] = {
      ...page.items[0],
      altText: 'Prior alt',
      status: 'complete',
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '', decorative: true });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.isDecorative).toBe(false);
    expect(row?.status).toBe('missing');
    assertEnvelopeHonest(cached, 4, 2);
  });

  it('PARTIAL cache patch follows server is_decorative even when prior cache and request disagree [A-03][TEST-15]', async () => {
    // Request decorative:true + empty alt would have made old nextIsDecorative
    // true on success; PARTIAL previously omitted decorative intent and preserved
    // prior. Server says is_decorative:true while prior cache is false — only
    // reading the server field can flip the row; re-derive from prior stays false.
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, {
        status: 500,
        stored_alt_text: '',
        is_decorative: true,
      }),
    );
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 3, totalPages: 1 });
    page.items[0] = {
      ...page.items[0],
      altText: null,
      status: 'missing',
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '', decorative: true });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.isDecorative).toBe(true);
    expect(row?.status).toBe('complete');
    expect(row?.altText).toBeNull();
  });

  it('PARTIAL without is_decorative leaves cache untouched [A-03][rg-015]', async () => {
    // Absent boolean must not invent decorative from request intent or prior.
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt' }),
    );
    const client = buildClient();
    const page = seedWorkbench(client, null, { total: 5, totalPages: 1 });
    page.items[0] = {
      ...page.items[0],
      altText: null,
      status: 'missing',
      isDecorative: false,
    };
    client.setQueryData(missingPageKey, page);
    const before = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Partial-saved alt', decorative: true });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached).toBe(before);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBeNull();
  });

  it('full success with empty alt patches status back to missing [WBUX-5-BR-112]', async () => {
    // Empty string is a legitimate stored value. A naive hard-code of
    // status: 'complete' would pass the non-empty case and fail here.
    correctMock.mockResolvedValue(successHistoryItem(42, '', 'Bridge'));
    const client = buildClient();
    // Seed complete so "back to missing" is observable (not a no-op stay).
    const page = seedWorkbench(client, 'Prior alt', { total: 4, totalPages: 2 });
    page.items[0] = { ...page.items[0], status: 'complete', altText: 'Prior alt' };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    // class-api.php:346 emits null for every !has_alt case — never '' [rg-015].
    expect(row?.altText).toBeNull();
    expect(row?.status).toBe('missing');
    expect(row?.isDecorative).toBe(false);
    expect(cached?.total).toBe(4);
    expect(cached?.totalPages).toBe(2);
    assertEnvelopeHonest(cached, 4, 2);
  });

  it('full success with whitespace-only alt patches status to missing [WBUX-5-BR-112]', async () => {
    // PHP: $has_alt = '' !== trim( $alt_text ). A naive altText !== '' would
    // mark '   ' complete and pass wrongly. Seed complete so staying complete
    // (no status patch, or hard-coded complete) fails the assertion.
    // Whitespace-only trims to empty → null on the wire (class-api.php:346).
    correctMock.mockResolvedValue(successHistoryItem(42, '   ', 'Bridge'));
    const client = buildClient();
    const page = seedWorkbench(client, 'Prior alt', { total: 8, totalPages: 4 });
    page.items[0] = { ...page.items[0], status: 'complete', altText: 'Prior alt' };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '   ' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBeNull();
    expect(row?.status).toBe('missing');
    expect(row?.isDecorative).toBe(false);
    expect(cached?.total).toBe(8);
    expect(cached?.totalPages).toBe(4);
    assertEnvelopeHonest(cached, 8, 2);
  });

  it('partial failure patches status from stored_alt_text [WBUX-5-BR-112]', async () => {
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt', is_decorative: false }),
    );
    const client = buildClient();
    seedWorkbench(client, null, { total: 6, totalPages: 2 });
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Partial-saved alt' });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBe('Partial-saved alt');
    expect(row?.status).toBe('complete');
    expect(cached?.total).toBe(6);
    expect(cached?.totalPages).toBe(2);
    assertEnvelopeHonest(cached, 6, 2);
  });

  it('partial failure with blank stored_alt_text patches status to missing [WBUX-5-BR-112]', async () => {
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: '', is_decorative: false }),
    );
    const client = buildClient();
    const page = seedWorkbench(client, 'Prior honest alt', { total: 3, totalPages: 1 });
    page.items[0] = { ...page.items[0], status: 'complete', altText: 'Prior honest alt' };
    client.setQueryData(missingPageKey, page);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '   ' });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    // Blank stored_alt_text normalizes to null (class-api.php:346); PARTIAL
    // never stores the decorative marker, so isDecorative stays false.
    expect(row?.altText).toBeNull();
    expect(row?.status).toBe('missing');
    expect(row?.isDecorative).toBe(false);
    expect(cached?.total).toBe(3);
    expect(cached?.totalPages).toBe(1);
    assertEnvelopeHonest(cached, 3, 2);
  });

  it('partial without stored_alt_text leaves cache status and alt untouched [WBUX-5-BR-112]', async () => {
    correctMock.mockRejectedValueOnce(partialError(PARTIAL_MESSAGE, { status: 500 }));
    const client = buildClient();
    const page = seedWorkbench(client, 'Prior honest alt', { total: 7, totalPages: 3 });
    page.items[0] = { ...page.items[0], status: 'complete', altText: 'Prior honest alt' };
    client.setQueryData(missingPageKey, page);
    const before = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Would fabricate' });
    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    const row = cached?.items.find((item) => item.id === 42);
    expect(row?.altText).toBe('Prior honest alt');
    expect(row?.status).toBe('complete');
    // Same object reference — null-only gate skipped the write entirely.
    expect(cached).toBe(before);
    expect(cached?.total).toBe(7);
    expect(cached?.totalPages).toBe(3);
    assertEnvelopeHonest(cached, 7, 2);
  });

  it('successful correction does not invalidate or refetch the workbench list query [WBUX-5-BR-112][RLSE-04]', async () => {
    // Regression pin: do not "fix" stale status by invalidateQueries(workbench).
    // Observe query-client state — not a spy on an internal helper.
    // If the list were invalidated+refetched under status=missing, the server
    // would drop the corrected row; the trap response below encodes that.
    correctMock.mockResolvedValue(successHistoryItem(42, 'Saved alt', 'Bridge'));
    fetchWorkbenchMock.mockImplementation((params) => {
      if (params.status === 'missing' && params.perPage === 20) {
        return Promise.resolve({
          items: [
            {
              id: 99,
              title: 'Other',
              status: 'missing' as const,
              thumbnailUrl: null,
              altText: null,
              isDecorative: false,
              editUrl: null,
              tags: [],
            },
          ],
          total: 1,
          totalPages: 1,
        });
      }
      if (params.status === 'missing' && params.perPage === 1) {
        return Promise.resolve(statsEnvelope(6));
      }
      return Promise.resolve(statsEnvelope(20));
    });

    const client = buildClient();
    seedWorkbench(client, null);
    const wrapper = createWrapper(client);

    // Active list observer with a real queryFn so invalidateQueries would refetch.
    // Seeded setQueryData is already in cache; do not refetch on mount — only an
    // invalidation (or explicit refetch) should hit queryFn / fetchWorkbenchMedia.
    const { result: listResult } = renderHook(
      () =>
        useQuery({
          queryKey: missingPageKey,
          queryFn: () =>
            workbenchMediaApi.fetchWorkbenchMedia({ page: 1, perPage: 20, status: 'missing' }),
          staleTime: Infinity,
          refetchOnMount: false,
          refetchOnWindowFocus: false,
        }),
      { wrapper },
    );

    // Also mount stats so invalidateMediaStats can run without affecting the list key.
    renderHook(() => useMediaStats(), { wrapper });

    const stateBefore = client.getQueryState(missingPageKey);
    expect(stateBefore?.isInvalidated).not.toBe(true);
    const listFetchesBefore = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].page === 1 && call[0].perPage === 20 && call[0].status === 'missing',
    ).length;

    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper });
    result.current.mutate({ mediaId: 42, altText: 'Saved alt' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // Allow any accidental list refetch to schedule.
    await new Promise((resolve) => setTimeout(resolve, 80));

    const stateAfter = client.getQueryState(missingPageKey);
    // Observable query-client state: list page is not marked invalidated/stale-by-invalidation.
    expect(stateAfter?.isInvalidated).not.toBe(true);
    expect(stateAfter?.status).toBe('success');
    expect(stateAfter?.fetchStatus).toBe('idle');
    expect(listResult.current.isFetching).toBe(false);

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    // Corrected row object still in the cache (would be absent after a missing-list refetch).
    const row = cached?.items.find((item) => item.id === 42);
    expect(row).toBeDefined();
    expect(row?.altText).toBe('Saved alt');
    expect(row?.status).toBe('complete');
    expect(cached?.items.map((item) => item.id).sort((a, b) => a - b)).toEqual([42, 99]);
    expect(cached?.total).toBe(2);

    const listFetchesAfter = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0].page === 1 && call[0].perPage === 20 && call[0].status === 'missing',
    ).length;
    expect(listFetchesAfter).toBe(listFetchesBefore);
    assertEnvelopeHonest(cached, 2);
  });

  it('reconciles cached workbench alt text on description_correction_partial without invalidating [WBUX-5-BR-51]', async () => {
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctMock.mockRejectedValueOnce(
      partialError(partialMessage, { status: 500, stored_alt_text: 'Partial-saved alt', is_decorative: false }),
    );
    const client = buildClient();
    seedWorkbench(client, null);
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Partial-saved alt' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    // Invariant 1: displayed alt reflects storage after partial success.
    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('Partial-saved alt');
    // Sibling row untouched.
    expect(cached?.items.find((item) => item.id === 99)?.altText).toBeNull();
    // Row still present (no tree invalidation). Status derived from stored alt
    // (non-empty → complete) — same rule as full success [WBUX-5-BR-112].
    expect(cached?.items).toHaveLength(2);
    expect(cached?.items.find((item) => item.id === 42)?.status).toBe('complete');
    assertEnvelopeHonest(cached, 2);
    expect(invalidateSpy).not.toHaveBeenCalled();

    // Invariant 2: error message still present and readable after reconciliation.
    expect(result.current.error).toBeInstanceOf(Error);
    expect(describeApi.resolveDescribeErrorMessage(result.current.error, 'fallback')).toBe(partialMessage);
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe('description_correction_partial');
  });

  it('patches workbench cache with server stored_alt_text when it differs from the request [S1][rg-015]', async () => {
    // Decisive fixture: request still has markup/whitespace; server reports the
    // normalized value actually stored. A request-body patch would green falsely.
    const submitted = '  <em>Sunset</em> over the bay  ';
    const stored = 'Sunset over the bay';
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: stored, is_decorative: false }),
    );
    const client = buildClient();
    seedWorkbench(client, 'Prior alt');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: submitted });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe(stored);
    expect(cached?.items.find((item) => item.id === 42)?.altText).not.toBe(submitted);
    assertEnvelopeHonest(cached, 2);
  });

  it('reconciles blank stored_alt_text on partial — blank server fact overwrites prior alt [TEST-15][rg-015]', async () => {
    // sanitize_text_field of a blank correction yields ''. A truthy guard
    // (`if (!storedAltText)`) would skip reconciliation and leave the prior
    // alt — the class of lie this slice removed. Null-only gate must apply the
    // blank server fact; cache normalizes it to null (class-api.php:346).
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: '', is_decorative: false }),
    );
    const client = buildClient();
    seedWorkbench(client, 'Prior honest alt');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '   ' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBeNull();
    // Discriminating pin: blank server value is APPLIED, not ignored.
    expect(cached?.items.find((item) => item.id === 42)?.altText).not.toBe('Prior honest alt');
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe(
      describeApi.DESCRIPTION_CORRECTION_CODE.PARTIAL,
    );
  });

  it('does not patch workbench cache when partial lacks stored_alt_text; error still surfaces [S1][RLSE-05]', async () => {
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500 }),
    );
    const client = buildClient();
    seedWorkbench(client, 'Prior honest alt');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '  <em>Would fabricate</em>  ' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    // Stale-but-real: prior cache value preserved; request body never written in.
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('Prior honest alt');
    expect(cached?.items.find((item) => item.id === 42)?.altText).not.toBe('  <em>Would fabricate</em>  ');
    // Operator still informed — mutation error is present for the alert path.
    expect(result.current.isError).toBe(true);
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe(
      describeApi.DESCRIPTION_CORRECTION_CODE.PARTIAL,
    );
    expect(describeApi.resolveDescribeErrorMessage(result.current.error, 'fallback')).toBe(PARTIAL_MESSAGE);
  });

  it('does not reconcile cache on a total correction failure', async () => {
    correctMock.mockRejectedValueOnce(totalFailureError());
    const client = buildClient();
    seedWorkbench(client, null);
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Would-be alt' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBeNull();
    expect(invalidateSpy).not.toHaveBeenCalled();
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe('description_correction_failed');
  });

  it('gates partial reconcile on stable code, not message text (total fail with partial wording) [WBUX-5-BR-51]', async () => {
    // Decisive fixture: failed code + message that still contains the partial
    // phrase. A message-includes gate would wrongly reconcile; the code gate must not.
    const deceptiveMessage =
      'Could not save the alt text correction: the human-edit record could not be stored either.';
    correctMock.mockRejectedValueOnce(totalFailureError(deceptiveMessage));
    const client = buildClient();
    seedWorkbench(client, null);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Must-not-appear-in-cache' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBeNull();
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe(
      describeApi.DESCRIPTION_CORRECTION_CODE.FAILED,
    );
    expect(describeApi.resolveDescribeErrorMessage(result.current.error, 'fallback')).toContain(
      'human-edit record could not be stored',
    );
  });

  it('reconciles on partial code even when the message text is unrelated [WBUX-5-BR-51]', async () => {
    const unrelatedMessage = 'Marker write failed with storage code 503.';
    correctMock.mockRejectedValueOnce(
      partialError(unrelatedMessage, { status: 500, stored_alt_text: 'Code-gated partial alt', is_decorative: false }),
    );
    const client = buildClient();
    seedWorkbench(client, null);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Code-gated partial alt' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('Code-gated partial alt');
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe(
      describeApi.DESCRIPTION_CORRECTION_CODE.PARTIAL,
    );
    expect(describeApi.resolveDescribeErrorMessage(result.current.error, 'fallback')).toBe(unrelatedMessage);
  });

  it('keeps partial row A in cache after sibling B success — no media.all invalidation [RLSE-04]', async () => {
    // The old pin-store test was vacuous [TEST-17]: it asserted isError on a
    // standalone renderHook that the workbench cache cannot unmount. Replaced
    // by the component-level MediaAltInlineEditor sibling test for alert+draft.
    // This hook-level check only asserts the cache/invalidation contract.
    const client = buildClient();
    seedWorkbench(client, null);
    const wrapper = createWrapper(client);
    const { result: rowA } = renderHook(() => useCorrectMediaAlt(), { wrapper });
    const { result: rowB } = renderHook(() => useCorrectMediaAlt(), { wrapper });

    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt', is_decorative: false }),
    );
    rowA.current.mutate({ mediaId: 42, altText: 'Partial-saved alt' });
    await waitFor(() => expect(rowA.current.isError).toBe(true));

    const afterPartial = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(afterPartial?.items.map((item) => item.id).sort((a, b) => a - b)).toEqual([42, 99]);
    expect(afterPartial?.items.find((item) => item.id === 42)?.altText).toBe('Partial-saved alt');
    assertEnvelopeHonest(afterPartial, 2);

    correctMock.mockResolvedValueOnce(successHistoryItem(99, 'Sibling saved', 'Other'));
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    rowB.current.mutate({ mediaId: 99, altText: 'Sibling saved' });
    await waitFor(() => expect(rowB.current.isSuccess).toBe(true));

    // Targeted patch: B's alt updated, A still present, envelope honest.
    const afterSibling = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(afterSibling?.items.find((item) => item.id === 42)?.altText).toBe('Partial-saved alt');
    expect(afterSibling?.items.find((item) => item.id === 99)?.altText).toBe('Sibling saved');
    expect(afterSibling?.items).toHaveLength(2);
    assertEnvelopeHonest(afterSibling, 2);
    expect(invalidateSpy).not.toHaveBeenCalledWith({ queryKey: queryKeys.media.all });

    // Row A's mutation error (the role=alert source) is still present.
    expect(rowA.current.isError).toBe(true);
    expect(describeApi.resolveDescribeErrorCode(rowA.current.error)).toBe(
      describeApi.DESCRIPTION_CORRECTION_CODE.PARTIAL,
    );
  });

  it('patches success alt from server current_alt_text when it differs from the request [rg-015]', async () => {
    const submitted = '  <b>Bridge</b>  ';
    const stored = 'Bridge';
    correctMock.mockResolvedValueOnce(successHistoryItem(42, stored, 'Bridge'));
    const client = buildClient();
    seedWorkbench(client, null);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: submitted });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe(stored);
    expect(cached?.items.find((item) => item.id === 42)?.altText).not.toBe(submitted);
    assertEnvelopeHonest(cached, 2);
  });

  /**
   * No module state: two sequential tests with no explicit reset must not leak.
   * (The deleted pin store required _resetPinnedPartialsForTests in beforeEach.)
   */
  it('sequential partial then success do not leave phantom rows for a later client [no module state]', async () => {
    const client1 = buildClient();
    seedWorkbench(client1, null);
    const { result: r1 } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client1) });
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Pinned-would-leak', is_decorative: false }),
    );
    r1.current.mutate({ mediaId: 42, altText: 'Pinned-would-leak' });
    await waitFor(() => expect(r1.current.isError).toBe(true));

    // Fresh client, no shared registry. Seeding a page without 42 must stay
    // without 42 — a module-level pin subscriber would re-splice it in.
    const client2 = buildClient();
    client2.setQueryData<WorkbenchMediaResponse>(missingPageKey, {
      items: [
        {
          id: 99,
          title: 'Other',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    });
    // Mount the hook so any render-time subscriber would install (old design).
    renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client2) });
    // Trigger a cache write the old QueryCache subscriber watched.
    client2.setQueryData<WorkbenchMediaResponse>(missingPageKey, {
      items: [
        {
          id: 99,
          title: 'Other',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    });

    const cached = client2.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)).toBeUndefined();
    expect(cached?.items.map((item) => item.id)).toEqual([99]);
    assertEnvelopeHonest(cached, 1);
  });

  it('envelope stays honest after partial then success on the same page [rg-015]', async () => {
    const client = buildClient();
    seedWorkbench(client, null);
    const wrapper = createWrapper(client);
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper });

    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt', is_decorative: false }),
    );
    result.current.mutate({ mediaId: 42, altText: 'Partial-saved alt' });
    await waitFor(() => expect(result.current.isError).toBe(true));
    assertEnvelopeHonest(client.getQueryData<WorkbenchMediaResponse>(missingPageKey), 2);

    correctMock.mockResolvedValueOnce(successHistoryItem(99, 'Sibling saved', 'Other'));
    result.current.mutate({ mediaId: 99, altText: 'Sibling saved' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    // total is still the server-seeded 2 — never fabricated upward to match items.
    expect(cached?.total).toBe(2);
    expect(cached?.items.length).toBeLessThanOrEqual(PER_PAGE);
    expect(cached?.items.length).toBe(2);
  });
});
