import type { QueryClient } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { __ } from '@wordpress/i18n';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { QueueDraftCell } from '../QueueDraftCell';
import {
  applyDescribeRunDrafts,
  correctDescriptionHistoryItem,
  DESCRIPTION_CORRECTION_CODE,
} from '../../../api/describeApi';
import { buildTestQueryClient, createQueryWrapper } from '../../../test-utils/queryClient';

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

const renderCell = (element: ReactElement, client = buildTestQueryClient()) => ({
  client,
  ...render(element, { wrapper: createQueryWrapper(client) }),
});

describe('QueueDraftCell', () => {
  let client: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = buildTestQueryClient();
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
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." autoFocus />, client);

    expect(screen.getByRole('button', { name: /^accept$/i })).toHaveFocus();
    expect(screen.getByRole('button', { name: /^dismiss$/i })).not.toHaveFocus();
  });

  it('does not claim focus on mount without autoFocus (table rows)', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);

    expect(screen.getByRole('button', { name: /^accept$/i })).not.toHaveFocus();
    expect(document.activeElement).toBe(document.body);
  });

  it('lands programmatic focus on Edit draft when the draft is not committable [WBUX-5]', () => {
    renderCell(<QueueDraftCell mediaId={71} draftText="   " autoFocus />, client);

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

  it.each(['Accept', 'Edit-save'] as const)('does not write or release a refused row claim for %s', async (action) => {
    const onCommitStart = vi.fn(() => false);
    const onCommitEnd = vi.fn();
    renderCell(
      <QueueDraftCell mediaId={71} draftText="A flower." onCommitStart={onCommitStart} onCommitEnd={onCommitEnd} />,
      client,
    );
    if (action === 'Edit-save') {
      fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'My reviewed flower draft.' } });
    }
    fireEvent.click(screen.getByRole('button', { name: action === 'Accept' ? /^accept$/i : /^save alt text$/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/save is in progress/i);
    expect(onCommitStart).toHaveBeenCalledTimes(1);
    expect(onCommitEnd).not.toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
    if (action === 'Edit-save') {
      expect(screen.getByRole('textbox')).toHaveValue('My reviewed flower draft.');
    } else {
      expect(screen.getByText('A flower.')).toBeInTheDocument();
    }
  });

  it('blocks same-tick duplicate writes even for a standalone cell', async () => {
    correctMock.mockImplementation(() => new Promise(() => undefined));
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);
    const accept = screen.getByRole('button', { name: /^accept$/i });
    // Both clicks arrive before React paints disabled/isPending.
    act(() => {
      accept.click();
      accept.click();
    });
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
  });

  it('preserves the edit buffer and associates a stale-baseline alert with the textarea', () => {
    const { rerender } = renderCell(<QueueDraftCell mediaId={71} draftText="A flower." committedAlt={null} />, client);
    fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
    const field = screen.getByRole('textbox');
    fireEvent.change(field, { target: { value: 'My reviewed flower draft.' } });
    rerender(<QueueDraftCell mediaId={71} draftText="A flower." committedAlt="Human alt" />);
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    expect(correctMock).not.toHaveBeenCalled();
    expect(field).toHaveValue('My reviewed flower draft.');
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(field).toHaveAttribute('aria-describedby', screen.getByRole('alert').id);
    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));
    expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus();
    // Cancel/Edit must not silently make this same stale draft committable.
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/changed/i);
    expect(correctMock).not.toHaveBeenCalled();
  });

  it('allows a standalone cell without committedAlt to retry a partial write', async () => {
    correctMock.mockRejectedValueOnce(
      new Error(
        JSON.stringify({
          code: DESCRIPTION_CORRECTION_CODE.PARTIAL,
          message: 'Alt was saved but correction history failed.',
          data: { status: 500, stored_alt_text: 'A flower.', is_decorative: false },
        }),
      ),
    );
    renderCell(<QueueDraftCell mediaId={71} draftText="A flower." />, client);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await screen.findByRole('alert');
    await waitFor(() => expect(screen.getByRole('button', { name: /^accept$/i })).not.toBeDisabled());
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
});
