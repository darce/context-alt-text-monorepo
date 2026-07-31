/**
 * WBUX-5-BR-112 (remaining half): statusMessage envelope count stays server
 * truth; when Status=missing and listed rows have been corrected to complete,
 * a reconciliation sentence is appended from listed-row observation only.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor, act } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../api/queryKeys';
import type { WorkbenchMediaItem, WorkbenchMediaResponse } from '../../../api/workbenchMediaApi';
import * as workbenchMediaApi from '../../../api/workbenchMediaApi';
import * as recognitionApi from '../../../api/recognition';
import { WorkbenchMediaProvider, useWorkbenchMediaContext } from '../WorkbenchMediaContext';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

vi.mock('../../../api/workbenchMediaApi', async () => {
  const actual = await vi.importActual<typeof import('../../../api/workbenchMediaApi')>(
    '../../../api/workbenchMediaApi',
  );
  return {
    ...actual,
    fetchWorkbenchMedia: vi.fn(),
    fetchWorkbenchMediaDetail: vi.fn(),
  };
});

vi.mock('../../../api/recognition', async () => {
  const actual = await vi.importActual<typeof import('../../../api/recognition')>(
    '../../../api/recognition',
  );
  return {
    ...actual,
    fetchMediaIdentities: vi.fn(),
  };
});

const fetchWorkbenchMock = vi.mocked(workbenchMediaApi.fetchWorkbenchMedia);
const fetchDetailMock = vi.mocked(workbenchMediaApi.fetchWorkbenchMediaDetail);
const fetchIdentitiesMock = vi.mocked(recognitionApi.fetchMediaIdentities);

const PER_PAGE = 10;
const missingPageKey = (search = '') =>
  queryKeys.media.workbenchPage({ page: 1, perPage: PER_PAGE, search, status: 'missing' });
const allPageKey = (search = '') =>
  queryKeys.media.workbenchPage({ page: 1, perPage: PER_PAGE, search, status: 'all' });

const makeItem = (
  id: number,
  status: WorkbenchMediaItem['status'] = 'missing',
  overrides: Partial<WorkbenchMediaItem> = {},
): WorkbenchMediaItem => ({
  id,
  title: `Item ${id}`,
  status,
  thumbnailUrl: null,
  altText: status === 'complete' ? `Alt for ${id}` : null,
  isDecorative: false,
  editUrl: null,
  tags: [],
  ...overrides,
});

const seedPage = (
  client: QueryClient,
  {
    items,
    total,
    totalPages = 1,
    status = 'missing' as const,
    search = '',
  }: {
    items: WorkbenchMediaItem[];
    total: number;
    totalPages?: number;
    status?: 'missing' | 'all';
    search?: string;
  },
): WorkbenchMediaResponse => {
  const page: WorkbenchMediaResponse = { items, total, totalPages };
  const key =
    status === 'missing'
      ? missingPageKey(search)
      : allPageKey(search);
  client.setQueryData(key, page);
  return page;
};

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Infinity,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });

const StatusProbe = (): React.JSX.Element => {
  const { mediaQueue } = useWorkbenchMediaContext();
  return <span data-testid="status-message">{mediaQueue.statusMessage}</span>;
};

const renderProvider = (
  client: QueryClient,
  initialEntry = '/?status=missing',
): ReturnType<typeof render> =>
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <WorkbenchMediaProvider>
          <StatusProbe />
        </WorkbenchMediaProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );

const waitForIdleStatus = async (): Promise<HTMLElement> => {
  await waitFor(() => {
    const el = screen.getByTestId('status-message');
    expect(el.textContent).not.toBe('Updating media queue…');
  });
  return screen.getByTestId('status-message');
};

/**
 * Mirror patchWorkbenchRowAlt from useCorrectMediaAlt: patch status+alt on a
 * row without touching total/totalPages or invalidating the list.
 */
const patchRowComplete = (client: QueryClient, key: readonly unknown[], mediaId: number): void => {
  const data = client.getQueryData<WorkbenchMediaResponse>(key);
  if (!data?.items) {
    return;
  }
  client.setQueryData<WorkbenchMediaResponse>(key, {
    ...data,
    items: data.items.map((item) =>
      item.id === mediaId
        ? {
            ...item,
            altText: `Corrected ${mediaId}`,
            status: 'complete',
            isDecorative: false,
          }
        : item,
    ),
  });
};

/** Mirror a successful decorative mark: null alt + complete + isDecorative. */
const patchRowDecorative = (
  client: QueryClient,
  key: readonly unknown[],
  mediaId: number,
): void => {
  const data = client.getQueryData<WorkbenchMediaResponse>(key);
  if (!data?.items) {
    return;
  }
  client.setQueryData<WorkbenchMediaResponse>(key, {
    ...data,
    items: data.items.map((item) =>
      item.id === mediaId
        ? { ...item, altText: null, status: 'complete', isDecorative: true }
        : item,
    ),
  });
};

