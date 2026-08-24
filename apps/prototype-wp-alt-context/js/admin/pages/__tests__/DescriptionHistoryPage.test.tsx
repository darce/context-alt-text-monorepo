import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DescriptionHistoryPage } from '../DescriptionHistoryPage';
import {
  correctDescriptionHistoryItem,
  fetchDescribeRunItems,
  fetchDescriptionHistory,
  RECOVERY_KIND,
  type DescriptionHistoryItem,
} from '../../api/describeApi';
import { mediaStatsMissingQueryKey, mediaStatsTotalQueryKey } from '../../hooks/useMediaStats';
import { queryKeys } from '../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';

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

vi.mock('../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/describeApi')>('../../api/describeApi');
  return {
    ...actual,
    fetchDescriptionHistory: vi.fn(),
    correctDescriptionHistoryItem: vi.fn(),
    fetchDescribeRunItems: vi.fn(),
    applyDescribeRunDrafts: vi.fn(),
  };
});

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const renderPage = (
  initialEntries: string[] = ['/description-history'],
  queryClient: QueryClient = buildClient(),
) => ({
  queryClient,
  ...render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <DescriptionHistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  ),
});

// Annotated so human_edit widens to DescriptionHistoryHumanEdit | null: an
// inferred `null` makes every derived fixture unable to supply a human edit.
const historyItem: DescriptionHistoryItem = {
  media_id: 42,
  title: 'Bridge',
  mime_type: 'image/jpeg',
  current_alt_text: 'Bridge at dusk',
  generated_alt_text: 'A bridge over water.',
  provenance: {
    tenant_id: 'tenant-1',
    media_id: 42,
    image_hash: 'sha256:abc',
    context_hash: 'ctx',
    adapter: 'local_cpu',
    model_id: 'microsoft/Florence-2-base-ft',
    model_version: 'florence-2-base-ft',
    prompt_or_task_version: 'more_detailed_caption+od.b3.v1',
    visual_facts: { caption: 'A red flower.', objects: ['flower'], ocr_text: null },
    alt_text_draft: 'A bridge over water.',
    context_used: { sources: [], applied: false },
    provider_disclosure: { provider: 'local', left_service_boundary: false },
    cached: false,
    duration_ms: 13800,
    retention_class: 'retain_all',
  },
  human_edit: null,
  run_status: {
    status: 'completed',
    updated_at: '2026-07-04 11:00:00',
  },
  is_decorative: false,
};

const failedHistoryItem = {
  ...historyItem,
  media_id: 84,
  title: 'Portrait',
  current_alt_text: 'Portrait alt text',
  generated_alt_text: 'A studio portrait.',
  run_status: {
    status: 'failed',
    updated_at: '2026-07-04 11:05:00',
  },
};

/** Seed a workbench missing-status page so history corrections can be checked for row reconcile. */
const workbenchMissingPageKey = queryKeys.media.workbenchPage({
  page: 1,
  perPage: 20,
  status: 'missing',
});

