import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { __ } from '@wordpress/i18n';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ALT_COMMIT_CONFLICT_MESSAGE,
  DECORATIVE_IDLE_LABEL,
  MediaAltInlineEditor,
} from '../MediaAltInlineEditor';
import { correctDescriptionHistoryItem } from '../../../api/describeApi';
import { queryKeys } from '../../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../../api/workbenchMediaApi';

vi.mock('@wordpress/i18n', () => ({
  __: vi.fn((text: string) => text),
  // Sentinel wrap so a bare JS concat producing the same English string cannot
  // satisfy the accessible-name assertion [C-04][TEST-15].
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

  it('qualifies the edit control accessible name with the media title [WBUX-5-D-05][A11Y-04][C-04]', () => {
    // Predicted RED: button accessible name is bare "Edit alt text" for every
    // row, so AT element lists cannot tell which image the control belongs to.
    // sprintf mock wraps output in ⟦…⟧ so a raw JS concat of the English phrase
    // cannot satisfy the name query [C-04][TEST-15].
    renderEditor(
      <MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" title="Ornamental border" />,
    );

    const edit = screen.getByRole('button', { name: '⟦Edit alt text for Ornamental border⟧' });
    expect(edit).toBeInTheDocument();
    // Visible label stays the short phrase; title is for AT only.
    expect(edit).toHaveTextContent('Edit alt text');
    // Pin the i18n construct — not merely the rendered English string.
    expect(vi.mocked(__)).toHaveBeenCalledWith('Edit alt text for %s', 'alt-context');
  });

  it('decodes stored entity-encoded alt for the read display and edit seed (BR-140)', () => {
    // Storage form from sanitize_text_field("x <= y"). Build the entity string in
    // JS (not a JSX attribute literal) so the bundler cannot HTML-decode `&lt;`
    // at transform time and short-circuit the test.
    const storedEncoded = 'x ' + '&lt;' + '= y';
    renderEditor(<MediaAltInlineEditor mediaId={42} altText={storedEncoded} />);

    expect(screen.getByText('x <= y')).toBeInTheDocument();
    expect(screen.queryByText(storedEncoded)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: /alt text/i });
    expect(field.value).toBe('x <= y');
  });

  it('exposes the edit control even from the empty (no-alt) zero state [rg-003]', () => {
    renderEditor(<MediaAltInlineEditor mediaId={42} altText={null} />);

    expect(screen.getByRole('button', { name: /edit alt text/i })).toBeInTheDocument();
    expect(screen.getByText('No alt text yet')).toBeInTheDocument();
  });

  it('renders a decorative-specific idle label instead of "No alt text yet" [A11Y-02]', () => {
    // Operator just marked decorative: alt is null but isDecorative is true.
    // Claiming "No alt text yet" contradicts the success message and invites a
    // redundant edit of a deliberate empty-alt choice.
    renderEditor(<MediaAltInlineEditor mediaId={42} altText={null} isDecorative />);

    expect(screen.getByText(DECORATIVE_IDLE_LABEL)).toBeInTheDocument();
    expect(screen.queryByText('No alt text yet')).not.toBeInTheDocument();
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

  it('patches the workbench row altText from the server response and does not invalidate media.all [BR-77][BR-121]', async () => {
    // Old contract invalidated media.all so every projection refetched; that is
    // the BR-77 root cause (sibling success drops partial rows). Success now
    // patches the workbench row from the server response and leaves the list
    // mounted. media.details / identities carry no alt field — no invalidation.
    //
    // [TEST-17] name/body must pin the patch: seed a workbench page, save, assert
    // the cached row's altText equals the server current_alt_text. A no-op
    // patchWorkbenchRowAlt would leave this RED while the media.all check alone
    // would stay green [TEST-15][BR-121].
    const savedAlt = 'A stone bridge over a calm river at dusk.';
    const serverAlt = 'Server-normalized bridge alt';
    correctMock.mockResolvedValueOnce({
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: serverAlt,
      generated_alt_text: null,
      provenance: null,
      human_edit: { alt_text: serverAlt, edited_at: '2026-07-28 12:00:00', user_id: 7 },
      run_status: null,
    } as never);

    const workbenchKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const { client } = renderEditor(<MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" />);
    client.setQueryData<WorkbenchMediaResponse>(workbenchKey, {
      items: [
        {
          id: 42,
          title: 'Bridge',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
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
    });
    const invalidateSpy = vi.spyOn(client, 'invalidateQueries');

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: savedAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    await waitFor(() => expect(screen.queryByRole('textbox', { name: /alt text/i })).not.toBeInTheDocument());

    const cached = client.getQueryData<WorkbenchMediaResponse>(workbenchKey);
    expect(cached?.items.find((item) => item.id === 42)?.altText).toBe(serverAlt);
    // Sibling untouched — targeted row patch, not list rebuild.
    expect(cached?.items.find((item) => item.id === 99)?.altText).toBeNull();
    expect(cached?.items).toHaveLength(2);

    expect(invalidateSpy).not.toHaveBeenCalledWith(expect.objectContaining({ queryKey: queryKeys.media.all }));
    expect(
      invalidateSpy.mock.calls.some(
        (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: queryKeys.media.all }),
      ),
    ).toBe(false);
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

    // Re-enter; enterEditMode clears the cue. Save only exists while isEditing,
    // and enterEditMode is the sole path into isEditing — so statusMessage is
    // already '' before any failed save can fire. [TEST-15] goes red if
    // enterEditMode stops clearing.
    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    // Present-then-empty: cue was set above; enter-edit must retire it before the
    // failure path.
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

  it('does not write when onCommitStart refuses the lock claim [S2c-4b-ii BR-01]', async () => {
    // WBUX-5-S2C4B-BR-05: refused claim must raise a distinct assertive message.
    // Predict RED: no role=alert, or alert reuses ALT_COMMIT_CONFLICT_MESSAGE.
    const onCommitStart = vi.fn((): boolean => false);
    renderEditor(
      <MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" onCommitStart={onCommitStart} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Must not be persisted after refused claim.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    expect(onCommitStart).toHaveBeenCalledTimes(1);
    expect(correctMock).not.toHaveBeenCalled();
    // Buffer kept; Cancel remains reachable [rg-003].
    expect(screen.getByRole('textbox', { name: /alt text/i })).toHaveValue(
      'Must not be persisted after refused claim.',
    );
    expect(screen.getByRole('button', { name: /cancel/i })).not.toBeDisabled();

    // [TEST-15] discrimination: alert must exist and must not be the CAS copy.
    const alert = await screen.findByRole('alert');
    expect(alert.textContent ?? '').not.toBe(ALT_COMMIT_CONFLICT_MESSAGE);
    expect(alert).toHaveTextContent(/try again|busy|in progress|wait/i);
    expect(alert).not.toHaveTextContent(/changed while you were editing/i);
  });

  it('does not clear a pre-existing conflict message when onCommitStart refuses [WBUX-5-S2C4B-BR-05][RLSE-05]', async () => {
    // [TEST-15] discrimination: goes RED if setConflictMessage(null) is still
    // above the claim — the CAS warning would vanish on refusal.
    const onCommitStart = vi.fn((): boolean => false);
    const { client, rerender } = renderEditor(
      <MediaAltInlineEditor mediaId={42} altText="Bridge at dusk" onCommitStart={onCommitStart} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Operator buffer that must survive.' },
    });

    // Sibling commit moves the prop → CAS conflict message on screen.
    // Baseline (previousAltTextRef) stays "Bridge at dusk" while editing [S2A-BR-03].
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltInlineEditor
          mediaId={42}
          altText="Sibling committed this."
          onCommitStart={onCommitStart}
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));
    const casAlert = await screen.findByRole('alert');
    expect(casAlert).toHaveTextContent(ALT_COMMIT_CONFLICT_MESSAGE);
    // CAS returns before claim — lock was not consulted on that click.
    expect(onCommitStart).not.toHaveBeenCalled();

    // Restore prop so CAS passes; claim still refuses. The CAS warning must remain
    // (setConflictMessage(null) must not run above a refused claim).
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltInlineEditor
          mediaId={42}
          altText="Bridge at dusk"
          onCommitStart={onCommitStart}
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    expect(onCommitStart).toHaveBeenCalledTimes(1);
    expect(correctMock).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox', { name: /alt text/i })).toHaveValue(
      'Operator buffer that must survive.',
    );
    expect(screen.getByRole('button', { name: /cancel/i })).not.toBeDisabled();

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(ALT_COMMIT_CONFLICT_MESSAGE);
  });

  it('refuses Save when committed alt moves under an open buffer [S2c-4b-ii BR-03]', async () => {
    // Pins the display-sync effect's `if (isEditing) return` early-return: while
    // editing, previousAltTextRef must NOT advance with the prop. If that guard
    // is removed, a sibling commit updates the CAS baseline mid-edit and Save
    // incorrectly proceeds (or clobbers the operator buffer via setDraft).
    //
    // [TEST-15] discrimination: goes RED if the isEditing early-return is deleted.
    const { client, rerender } = renderEditor(
      <MediaAltInlineEditor mediaId={42} altText="Existing alt" />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Stale open buffer that must not clobber sibling.' },
    });

    // Sibling commit (or cache patch) delivers a new committed value while open.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltInlineEditor mediaId={42} altText="Sibling committed this." />
      </QueryClientProvider>,
    );

    // Buffer must survive the prop change (effect must not setDraft while editing).
    expect(screen.getByRole('textbox', { name: /alt text/i })).toHaveValue(
      'Stale open buffer that must not clobber sibling.',
    );

    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/changed/i);
    expect(correctMock).not.toHaveBeenCalled();
    // Buffer kept; Cancel remains reachable [rg-003].
    expect(screen.getByRole('textbox', { name: /alt text/i })).toHaveValue(
      'Stale open buffer that must not clobber sibling.',
    );
    expect(screen.getByRole('button', { name: /cancel/i })).not.toBeDisabled();
  });

  it('allows Save retry after PARTIAL without false CAS conflict [rg-002]', async () => {
    // Reachable lockout: open Edit on missing (baseline null), save "Hello",
    // PARTIAL returns stored_alt_text "Hello" and patches the prop while open.
    // Without re-seeding previousAltTextRef, second Save compares null !== "Hello"
    // and surfaces ALT_COMMIT_CONFLICT_MESSAGE — never reaches the wire.
    const partialMessage =
      'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.';
    correctMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: 'Hello' , is_decorative: false },
        })}`,
      ),
    );

    const workbenchKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });
    const { client, rerender } = renderEditor(
      <MediaAltInlineEditor mediaId={42} altText={null} />,
    );
    client.setQueryData<WorkbenchMediaResponse>(workbenchKey, {
      items: [
        {
          id: 42,
          title: 'Bridge',
          status: 'missing',
          thumbnailUrl: null,
          altText: null,
          isDecorative: false,
          editUrl: null,
          tags: [],
        },
      ],
      total: 1,
      totalPages: 1,
    });

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /alt text/i }), {
      target: { value: 'Hello' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/human-edit record could not be stored/i);
    expect(correctMock).toHaveBeenCalledTimes(1);

    // Simulate the parent re-render from useCorrectMediaAlt's PARTIAL patch.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltInlineEditor mediaId={42} altText="Hello" />
      </QueryClientProvider>,
    );

    // Retry must reach the wire — not false CAS from stale null baseline.
    correctMock.mockResolvedValueOnce({
      media_id: 42,
      title: 'Bridge',
      mime_type: 'image/jpeg',
      current_alt_text: 'Hello',
      generated_alt_text: null,
      provenance: null,
      human_edit: { alt_text: 'Hello', edited_at: '2026-07-28 12:00:00', user_id: 7 },
      run_status: null,
    } as never);

    fireEvent.click(screen.getByRole('button', { name: /^save/i }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(ALT_COMMIT_CONFLICT_MESSAGE)).not.toBeInTheDocument();
  });
});