describe('WorkbenchMediaContext statusMessage [WBUX-5-BR-112]', () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    fetchWorkbenchMock.mockResolvedValue({ items: [], total: 0, totalPages: 1 });
    fetchDetailMock.mockResolvedValue({
      detailsByMedia: {},
      limit: 100,
      total: 0,
      truncated: false,
    });
    fetchIdentitiesMock.mockResolvedValue({
      identities_by_media: {},
      data_source: 'local_projection',
    } as never);
  });

  it('[TEST-06] headline: missing filter, three cached rows, two patched complete — envelope count + reconciliation', async () => {
    // Predicted RED (pre-fix): message is exactly "Showing 3 media items." with
    // no reconciliation about the two corrected rows — that is today's defect.
    const client = buildClient();
    const key = missingPageKey();
    seedPage(client, {
      items: [makeItem(1), makeItem(2), makeItem(3)],
      total: 3,
      status: 'missing',
    });

    renderProvider(client, '/?status=missing');
    let status = await waitForIdleStatus();
    expect(status.textContent).toContain('Showing 3 media items.');

    act(() => {
      patchRowComplete(client, key, 1);
      patchRowComplete(client, key, 2);
    });

    status = await waitForIdleStatus();
    // Envelope total untouched in the message [rg-015].
    expect(status.textContent).toMatch(/Showing 3 media items\./);
    // Discrimination: must report the two listed rows that now have alt.
    // Pre-fix code never emits this — fails if reconciliation is missing.
    expect(status.textContent).toMatch(/2 now have alt text/);
    expect(status.textContent).toMatch(/will leave this view when the list next refreshes/);
    // Must not invent a decremented total.
    expect(status.textContent).not.toMatch(/Showing 1 media item/);
  });

  it('keeps the original envelope total in the message after listed rows are corrected', async () => {
    const client = buildClient();
    const key = missingPageKey();
    seedPage(client, {
      items: [makeItem(1), makeItem(2), makeItem(3)],
      total: 3,
      status: 'missing',
    });
    renderProvider(client, '/?status=missing');
    await waitForIdleStatus();

    act(() => {
      patchRowComplete(client, key, 1);
    });

    const status = await waitForIdleStatus();
    expect(status.textContent).toContain('Showing 3 media items.');
    // Cache envelope also unchanged.
    const cached = client.getQueryData<WorkbenchMediaResponse>(key);
    expect(cached?.total).toBe(3);
    expect(cached?.totalPages).toBe(1);
  });

  it('does not append a reconciliation sentence when the filter is not missing', async () => {
    const client = buildClient();
    const key = allPageKey();
    seedPage(client, {
      items: [makeItem(1, 'missing'), makeItem(2, 'complete'), makeItem(3, 'complete')],
      total: 3,
      status: 'all',
    });
    renderProvider(client, '/?status=all');
    const status = await waitForIdleStatus();
    expect(status.textContent).toBe('Showing 3 media items.');
    expect(status.textContent).not.toMatch(/now have alt text|now has alt text/);
    // Still true after a further listed-row patch under status=all.
    act(() => {
      patchRowComplete(client, key, 1);
    });
    const after = await waitForIdleStatus();
    expect(after.textContent).toBe('Showing 3 media items.');
    expect(after.textContent).not.toMatch(/now have alt text|now has alt text/);
  });

  it('does not append a reconciliation sentence when zero listed rows read complete', async () => {
    const client = buildClient();
    seedPage(client, {
      items: [makeItem(1), makeItem(2), makeItem(3)],
      total: 3,
      status: 'missing',
    });
    renderProvider(client, '/?status=missing');
    const status = await waitForIdleStatus();
    expect(status.textContent).toBe('Showing 3 media items.');
    expect(status.textContent).not.toMatch(/now have alt text|now has alt text|will leave this view/);
  });

  it('pluralises the reconciliation sentence for one corrected row vs several', async () => {
    const client = buildClient();
    const key = missingPageKey();
    seedPage(client, {
      items: [makeItem(1), makeItem(2), makeItem(3)],
      total: 3,
      status: 'missing',
    });
    renderProvider(client, '/?status=missing');
    await waitForIdleStatus();

    act(() => {
      patchRowComplete(client, key, 1);
    });
    let status = await waitForIdleStatus();
    expect(status.textContent).toMatch(/1 now has alt text/);
    expect(status.textContent).not.toMatch(/1 now have alt text/);

    act(() => {
      patchRowComplete(client, key, 2);
    });
    status = await waitForIdleStatus();
    expect(status.textContent).toMatch(/2 now have alt text/);
    expect(status.textContent).not.toMatch(/2 now has alt text/);
  });

  it('does not claim alt text for decorative complete rows [INT-08]', async () => {
    // After Mark as decorative the row is complete with null alt + isDecorative.
    // Saying "now has alt text" is false — the operator deliberately has none.
    const client = buildClient();
    const key = missingPageKey();
    seedPage(client, {
      items: [makeItem(1), makeItem(2), makeItem(3)],
      total: 3,
      status: 'missing',
    });
    renderProvider(client, '/?status=missing');
    await waitForIdleStatus();

    act(() => {
      patchRowDecorative(client, key, 1);
    });

    const status = await waitForIdleStatus();
    expect(status.textContent).toMatch(/1 marked decorative/);
    expect(status.textContent).toMatch(/will leave this view when the list next refreshes/);
    expect(status.textContent).not.toMatch(/now has alt text|now have alt text/);
  });

  it('does not invalidate or mark the workbench list stale after a successful listed-row correction', async () => {
    const client = buildClient();
    const key = missingPageKey();
    seedPage(client, {
      items: [makeItem(1), makeItem(2), makeItem(3)],
      total: 3,
      status: 'missing',
    });
    renderProvider(client, '/?status=missing');
    await waitForIdleStatus();

    const stateBefore = client.getQueryState(key);
    expect(stateBefore?.data).toBeDefined();
    const dataUpdatedAtBefore = stateBefore?.dataUpdatedAt;
    const fetchStatusBefore = stateBefore?.fetchStatus;

    act(() => {
      // Same shape as useCorrectMediaAlt patch: setQueryData, no invalidate.
      patchRowComplete(client, key, 1);
    });

    const stateAfter = client.getQueryState(key);
    // Row stays mounted in the cache (not dropped by a missing-filter refetch).
    expect(stateAfter?.data).toBeDefined();
    const cached = stateAfter?.data as WorkbenchMediaResponse;
    expect(cached.items).toHaveLength(3);
    expect(cached.items.find((i) => i.id === 1)?.status).toBe('complete');
    expect(cached.total).toBe(3);
    // Observable query-client state: not invalidated / not refetching.
    expect(stateAfter?.isInvalidated).toBe(false);
    expect(stateAfter?.fetchStatus).toBe(fetchStatusBefore);
    expect(stateAfter?.fetchStatus).not.toBe('fetching');
    // dataUpdatedAt may change on setQueryData; the pin is no invalidation/refetch.
    expect(stateAfter?.status).toBe('success');
    void dataUpdatedAtBefore;
    // fetchWorkbenchMedia must not have been re-issued for this page after the patch.
    const callsAfterMount = fetchWorkbenchMock.mock.calls.filter(
      (call) => call[0]?.status === 'missing' && call[0]?.page === 1,
    );
    // With staleTime Infinity + seeded cache, mount may still not call; assert zero post-patch growth.
    const callCountAtIdle = fetchWorkbenchMock.mock.calls.length;
    act(() => {
      patchRowComplete(client, key, 2);
    });
    expect(fetchWorkbenchMock.mock.calls.length).toBe(callCountAtIdle);
    void callsAfterMount;
  });

  it('fetching branch still reports Updating media queue…', async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: 0 },
        mutations: { retry: false },
      },
    });
    let resolveFetch: (value: WorkbenchMediaResponse) => void = () => undefined;
    fetchWorkbenchMock.mockImplementation(
      () =>
        new Promise<WorkbenchMediaResponse>((resolve) => {
          resolveFetch = resolve;
        }),
    );

    renderProvider(client, '/?status=missing');
    expect(screen.getByTestId('status-message').textContent).toBe('Updating media queue…');

    await act(async () => {
      resolveFetch({ items: [makeItem(1)], total: 1, totalPages: 1 });
      await Promise.resolve();
    });
    await waitForIdleStatus();
  });

  it('error branch still reports Unable to load media…', async () => {
    const client = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: 0 },
        mutations: { retry: false },
      },
    });
    fetchWorkbenchMock.mockRejectedValue(new Error('network down'));
    renderProvider(client, '/?status=missing');
    await waitFor(() => {
      expect(screen.getByTestId('status-message').textContent).toBe(
        'Unable to load media. Please try again.',
      );
    });
  });

  it('empty branch: generic and search-specific messages unchanged', async () => {
    const client = buildClient();
    seedPage(client, { items: [], total: 0, status: 'missing' });
    renderProvider(client, '/?status=missing');
    let status = await waitForIdleStatus();
    expect(status.textContent).toBe('No media items match the current filters.');

    cleanup();

    const clientSearch = buildClient();
    seedPage(clientSearch, { items: [], total: 0, status: 'missing', search: 'bridge' });
    renderProvider(clientSearch, '/?status=missing&s=bridge');
    status = await waitForIdleStatus();
    expect(status.textContent).toBe('No media found for “bridge”.');
  });
});
