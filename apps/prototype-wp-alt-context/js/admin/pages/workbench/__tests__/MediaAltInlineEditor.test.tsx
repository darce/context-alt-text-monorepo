import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MediaAltInlineEditor } from '../MediaAltInlineEditor';
import { correctDescriptionHistoryItem } from '../../../api/describeApi';
import { queryKeys } from '../../../api/queryKeys';

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

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const renderEditor = (element: ReactElement, client = buildClient()) => ({
  client,
  ...render(<QueryClientProvider client={client}>{element}</QueryClientProvider>),
});

describe('MediaAltInlineEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The correction endpoint echoes the saved alt back as the persisted value.
    correctMock.mockImplementation((mediaId, altText) =>
      Promise.resolve({
        media_id: mediaId,
        title: 'Bridge',
        mime_type: 'image/jpeg',
        current_alt_text: altText,
        generated_alt_text: null,
        provenance: null,
        human_edit: { alt_text: altText, edited_at: '2026-07-28 12:00:00', user_id: 7 },
        run_status: null,
      } as never),
    );
  });

  it('renders the current alt text in a read affordance with an edit control', () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    expect(screen.getByText('Bridge at dusk')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /edit alt text/i })).toBeInTheDocument();
  });

  it('exposes the edit control even from the empty (no-alt) zero state [rg-003]', () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText={null} />);

    expect(screen.getByRole('button', { name: /edit alt text/i })).toBeInTheDocument();
  });

  it('opens an editable field seeded with the current alt text', () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));

    const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: /alt text/i });
    expect(field).toBeInTheDocument();
    expect(field.value).toBe('Bridge at dusk');
  });

  it('saves the EDITED alt text (not the seed) via the manual correction endpoint', async () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    // [TEST-15] discrimination: goes red if the editor forwards the seed instead of
    // the edited value, or targets the wrong media id.
    expect(correctMock).toHaveBeenCalledWith(42, 'A stone bridge over a calm river at dusk.');
  });

  it('invalidates the media query tree on save so every projection refetches', async () => {
    const { client } = renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith(expect.objectContaining({ queryKey: queryKeys.media.all })),
    );
  });

  it('returns to the read affordance showing the saved value after a successful save', async () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    // Wait for edit mode to exit first. The editing textarea transiently holds the
    // same draft text during the pending save, so asserting the text before the
    // editor closes would race onto the (about-to-detach) textarea instead of the
    // settled read paragraph.
    await waitFor(() => expect(screen.queryByRole('textbox', { name: /alt text/i })).not.toBeInTheDocument());
    expect(screen.getByText('A stone bridge over a calm river at dusk.')).toBeInTheDocument();
  });

  it('cancels back to the read affordance without persisting an edit', () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Discarded draft.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

    expect(correctMock).not.toHaveBeenCalled();
    expect(screen.getByText('Bridge at dusk')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: /alt text/i })).not.toBeInTheDocument();
  });

  it('restores focus to the Edit control after a successful save [a11y][WBUX-5-S2A-BR-01]', async () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    await waitFor(() => expect(screen.queryByRole('textbox', { name: /alt text/i })).not.toBeInTheDocument());
    // Save must return focus to the Edit control like Cancel does, otherwise focus
    // falls to document.body when the (disabled) Save button detaches.
    expect(screen.getByRole('button', { name: /edit alt text/i })).toHaveFocus();
  });

  it('announces the saved state via a live region [a11y][WBUX-5-S2A-BR-02][WBUX-5-BR-58]', async () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);
    // Always-mounted empty region (BR-32 / BR-58): present before save, no cue yet.
    // Mount-then-mutate is required so aria-live observes a text change; a region
    // that appears with its text is frequently not announced.
    // data-testid disambiguates from MediaAltSuggest's sibling role=status.
    const status = screen.getByTestId('media-alt-inline-editor-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    // Same stable node receives the cue text (not a remount-with-text).
    await waitFor(() => expect(status).toHaveTextContent('Alt text saved.'));
    expect(screen.getByTestId('media-alt-inline-editor-status')).toBe(status);
  });

  it('clears the polite saved cue when re-entering edit [a11y][WBUX-5-BR-58]', async () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const status = screen.getByTestId('media-alt-inline-editor-status');
    await waitFor(() => expect(status).toHaveTextContent('Alt text saved.'));

    // Re-enter edit: the saved cue must retire so it does not sit beside a later
    // Suggest announcement on the same row (asymmetric with Suggest's own retirement).
    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));

    // [TEST-15] discrimination: goes red if enterEditMode stops clearing
    // statusMessage. Assert present-then-empty (not merely absent) so "cleared"
    // is distinguished from "never set". toBeEmptyDOMElement — not toHaveTextContent('').
    expect(status).toBeEmptyDOMElement();
    expect(status).not.toHaveTextContent(/saved/i);
  });

  it('keeps the polite region empty beside a save-failure alert [a11y][WBUX-5-BR-58]', async () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'First save that succeeds.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const status = screen.getByTestId('media-alt-inline-editor-status');
    await waitFor(() => expect(status).toHaveTextContent('Alt text saved.'));

    // Re-enter; enterEditMode clears the cue (primary path). Production also
    // clears in mutate onError so a leftover polite cue cannot sit beside the
    // assertive alert if enter-edit clear is ever skipped (defense-in-depth,
    // mirrors MediaAltSuggest BR-39 / BR-46). This component has no intermediate
    // polite "Saving…" cue, so onError alone is not independently pin-able here.
    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    // Present-then-empty: cue was set above; enter-edit must retire it before the
    // failure path. [TEST-15] goes red if enterEditMode stops clearing.
    expect(status).toBeEmptyDOMElement();

    correctMock.mockRejectedValueOnce(
      new Error('Request to /wp-json/acx/v1/media/42/alt failed (502): <html>proxy-internal-detail</html>'),
    );
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not save/i);

    // Invariant after failure: polite region stays empty (does not re-announce
    // "saved" and does not compete with the assertive alert).
    expect(status).toBeEmptyDOMElement();
    expect(status).not.toHaveTextContent(/saved/i);
  });

  it('retires a saved status message when focus leaves the idle surface [a11y][WBUX-5-BR-58]', async () => {
    renderEditor(
      <>
        <MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />
        <button type="button">Elsewhere</button>
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'A stone bridge over a calm river at dusk.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const status = screen.getByTestId('media-alt-inline-editor-status');
    await waitFor(() => expect(status).toHaveTextContent('Alt text saved.'));
    await waitFor(() => expect(screen.getByRole('button', { name: /edit alt text/i })).toHaveFocus());

    // Leave the surface — the message has been announced; keeping "Alt text saved."
    // forever collides with a later Suggest status on the same row. Blur with
    // relatedTarget so the container's onBlur sees focus exiting (native .focus()
    // on Elsewhere does not reliably populate relatedTarget under jsdom).
    const elsewhere = screen.getByRole('button', { name: /^elsewhere$/i });
    fireEvent.blur(screen.getByRole('button', { name: /edit alt text/i }), {
      relatedTarget: elsewhere,
    });

    // [TEST-15] discrimination: goes red if handleContainerBlur stops clearing
    // status on idle focus-leave, or if the idle surface omits onBlur.
    // Region stays mounted; cue text clears. Present-then-empty, not merely absent.
    await waitFor(() => expect(status).toBeEmptyDOMElement());
    expect(status).not.toHaveTextContent(/saved/i);
  });

  it('resyncs the read view to a prop change that arrived mid-edit, after cancel [WBUX-5-S2A-BR-03]', () => {
    const { client, rerender } = renderEditor(<MediaAltInlineEditor mediaId={42} altText="Old alt" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    // A parent refetch delivers a fresher value while the editor is open.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltInlineEditor mediaId={42} altText="Fresh alt from refetch" />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));

    // Cancel must surface the value that landed during editing, not the stale seed.
    expect(screen.getByText('Fresh alt from refetch')).toBeInTheDocument();
    expect(screen.queryByText('Old alt')).not.toBeInTheDocument();
  });

  it('shows a user-safe error, not the raw HTTP body, when the save fails [error-ux][WBUX-5-S2A-BR-04]', async () => {
    correctMock.mockRejectedValueOnce(
      new Error('Request to /wp-json/acx/v1/media/42/alt failed (502): <html>proxy-internal-detail</html>'),
    );
    renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not save/i);
    expect(alert).not.toHaveTextContent(/wp-json/i);
    expect(alert).not.toHaveTextContent(/proxy-internal-detail/i);
  });
});
