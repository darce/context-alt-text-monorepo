/**
 * Component-level proof of BR-77 fix: a partial on row A must keep its
 * role="alert" and the operator's typed draft after a sibling success on row B.
 *
 * The old pin-store suite only asserted isError on a standalone renderHook —
 * vacuous because the workbench list cannot unmount that hook instance [TEST-17].
 * This test mounts real MediaAltInlineEditor rows driven by the workbench cache
 * (MediaSelectionTableBody row surface), so an invalidateQueries(media.all) +
 * missing-list refetch that drops A actually unmounts the editor and fails.
 *
 * BR-101 companion: also mounts the missing-alt stats probe (perPage:1). Success
 * invalidates that probe; the list page (perPage:20) must stay mounted so row A
 * keeps its alert + draft — proving the stats refresh is key-safe.
 */
import React, { useMemo } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { correctDescriptionHistoryItem } from '../../../api/describeApi';
import { queryKeys } from '../../../api/queryKeys';
import type { WorkbenchMediaItem, WorkbenchMediaResponse } from '../../../api/workbenchMediaApi';
import { mediaStatsMissingQueryKey } from '../../../hooks/useMediaStats';
import { MediaAltInlineEditor } from '../MediaAltInlineEditor';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
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

vi.mock('../../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../../api/describeApi')>('../../../api/describeApi');
  return {
    ...actual,
    correctDescriptionHistoryItem: vi.fn(),
  };
});

const correctMock = vi.mocked(correctDescriptionHistoryItem);

const PARTIAL_MESSAGE =
  'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';

const partialError = (storedAlt: string): Error =>
  new Error(
    `Request to /correction failed (500): ${JSON.stringify({
      code: 'description_correction_partial',
      message: PARTIAL_MESSAGE,
      data: { status: 500, stored_alt_text: storedAlt , is_decorative: false },
    })}`,
  );

const successItem = (mediaId: number, altText: string, title: string) => ({
  media_id: mediaId,
  title,
  mime_type: 'image/jpeg',
  current_alt_text: altText,
  generated_alt_text: null,
  provenance: null,
  human_edit: { alt_text: altText, edited_at: '2026-07-28 12:00:00', user_id: 7 },
  run_status: null,
});

const missingPageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
const PER_PAGE = 20;

const rowA: WorkbenchMediaItem = {
  id: 42,
  title: 'Bridge',
  status: 'missing',
  thumbnailUrl: null,
  altText: null,
  isDecorative: false,
  editUrl: null,
  tags: [],
};

const rowB: WorkbenchMediaItem = {
  id: 99,
  title: 'Other',
  status: 'missing',
  thumbnailUrl: null,
  altText: null,
  isDecorative: false,
  editUrl: null,
  tags: [],
};

/**
 * Minimal workbench list surface: items come from the same query key
 * MediaSelection / useWorkbenchMedia use. If success invalidates media.all and
 * the queryFn returns without A, row A unmounts — which is exactly the defect.
 *
 * statsQueryFn drives the perPage:1 missing probe that useCorrectMediaAlt
 * refreshes on success (BR-101). It must be a different cache entry from the list.
 */