const seedWorkbenchCache = (
  client: QueryClient,
  altText: string | null = 'Bridge at dusk',
  status: 'missing' | 'complete' = 'missing',
): WorkbenchMediaResponse => {
  const page: WorkbenchMediaResponse = {
    items: [
      {
        id: 42,
        title: 'Bridge',
        status,
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
  };
  client.setQueryData(workbenchMissingPageKey, page);
  return page;
};

describe('DescriptionHistoryPage', () => {
  const fetchHistoryMock = vi.mocked(fetchDescriptionHistory);
  const correctHistoryMock = vi.mocked(correctDescriptionHistoryItem);
  const fetchRunItemsMock = vi.mocked(fetchDescribeRunItems);

  beforeEach(() => {
    vi.clearAllMocks();
    fetchHistoryMock.mockResolvedValue({ total: 1, items: [historyItem] });
    correctHistoryMock.mockImplementation((_mediaId, altText) =>
      Promise.resolve({
        ...historyItem,
        current_alt_text: altText,
        human_edit: {
          alt_text: altText,
          edited_at: '2026-07-04 12:00:00',
          user_id: 7,
        },
      }),
    );
  });

  it('renders generated history with provenance and current alt text', async () => {
    renderPage();

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    // The visible hero title is now a <p> (WordPress shell owns the page's only
    // <h1>, ORCH-UX-UI-BR-23); assert via the section's accessible name so the
    // test still fails if the preserved id/aria-labelledby link is broken.
    expect(screen.getByRole('region', { name: 'Description Runs' })).toBeInTheDocument();
    expect(screen.getByText('A bridge over water.')).toBeInTheDocument();
    expect(screen.getAllByText('Bridge at dusk')).toHaveLength(2);
    expect(screen.getByText('microsoft/Florence-2-base-ft')).toBeInTheDocument();
    expect(screen.getAllByText('completed')).toHaveLength(2);
    // No recovery line when recovered_from is absent / none.
    expect(screen.queryByTestId('acx-history-recovery')).not.toBeInTheDocument();
  });

  it('keeps the hero and live status mounted while loading becomes ready [D-16][A11Y-21]', async () => {
    let resolveHistory!: (value: { total: number; items: DescriptionHistoryItem[] }) => void;
    fetchHistoryMock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveHistory = resolve;
      }),
    );

    const { container } = renderPage();

    expect(container.querySelector('.acx-history__hero')).toBeInTheDocument();
    expect(screen.getByText('Review')).toBeInTheDocument();
    expect(screen.getByText('Review generated alt text, provenance, and human corrections in one workspace.')).toBeInTheDocument();
    const page = screen.getByRole('region', { name: 'Description Runs' });
    expect(page).toHaveAttribute('aria-busy', 'true');
    const liveStatus = screen.getByTestId('acx-description-history-status');
    expect(liveStatus).toHaveAttribute('role', 'status');
    expect(liveStatus).toHaveAttribute('aria-live', 'polite');
    expect(liveStatus).toHaveTextContent('Loading description history...');

    resolveHistory({ total: 1, items: [historyItem] });

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    expect(screen.getByTestId('acx-description-history-status')).toBe(liveStatus);
    expect(liveStatus).toHaveTextContent('Description history ready.');
    expect(page).not.toHaveAttribute('aria-busy');
  });

  /**
   * R23-BR-22 [TEST-15]: history row must surface recovery origin when a foreign
   * recovery occurred. RED under: drop the recovery block from the row (operator
   * still sees only model_id).
   */
  it('renders recovery origin when provenance recovered_from describes a foreign recovery', async () => {
    const originRun = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';
    fetchHistoryMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...historyItem,
          provenance: {
            adapter: 'florence',
            model_id: 'microsoft/Florence-2-base-ft',
            source: 'bulk_describe_run',
            run_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
            alt_text_draft: 'A bridge over water.',
            recovered_from: {
              origin: originRun,
              kind: RECOVERY_KIND.RUN,
              chain: [originRun],
            },
          },
        },
      ],
    });

    renderPage();

    expect(await screen.findByTestId('acx-history-recovery')).toBeInTheDocument();
    expect(screen.getByTestId('acx-history-recovery-icon')).toBeInTheDocument();
    expect(screen.getByTestId('acx-history-recovery-origin')).toHaveTextContent(
      `Recovered from Run ${originRun}`,
    );
  });

  it('renders surface recovery origin with a human label (not raw sentinel)', async () => {
    fetchHistoryMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...historyItem,
          provenance: {
            model_id: 'microsoft/Florence-2-base-ft',
            recovered_from: {
              origin: 'cli',
              kind: RECOVERY_KIND.SURFACE,
              chain: ['cli'],
            },
          },
        },
      ],
    });

    renderPage();

    expect(await screen.findByTestId('acx-history-recovery-origin')).toHaveTextContent(
      'Recovered from CLI generate',
    );
  });

  it('does not render recovery for explicit none kind', async () => {
    fetchHistoryMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...historyItem,
          provenance: {
            model_id: 'microsoft/Florence-2-base-ft',
            recovered_from: {
              origin: null,
              kind: RECOVERY_KIND.NONE,
              chain: [],
            },
          },
        },
      ],
    });

    renderPage();

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    expect(screen.queryByTestId('acx-history-recovery')).not.toBeInTheDocument();
  });

  it('decodes entity-encoded stored alts for display and the correction editor (BR-140)', async () => {
    // Build entity strings via concatenation so JSX/bundler HTML decoding cannot
    // turn `&lt;` into `<` before the test exercises decode-on-read.
    const storedCurrent = 'x ' + '&lt;' + '= y';
    const storedGenerated = 'chart where a ' + '&lt;' + ' b';
    fetchHistoryMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...historyItem,
          current_alt_text: storedCurrent,
          generated_alt_text: storedGenerated,
        },
      ],
    });

    renderPage();

    // Current alt appears in the read column and seeds the correction textarea.
    expect(await screen.findByText('chart where a < b')).toBeInTheDocument();
    const currentColumn = screen.getByRole('heading', { name: 'Current alt text' }).closest('section');
    expect(currentColumn).toHaveTextContent('x <= y');
    // Storage form must not appear as literal entity text in the document.
    expect(currentColumn?.textContent).not.toContain('&lt;');

    const textarea = screen.getByLabelText<HTMLTextAreaElement>('Alt text correction for Bridge');
    // Correction editor seeds from decoded current alt, not the storage form.
    expect(textarea.value).toBe('x <= y');
  });

  it('saves human alt text corrections inline', async () => {
    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'A corrected bridge description.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledWith(42, 'A corrected bridge description.');
    });
    expect(await screen.findAllByText('A corrected bridge description.')).toHaveLength(2);
    expect(screen.getByText('Human edited')).toBeInTheDocument();
  });

  /**
   * Headline [TEST-06][WBUX-5-BR-75]: a successful correction from the history page
   * must patch the workbench media cache row (altText + status), not only HISTORY_QUERY_KEY.
   *
   * Discrimination: before the fix only the history list was patched; a seeded
   * workbench row would keep prior altText and status:'missing'.
   *
   * Predicted RED against unfixed DescriptionHistoryPage (own useMutation, no
   * workbench patch):
   *   expect(row?.altText).toBe('History-page corrected bridge.')
   *   → expected 'History-page corrected bridge.' / received 'Bridge at dusk'
   *   (or status expected 'complete' / received 'missing')
   */
  it('patches workbench media cache altText and status on successful history correction [TEST-06][WBUX-5-BR-75]', async () => {
    const queryClient = buildClient();
    seedWorkbenchCache(queryClient, 'Bridge at dusk', 'missing');
    const before = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    expect(before?.items.find((item) => item.id === 42)?.altText).toBe('Bridge at dusk');
    expect(before?.items.find((item) => item.id === 42)?.status).toBe('missing');

    renderPage(['/description-history'], queryClient);

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'History-page corrected bridge.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledWith(42, 'History-page corrected bridge.');
    });

    // History cache still patches (operator sees updated current alt + human edit).
    expect(await screen.findAllByText('History-page corrected bridge.')).toHaveLength(2);
    expect(screen.getByText('Human edited')).toBeInTheDocument();

    // Behavioural gap: workbench row must also reconcile from server response.
    await waitFor(() => {
      const cached = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
      const row = cached?.items.find((item) => item.id === 42);
      expect(row?.altText).toBe('History-page corrected bridge.');
      expect(row?.status).toBe('complete');
    });

    const after = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    // Sibling untouched; envelope stays server seed (no list invalidate).
    expect(after?.items.find((item) => item.id === 99)?.altText).toBeNull();
    expect(after?.items).toHaveLength(2);
    expect(after?.total).toBe(2);
  });

  it('offers context and a front door from the zero state [D-18][NAV-08]', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 0, items: [] });

    renderPage();

    expect(await screen.findByText('No generated descriptions yet.')).toBeInTheDocument();
    expect(
      screen.getByText('Select images in Review Queue, then describe them to create drafts.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Review Queue' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('shows translated plain-language labels for status enum options [D-17][COG-01][sr-007]', async () => {
    fetchHistoryMock.mockResolvedValue({
      total: 1,
      items: [
        {
          ...historyItem,
          run_status: {
            status: 'completed_with_errors',
            updated_at: '2026-07-04 11:00:00',
          },
        },
      ],
    });

    renderPage();

    const option = await screen.findByRole('option', { name: 'Completed with errors' });
    expect(option).toHaveValue('completed_with_errors');
    expect(screen.queryByRole('option', { name: 'completed_with_errors' })).not.toBeInTheDocument();
  });

  it('filters history by search text and run status', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });

    renderPage();

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    expect(screen.getByText('Portrait')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Search descriptions'), { target: { value: 'portrait' } });

    expect(screen.queryByText('Bridge')).not.toBeInTheDocument();
    expect(screen.getByText('Portrait')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Run status filter'), { target: { value: 'completed' } });

    expect(screen.getByText('No history items match the current filters.')).toBeInTheDocument();
  });

  it('clears search and status filters with one action from filtered-empty [D-18][NAV-08]', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });

    renderPage();

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search descriptions'), { target: { value: 'portrait' } });
    fireEvent.change(screen.getByLabelText('Run status filter'), { target: { value: 'completed' } });
    expect(screen.getByText('No history items match the current filters.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }));

    expect(screen.getByLabelText('Search descriptions')).toHaveValue('');
    expect(screen.getByLabelText('Run status filter')).toHaveValue('all');
    expect(screen.getByText('Bridge')).toBeInTheDocument();
    expect(screen.getByText('Portrait')).toBeInTheDocument();
  });

  it('retains the last good list and shows the refetch error in the shared notice [D-19][HAI-15][RLSE-04]', async () => {
    const queryClient = buildClient();
    fetchHistoryMock
      .mockResolvedValueOnce({ total: 1, items: [historyItem] })
      .mockRejectedValueOnce(new Error('History refresh failed.'));

    renderPage(['/description-history'], queryClient);

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ['description-history'] });
    });

    expect(screen.getByText('Bridge')).toBeInTheDocument();
    const notice = await screen.findByTestId('acx-user-facing-error');
    expect(notice).toHaveAttribute('data-error-kind', 'generic');
    expect(notice).toHaveTextContent('History refresh failed.');
  });

  it('switches to the run-apply surface when a ?run= deep link is present', async () => {
    fetchRunItemsMock.mockResolvedValue({
      run_id: 'run-abc',
      items: [
        { media_id: 71, status: 'completed', alt_text_draft: 'A red flower.', caption: 'A flower.', provenance: null, existing_alt: false },
      ],
    });

    renderPage(['/description-history?run=run-abc']);

    expect(await screen.findByText('Apply generated descriptions')).toBeInTheDocument();
    expect(await screen.findByText('A red flower.')).toBeInTheDocument();
    expect(fetchRunItemsMock).toHaveBeenCalledWith('run-abc');
    // The full-history list query must not fire in run-scoped mode.
    expect(fetchHistoryMock).not.toHaveBeenCalled();
  });

  it('announces a correction failure on the failed row without clearing the draft [WBUX-5-BR-52][RLSE-05][A11Y-21]', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: 'Corrected bridge alt.' , is_decorative: false },
        })}`,
      ),
    );

    renderPage();

    const bridgeTextarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(bridgeTextarea, { target: { value: 'Corrected bridge alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    // Scoped to the row that failed: alert must live inside Bridge's article
    // (a page-level banner would satisfy findByRole but not this pin).
    const bridgeArticle = screen.getByText('Bridge').closest('article');
    expect(bridgeArticle).toBeTruthy();
    expect(bridgeArticle?.querySelector('[role="alert"]')).toBe(alert);

    // Portrait row must not host an alert.
    const portraitArticle = screen.getByText('Portrait').closest('article');
    expect(portraitArticle).toBeTruthy();
    expect(portraitArticle?.querySelector('[role="alert"]')).toBeNull();

    // Draft is the only operator copy — keep it on failure.
    expect(bridgeTextarea).toHaveValue('Corrected bridge alt.');
    // Button left "Saving…" and returned to idle.
    expect(screen.getByRole('button', { name: 'Save correction for Bridge' })).not.toBeDisabled();
  });

  it('uses the localized fallback when a correction rejection has no structured message', async () => {
    correctHistoryMock.mockRejectedValueOnce(new Error('network down'));

    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Still the draft.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not save the alt text. Please try again.');
    expect(textarea).toHaveValue('Still the draft.');
  });

  it('keeps row A failure alert when row B starts saving [RLSE-05]', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });
    const bridgeMessage = 'Bridge correction failed: storage rejected write.';
    let resolvePortrait!: (value: typeof failedHistoryItem) => void;
    const portraitPending = new Promise<typeof failedHistoryItem>((resolve) => {
      resolvePortrait = resolve;
    });

    correctHistoryMock
      .mockRejectedValueOnce(
        new Error(
          `Request to /correction failed (500): ${JSON.stringify({
            code: 'description_correction_failed',
            message: bridgeMessage,
            data: { status: 500 },
          })}`,
        ),
      )
      .mockReturnValueOnce(portraitPending);

    renderPage();

    const bridgeTextarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(bridgeTextarea, { target: { value: 'Bridge draft.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const bridgeArticle = (await screen.findByText('Bridge')).closest('article');
    await waitFor(() => {
      expect(bridgeArticle?.querySelector('[role="alert"]')).toHaveTextContent(bridgeMessage);
    });

    const portraitTextarea = screen.getByLabelText('Alt text correction for Portrait');
    fireEvent.change(portraitTextarea, { target: { value: 'Portrait draft.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Portrait' }));

    // While Portrait is in flight, Bridge's unread failure must still be visible.
    expect(await screen.findByRole('button', { name: 'Saving...' })).toBeInTheDocument();
    expect(bridgeArticle?.querySelector('[role="alert"]')).toHaveTextContent(bridgeMessage);

    resolvePortrait({
      ...failedHistoryItem,
      current_alt_text: 'Portrait draft.',
      human_edit: {
        alt_text: 'Portrait draft.',
        edited_at: '2026-07-04 12:00:00',
        user_id: 7,
      },
    });

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Saving...' })).not.toBeInTheDocument();
    });
    expect(bridgeArticle?.querySelector('[role="alert"]')).toHaveTextContent(bridgeMessage);
  });

  it('shows Saving… on both rows when two corrections stay in flight [TEST-15]', async () => {
    // Pins the mediaId-keyed savingIds map: a scalar savingId is overwritten by
    // the second mutate, so only one row can show "Saving…". Both stay pending
    // so the busy state cannot collapse via resolution order.
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });

    const bridgePending = new Promise<DescriptionHistoryItem>(() => {
      /* never resolves */
    });
    const portraitPending = new Promise<DescriptionHistoryItem>(() => {
      /* never resolves */
    });
    correctHistoryMock.mockReturnValueOnce(bridgePending).mockReturnValueOnce(portraitPending);

    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Bridge concurrent draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    fireEvent.change(screen.getByLabelText('Alt text correction for Portrait'), {
      target: { value: 'Portrait concurrent draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Portrait' }));

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Saving...' })).toHaveLength(2);
    });

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    const portraitArticle = screen.getByText('Portrait').closest('article');
    const bridgeSave = bridgeArticle?.querySelector('button');
    const portraitSave = portraitArticle?.querySelector('button');
    expect(bridgeSave).toHaveTextContent('Saving...');
    expect(portraitSave).toHaveTextContent('Saving...');
    expect(bridgeSave).toBeDisabled();
    expect(portraitSave).toBeDisabled();
    expect(correctHistoryMock).toHaveBeenCalledWith(42, 'Bridge concurrent draft.');
    expect(correctHistoryMock).toHaveBeenCalledWith(84, 'Portrait concurrent draft.');
  });

  /**
   * BR-81 [TEST-06]: saveCorrection must refuse a second same-mediaId write while
   * one is already outstanding. Latent only — the Save button's disabled={isSaving}
   * blocks ordinary double-clicks; this models two events delivered in one tick
   * (same-tick dispatch) so no re-render / disabled intervenes.
   *
   * Predicted RED against unfixed saveCorrection:
   *   expected number of calls: 1
   *   received number of calls: 2
   */
  it('refuses a second same-mediaId save while one request is already in flight [BR-81]', async () => {
    // Hold the mutation open so a missing guard cannot be masked by settle-order.
    correctHistoryMock.mockImplementation(() => new Promise<DescriptionHistoryItem>(() => {
      /* never resolves during this assertion */
    }));

    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Same-tick concurrent draft.' },
    });

    const saveButton = screen.getByRole('button', { name: 'Save correction for Bridge' });

    // Same-tick route: two native clicks inside one act so React batches and the
    // disabled attribute never lands between them. fireEvent.click alone flushes
    // a render after each click and would hit disabled — proving nothing.
    act(() => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    // mutationFn is scheduled asynchronously by react-query; wait until at least
    // one call lands, then assert no duplicate was accepted.
    await waitFor(() => {
      expect(correctHistoryMock.mock.calls.length).toBeGreaterThanOrEqual(1);
    });
    // Brief settle window so a second in-flight call has time to register if the
    // guard is missing (unfixed code reaches 2 within this window).
    await new Promise((resolve) => setTimeout(resolve, 50));

    // Call count is the carrier for "exactly one request" — not button text alone.
    expect(correctHistoryMock).toHaveBeenCalledTimes(1);
    expect(correctHistoryMock).toHaveBeenCalledWith(42, 'Same-tick concurrent draft.');
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
  });

  it('still fires exactly one request for a single save [BR-81]', async () => {
    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Single save draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledTimes(1);
    });
    expect(correctHistoryMock).toHaveBeenCalledWith(42, 'Single save draft.');
    expect(await screen.findAllByText('Single save draft.')).toHaveLength(2);
  });

  it('allows a second sequential save on the same row after the first settles [BR-81]', async () => {
    // Guard must not latch: once busy clears, a later save is a new write.
    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'First sequential draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByRole('button', { name: 'Save correction for Bridge' })).not.toBeDisabled();

    fireEvent.change(screen.getByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Second sequential draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledTimes(2);
    });
    expect(correctHistoryMock).toHaveBeenNthCalledWith(2, 42, 'Second sequential draft.');
  });

  it('allows a retry after a failed save on the same row [BR-81]', async () => {
    // Error path clears busy; a refused-start guard must not block legitimate retry.
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_failed',
          message: 'First attempt failed.',
          data: { status: 500 },
        })}`,
      ),
    );

    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Retry draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('First attempt failed.');
    expect(correctHistoryMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledTimes(2);
    });
    expect(correctHistoryMock).toHaveBeenNthCalledWith(2, 42, 'Retry draft.');
    expect(await screen.findAllByText('Retry draft.')).toHaveLength(2);
  });

  it('shows distinct durable alerts when two rows fail sequentially [RLSE-05]', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });
    const bridgeMessage = 'Bridge-only failure message.';
    const portraitMessage = 'Portrait-only failure message.';

    correctHistoryMock
      .mockRejectedValueOnce(
        new Error(
          `Request to /correction failed (500): ${JSON.stringify({
            code: 'description_correction_failed',
            message: bridgeMessage,
            data: { status: 500 },
          })}`,
        ),
      )
      .mockRejectedValueOnce(
        new Error(
          `Request to /correction failed (500): ${JSON.stringify({
            code: 'description_correction_failed',
            message: portraitMessage,
            data: { status: 500 },
          })}`,
        ),
      );

    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Bridge draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(screen.getByText('Bridge').closest('article')?.querySelector('[role="alert"]')).toHaveTextContent(
        bridgeMessage,
      );
    });

    fireEvent.change(screen.getByLabelText('Alt text correction for Portrait'), {
      target: { value: 'Portrait draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Portrait' }));

    await waitFor(() => {
      expect(screen.getByText('Portrait').closest('article')?.querySelector('[role="alert"]')).toHaveTextContent(
        portraitMessage,
      );
    });

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    const portraitArticle = screen.getByText('Portrait').closest('article');
    expect(bridgeArticle?.querySelector('[role="alert"]')).toHaveTextContent(bridgeMessage);
    expect(portraitArticle?.querySelector('[role="alert"]')).toHaveTextContent(portraitMessage);
    expect(bridgeArticle?.querySelector('[role="alert"]')?.textContent).not.toBe(
      portraitArticle?.querySelector('[role="alert"]')?.textContent,
    );
  });

  it('clears only the retried row alert on success; sibling alert stays [RLSE-05]', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 2, items: [historyItem, failedHistoryItem] });
    const bridgeMessage = 'Bridge still failed first time.';
    const portraitMessage = 'Portrait failed and stays failed.';

    correctHistoryMock
      .mockRejectedValueOnce(
        new Error(
          `Request to /correction failed (500): ${JSON.stringify({
            code: 'description_correction_failed',
            message: bridgeMessage,
            data: { status: 500 },
          })}`,
        ),
      )
      .mockRejectedValueOnce(
        new Error(
          `Request to /correction failed (500): ${JSON.stringify({
            code: 'description_correction_failed',
            message: portraitMessage,
            data: { status: 500 },
          })}`,
        ),
      )
      .mockImplementationOnce((_mediaId, altText) =>
        Promise.resolve({
          ...historyItem,
          current_alt_text: altText,
          human_edit: {
            alt_text: altText,
            edited_at: '2026-07-04 12:30:00',
            user_id: 7,
          },
        }),
      );

    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Bridge draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));
    await screen.findByText(bridgeMessage);

    fireEvent.change(screen.getByLabelText('Alt text correction for Portrait'), {
      target: { value: 'Portrait draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Portrait' }));
    await screen.findByText(portraitMessage);

    // Retry Bridge only — success must clear Bridge's alert and leave Portrait's.
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(screen.getByText('Bridge').closest('article')?.querySelector('[role="alert"]')).toBeNull();
      expect(screen.getByText('Portrait').closest('article')?.querySelector('[role="alert"]')).toHaveTextContent(
        portraitMessage,
      );
    });
  });

  it('updates Current alt text on description_correction_partial while keeping the alert [RLSE-04]', async () => {
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: 'Partial-saved bridge alt.' , is_decorative: false },
        })}`,
      ),
    );

    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Partial-saved bridge alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    // Cache patched from stored_alt_text: "Current alt text" shows server value.
    const bridgeArticle = screen.getByText('Bridge').closest('article');
    expect(bridgeArticle).toBeTruthy();
    // Draft textarea + current alt column both hold the new text.
    expect(bridgeArticle).toHaveTextContent('Partial-saved bridge alt.');
    expect(bridgeArticle).not.toHaveTextContent('Bridge at dusk');
    expect(textarea).toHaveValue('Partial-saved bridge alt.');
  });

  it('PARTIAL patches history cache is_decorative from server when present [A-03][rg-015][TEST-15]', async () => {
    // Production spreads is_decorative onto the history row when the PARTIAL
    // payload carries it. Without this pin the suite stayed green if that
    // spread were dropped. Seed false; server true is the only way the row flips.
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: {
            status: 500,
            stored_alt_text: 'Partial-saved bridge alt.',
            is_decorative: true,
          },
        })}`,
      ),
    );

    const queryClient = buildClient();
    renderPage(['/description-history'], queryClient);

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Partial-saved bridge alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await screen.findByRole('alert');

    await waitFor(() => {
      const history = queryClient.getQueryData<{
        items: DescriptionHistoryItem[];
      }>(['description-history']);
      const row = history?.items.find((item) => item.media_id === 42);
      expect(row?.current_alt_text).toBe('Partial-saved bridge alt.');
      expect(row?.is_decorative).toBe(true);
    });
  });

  it('patches Current alt text with server stored_alt_text when it differs from the request [S1][rg-015]', async () => {
    // Decisive fixture: submitted text differs from what storage holds.
    const submitted = '  <em>Sunset</em> over the bay  ';
    const stored = 'Sunset over the bay';
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: stored , is_decorative: false },
        })}`,
      ),
    );

    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: submitted } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    expect(bridgeArticle).toBeTruthy();
    // Scope to the "Current alt text" column — the draft textarea still holds
    // the raw request (operator's only copy) and must not pollute this pin.
    const currentAltHeading = Array.from(bridgeArticle?.querySelectorAll('h3') ?? []).find(
      (h) => h.textContent === 'Current alt text',
    );
    const currentAltText = currentAltHeading?.parentElement?.querySelector('p');
    expect(currentAltText).toHaveTextContent(stored);
    expect(currentAltText?.textContent).not.toContain('<em>');
    expect(currentAltText).not.toHaveTextContent('Bridge at dusk');
    // Draft keeps the operator's typed value (only copy of their input).
    expect(textarea).toHaveValue(submitted);
  });

  it('does not patch Current alt text when partial lacks stored_alt_text; alert still shows [S1][RLSE-05]', async () => {
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500 },
        })}`,
      ),
    );

    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: '  <em>Would fabricate</em>  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    const currentAltHeading = Array.from(bridgeArticle?.querySelectorAll('h3') ?? []).find(
      (h) => h.textContent === 'Current alt text',
    );
    const currentAltText = currentAltHeading?.parentElement?.querySelector('p');
    // Stale-but-real prior value; request body never written into the column.
    expect(currentAltText).toHaveTextContent('Bridge at dusk');
    expect(currentAltText?.textContent).not.toContain('<em>');
    expect(textarea).toHaveValue('  <em>Would fabricate</em>  ');
  });

  it('patches Current alt text to empty when partial reports stored_alt_text: "" [TEST-15]', async () => {
    // Empty string is a legitimate stored alt (sanitize_text_field of a blank
    // correction). The guard must be `=== null`, not truthiness: `if (!storedAltText)`
    // would skip reconciliation and leave the operator reading the prior text.
    const submitted = '  <em></em>  ';
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: '' , is_decorative: false },
        })}`,
      ),
    );

    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: submitted } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    const currentAltHeading = Array.from(bridgeArticle?.querySelectorAll('h3') ?? []).find(
      (h) => h.textContent === 'Current alt text',
    );
    const currentAltText = currentAltHeading?.parentElement?.querySelector('p');
    // Server holds blank alt → column must not keep the pre-correction text.
    expect(currentAltText).not.toHaveTextContent('Bridge at dusk');
    // Empty current_alt_text renders the empty placeholder, not leftover markup.
    expect(currentAltText).toHaveTextContent('No alt text saved.');
    expect(currentAltText?.textContent).not.toContain('<em>');
    // Draft keeps the operator's only copy of the typed input.
    expect(textarea).toHaveValue(submitted);
  });

  it('does not patch Current alt text on description_correction_failed', async () => {
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_failed',
          message: 'Could not save the alt text correction.',
          data: { status: 500 },
        })}`,
      ),
    );

    renderPage();

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Would-be bridge alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the alt text correction.');

    // Current alt column must still show the pre-failure value.
    const bridgeArticle = screen.getByText('Bridge').closest('article');
    expect(bridgeArticle).toHaveTextContent('Bridge at dusk');
    // Draft is kept; it is not the same as the current-alt column source after a total fail.
    expect(textarea).toHaveValue('Would-be bridge alt.');
  });

  it('invalidates the missing-alt stats probe after a successful history correction [BR-124]', async () => {
    // History-page corrections must refresh dashboard coverage; only the shared
    // missing probe (not media.all, not the total probe) [BR-124][BR-77].
    // Exactly once: invalidateMediaStats lives in the hook — page must not
    // double-fire after consuming useCorrectMediaAlt [WBUX-5-BR-75].
    const { queryClient } = renderPage();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'A corrected bridge description.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledWith(42, 'A corrected bridge description.');
    });
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: mediaStatsMissingQueryKey });
    });
    const missingProbeCalls = invalidateSpy.mock.calls.filter(
      (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: mediaStatsMissingQueryKey }),
    );
    expect(missingProbeCalls).toHaveLength(1);
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

  it('does not refresh stats counters on a failed history correction [BR-124]', async () => {
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_failed',
          message: 'Could not save the alt text correction.',
          data: { status: 500 },
        })}`,
      ),
    );
    const { queryClient } = renderPage();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Would-be bridge alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the alt text correction.');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(
      invalidateSpy.mock.calls.some(
        (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: mediaStatsMissingQueryKey }),
      ),
    ).toBe(false);
  });

  /**
   * Partial from the history page must reconcile BOTH caches from stored_alt_text
   * and still raise the per-row durable alert [WBUX-5-BR-75][RLSE-04][RLSE-05].
   * Discrimination: before the shared hook, only HISTORY_QUERY_KEY was patched.
   */
  it('partial failure from history reconciles history and workbench caches from stored_alt_text [WBUX-5-BR-75]', async () => {
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    const stored = 'Partial-from-history stored alt.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: stored , is_decorative: false },
        })}`,
      ),
    );

    const queryClient = buildClient();
    seedWorkbenchCache(queryClient, 'Bridge at dusk', 'missing');
    renderPage(['/description-history'], queryClient);

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Partial-from-history stored alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    expect(bridgeArticle?.querySelector('[role="alert"]')).toBe(alert);
    // History current-alt column reflects server stored value.
    const currentAltHeading = Array.from(bridgeArticle?.querySelectorAll('h3') ?? []).find(
      (h) => h.textContent === 'Current alt text',
    );
    expect(currentAltHeading?.parentElement?.querySelector('p')).toHaveTextContent(stored);
    expect(textarea).toHaveValue('Partial-from-history stored alt.');

    // Workbench row also reconciles (the pre-fix gap).
    await waitFor(() => {
      const cached = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
      const row = cached?.items.find((item) => item.id === 42);
      expect(row?.altText).toBe(stored);
      expect(row?.status).toBe('complete');
    });
    const after = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    expect(after?.items.find((item) => item.id === 99)?.altText).toBeNull();
    expect(after?.total).toBe(2);
  });

  it('partial without stored_alt_text leaves history and workbench caches untouched; alert still shows [WBUX-5-BR-75]', async () => {
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500 },
        })}`,
      ),
    );

    const queryClient = buildClient();
    seedWorkbenchCache(queryClient, 'Bridge at dusk', 'missing');
    const workbenchBefore = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    renderPage(['/description-history'], queryClient);

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: '  <em>Would fabricate</em>  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    const currentAltHeading = Array.from(bridgeArticle?.querySelectorAll('h3') ?? []).find(
      (h) => h.textContent === 'Current alt text',
    );
    expect(currentAltHeading?.parentElement?.querySelector('p')).toHaveTextContent('Bridge at dusk');
    expect(textarea).toHaveValue('  <em>Would fabricate</em>  ');

    const workbenchAfter = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    expect(workbenchAfter).toBe(workbenchBefore);
    expect(workbenchAfter?.items.find((item) => item.id === 42)?.altText).toBe('Bridge at dusk');
    expect(workbenchAfter?.items.find((item) => item.id === 42)?.status).toBe('missing');
  });

  it('total failure from history touches neither cache and still raises the alert [WBUX-5-BR-75]', async () => {
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_failed',
          message: 'Could not save the alt text correction.',
          data: { status: 500 },
        })}`,
      ),
    );

    const queryClient = buildClient();
    seedWorkbenchCache(queryClient, 'Bridge at dusk', 'missing');
    const workbenchBefore = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    renderPage(['/description-history'], queryClient);

    const textarea = await screen.findByLabelText('Alt text correction for Bridge');
    fireEvent.change(textarea, { target: { value: 'Would-be bridge alt.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save the alt text correction.');

    const bridgeArticle = screen.getByText('Bridge').closest('article');
    expect(bridgeArticle).toHaveTextContent('Bridge at dusk');
    expect(textarea).toHaveValue('Would-be bridge alt.');

    const workbenchAfter = queryClient.getQueryData<WorkbenchMediaResponse>(workbenchMissingPageKey);
    expect(workbenchAfter).toBe(workbenchBefore);
    expect(workbenchAfter?.items.find((item) => item.id === 42)?.altText).toBe('Bridge at dusk');
    expect(workbenchAfter?.items.find((item) => item.id === 42)?.status).toBe('missing');
  });

  /**
   * [BR-81] item 7: a refused start must not clear correctionErrors.
   *
   * Production never holds busy+error for the same mediaId at once (accepted
   * start clears the row error; failure clears busy). The observable pin is:
   * after a durable failure, a same-tick double-click enqueues exactly one
   * retry request — the second start returns before any state writes, so it
   * cannot re-enter the clear-error path or fire a second network call.
   * Discrimination: missing ref guard → 2 retry calls (3 total with the fail).
   */
  it('refused start does not clear correctionErrors and enqueues no extra request [BR-81]', async () => {
    const durableMessage = 'Prior failure still unread.';
    correctHistoryMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_failed',
          message: durableMessage,
          data: { status: 500 },
        })}`,
      ),
    );

    renderPage();

    fireEvent.change(await screen.findByLabelText('Alt text correction for Bridge'), {
      target: { value: 'Retry then refuse draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction for Bridge' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(durableMessage);
    expect(correctHistoryMock).toHaveBeenCalledTimes(1);

    // Next request hangs so busy stays set after the accepted half of the pair.
    correctHistoryMock.mockImplementationOnce(
      () => new Promise<DescriptionHistoryItem>(() => {
        /* never resolves */
      }),
    );

    const saveButton = screen.getByRole('button', { name: 'Save correction for Bridge' });
    // Same-tick: first accepted (clears this row's error, sets busy, mutates);
    // second refused at the ref guard — no third request, no further state write.
    act(() => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    await waitFor(() => {
      expect(correctHistoryMock).toHaveBeenCalledTimes(2);
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(correctHistoryMock).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled();
  });
});
