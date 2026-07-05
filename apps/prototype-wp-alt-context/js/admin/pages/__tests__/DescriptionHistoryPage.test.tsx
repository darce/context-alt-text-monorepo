import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DescriptionHistoryPage } from '../DescriptionHistoryPage';
import { correctDescriptionHistoryItem, fetchDescriptionHistory } from '../../api/describeApi';

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
  };
});

const renderPage = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <DescriptionHistoryPage />
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

describe('DescriptionHistoryPage', () => {
  const fetchHistoryMock = vi.mocked(fetchDescriptionHistory);
  const correctHistoryMock = vi.mocked(correctDescriptionHistoryItem);

  beforeEach(() => {
    vi.clearAllMocks();
    fetchHistoryMock.mockResolvedValue({ total: 1, items: [historyItem] });
    correctHistoryMock.mockImplementation(async (_mediaId, altText) => ({
      ...historyItem,
      current_alt_text: altText,
      human_edit: {
        alt_text: altText,
        edited_at: '2026-07-04 12:00:00',
        user_id: 7,
      },
    }));
  });

  it('renders generated history with provenance and current alt text', async () => {
    renderPage();

    expect(await screen.findByText('Bridge')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Description Review History' })).toBeInTheDocument();
    expect(screen.getByText('A bridge over water.')).toBeInTheDocument();
    expect(screen.getAllByText('Bridge at dusk')).toHaveLength(2);
    expect(screen.getByText('microsoft/Florence-2-base-ft')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
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
});
