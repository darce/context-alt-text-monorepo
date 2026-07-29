import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DescriptionHistoryPage } from '../DescriptionHistoryPage';
import {
  correctDescriptionHistoryItem,
  fetchDescribeRunItems,
  fetchDescriptionHistory,
} from '../../api/describeApi';

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

const renderPage = (initialEntries: string[] = ['/description-history']) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <DescriptionHistoryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const historyItem = {
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
          data: { status: 500 },
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
});