const WorkbenchAltList = ({
  queryFn,
  statsQueryFn,
}: {
  queryFn: () => Promise<WorkbenchMediaResponse>;
  statsQueryFn?: () => Promise<WorkbenchMediaResponse>;
}): React.JSX.Element => {
  const { data } = useQuery({
    queryKey: missingPageKey,
    queryFn,
    staleTime: 0,
  });
  // Optional observer so invalidateMediaStats has an active subscriber to refetch.
  useQuery({
    queryKey: mediaStatsMissingQueryKey,
    queryFn: statsQueryFn ?? (() => Promise.resolve({ items: [], total: 0, totalPages: 1 })),
    staleTime: 5 * 60 * 1000,
    enabled: Boolean(statsQueryFn),
  });
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const envelope = useMemo(
    () => ({
      itemCount: items.length,
      total,
      perPage: PER_PAGE,
    }),
    [items.length, total],
  );

  return (
    <div>
      <p data-testid="envelope-summary">
        items={envelope.itemCount} total={envelope.total} perPage={envelope.perPage}
      </p>
      <table>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} data-testid={`media-row-${item.id}`}>
              <td>
                <span data-testid={`media-title-${item.id}`}>{item.title}</span>
                <MediaAltInlineEditor mediaId={item.id} altText={item.altText ?? null} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const buildClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

describe('MediaAltInlineEditor — sibling success must not destroy partial row A [BR-77]', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps row A mounted with its role=alert and operator draft after sibling B succeeds', async () => {
    // Server truth for the missing-status list: both rows present initially.
    // If media.all is invalidated (old onSuccess), queryFn re-runs. After B
    // succeeds the server would drop fully-corrected B — and would also drop A
    // once its partial alt is stored. Simulate the post-refetch envelope that
    // omits A (the production defect path).
    let bSucceeded = false;
    const queryFn = vi.fn((): Promise<WorkbenchMediaResponse> => {
      if (bSucceeded) {
        // Missing list after sibling success + partial A having stored alt:
        // production class-api excludes both. Old pin store re-spliced A and
        // fabricated items vs total; new code never refetches so this path is
        // only taken if media.all invalidation is re-introduced.
        return Promise.resolve({ items: [], total: 0, totalPages: 1 });
      }
      return Promise.resolve({
        items: [rowA, rowB],
        total: 2,
        totalPages: 1,
      });
    });

    // BR-101: stats probe starts at 7 missing; after B succeeds server would
    // report 6. Success must refetch THIS key without touching the list page.
    const statsQueryFn = vi.fn((): Promise<WorkbenchMediaResponse> => {
      if (bSucceeded) {
        return Promise.resolve({ items: [], total: 6, totalPages: 6 });
      }
      return Promise.resolve({ items: [], total: 7, totalPages: 7 });
    });

    const client = buildClient();
    render(
      <QueryClientProvider client={client}>
        <WorkbenchAltList queryFn={queryFn} statsQueryFn={statsQueryFn} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('media-row-42')).toBeInTheDocument());
    expect(screen.getByTestId('media-row-99')).toBeInTheDocument();
    await waitFor(() => expect(statsQueryFn).toHaveBeenCalled());
    const statsFetchesBefore = statsQueryFn.mock.calls.length;

    // --- Row A: open editor, save → partial ---
    const rowANode = screen.getByTestId('media-row-42');
    fireEvent.click(within(rowANode).getByRole('button', { name: /edit alt text/i }));
    const textareaA = within(rowANode).getByRole<HTMLTextAreaElement>('textbox', { name: /alt text/i });
    fireEvent.change(textareaA, { target: { value: 'Partial-saved alt' } });

    correctMock.mockRejectedValueOnce(partialError('Partial-saved alt'));
    fireEvent.click(within(rowANode).getByRole('button', { name: /^save/i }));

    const alertA = await within(rowANode).findByRole('alert');
    expect(alertA).toHaveTextContent(PARTIAL_MESSAGE);

    // Operator keeps typing a retry draft while the assertive failure is unread.
    const draftAfterPartial = 'Operator retry draft — must survive sibling success';
    fireEvent.change(within(rowANode).getByRole('textbox', { name: /alt text/i }), {
      target: { value: draftAfterPartial },
    });
    expect(within(rowANode).getByRole<HTMLTextAreaElement>('textbox', { name: /alt text/i }).value).toBe(
      draftAfterPartial,
    );

    // --- Row B: full success (the sibling that used to invalidate media.all) ---
    const rowBNode = screen.getByTestId('media-row-99');
    fireEvent.click(within(rowBNode).getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(within(rowBNode).getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Sibling saved' },
    });

    correctMock.mockImplementationOnce((mediaId, altText) => {
      bSucceeded = true;
      return Promise.resolve(successItem(mediaId, altText, 'Other') as never);
    });
    fireEvent.click(within(rowBNode).getByRole('button', { name: /^save/i }));

    await waitFor(() => expect(within(rowBNode).queryByRole('textbox', { name: /alt text/i })).not.toBeInTheDocument());

    // Stats probe must have refetched (BR-101) while list did not (BR-77).
    await waitFor(() => expect(statsQueryFn.mock.calls.length).toBeGreaterThan(statsFetchesBefore));
    expect(client.getQueryData<WorkbenchMediaResponse>(mediaStatsMissingQueryKey)?.total).toBe(6);

    // --- Invariants the pin store claimed to protect but never tested ---
    // 1. Row A still mounted (not dropped by sibling invalidate+refetch).
    expect(screen.getByTestId('media-row-42')).toBeInTheDocument();
    // 2. Assertive partial alert still in the DOM with the partial message.
    expect(within(screen.getByTestId('media-row-42')).getByRole('alert')).toHaveTextContent(PARTIAL_MESSAGE);
    // 3. Operator draft still in the textarea — proves no unmount/remount.
    expect(
      within(screen.getByTestId('media-row-42')).getByRole<HTMLTextAreaElement>('textbox', { name: /alt text/i })
        .value,
    ).toBe(draftAfterPartial);

    // Envelope honesty: total is still server seed (2); items not grown by splice.
    const summary = screen.getByTestId('envelope-summary');
    expect(summary).toHaveTextContent('items=2');
    expect(summary).toHaveTextContent('total=2');
    // queryFn must not have been re-invoked by media.all invalidation after B.
    // Initial mount = 1 call. A re-introduced invalidateQueries(media.all) would
    // refetch and return items=[] total=0 — this test goes RED.
    expect(queryFn).toHaveBeenCalledTimes(1);
  });


  it('envelope total equals server seed and items.length <= perPage after partial then success', async () => {
    const queryFn = vi.fn((): Promise<WorkbenchMediaResponse> =>
      Promise.resolve({
        items: [rowA, rowB],
        total: 2,
        totalPages: 1,
      }),
    );

    const client = buildClient();
    render(
      <QueryClientProvider client={client}>
        <WorkbenchAltList queryFn={queryFn} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('media-row-42')).toBeInTheDocument());

    const rowANode = screen.getByTestId('media-row-42');
    fireEvent.click(within(rowANode).getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(within(rowANode).getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Partial alt' },
    });
    correctMock.mockRejectedValueOnce(partialError('Partial alt'));
    fireEvent.click(within(rowANode).getByRole('button', { name: /^save/i }));
    await within(rowANode).findByRole('alert');

    const rowBNode = screen.getByTestId('media-row-99');
    fireEvent.click(within(rowBNode).getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(within(rowBNode).getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Sibling saved' },
    });
    correctMock.mockResolvedValueOnce(successItem(99, 'Sibling saved', 'Other') as never);
    fireEvent.click(within(rowBNode).getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(within(rowBNode).queryByRole('textbox', { name: /alt text/i })).not.toBeInTheDocument());

    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.total).toBe(2);
    expect(cached?.items.length).toBeLessThanOrEqual(PER_PAGE);
    expect(cached?.items.length).toBe(2);
    // items.length must never exceed total via a re-introduced pin splice when
    // total is 0 (the measured items=1 total=0 fabrication).
    if (cached?.total === 0) {
      expect(cached.items.length).toBe(0);
    }
  });
});

