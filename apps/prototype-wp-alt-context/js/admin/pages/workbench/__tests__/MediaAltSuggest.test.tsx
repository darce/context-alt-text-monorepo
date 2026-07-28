import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MediaAltInlineEditor } from '../MediaAltInlineEditor';
import { MediaAltSuggest } from '../MediaAltSuggest';
import { correctDescriptionHistoryItem, describeMedia } from '../../../api/describeApi';
import type { DescriptionHistoryItem, VisualFactsResponse } from '../../../api/describeApi';

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
    describeMedia: vi.fn(),
    correctDescriptionHistoryItem: vi.fn(),
  };
});

const describeMock = vi.mocked(describeMedia);
const correctMock = vi.mocked(correctDescriptionHistoryItem);

const draft = 'A stone bridge over a calm river at dusk.';
const editedDraft = 'A stone bridge over the Aire at dusk, seen from the north bank.';

const sampleHistoryItem = (altTextValue = draft): DescriptionHistoryItem => ({
  media_id: 42,
  title: 'bridge.jpg',
  mime_type: 'image/jpeg',
  current_alt_text: altTextValue,
  generated_alt_text: draft,
  provenance: null,
  human_edit: { alt_text: altTextValue, edited_at: null, user_id: 1 },
  run_status: null,
});

const sampleResponse = (altTextDraft = draft): VisualFactsResponse => ({
  tenant_id: '00000000-0000-4000-8000-000000000001',
  media_id: 42,
  image_hash: 'sha256:abc',
  context_hash: 'ctx',
  adapter: 'local_cpu',
  model_id: 'microsoft/Florence-2-base-ft',
  model_version: 'florence-2-base-ft',
  prompt_or_task_version: 'v1',
  visual_facts: { caption: altTextDraft, objects: ['bridge'], ocr_text: null },
  alt_text_draft: altTextDraft,
  context_used: { sources: [], applied: false },
  provider_disclosure: { provider: 'local', left_service_boundary: false },
  cached: false,
  duration_ms: 13800,
  retention_class: 'retain_all',
});

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const renderSuggest = (element: ReactElement, client = buildClient()) => ({
  client,
  ...render(<QueryClientProvider client={client}>{element}</QueryClientProvider>),
});

/** Visible-text accessible name for controls whose names come from textContent. */
const buttonAccessibleName = (button: HTMLElement): string => (button.textContent ?? '').trim();

// jsdom neither blurs on disable nor honours blur() on an already-disabled element,
// so the disabled Accept/Save keeps focus. Park on body via a focusable stand-in.
const parkFocusOnBody = (): void => {
  const parking = document.createElement('button');
  document.body.appendChild(parking);
  parking.focus();
  parking.blur();
  parking.remove();
};

