import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { __ } from '@wordpress/i18n';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueueDraftCell } from '../QueueDraftCell';
import { applyDescribeRunDrafts, correctDescriptionHistoryItem } from '../../../api/describeApi';

vi.mock('@wordpress/i18n', () => ({
  __: vi.fn((text: string) => text),
  sprintf: vi.fn((format: string, ...args: (string | number)[]) => {
    let sequentialIndex = 0;
    const interpolated = format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
    return `⟦${interpolated}⟧`;
  }),
}));

vi.mock('../../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../../api/describeApi')>('../../../api/describeApi');
  return {
    ...actual,
    correctDescriptionHistoryItem: vi.fn(),
    applyDescribeRunDrafts: vi.fn(),
  };
});

const correctMock = vi.mocked(correctDescriptionHistoryItem);
const applyRunMock = vi.mocked(applyDescribeRunDrafts);

const buildClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const renderCell = (element: ReactElement, client = buildClient()) => ({
  client,
  ...render(<QueryClientProvider client={client}>{element}</QueryClientProvider>),
});

describe('QueueDraftCell', () => {
  let client: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = buildClient();
    correctMock.mockImplementation((mediaId, altText) =>
      Promise.resolve({
        media_id: mediaId,
        title: 'Flower',
        mime_type: 'image/jpeg',
        current_alt_text: altText,
        generated_alt_text: 'A flower.',
        provenance: null,
        human_edit: { alt_text: altText, edited_at: '2026-09-18 12:00:00', user_id: 7 },
        run_status: null,
        is_decorative: false,
      }),
    );
  });

  afterEach(() => {
    void client.cancelQueries();
    client.clear();
    cleanup();
  });

  it('previews the draft beside Accept, Edit, and Dismiss [INT-07][NAV-06]', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    expect(screen.getByText('A flower.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^accept$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^edit draft$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^dismiss$/i })).toBeInTheDocument();
    expect(correctMock).not.toHaveBeenCalled();
    expect(applyRunMock).not.toHaveBeenCalled();
  });

  it('qualifies action names with the media title when provided [A11Y-04]', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." title="Garden path" />, client);

    expect(screen.getByRole('button', { name: '⟦Accept draft for Garden path⟧' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '⟦Edit draft for Garden path⟧' })).toBeInTheDocument();
    expect(vi.mocked(__)).toHaveBeenCalledWith('Accept draft for %s', 'alt-context');
    expect(vi.mocked(__)).toHaveBeenCalledWith('Edit draft for %s', 'alt-context');
  });

  it('applies the previewed draft with one correction write and never bulk-applies [HAI-04][rg-002]', async () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(71, 'A flower.');
    expect(applyRunMock).not.toHaveBeenCalled();
  });

  it('edits the draft and applies the edited text, not the seed', async () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
    const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: /edit draft alt text/i });
    expect(field.value).toBe('A flower.');

    fireEvent.change(field, { target: { value: 'A red flower in morning light.' } });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(71, 'A red flower in morning light.');
    expect(applyRunMock).not.toHaveBeenCalled();
  });

  it('dismisses without writing and keeps Dismiss in tab order [HAI-04]', () => {
    const onDismiss = vi.fn();
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." onDismiss={onDismiss} />, client);

    const dismiss = screen.getByRole('button', { name: /^dismiss$/i });
    expect(dismiss).not.toHaveAttribute('tabindex', '-1');

    fireEvent.click(dismiss);

    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(correctMock).not.toHaveBeenCalled();
    expect(applyRunMock).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /^accept$/i })).not.toBeInTheDocument();
  });

  it('lands programmatic focus on Accept for a committable draft, not Dismiss [WBUX-5]', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    expect(screen.getByRole('button', { name: /^accept$/i })).toHaveFocus();
    expect(screen.getByRole('button', { name: /^dismiss$/i })).not.toHaveFocus();
  });

  it('lands programmatic focus on Edit draft when the draft is not committable [WBUX-5]', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="   " />, client);

    expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus();
    expect(screen.getByRole('button', { name: /^accept$/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^dismiss$/i })).not.toHaveFocus();
  });

  it('returns focus to Edit after Cancel edit', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));

    expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus();
    expect(screen.getByRole('button', { name: /^dismiss$/i })).not.toHaveFocus();
  });

  it('does not apply a second time while Accept is in flight [rg-002]', async () => {
    correctMock.mockImplementation(() => new Promise(() => undefined));
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    const busy = await screen.findByRole('button', { name: /accepting draft/i });
    fireEvent.click(busy);

    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(busy).toBeDisabled();
  });
});