describe('MediaAltInlineEditor — no module pin state across sequential tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('first test: partial on A leaves cache patched for this client only', async () => {
    const queryFn = vi.fn((): Promise<WorkbenchMediaResponse> =>
      Promise.resolve({
        items: [rowA, rowB],
        total: 2,
        totalPages: 1,
      }),
    );
    const client = buildClient();
    render(
      <QueryClientProvider client={client}>
        <WorkbenchAltList queryFn={queryFn} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('media-row-42')).toBeInTheDocument());

    const rowANode = screen.getByTestId('media-row-42');
    fireEvent.click(within(rowANode).getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(within(rowANode).getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Would-leak-if-pinned' },
    });
    correctMock.mockRejectedValueOnce(partialError('Would-leak-if-pinned'));
    fireEvent.click(within(rowANode).getByRole('button', { name: /^save/i }));
    await within(rowANode).findByRole('alert');

    expect(client.getQueryData<WorkbenchMediaResponse>(missingPageKey)?.items.find((i) => i.id === 42)?.altText).toBe(
      'Would-leak-if-pinned',
    );
  });

  it('second test: fresh client has no resurrected phantom row from prior partial', async () => {
    // No _resetPinnedPartialsForTests — module state must not exist.
    // Seed a list that never included 42; a pin-store subscriber would splice it back.
    const queryFn = vi.fn((): Promise<WorkbenchMediaResponse> =>
      Promise.resolve({
        items: [rowB],
        total: 1,
        totalPages: 1,
      }),
    );
    const client = buildClient();
    render(
      <QueryClientProvider client={client}>
        <WorkbenchAltList queryFn={queryFn} />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('media-row-99')).toBeInTheDocument());

    // Force a cache "updated" event the old QueryCache subscriber listened to.
    client.setQueryData<WorkbenchMediaResponse>(missingPageKey, {
      items: [rowB],
      total: 1,
      totalPages: 1,
    });

    expect(screen.queryByTestId('media-row-42')).not.toBeInTheDocument();
    const cached = client.getQueryData<WorkbenchMediaResponse>(missingPageKey);
    expect(cached?.items.find((i) => i.id === 42)).toBeUndefined();
    expect(cached?.total).toBe(1);
    expect(cached?.items.length).toBe(1);
  });
});