describe('MediaAltSuggest', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a Suggest alt text control', () => {
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument();
  });

  it('generates a draft for the row id and shows a pending state', async () => {
    // Never resolves: keeps the mutation pending so we can observe the generating state.
    describeMock.mockReturnValue(new Promise<VisualFactsResponse>(() => undefined));
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    // React Query dispatches the pending state synchronously but invokes the
    // mutationFn on a microtask, so await the generating affordance before asserting
    // the call landed (mirrors the awaited mutation pattern in MediaAltInlineEditor).
    expect(await screen.findByRole('button', { name: /generating/i })).toBeDisabled();
    // [TEST-15] discrimination: goes red if it generates for the wrong id, or writes
    // (a second positional arg / write_alt) instead of a read-only draft.
    expect(describeMock).toHaveBeenCalledTimes(1);
    expect(describeMock).toHaveBeenCalledWith(42);
  });

  it('shows the generated draft with a synthetic-authorship disclosure and verify cue [HAI-14][HAI-13]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    expect(await screen.findByText(draft)).toBeInTheDocument();
    // Synthetic authorship must be disclosed (labelled AI) AND carry a verify cue,
    // so an operator never mistakes a machine draft for a confirmed human alt.
    const disclosure = screen.getByText(/drafted by ai/i);
    expect(disclosure).toHaveTextContent(/review/i);
  });

  it('announces the ready state via a named polite live region [HAI-13]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);
    // No live region before a generation (conditional render avoids colliding with
    // other single-status-region consumers on the same row).
    expect(screen.queryByRole('status')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/ready/i));
  });

  it('shows a user-safe error, not the raw HTTP body, and a retry control on failure [INT-11]', async () => {
    describeMock.mockRejectedValueOnce(
      new Error('Request to /wp-json/acx/v1/recognition/describe failed (502): <html>proxy-internal-detail</html>'),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not generate|couldn.?t generate|unable to generate/i);
    expect(alert).not.toHaveTextContent(/wp-json/i);
    expect(alert).not.toHaveTextContent(/proxy-internal-detail/i);
    expect(screen.getByRole('button', { name: /try again|retry/i })).toBeInTheDocument();
  });

  it('re-invokes generation when retry is pressed after a failure [INT-11]', async () => {
    describeMock
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /try again|retry/i }));

    // [TEST-15] discrimination: goes red if retry re-renders the error without
    // re-calling generation, or if it never recovers to show the fresh draft.
    expect(await screen.findByText(draft)).toBeInTheDocument();
    expect(describeMock).toHaveBeenCalledTimes(2);
  });

  it('dismisses the suggestion back to the Suggest control', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText(draft)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument();
    // [WBUX-5-S2C3A-BR-15] discrimination: goes red if Dismiss stops clearing
    // statusMessage — the idle surface would keep "Draft ready. Review before saving."
    // with no draft left to review.
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('restores focus to the Suggest control after dismiss [a11y][WBUX-5-S2C-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /dismiss/i }));

    // Dismiss unmounts the focused button; focus must return to the reborn Suggest
    // trigger, not fall to document.body (mirrors MediaAltInlineEditor save/cancel).
    expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus();
  });

  it('moves focus to a stable control after a draft lands, not document.body [a11y][WBUX-5-S2C-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    // The focused trigger is replaced when the draft lands; focus must move to an
    // actionable control in the new state so a keyboard user is not stranded on body.
    await waitFor(() => expect(screen.getByRole('button', { name: /dismiss/i })).toHaveFocus());
  });

  it('moves focus to the retry control on failure so keyboard users are not stranded [a11y][WBUX-5-S2C-BR-01]', async () => {
    describeMock.mockRejectedValueOnce(new Error('boom'));
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /try again|retry/i })).toHaveFocus(),
    );
  });

  it('does not steal focus when a draft lands while the operator is elsewhere [a11y][WBUX-5-S2C3A-BR-11]', async () => {
    let resolveDescribe!: (value: VisualFactsResponse) => void;
    describeMock.mockReturnValue(
      new Promise<VisualFactsResponse>((resolve) => {
        resolveDescribe = resolve;
      }),
    );
    renderSuggest(
      <>
        <button type="button">Elsewhere</button>
        <MediaAltSuggest mediaId={42} />
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    expect(await screen.findByRole('button', { name: /generating/i })).toBeDisabled();

    const elsewhere = screen.getByRole('button', { name: /^elsewhere$/i });
    elsewhere.focus();
    expect(elsewhere).toHaveFocus();

    resolveDescribe(sampleResponse());
    await screen.findByText(draft);

    // [TEST-15] discrimination: goes red if the draft-landing focus effect always
    // focuses Dismiss without checking containerRef.contains(activeElement) —
    // generation is slow (fixture duration_ms 13800) and a per-row control must
    // not yank focus mid-keystroke on another control.
    expect(screen.getByRole('button', { name: /^elsewhere$/i })).toHaveFocus();
  });

  it('offers an Accept control alongside the shown draft [HAI-12][S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // The accept leg of the accept/edit/regenerate triad must be reachable from
    // the draft state, next to Dismiss.
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  it('commits the shown draft as the media alt via the correction endpoint [S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    // Never resolves: hold the correction pending so we can assert the call
    // landed before any state transition (mirrors the awaited-mutation pattern).
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // React Query dispatches the pending state synchronously but invokes the
    // mutationFn on a microtask, so await the saving affordance first.
    expect(await screen.findByRole('button', { name: /saving/i })).toBeDisabled();
    // [TEST-15] discrimination: red if it commits the wrong id or wrong text, or
    // routes through the read-only describe writeAlt path instead of the
    // correction endpoint.
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, draft);
  });

  it('announces the saved state and returns to the Suggest control after accept [S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // The committed alt now lives on the row's inline editor, so the suggest
    // surface resets to idle and a polite region announces the save.
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/saved/i));
    expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument();
    expect(screen.queryByText(draft)).not.toBeInTheDocument();
  });

  it('restores focus to the Suggest control after a successful accept [a11y][S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // Accept unmounts the focused control; focus must return to the reborn
    // Suggest trigger, not fall to document.body (mirrors Dismiss).
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus(),
    );
  });

  it('settles accept without waiting for media-tree invalidation [WBUX-5-S2C3A-BR-05]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    const client = buildClient();
    // Never resolves: splits void vs await in useCorrectMediaAlt's hook-level
    // onSuccess. With await, query-core never dispatches success.
    vi.spyOn(client, 'invalidateQueries').mockReturnValue(new Promise<void>(() => undefined));
    renderSuggest(<MediaAltSuggest mediaId={42} />, client);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // [TEST-15] discrimination: goes red if useCorrectMediaAlt restores
    // `onSuccess: async () => { await queryClient.invalidateQueries(...) }` —
    // the mutation stays pending for the never-settling invalidation, so the
    // component's mutate-level onSuccess never runs and these time out.
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/saved/i));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus(),
    );
  });

  it('keeps the draft and shows a user-safe error when accept fails [INT-11][S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not save|couldn.?t save|unable to save/i);
    expect(alert).not.toHaveTextContent(/wp-json/i);
    expect(alert).not.toHaveTextContent(/proxy-internal-detail/i);
    // The operator keeps the draft and can retry the accept — no full restart (INT-11).
    expect(screen.getByText(draft)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  it('returns focus to Accept after a failed accept when the browser blurred the disabled control [a11y][WBUX-5-S2C3A-BR-18]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    const accept = await screen.findByRole('button', { name: /accept/i });
    accept.focus();
    fireEvent.click(accept);
    // Stands in for the browser blurring the control isAccepting just disabled.
    parkFocusOnBody();

    await screen.findByRole('alert');
    // [TEST-15] discrimination: goes red if the isAcceptError focus-restore effect
    // (or its acceptButtonRef) is removed from MediaAltSuggest.tsx — focus stays
    // on document.body instead of returning to Accept.
    expect(screen.getByRole('button', { name: /accept/i })).toHaveFocus();
  });

  it('does not steal focus from elsewhere on the page when accept fails [a11y][WBUX-5-S2C3A-BR-20]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(
      <>
        <MediaAltSuggest mediaId={42} />
        <button type="button">Elsewhere</button>
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /accept/i }));
    // Operator tabs away while the commit is in flight. fireEvent.click is
    // synchronous and React Query invokes the mutationFn on a microtask, so
    // this focus must land before the rejection settles and the restore effect
    // runs — no await between the click and .focus().
    const elsewhere = screen.getByRole('button', { name: /^elsewhere$/i });
    elsewhere.focus();
    expect(elsewhere).toHaveFocus();

    await screen.findByRole('alert');
    // [TEST-15] discrimination: goes red if the ownsFocus block is deleted from
    // the isAcceptError effect in MediaAltSuggest.tsx — focus is pulled back to
    // Accept even though the operator has moved on.
    expect(screen.getByRole('button', { name: /^elsewhere$/i })).toHaveFocus();
  });

  it('does not resurface a prior accept error on a freshly regenerated draft [INT-11][a11y][WBUX-5-S2C2-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    // Draft A -> Accept fails -> the save-failure alert appears for this draft.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    await screen.findByRole('alert');

    // Dismiss the failed draft, then generate a brand-new one.
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus(),
    );
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // [TEST-15] discrimination: the fresh draft was never accepted, so no stale
    // assertive save-failure alert may fire — it would announce a false failure to
    // SR users. Goes red while the accept mutation is not reset on dismiss/generate.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  // --- S2c-3a: the Edit leg of the accept/edit/regenerate triad -------------
  // The operator must be able to amend the machine draft before committing it
  // [HAI-11] (an accept/reject-only pre-label UI degrades to the model's priors)
  // and refinement happens in place on the surface holding the draft [INT-11].

  it('offers an Edit control alongside the shown draft [HAI-11][HAI-12][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // The edit leg must be reachable from the draft state; accept/dismiss-only
    // would collapse the operator's role to rubber-stamping the model.
    expect(screen.getByRole('button', { name: /^edit draft$/i })).toBeInTheDocument();
  });

  it('seeds the edit field with the draft so the good prefix is preserved [INT-11][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));

    // [TEST-15] discrimination: red on an empty field (full-restart authoring)
    // or on a field seeded from the committed alt instead of the shown draft.
    expect(await screen.findByLabelText(/edit draft alt text/i)).toHaveValue(draft);
  });

  it('re-seeds the edit buffer from the draft on every Edit entry [S2c-3a][WBUX-5-S2C3A-BR-10]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));

    // [TEST-15] discrimination: goes red if enterEditMode uses a conditional seed
    // such as setEditDraft((prev) => prev || data.alt_text_draft) — the operator's
    // abandoned amendment would leak back in instead of the machine draft.
    expect(await screen.findByLabelText(/edit draft alt text/i)).toHaveValue(draft);
    expect(screen.getByLabelText(/edit draft alt text/i)).not.toHaveValue(editedDraft);
  });

  it('names the edit field distinctly from the row inline editor [A11Y-03][A11Y-04][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));

    // The row also renders MediaAltInlineEditor, whose textarea is labelled
    // "Alt text". Two identically named fields in one row leave a voice-control
    // or SR user unable to say which one they mean, so this label must be
    // programmatically associated AND distinct.
    const field = await screen.findByLabelText(/edit draft alt text/i);
    expect(field.tagName).toBe('TEXTAREA');
    expect(screen.queryByLabelText(/^alt text$/i)).not.toBeInTheDocument();
  });

  it('keeps co-mounted suggest and inline editors free of duplicate accessible names [A11Y-03][WBUX-5-S2C3A-BR-08]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(
      <>
        <MediaAltInlineEditor mediaId={42} altText="An existing human-authored alt text." />
        <MediaAltSuggest mediaId={42} />
      </>,
    );

    // Open both editors exactly as the table row can: inline edit + suggest edit.
    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    await screen.findByLabelText(/edit draft alt text/i);

    const textboxes = screen.getAllByRole('textbox');
    expect(textboxes).toHaveLength(2);
    const textboxNames = textboxes.map((el) => {
      const id = el.getAttribute('id');
      if (id) {
        const label = Array.from(document.querySelectorAll('label')).find(
          (node) => node.htmlFor === id,
        );
        if (label?.textContent) {
          return label.textContent.trim();
        }
      }
      return (el.getAttribute('aria-label') ?? '').trim();
    });
    // [TEST-15] discrimination: red if either field reuses the other's label
    // (e.g. both "Alt text") — voice control cannot disambiguate.
    expect(new Set(textboxNames).size).toBe(textboxNames.length);

    const buttonNames = screen.getAllByRole('button').map(buttonAccessibleName);
    const duplicateNames = buttonNames.filter((name, index) => buttonNames.indexOf(name) !== index);
    // [TEST-15] discrimination: red today with pre-BR-03 labels (two "Save", two
    // "Cancel"); green once suggest uses "Save alt text" / "Cancel edit".
    expect(duplicateNames).toEqual([]);
  });

  it('moves focus into the edit field on Edit [a11y][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));

    // Edit unmounts the focused control; a keyboard user must land in the field
    // they asked for, not on document.body (mirrors WBUX-5-S2C-BR-01).
    await waitFor(() => expect(screen.getByLabelText(/edit draft alt text/i)).toHaveFocus());
  });

  it('keeps a single commit authority while editing [S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    await screen.findByLabelText(/edit draft alt text/i);

    // Accept commits the ORIGINAL draft. Leaving it live beside Save would let
    // one mis-click silently discard the operator's edit, so edit mode replaces
    // the accept/dismiss pair with save/cancel.
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument();
    // [WBUX-5-S2C3A-BR-14] discrimination: goes red if Dismiss stays mounted in
    // edit mode — a mis-click would destroy the in-progress amendment.
    expect(screen.queryByRole('button', { name: /dismiss/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^save alt text$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^cancel edit$/i })).toBeInTheDocument();
  });

  it('disables Save when the edit buffer is empty or whitespace-only [S2c-3a][WBUX-5-S2C3A-BR-04]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);

    fireEvent.change(field, { target: { value: '' } });
    // [TEST-15] discrimination: goes red if saveEdit still commits editDraft with
    // no empty guard — select-all + delete + Save would wipe the attachment alt.
    expect(screen.getByRole('button', { name: /^save alt text$/i })).toBeDisabled();

    fireEvent.change(field, { target: { value: '   ' } });
    expect(screen.getByRole('button', { name: /^save alt text$/i })).toBeDisabled();

    fireEvent.change(field, { target: { value: editedDraft } });
    expect(screen.getByRole('button', { name: /^save alt text$/i })).not.toBeDisabled();
  });

  it('commits the edited text, not the original draft [HAI-02][INT-11][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    // Never resolves: hold the correction pending so the call is asserted before
    // any state transition (mirrors the awaited-mutation pattern above).
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    expect(await screen.findByRole('button', { name: /saving alt text/i })).toBeDisabled();
    // [TEST-15] discrimination: this is the whole point of the edit leg. It goes
    // red the moment the commit reads data.alt_text_draft instead of the field,
    // which is exactly how a seeded-but-ignored editor would fail.
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, editedDraft);
  });

  it('cancels back to the draft without committing [INT-09][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));

    // Abandoning an edit must not write, and must restore the unmodified
    // proposal alongside its accept path.
    expect(correctMock).not.toHaveBeenCalled();
    expect(screen.getByText(draft)).toBeInTheDocument();
    expect(screen.queryByText(editedDraft)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus(),
    );
  });

  it('announces the saved state and returns to the Suggest control after an edited save [S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem(editedDraft));
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    // The committed alt now lives on the row's inline editor, so the suggest
    // surface resets to idle exactly as the accept leg does.
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/saved/i));
    expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/edit draft alt text/i)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus(),
    );
  });

  it('keeps the edited text and shows a user-safe error when the edited save fails [INT-11][FORM-05][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not save|couldn.?t save|unable to save/i);
    expect(alert).not.toHaveTextContent(/wp-json/i);
    expect(alert).not.toHaveTextContent(/proxy-internal-detail/i);
    // [INT-11] the operator's typing is the good prefix: a failed save must not
    // drop them back to the machine draft and make them retype the amendment.
    expect(screen.getByLabelText(/edit draft alt text/i)).toHaveValue(editedDraft);
    expect(screen.getByRole('button', { name: /^save alt text$/i })).toBeInTheDocument();
  });

  it('returns focus to Save alt text after a failed save when the browser blurred the disabled control [a11y][WBUX-5-S2C3A-BR-18]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    const save = screen.getByRole('button', { name: /^save alt text$/i });
    save.focus();
    fireEvent.click(save);
    // Stands in for the browser blurring the control isAccepting just disabled.
    parkFocusOnBody();

    await screen.findByRole('alert');
    // [TEST-15] discrimination: goes red if the isAcceptError focus-restore effect
    // (or its saveButtonRef) is removed from MediaAltSuggest.tsx — focus stays
    // on document.body instead of returning to Save alt text.
    expect(screen.getByRole('button', { name: /^save alt text$/i })).toHaveFocus();
  });

  it('describes the edit field with the disclosure and associates a save error [a11y][WBUX-5-S2C3A-BR-09]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);

    const describedBy = field.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const descriptionText = (describedBy ?? '')
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    // [TEST-15] discrimination: goes red if the textarea has no aria-describedby
    // pointing at the AI disclosure — SR users re-entering the field get no cue.
    expect(descriptionText).toMatch(/drafted by ai/i);
    expect(field).not.toHaveAttribute('aria-invalid', 'true');

    fireEvent.change(field, { target: { value: editedDraft } });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));
    await screen.findByRole('alert');

    const fieldAfterFail = screen.getByLabelText(/edit draft alt text/i);
    expect(fieldAfterFail).toHaveAttribute('aria-invalid', 'true');
    const describedByAfter = fieldAfterFail.getAttribute('aria-describedby');
    expect(describedByAfter).toBeTruthy();
    const descriptionAfter = (describedByAfter ?? '')
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    // [TEST-15] discrimination: goes red if a failed save leaves the field without
    // aria-invalid / without chaining the alert id into describedby — role=alert
    // only fires once on mount, so returning focus later needs the association.
    expect(descriptionAfter).toMatch(/drafted by ai/i);
    expect(descriptionAfter).toMatch(/could not save|couldn.?t save|unable to save/i);
  });

  it('does not resurface a prior save error on re-entering edit [INT-11][a11y][WBUX-5-S2C3A-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    // Edit -> Save fails -> the save-failure alert appears for this attempt.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^save alt text$/i }));
    await screen.findByRole('alert');

    // Back out, then re-enter edit for a fresh attempt.
    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));
    await screen.findByRole('button', { name: /accept/i });
    fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
    await screen.findByLabelText(/edit draft alt text/i);

    // [TEST-15] discrimination: the new attempt has not failed, so no stale
    // assertive alert may fire — it announces a false failure to SR users. Red
    // while the correction mutation is not reset on cancel/enter-edit. Same bug
    // class as WBUX-5-S2C2-BR-01, guarded here rather than rediscovered.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('does not resurface a prior accept error when entering edit from draft review [INT-11][a11y][WBUX-5-S2C3A-BR-07]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    // Accept fails while NOT editing — the path enterEditMode's resetAccept guards.
    // No Cancel: cancelEdit also resets, so a Cancel-based test cannot pin this line.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
    await screen.findByLabelText(/edit draft alt text/i);

    // [TEST-15] discrimination: goes red if resetAccept() is removed from
    // enterEditMode — the Accept failure alert would reappear on a fresh edit.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('returns a later draft to the review state, not a stale edit buffer [HAI-12][WBUX-5-S2C3A-BR-02]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem(editedDraft));
    renderSuggest(<MediaAltSuggest mediaId={42} />);

    // Edit -> Save succeeds -> surface resets to idle.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus(),
    );

    // Generate again on the same row.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // [TEST-15] discrimination: red when edit mode is not exited on a successful
    // save. The stale flag drops the operator straight into a textarea holding
    // the PREVIOUS row edit instead of showing the new machine proposal for
    // review — the proposal is never seen, which defeats the review step, and
    // the draft-land focus target (Dismiss) is not rendered so focus is lost.
    expect(screen.queryByLabelText(/edit draft alt text/i)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(editedDraft)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /dismiss/i })).toHaveFocus());
  });
});
