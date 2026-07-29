import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DescriptionHistoryPage } from '../DescriptionHistoryPage';
import {
  correctDescriptionHistoryItem,
  fetchDescribeRunItems,
  fetchDescriptionHistory,
  type DescriptionHistoryItem,
} from '../../api/describeApi';
import { mediaStatsMissingQueryKey, mediaStatsTotalQueryKey } from '../../hooks/useMediaStats';
import { queryKeys } from '../../api/queryKeys';

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
    expect(screen.getByRole('heading', { name: 'Description Review History' })).toBeInTheDocument();
    expect(screen.getByText('A bridge over water.')).toBeInTheDocument();
    expect(screen.getAllByText('Bridge at dusk')).toHaveLength(2);
    expect(screen.getByText('microsoft/Florence-2-base-ft')).toBeInTheDocument();
    expect(screen.getAllByText('completed')).toHaveLength(2);
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

  it('shows an empty state when no generated descriptions exist', async () => {
    fetchHistoryMock.mockResolvedValue({ total: 0, items: [] });

    renderPage();

    expect(await screen.findByText('No generated descriptions yet.')).toBeInTheDocument();
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
          data: { status: 500, stored_alt_text: 'Corrected bridge alt.' },
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
          data: { status: 500, stored_alt_text: 'Partial-saved bridge alt.' },
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
          data: { status: 500, stored_alt_text: stored },
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
          data: { status: 500, stored_alt_text: '' },
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
});
