import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCorrectMediaAlt } from '../useCorrectMediaAlt';
import * as describeApi from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';

vi.mock('../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/describeApi')>('../../api/describeApi');
  return {
    ...actual,
    correctDescriptionHistoryItem: vi.fn(),
  };
});

const correctMock = vi.mocked(describeApi.correctDescriptionHistoryItem);

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

const seedWorkbench = (client: QueryClient, altText: string | null = null): void => {
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
  };
  client.setQueryData(queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' }), page);
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

describe('useCorrectMediaAlt', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('invalidates the media tree on full success', async () => {
    correctMock.mockResolvedValue({
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: 'Saved alt',
      generated_alt_text: 'Generated',
      provenance: null,
      human_edit: { alt_text: 'Saved alt', edited_at: '2026-07-28 12:00:00', user_id: 7 },
      run_status: null,
    });
    const client = buildClient();
    seedWorkbench(client, null);
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');
    const { result } = renderHook(() => useCorrectMediaAlt(), { wrapper: createWrapper(client) });

    result.current.mutate({ mediaId: 42, altText: 'Saved alt' });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: queryKeys.media.all });
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
    const pageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const cached = client.getQueryData<WorkbenchMediaResponse>(pageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('Partial-saved alt');
    // Sibling row untouched.
    expect(cached?.items.find((item) => item.id === 99)?.altText).toBeNull();
    // Row still present (status not rewritten; no tree invalidation).
    expect(cached?.items).toHaveLength(2);
    expect(cached?.items.find((item) => item.id === 42)?.status).toBe('missing');
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

    const pageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const cached = client.getQueryData<WorkbenchMediaResponse>(pageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe(stored);
    expect(cached?.items.find((item) => item.id === 42)?.altText).not.toBe(submitted);
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

    const pageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const cached = client.getQueryData<WorkbenchMediaResponse>(pageKey);
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

    const pageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const cached = client.getQueryData<WorkbenchMediaResponse>(pageKey);
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

    const pageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const cached = client.getQueryData<WorkbenchMediaResponse>(pageKey);
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

    const pageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const cached = client.getQueryData<WorkbenchMediaResponse>(pageKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe('Code-gated partial alt');
    expect(describeApi.resolveDescribeErrorCode(result.current.error)).toBe(
      describeApi.DESCRIPTION_CORRECTION_CODE.PARTIAL,
    );
    expect(describeApi.resolveDescribeErrorMessage(result.current.error, 'fallback')).toBe(unrelatedMessage);
  });
});
