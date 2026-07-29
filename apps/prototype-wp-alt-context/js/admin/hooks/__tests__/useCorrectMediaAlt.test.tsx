import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
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
): describeApi.DescriptionHistoryItem => ({
  media_id: mediaId,
  title,
  mime_type: 'image/jpeg',
  current_alt_text: altText,
  generated_alt_text: 'Generated',
  provenance: null,
  human_edit: { alt_text: altText, edited_at: '2026-07-28 12:00:00', user_id: 7 },
  run_status: null,
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
        editUrl: null,
        tags: [],
      },
      {
        id: 99,
        title: 'Other',
        status: 'missing',
        thumbnailUrl: null,
        altText: null,
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

const assertEnvelopeHonest = (cached: WorkbenchMediaResponse | undefined, expectedTotal: number): void => {
  expect(cached).toBeDefined();
  // total is server seed — never fabricated upward to match a spliced items array.
  expect(cached!.total).toBe(expectedTotal);
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
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt' }),
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

  it('reconciles cached workbench alt text on description_correction_partial without invalidating [WBUX-5-BR-51]', async () => {
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctMock.mockRejectedValueOnce(
      partialError(partialMessage, { status: 500, stored_alt_text: 'Partial-saved alt' }),
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
    // Row still present (status not rewritten; no tree invalidation).
    expect(cached?.items).toHaveLength(2);
    expect(cached?.items.find((item) => item.id === 42)?.status).toBe('missing');
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
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: stored }),
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

  it('reconciles blank stored_alt_text on partial — empty string is legitimate [TEST-15][rg-015]', async () => {
    // sanitize_text_field of a blank correction yields ''. A truthy guard
    // (`if (!storedAltText)`) would skip reconciliation and leave the prior
    // alt — the class of lie this slice removed. Null-only gate must patch to ''.
    correctMock.mockRejectedValueOnce(
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: '' }),
    );
    const client = buildClient();
    seedWorkbench(client, 'Prior honest alt');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: '   ' });

    await waitFor(() => expect(result.current.isError).toBe(true));

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('');
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
      partialError(unrelatedMessage, { status: 500, stored_alt_text: 'Code-gated partial alt' }),
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
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt' }),
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
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Pinned-would-leak' }),
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
      partialError(PARTIAL_MESSAGE, { status: 500, stored_alt_text: 'Partial-saved alt' }),
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
