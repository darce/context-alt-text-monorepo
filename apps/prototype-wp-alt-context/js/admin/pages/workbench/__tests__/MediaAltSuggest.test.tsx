import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { MediaAltInlineEditor } from '../MediaAltInlineEditor';
import {
  ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE,
  formatAltLengthAdvisory,
  formatOverLengthReadyAnnouncement,
  MARK_DECORATIVE_LABEL,
  MediaAltSuggest,
  RECOMMENDED_ALT_TEXT_MAX_LENGTH,
  UNMARK_DECORATIVE_LABEL,
  UNMARK_DECORATIVE_SUCCESS_MESSAGE,
} from '../MediaAltSuggest';
import { correctDescriptionHistoryItem, describeMedia } from '../../../api/describeApi';
import type { DescriptionHistoryItem, VisualFactsResponse } from '../../../api/describeApi';
import { queryKeys } from '../../../api/queryKeys';
import type { WorkbenchMediaItem, WorkbenchMediaResponse } from '../../../api/workbenchMediaApi';

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

const sampleHistoryItem = (
  altTextValue = draft,
  isDecorative = false,
): DescriptionHistoryItem => ({
  media_id: 42,
  title: 'bridge.jpg',
  mime_type: 'image/jpeg',
  current_alt_text: altTextValue,
  generated_alt_text: draft,
  provenance: null,
  human_edit: { alt_text: altTextValue, edited_at: null, user_id: 1 },
  run_status: null,
  is_decorative: isDecorative,
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
  tier: 'provisional_cpu',
  result_generation: 1,
});

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const workbenchPageKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });

const seedWorkbenchRow = (
  client: QueryClient,
  altText: string | null,
  status: WorkbenchMediaItem['status'] = altText && altText.trim() !== '' ? 'complete' : 'missing',
  isDecorative = false,
): WorkbenchMediaResponse => {
  const page: WorkbenchMediaResponse = {
    items: [
      {
        id: 42,
        title: 'Bridge',
        status,
        thumbnailUrl: null,
        altText,
        isDecorative,
        editUrl: null,
        tags: [],
      },
    ],
    total: 1,
    totalPages: 1,
  };
  client.setQueryData(workbenchPageKey, page);
  return page;
};

/**
 * Co-mounted InlineEditor + Suggest driven by the workbench cache so a successful
 * decorative mark that patches via useCorrectMediaAlt re-renders the row surfaces
 * with live item.altText [S7-BR-01][HARM-BR-02].
 */
const LiveWorkbenchAltRow = ({ initial }: { initial: WorkbenchMediaResponse }): ReactElement => {
  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- seed only; live truth is cache patches
  const { data } = useQuery({
    queryKey: workbenchPageKey,
    queryFn: (): Promise<WorkbenchMediaResponse> => Promise.resolve(initial),
    initialData: initial,
    staleTime: Infinity,
  });
  const item = data?.items.find((row) => row.id === 42);
  const altText = item?.altText ?? null;
  const isDecorative = item?.isDecorative === true;
  return (
    <div data-testid="live-workbench-alt-row">
      <MediaAltInlineEditor mediaId={42} altText={altText} isDecorative={isDecorative} />
      <MediaAltSuggest isDecorative={isDecorative} mediaId={42} committedAlt={altText} />
      <span data-testid="live-row-status">{item?.status ?? ''}</span>
    </div>
  );
};

const renderLiveAltRow = (altText: string, status: WorkbenchMediaItem['status'] = 'complete') => {
  const client = buildClient();
  const initial = seedWorkbenchRow(client, altText, status);
  const view = render(
    <QueryClientProvider client={client}>
      <LiveWorkbenchAltRow initial={initial} />
    </QueryClientProvider>,
  );
  return { client, ...view };
};

const cachedRow = (client: QueryClient) =>
  client.getQueryData<WorkbenchMediaResponse>(workbenchPageKey)?.items.find((item) => item.id === 42);

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
    // resetAllMocks (not clearAllMocks): mockResolvedValueOnce / mockRejectedValueOnce
    // queues survive clearAllMocks and leak into later tests (BR-35). Measured:
    // residual describeMedia implementations inflated full-file blast radii for
    // generate-wiring mutations (see REPORT.md).
    vi.resetAllMocks();
  });

  it('renders a Suggest alt text control', () => {
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument();
  });

  it('W3-C-04 Accept is secondary; Save alt text is the single primary', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    const accept = await screen.findByRole('button', { name: /^accept$/i });
    expect(accept).toHaveClass('button-secondary');
    expect(accept).not.toHaveClass('button-primary');

    fireEvent.click(screen.getByRole('button', { name: /^edit draft$/i }));
    const save = await screen.findByRole('button', { name: /^save alt text$/i });
    expect(save).toHaveClass('button-primary');
    const primaries = screen
      .getAllByRole('button')
      .filter(
        (button) =>
          button.classList.contains('button-primary') || button.classList.contains('acx-button--primary'),
      );
    expect(primaries).toHaveLength(1);
    expect(primaries[0]).toBe(save);
  });

  it('generates a draft for the row id and shows a pending state', async () => {
    // Never resolves: keeps the mutation pending so we can observe the generating state.
    describeMock.mockReturnValue(new Promise<VisualFactsResponse>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    expect(await screen.findByText(draft)).toBeInTheDocument();
    // Synthetic authorship must be disclosed (labelled AI) AND carry a verify cue,
    // so an operator never mistakes a machine draft for a confirmed human alt.
    const disclosure = screen.getByText(/drafted by ai/i);
    expect(disclosure).toHaveTextContent(/review/i);
  });

  it('announces the ready state via a named polite live region [HAI-13]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);
    // Always-mounted empty region (BR-32): present before generation, no cue text yet.
    // data-testid disambiguates from MediaAltInlineEditor's sibling role=status.
    const status = screen.getByTestId('media-alt-suggest-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent('');

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/ready/i));
  });

  it('shows a user-safe error, not the raw HTTP body, and a retry control on failure [INT-11]', async () => {
    describeMock.mockRejectedValueOnce(
      new Error('Request to /wp-json/acx/v1/recognition/describe failed (502): <html>proxy-internal-detail</html>'),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not generate|couldn.?t generate|unable to generate/i);
    expect(alert).not.toHaveTextContent(/wp-json/i);
    expect(alert).not.toHaveTextContent(/proxy-internal-detail/i);
    expect(screen.getByRole('button', { name: /try again|retry/i })).toBeInTheDocument();
  });

  it('clears the polite generating cue when generation fails so only the alert describes the row [a11y][BR-46]', async () => {
    describeMock.mockRejectedValueOnce(
      new Error('Request to /wp-json/acx/v1/recognition/describe failed (502): <html>proxy-internal-detail</html>'),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    // [TEST-15][BR-53]: pin that the generating cue was actually announced while
    // pending — without this, the post-failure emptiness pins only "not sitting
    // on Generating… now", which is also true if announceStatus never ran.
    // Goes red if announceStatus('Generating…') is removed from generate().
    const status = screen.getByTestId('media-alt-suggest-status');
    expect(status).toHaveTextContent(/generating/i);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not generate|couldn.?t generate|unable to generate/i);

    // [TEST-15] discrimination: goes red if clearStatus() is removed from
    // generate()'s onError — the always-mounted polite region keeps the stale
    // "Generating…" cue beside the assertive failure alert. Single-line: delete
    // clearStatus() from the onError callback (or the whole onError option).
    // toBeEmptyDOMElement (not toHaveTextContent('')): jest-dom's recommended
    // empty check — readability only; the prior form already failed on non-empty.
    expect(status).toBeEmptyDOMElement();
    expect(status).not.toHaveTextContent(/generating/i);
  });

  it('re-invokes generation when retry is pressed after a failure [INT-11]', async () => {
    describeMock.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /try again|retry/i }));

    // [TEST-15] discrimination: goes red if retry re-renders the error without
    // re-calling generation, or if it never recovers to show the fresh draft.
    expect(await screen.findByText(draft)).toBeInTheDocument();
    expect(describeMock).toHaveBeenCalledTimes(2);
  });

  it('dismisses the suggestion back to the Suggest control', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));

    expect(screen.queryByText(draft)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument();
    // [WBUX-5-S2C3A-BR-15] discrimination: goes red if Dismiss stops clearing
    // statusMessage — the idle surface would keep "Draft ready. Review before saving."
    // with no draft left to review. Region stays mounted (BR-32); cue text clears.
    expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent('');
  });

  it('restores focus to the Suggest control after dismiss [a11y][WBUX-5-S2C-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /dismiss/i }));

    // Dismiss unmounts the focused button; focus must return to the reborn Suggest
    // trigger, not fall to document.body (mirrors MediaAltInlineEditor save/cancel).
    expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus();
  });

  it('moves focus to Accept after a draft lands, not Dismiss or document.body [a11y][WBUX-5-S2C-BR-01][BR-57]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    // BR-57 design revision: previously landed on Dismiss ("stable control") so
    // Enter discarded the draft the polite cue just asked the operator to review.
    // Land on Accept — the primary act-on-draft control — instead. Dismiss stays
    // in tab order; it is no longer the programmatic landing target.
    // [TEST-15] discrimination: goes red if the data-landing leg still focuses
    // dismissButtonRef (pre-BR-57), or if it stops focusing any control (body).
    await waitFor(() => expect(screen.getByRole('button', { name: /accept/i })).toHaveFocus());
    expect(screen.getByRole('button', { name: /dismiss/i })).not.toHaveFocus();
  });

  it('moves focus to Edit draft when a whitespace-only draft lands [a11y][BR-57]', async () => {
    describeMock.mockResolvedValue(sampleResponse('   '));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    // Accept is disabled for empty/whitespace drafts — land on Edit so the
    // operator can act on the draft rather than discard it.
    // [TEST-15] discrimination: goes red if the landing always focuses Accept
    // (disabled) or still focuses Dismiss for non-committable drafts.
    await waitFor(() => expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus());
    expect(screen.getByRole('button', { name: /accept/i })).not.toHaveFocus();
    expect(screen.getByRole('button', { name: /dismiss/i })).not.toHaveFocus();
  });

  it('moves focus to the retry control on failure so keyboard users are not stranded [a11y][WBUX-5-S2C-BR-01]', async () => {
    describeMock.mockRejectedValueOnce(new Error('boom'));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));

    await waitFor(() => expect(screen.getByRole('button', { name: /try again|retry/i })).toHaveFocus());
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
        <MediaAltSuggest isDecorative={false} mediaId={42} />
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
    // focuses Accept (or any landing target) without checking
    // containerRef.contains(activeElement) — generation is slow (fixture
    // duration_ms 13800) and a per-row control must not yank focus mid-keystroke
    // on another control. The ownsFocus gate is preserved across the BR-57
    // landing-target change.
    expect(screen.getByRole('button', { name: /^elsewhere$/i })).toHaveFocus();
  });

  it('offers an Accept control alongside the shown draft [HAI-12][S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // The accept leg of the accept/edit/regenerate triad must be reachable from
    // the draft state, next to Dismiss.
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  it('disables Accept when the machine draft is empty or whitespace-only [WBUX-5-S2C3A-BR-24]', async () => {
    describeMock.mockResolvedValue(sampleResponse('   '));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByRole('button', { name: /accept/i });

    // [TEST-15] discrimination: goes red if canAcceptDraft is dropped from
    // Accept's disabled expression — Accept would commit a blank draft and
    // silently erase whatever alt the image already had.
    expect(screen.getByRole('button', { name: /accept/i })).toBeDisabled();
  });

  it('commits the shown draft as the media alt via the correction endpoint [S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    // Never resolves: hold the correction pending so we can assert the call
    // landed before any state transition (mirrors the awaited-mutation pattern).
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // React Query dispatches the pending state synchronously but invokes the
    // mutationFn on a microtask, so await the accepting affordance first.
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();
    // [TEST-15] discrimination: red if it commits the wrong id or wrong text, or
    // routes through the read-only describe writeAlt path instead of the
    // correction endpoint.
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, draft);
  });

  it('announces accepting into the polite region while the commit is in flight [a11y][BR-56]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await waitFor(() => expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(/ready/i));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();

    // [TEST-15] discrimination: goes red if accept() omits announceStatus at
    // mutate start — polite region keeps the stale "Draft ready. Review before
    // saving." while the visible button already reads "Accepting draft…".
    // Single-line: delete announceStatus(__('Accepting draft…', …)) from accept().
    const status = screen.getByTestId('media-alt-suggest-status');
    expect(status).toHaveTextContent(/accepting draft/i);
    expect(status).not.toHaveTextContent(/ready/i);
  });

  it('marks the draft host busy and parks focus while accepting [a11y][BR-56]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    const accept = await screen.findByRole('button', { name: /accept/i });
    accept.focus();
    fireEvent.click(accept);
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();
    // Stands in for the browser blurring the control native `disabled` just applied.
    parkFocusOnBody();

    const host = screen
      .getByRole('button', { name: /accepting draft/i })
      .closest('.acx-media-selection__media-alt-suggest');
    expect(host).toBeTruthy();
    if (!(host instanceof HTMLElement)) {
      throw new Error('expected accepting host container');
    }

    // [TEST-15] discrimination: goes red if aria-busy is omitted from the data
    // branch host while isAccepting, or if useFocusPark is still gated on
    // isPending alone (not isAccepting) — focus stays on document.body for the
    // whole commit. Mirror of the generate BR-13 / BR-38 pins.
    expect(host).toHaveAttribute('aria-busy', 'true');
    expect(host).toHaveAccessibleName('Accepting draft…');
    await waitFor(() => {
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement).toHaveClass('acx-media-selection__media-alt-suggest');
    });
  });

  it('announces saving into the polite region while an edited save is in flight [a11y][BR-56]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));
    expect(await screen.findByRole('button', { name: /saving alt text/i })).toBeDisabled();

    // [TEST-15] discrimination: goes red if saveEdit() omits announceStatus at
    // mutate start — polite region keeps "Draft ready…" while Save shows
    // "Saving alt text…". Single-line: delete announceStatus from saveEdit().
    const status = screen.getByTestId('media-alt-suggest-status');
    expect(status).toHaveTextContent(/saving alt text/i);
    expect(status).not.toHaveTextContent(/ready/i);
  });

  it('announces the saved state and returns to the Suggest control after accept [S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // Accept unmounts the focused control; focus must return to the reborn
    // Suggest trigger, not fall to document.body (mirrors Dismiss).
    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus());
  });

  it('settles accept without waiting for media-tree invalidation [WBUX-5-S2C3A-BR-05]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    const client = buildClient();
    // Never resolves: splits void vs await in useCorrectMediaAlt's hook-level
    // onSuccess. With await, query-core never dispatches success.
    vi.spyOn(client, 'invalidateQueries').mockReturnValue(new Promise<void>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />, client);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    // [TEST-15] discrimination: goes red if useCorrectMediaAlt restores
    // `onSuccess: async () => { await queryClient.invalidateQueries(...) }` —
    // the mutation stays pending for the never-settling invalidation, so the
    // component's mutate-level onSuccess never runs and these time out.
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/saved/i));
    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus());
  });

  it('keeps the draft and shows a user-safe error when accept fails [INT-11][S2c-2]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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

  it('clears the polite ready cue when accept fails so only the alert describes the row [a11y][BR-39]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await waitFor(() => expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(/ready/i));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not save|couldn.?t save|unable to save/i);

    // [TEST-15] discrimination: goes red if clearStatus() is removed from
    // accept()'s onError — polite "Draft ready. Review before saving." stays
    // mounted beside the assertive save-failure alert. Single-line: delete
    // clearStatus() from accept's onError (or the whole onError option).
    // Cleared (not restated): the assertive alert is about to speak; a second
    // polite restatement would only compete.
    const status = screen.getByTestId('media-alt-suggest-status');
    expect(status).toHaveTextContent('');
    expect(status).not.toHaveTextContent(/ready/i);
    expect(status).not.toHaveTextContent(/draft ready/i);
  });

  it('returns focus to Accept after a failed accept when the browser blurred the disabled control [a11y][WBUX-5-S2C3A-BR-18]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
        <MediaAltSuggest isDecorative={false} mediaId={42} />
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

  it('does not steal focus from elsewhere on the page after a successful accept [a11y][WBUX-5-S2C3A-BR-22]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    renderSuggest(
      <>
        <MediaAltSuggest isDecorative={false} mediaId={42} />
        <button type="button">Elsewhere</button>
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /accept/i }));
    // Operator tabs away while the commit is in flight. fireEvent.click is
    // synchronous and React Query invokes the mutationFn on a microtask, so
    // this focus must land before the resolved mutation's microtasks run and
    // the idle-focus effect fires — no await between the click and .focus().
    const elsewhere = screen.getByRole('button', { name: /^elsewhere$/i });
    elsewhere.focus();
    expect(elsewhere).toHaveFocus();

    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toBeInTheDocument());
    // [TEST-15] discrimination: goes red if the ownsFocus gate is removed from
    // the shouldFocusSuggestRef leg in the [isError, data] effect — focus is
    // pulled to Suggest even though the operator has moved on.
    expect(screen.getByRole('button', { name: /^elsewhere$/i })).toHaveFocus();
  });

  it('does not resurface a prior accept error on a freshly regenerated draft [INT-11][a11y][WBUX-5-S2C2-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    // Draft A -> Accept fails -> the save-failure alert appears for this draft.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    await screen.findByRole('alert');

    // Dismiss the failed draft, then generate a brand-new one.
    // (Dismiss independently calls resetAccept — this pin does not cover the
    // Accept-fail → Regenerate path; see the Regenerate companion below.)
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus());
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // [TEST-15] discrimination: the fresh draft was never accepted, so no stale
    // assertive save-failure alert may fire — it would announce a false failure to
    // SR users. Goes red while the accept mutation is not reset on dismiss/generate.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  it('clears a prior accept error when Regenerate is pressed [INT-11][a11y][WBUX-5-S2C2-BR-01][BR-36]', async () => {
    const regenerated = 'A red brick viaduct crossing a canal at midday.';
    describeMock.mockResolvedValueOnce(sampleResponse(draft)).mockResolvedValueOnce(sampleResponse(regenerated));
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    // Draft A -> Accept fails -> sticky accept error alert.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    await screen.findByRole('alert');

    // Regenerate (not Dismiss): the path resetAccept() inside generate() was
    // added for. Without it the sticky accept alert rides onto the new draft.
    fireEvent.click(screen.getByRole('button', { name: /^regenerate$/i }));
    expect(await screen.findByText(regenerated)).toBeInTheDocument();

    // [TEST-15] discrimination: goes red if resetAccept() is removed from
    // generate() — Accept-fail → Regenerate leaves role="alert" on the fresh
    // draft. Single-line: delete `resetAccept();` from generate().
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  // --- S2c-3a: the Edit leg of the accept/edit/regenerate triad -------------
  // The operator must be able to amend the machine draft before committing it
  // [HAI-11] (an accept/reject-only pre-label UI degrades to the model's priors)
  // and refinement happens in place on the surface holding the draft [INT-11].

  it('offers an Edit control alongside the shown draft [HAI-11][HAI-12][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // The edit leg must be reachable from the draft state; accept/dismiss-only
    // would collapse the operator's role to rubber-stamping the model.
    expect(screen.getByRole('button', { name: /^edit draft$/i })).toBeInTheDocument();
  });

  it('seeds the edit field with the draft so the good prefix is preserved [INT-11][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));

    // [TEST-15] discrimination: red on an empty field (full-restart authoring)
    // or on a field seeded from the committed alt instead of the shown draft.
    expect(await screen.findByLabelText(/edit draft alt text/i)).toHaveValue(draft);
  });

  it('re-seeds the edit buffer from the draft on every Edit entry [S2c-3a][WBUX-5-S2C3A-BR-10]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
        <MediaAltSuggest isDecorative={false} mediaId={42} />
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
        const label = Array.from(document.querySelectorAll('label')).find((node) => node.htmlFor === id);
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

    // Pending names must stay distinct too (WBUX-5-S2C3A-BR-29): Accept used the
    // same "Saving…" as MediaAltInlineEditor's Save. Drive both commits pending
    // with a never-resolving correction mock, then re-check button names.
    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));
    await screen.findByRole('button', { name: /accept/i });
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    fireEvent.click(screen.getByRole('button', { name: /accept/i }));
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^saving…$/i })).toBeDisabled();
    const pendingButtonNames = screen.getAllByRole('button').map(buttonAccessibleName);
    const pendingDuplicates = pendingButtonNames.filter((name, index) => pendingButtonNames.indexOf(name) !== index);
    // [TEST-15] discrimination: red if Accept's pending label is still "Saving…"
    // — co-mounted commits yield ["Saving…","Cancel","Saving…",…].
    expect(pendingDuplicates).toEqual([]);
  });

  it('moves focus into the edit field on Edit [a11y][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));

    // Edit unmounts the focused control; a keyboard user must land in the field
    // they asked for, not on document.body (mirrors WBUX-5-S2C-BR-01).
    await waitFor(() => expect(screen.getByLabelText(/edit draft alt text/i)).toHaveFocus());
  });

  it('keeps a single commit authority while editing [S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    await waitFor(() => expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus());
  });

  it('announces the saved state and returns to the Suggest control after an edited save [S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem(editedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus());
  });

  it('keeps the edited text and shows a user-safe error when the edited save fails [INT-11][FORM-05][S2c-3a]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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

  it('clears the polite ready cue when the edited save fails so only the alert describes the row [a11y][BR-49]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await waitFor(() => expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(/ready/i));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not save|couldn.?t save|unable to save/i);

    // [TEST-15] discrimination: goes red if clearStatus() is removed from
    // saveEdit()'s onError — polite "Draft ready. Review before saving." stays
    // mounted beside the assertive save-failure alert. Single-line: delete
    // clearStatus() from saveEdit's onError (or the whole onError option).
    // Separate path from accept()'s onError (BR-39); mutating only this clear
    // must not kill the accept pin.
    const status = screen.getByTestId('media-alt-suggest-status');
    expect(status).toHaveTextContent('');
    expect(status).not.toHaveTextContent(/ready/i);
    expect(status).not.toHaveTextContent(/draft ready/i);
  });

  it('returns focus to Save alt text after a failed save when the browser blurred the disabled control [a11y][WBUX-5-S2C3A-BR-18]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

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
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    // Edit -> Save succeeds -> surface resets to idle.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus());

    // Generate again on the same row.
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // [TEST-15] discrimination: red only when setIsEditing(false) is removed from
    // BOTH generate() and saveEdit's onSuccess. Either call alone masks the other —
    // reset() clears data, and isEditing is only read inside the data branch, so a
    // surviving setIsEditing(false) still lands review state on the next generate.
    expect(screen.queryByLabelText(/edit draft alt text/i)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(editedDraft)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
    // BR-57: later draft lands on Accept (act-on-draft), not Dismiss.
    await waitFor(() => expect(screen.getByRole('button', { name: /accept/i })).toHaveFocus());
  });

  it('clears a failed-save alert and focuses Edit draft after Cancel edit [a11y][WBUX-5-S2C3A-BR-27]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    // Reach review via Cancel after a failed save — not enterEditMode. That path
    // is the only one that observes cancelEdit's resetAccept (enterEditMode also
    // resets, so a re-Edit test cannot pin this line).
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));
    await screen.findByRole('alert');

    fireEvent.click(screen.getByRole('button', { name: /^cancel edit$/i }));

    // [TEST-15] discrimination: goes red if resetAccept() is removed from
    // cancelEdit — isAcceptError survives the isEditing true→false transition,
    // the [isAcceptError, isEditing] effect re-keys and focuses Accept, and the
    // save-failure alert remounts in the review branch.
    await waitFor(() => expect(screen.getByRole('button', { name: /^edit draft$/i })).toHaveFocus());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('associates Accept with the save-failure alert after a failed accept [a11y][WBUX-5-S2C3A-BR-28]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    await screen.findByRole('alert');

    const accept = screen.getByRole('button', { name: /accept/i });
    // [TEST-15] discrimination: goes red if Accept lacks aria-describedby pointing
    // at the error element — the BR-18 focus restore lands on a control that
    // announces only "Accept, button" with no persistent failure cue.
    const describedBy = accept.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const descriptionText = (describedBy ?? '')
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    expect(descriptionText).toMatch(/could not save|couldn.?t save|unable to save/i);
  });

  // --- S2c-3b: the Regenerate leg of the accept/edit/regenerate triad --------
  // [HAI-12] an operator who finds the draft wrong but not worth hand-writing
  // must be able to request another draft without Dismiss → Suggest (which
  // reads as discarding work rather than retrying it).

  const regeneratedDraft = 'A red brick viaduct crossing a canal at midday.';

  it('offers a Regenerate control that requests a fresh draft for the same media id [HAI-12][WBUX-5-S2C3B]', async () => {
    describeMock.mockResolvedValueOnce(sampleResponse(draft)).mockResolvedValueOnce(sampleResponse(regeneratedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^regenerate$/i }));

    // [TEST-15] discrimination: goes red if Regenerate does not call generate()
    // / describeMedia for the same media id, or if the new draft fails to replace
    // the old one on screen (e.g. a no-op control or a forked path that never
    // mutates). Single-line: onClick={generate} removed from Regenerate, or
    // regenerate omitted from the review branch entirely.
    expect(await screen.findByText(regeneratedDraft)).toBeInTheDocument();
    expect(screen.queryByText(draft)).not.toBeInTheDocument();
    expect(describeMock).toHaveBeenCalledTimes(2);
    expect(describeMock).toHaveBeenLastCalledWith(42);
    // BR-02 companion: fresh draft lands in review, not a stale edit buffer.
    expect(screen.queryByLabelText(/edit draft alt text/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument();
  });

  it('re-announces the ready state when a regenerate returns the same cue [WBUX-5-S2C3B][WBUX-5-S2C3A-BR-12]', async () => {
    // Hold the regenerate request so the Generating cue is stable long enough to
    // assert textContent transition on the same DOM node (BR-32 persistence).
    let resolveRegenerate!: (value: VisualFactsResponse) => void;
    describeMock.mockResolvedValueOnce(sampleResponse(draft)).mockReturnValueOnce(
      new Promise<VisualFactsResponse>((resolve) => {
        resolveRegenerate = resolve;
      }),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/ready/i));
    // Capture the live-region node before regenerate. Persistence across the
    // branch change (ready → pending → ready) is the re-announce mechanism:
    // aria-live observes a text change inside a node the AT already tracks.
    const statusBefore = screen.getByTestId('media-alt-suggest-status');
    const firstSeq = statusBefore.getAttribute('data-announce-seq');
    expect(firstSeq).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: /^regenerate$/i }));
    await waitFor(() => expect(statusBefore).toHaveTextContent(/generating/i));
    // Same DOM node through pending — not a remount.
    expect(screen.getByTestId('media-alt-suggest-status')).toBe(statusBefore);
    const generatingSeq = statusBefore.getAttribute('data-announce-seq');
    expect(generatingSeq).toBeTruthy();
    expect(generatingSeq).not.toBe(firstSeq);

    resolveRegenerate(sampleResponse(regeneratedDraft));

    // [TEST-15] discrimination: pins the stable-region mechanism (BR-32/BR-34).
    // Observed mutation: restore per-branch `{statusRegion}` mounting → red
    // (second !== first; node identity breaks on branch change).
    // textContent Generating… → Draft ready… is the aria-live content change;
    // data-announce-seq is secondary only.
    // Note: generate() always inserts "Generating…" between two "Draft ready…"
    // cues, so useAriaAnnounce's equal-message seq remount is not load-bearing
    // here — do not pretend this pin certifies that path.
    await waitFor(() => {
      expect(statusBefore).toHaveTextContent(/ready/i);
    });
    const statusAfter = screen.getByTestId('media-alt-suggest-status');
    expect(statusAfter).toBe(statusBefore);
    const readySeq = statusAfter.getAttribute('data-announce-seq');
    expect(readySeq).not.toBe(firstSeq);
    expect(readySeq).not.toBe(generatingSeq);
    expect(await screen.findByText(regeneratedDraft)).toBeInTheDocument();
  });

  it('disables Regenerate while a commit is in flight [WBUX-5-S2C3B]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();

    // [TEST-15] discrimination: goes red if Regenerate omits disabled={isAccepting}
    // — the operator could fire a describe while a correction is in flight.
    // Single-line: `disabled={isAccepting}` removed from the Regenerate button.
    expect(screen.getByRole('button', { name: /^regenerate$/i })).toBeDisabled();
  });

  it('lands a failed regenerate on the error branch with Try again [INT-11][WBUX-5-S2C3B]', async () => {
    describeMock
      .mockResolvedValueOnce(sampleResponse(draft))
      .mockRejectedValueOnce(
        new Error('Request to /wp-json/acx/v1/recognition/describe failed (502): <html>proxy-internal-detail</html>'),
      )
      .mockResolvedValueOnce(sampleResponse(regeneratedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^regenerate$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/could not generate|couldn.?t generate|unable to generate/i);
    expect(alert).not.toHaveTextContent(/proxy-internal-detail/i);
    // Previous draft leaves the suggest surface (isError short-circuits data);
    // Try again keeps the generation path, and the row inline editor remains the
    // manual path [INT-11].
    expect(screen.queryByText(draft)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again|retry/i })).toBeInTheDocument();

    // [TEST-15][BR-43] discrimination: presence alone does not pin onClick={generate}
    // on the error-branch Try again (removing the handler left this green). Click
    // it and require a third describeMedia call plus a recovered draft — same
    // wiring pin shape as 're-invokes generation when retry is pressed after a
    // failure'. Single-line: onClick={generate} removed from the isError Try again.
    fireEvent.click(screen.getByRole('button', { name: /try again|retry/i }));
    expect(await screen.findByText(regeneratedDraft)).toBeInTheDocument();
    expect(describeMock).toHaveBeenCalledTimes(3);
  });

  it('keeps focus inside the surface while generating, not on document.body [a11y][WBUX-5-S2C3A-BR-13][WBUX-5-S2C3B]', async () => {
    describeMock.mockReturnValue(new Promise<VisualFactsResponse>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    expect(await screen.findByRole('button', { name: /generating/i })).toBeDisabled();
    // Stands in for the browser blurring the control native `disabled` just applied.
    parkFocusOnBody();

    // [TEST-15] discrimination: goes red if useFocusPark / its isPending effect
    // (or its document focusout listener) is removed — focus stays on
    // document.body for the whole generation. Single-line: deleting the
    // useFocusPark(isPending, containerRef) call (or the hook's useEffect).
    // Also goes red if the container loses tabIndex={-1} (focus() is a no-op on
    // non-focusable divs in some agents; observed here: without tabIndex,
    // activeElement remains body).
    await waitFor(() => {
      expect(document.activeElement).not.toBe(document.body);
      expect(document.activeElement).toHaveClass('acx-media-selection__media-alt-suggest');
    });
  });

  it('names the pending park target explicitly so SR users hear a single generating cue [a11y][BR-38]', async () => {
    describeMock.mockReturnValue(new Promise<VisualFactsResponse>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    const generating = await screen.findByRole('button', { name: /generating/i });
    expect(generating).toBeDisabled();
    const park = generating.closest('.acx-media-selection__media-alt-suggest');
    expect(park).toBeTruthy();
    if (!(park instanceof HTMLElement)) {
      throw new Error('expected pending park container');
    }

    // [TEST-15] discrimination: pins the *computed accessible name*, not merely
    // aria-busy presence. Goes red if aria-label is removed from the pending
    // container (name falls back to empty ACCNAME for a generic div, or to a
    // name-from-contents stutter of button + live-region text when the region
    // is nested). Single-line: delete aria-label={…} from the isPending branch.
    // role="group" is required so aria-label is a permitted name (ARIA 1.2
    // prohibits author names on role=generic); jsdom ACCNAME still resolves
    // without it, so the role pin is the browser-truth guard.
    expect(park).toHaveAttribute('role', 'group');
    expect(park).toHaveAccessibleName('Generating…');
    expect(park).toHaveAttribute('aria-busy', 'true');
    // Park target must remain focusable for BR-13.
    expect(park).toHaveAttribute('tabindex', '-1');
  });

  it('keeps role=group on the draft host while idle (not only while accepting) [a11y][BR-56]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    // Idle draft-ready: Accept is available, not "Accepting draft…".
    const accept = await screen.findByRole('button', { name: /^accept$/i });
    expect(accept).not.toBeDisabled();

    const host = accept.closest('.acx-media-selection__media-alt-suggest');
    expect(host).toBeTruthy();
    if (!(host instanceof HTMLElement)) {
      throw new Error('expected idle draft host container');
    }

    // role is constant so park release cannot mutate the a11y tree. aria-label
    // stays accepting-only — idle has no busy name.
    // [TEST-15] discrimination: goes red if role reverts to isAccepting-only
    // (`role={isAccepting ? 'group' : undefined}`) — idle state loses the role.
    expect(host).toHaveAttribute('role', 'group');
    expect(host).not.toHaveAttribute('aria-busy');
    expect(host).not.toHaveAttribute('aria-label');
  });

  it('names the accepting park target with a permitted role [a11y][BR-56]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();

    const host = screen
      .getByRole('button', { name: /accepting draft/i })
      .closest('.acx-media-selection__media-alt-suggest');
    expect(host).toBeTruthy();
    if (!(host instanceof HTMLElement)) {
      throw new Error('expected accepting host container');
    }

    // Companion to the BR-38 generate pin: accepting host also carries aria-label
    // on a focus-park div and needs role="group" so the name is ARIA-legal.
    // [TEST-15] discrimination: goes red if role="group" is omitted while
    // isAccepting (or if aria-label is dropped). Single-line: delete role=…
    // from the data-branch host.
    expect(host).toHaveAttribute('role', 'group');
    expect(host).toHaveAccessibleName('Accepting draft…');
    expect(host).toHaveAttribute('aria-busy', 'true');
  });

  it('does not let a pending row reclaim body focus stranded by a sibling [a11y][BR-33]', async () => {
    // Row A generating (never settles). Row B Accept disable-blurs to body.
    // Without instance-scoped park, A's document focusout listener claims body
    // and focus jumps to A's container.
    describeMock.mockImplementation((mediaId: number) => {
      if (mediaId === 1) {
        return new Promise<VisualFactsResponse>(() => undefined);
      }
      return Promise.resolve(sampleResponse(`draft-for-${mediaId}`));
    });
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(
      <>
        <div data-testid="row-a">
          <MediaAltSuggest isDecorative={false} mediaId={1} />
        </div>
        <div data-testid="row-b">
          <MediaAltSuggest isDecorative={false} mediaId={2} />
        </div>
      </>,
    );

    const rowA = screen.getByTestId('row-a');
    const rowB = screen.getByTestId('row-b');

    // fireEvent.click does not move focus — focus explicitly so park ownership
    // and focusout origin match real pointer activation.
    const suggestA = within(rowA).getByRole('button', { name: /suggest alt text/i });
    suggestA.focus();
    fireEvent.click(suggestA);
    expect(await within(rowA).findByRole('button', { name: /generating/i })).toBeDisabled();

    const suggestB = within(rowB).getByRole('button', { name: /suggest alt text/i });
    suggestB.focus();
    fireEvent.click(suggestB);
    expect(await screen.findByText('draft-for-2')).toBeInTheDocument();
    const acceptB = within(rowB).getByRole('button', { name: /accept/i });
    acceptB.focus();
    fireEvent.click(acceptB);
    expect(await within(rowB).findByRole('button', { name: /accepting draft/i })).toBeDisabled();
    // Sibling Accept disable-blurs to body (jsdom stand-in). focusout target is
    // B's Accept — A's origin guard must refuse to park.
    parkFocusOnBody();

    await new Promise<void>((resolve) => {
      queueMicrotask(() => resolve());
    });

    // [TEST-15] discrimination: goes red if useFocusPark parks on any body-strand
    // without checking that the focusout target was inside this container —
    // single-line: drop the `node.contains(target)` origin guard in useFocusPark.
    expect(rowA.contains(document.activeElement)).toBe(false);
  });

  it('does not let an accepting row reclaim body focus stranded by a sibling [a11y][BR-33]', async () => {
    // Flipped aggressor: row A is accepting (park live via isAccepting), not
    // generating. The widened useFocusPark(isPending || isAccepting) surface is
    // unpinned by the generating-side BR-33 cases alone — if the origin guard
    // broke only for the accepting park, those stay green.
    //
    // Row A: draft ready → Accept (never settles). Row B: also draft → Accept
    // disable-blurs to body. A's park must refuse the foreign strand.
    describeMock.mockImplementation((mediaId: number) => {
      return Promise.resolve(sampleResponse(`draft-for-${mediaId}`));
    });
    // Both accepts never settle so row A stays in the accepting park for the
    // whole assertion window (mirrors the generating never-settle pattern).
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(
      <>
        <div data-testid="row-a">
          <MediaAltSuggest isDecorative={false} mediaId={1} />
        </div>
        <div data-testid="row-b">
          <MediaAltSuggest isDecorative={false} mediaId={2} />
        </div>
      </>,
    );

    const rowA = screen.getByTestId('row-a');
    const rowB = screen.getByTestId('row-b');

    const suggestA = within(rowA).getByRole('button', { name: /suggest alt text/i });
    suggestA.focus();
    fireEvent.click(suggestA);
    expect(await within(rowA).findByText('draft-for-1')).toBeInTheDocument();
    const acceptA = within(rowA).getByRole('button', { name: /accept/i });
    acceptA.focus();
    fireEvent.click(acceptA);
    expect(await within(rowA).findByRole('button', { name: /accepting draft/i })).toBeDisabled();

    const suggestB = within(rowB).getByRole('button', { name: /suggest alt text/i });
    suggestB.focus();
    fireEvent.click(suggestB);
    expect(await within(rowB).findByText('draft-for-2')).toBeInTheDocument();
    const acceptB = within(rowB).getByRole('button', { name: /accept/i });
    acceptB.focus();
    fireEvent.click(acceptB);
    expect(await within(rowB).findByRole('button', { name: /accepting draft/i })).toBeDisabled();
    // Sibling Accept disable-blurs to body (jsdom stand-in). focusout target is
    // B's Accept — accepting row A's origin guard must refuse to park.
    parkFocusOnBody();

    await new Promise<void>((resolve) => {
      queueMicrotask(() => resolve());
    });

    // [TEST-15] discrimination: goes red if useFocusPark parks on any body-strand
    // without checking that the focusout target was inside this container —
    // single-line: drop the `node.contains(target)` origin guard in useFocusPark.
    // Same mutation the generating BR-33 cases pin; this one puts the accepting
    // park in the aggressor role.
    expect(rowA.contains(document.activeElement)).toBe(false);
  });

  it('does not silently claim body focus when two rows are generating [a11y][BR-33]', async () => {
    // Design: neither row claims a body-strand that did not originate inside it.
    // Operator focus sits on an outside control, then falls to body — both rows
    // stay hands-off (no initiating-row claim for foreign strands).
    describeMock.mockReturnValue(new Promise<VisualFactsResponse>(() => undefined));
    renderSuggest(
      <>
        <div data-testid="row-a">
          <MediaAltSuggest isDecorative={false} mediaId={1} />
        </div>
        <div data-testid="row-b">
          <MediaAltSuggest isDecorative={false} mediaId={2} />
        </div>
        <button type="button">Outside</button>
      </>,
    );

    const rowA = screen.getByTestId('row-a');
    const rowB = screen.getByTestId('row-b');

    const suggestA = within(rowA).getByRole('button', { name: /suggest alt text/i });
    suggestA.focus();
    fireEvent.click(suggestA);
    const suggestB = within(rowB).getByRole('button', { name: /suggest alt text/i });
    suggestB.focus();
    fireEvent.click(suggestB);
    expect(await screen.findAllByRole('button', { name: /generating/i })).toHaveLength(2);

    // Leave both surfaces for a real outside control. Flush the focusout
    // microtask from the generating row *before* stranding Outside to body —
    // same-turn body park after a leave would race the leave's microtask
    // (activeElement already body) and look like a false reclaim. Real pointer
    // sequences separate those turns.
    const outside = screen.getByRole('button', { name: /^outside$/i });
    outside.focus();
    expect(outside).toHaveFocus();
    await new Promise<void>((resolve) => {
      queueMicrotask(() => resolve());
    });
    expect(outside).toHaveFocus();
    parkFocusOnBody();
    await new Promise<void>((resolve) => {
      queueMicrotask(() => resolve());
    });

    // [TEST-15] discrimination: goes red under the pre-BR-33 global park (any
    // pending instance reclaims any body-strand). With origin scoping, a strand
    // whose focusout target was outside both containers is not reclaimed.
    const active = document.activeElement;
    expect(rowA.contains(active)).toBe(false);
    expect(rowB.contains(active)).toBe(false);
  });

  it('restores accept-error focus on row B while row A is still generating [a11y][BR-33]', async () => {
    // Cross-row correctness: if A's park steals body after B's Accept disables,
    // B's ownsFocus gate sees focus inside A and skips the accept-error restore.
    describeMock.mockImplementation((mediaId: number) => {
      if (mediaId === 1) {
        return new Promise<VisualFactsResponse>(() => undefined);
      }
      return Promise.resolve(sampleResponse(`draft-for-${mediaId}`));
    });
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/2/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(
      <>
        <div data-testid="row-a">
          <MediaAltSuggest isDecorative={false} mediaId={1} />
        </div>
        <div data-testid="row-b">
          <MediaAltSuggest isDecorative={false} mediaId={2} />
        </div>
      </>,
    );

    const rowA = screen.getByTestId('row-a');
    const rowB = screen.getByTestId('row-b');

    const suggestA = within(rowA).getByRole('button', { name: /suggest alt text/i });
    suggestA.focus();
    fireEvent.click(suggestA);
    expect(await within(rowA).findByRole('button', { name: /generating/i })).toBeDisabled();

    const suggestB = within(rowB).getByRole('button', { name: /suggest alt text/i });
    suggestB.focus();
    fireEvent.click(suggestB);
    expect(await screen.findByText('draft-for-2')).toBeInTheDocument();
    const acceptB = within(rowB).getByRole('button', { name: /accept/i });
    acceptB.focus();
    fireEvent.click(acceptB);
    parkFocusOnBody();

    await screen.findByRole('alert');
    // [TEST-15] discrimination: goes red if pending row A parks on itself when
    // B disable-blurs to body — B's accept-error restore then sees active inside
    // A and refuses to move focus back to Accept. Single-line: drop the origin
    // guard in useFocusPark (global body reclaim).
    expect(within(rowB).getByRole('button', { name: /accept/i })).toHaveFocus();
    expect(rowA.contains(document.activeElement)).toBe(false);
  });

  it('retires a saved status message when focus leaves the idle surface [WBUX-5-S2C3A-BR-17][WBUX-5-S2C3B]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem());
    renderSuggest(
      <>
        <MediaAltSuggest isDecorative={false} mediaId={42} />
        <button type="button">Elsewhere</button>
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /accept/i }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/saved/i));
    await waitFor(() => expect(screen.getByRole('button', { name: /suggest alt text/i })).toHaveFocus());

    // Leave the surface without generating or dismissing — the message has been
    // announced; keeping "Alt text saved." forever collides with a later inline-
    // editor save status on the same row. Blur with relatedTarget so the
    // container's onBlur sees focus exiting (native .focus() on Elsewhere does
    // not reliably populate relatedTarget under jsdom).
    const elsewhere = screen.getByRole('button', { name: /^elsewhere$/i });
    fireEvent.blur(screen.getByRole('button', { name: /suggest alt text/i }), {
      relatedTarget: elsewhere,
    });

    // [TEST-15] discrimination: goes red if handleContainerBlur stops clearing
    // status on idle focus-leave, or if the idle branch omits onBlur. Single-line:
    // clearStatus() removed from the !data && !isPending && !isError guard.
    // No real elapsed time — event-driven retirement, not a timeout.
    // Region stays mounted (BR-32); cue text clears so a later inline-editor
    // save status on the same row is not colliding with a sticky "Alt text saved."
    await waitFor(() => expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(''));
  });

  // --- S2c-3c (part i): automatic length advisory after generation [A11Y-34] ---
  // Branch (c): the tool checks accessibility of the actual draft string after
  // generation and surfaces a non-blocking advisory. WCAG does not specify a
  // max alt length; the threshold is a recommended practical maximum.
  // Boundary decision: exclusive of the threshold — length > RECOMMENDED is
  // over; exactly RECOMMENDED is still within the recommendation.

  /** Comfortably under the recommended maximum (the default fixture draft). */
  const underThresholdDraft = draft;
  /** Exactly at the recommended maximum — must NOT warn (inclusive upper bound). */
  const atThresholdDraft = 'A'.repeat(RECOMMENDED_ALT_TEXT_MAX_LENGTH);
  /** One character past the recommended maximum — must warn. */
  const overThresholdDraft = 'A'.repeat(RECOMMENDED_ALT_TEXT_MAX_LENGTH + 1);
  /** Clearly over so length figures are unambiguous in copy. */
  const longGeneratedDraft = 'A'.repeat(200);

  /**
   * Visible length advisory only — not the polite status cue, which reuses
   * "recommended maximum" wording for SR parity on the same over-length path.
   */
  const getVisibleLengthAdvisory = (): HTMLElement => {
    const node = document.querySelector('.acx-media-selection__media-alt-length-advisory');
    if (!(node instanceof HTMLElement)) {
      throw new Error('expected visible length advisory element');
    }
    return node;
  };

  const queryVisibleLengthAdvisory = (): HTMLElement | null => {
    const node = document.querySelector('.acx-media-selection__media-alt-length-advisory');
    return node instanceof HTMLElement ? node : null;
  };

  it('surfaces a length advisory naming actual length and threshold on an over-length generated draft [A11Y-34][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(longGeneratedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(longGeneratedDraft);

    // [TEST-15] discrimination: goes red if no length check runs after generation
    // — the draft is shown with only the static "Drafted by AI" sentence, which
    // is branch (d) alone and gives the author no numbers for *this* draft.
    // Anchored full-string pin: substring toHaveTextContent('200') stayed green
    // under a ×10 magnitude bug ("2000 characters…") [S3-BR-02][TEST-15].
    const advisory = getVisibleLengthAdvisory();
    expect(advisory.textContent).toBe(formatAltLengthAdvisory(200));
    expect(advisory).toHaveTextContent(/recommended maximum/i);
    // Honesty: must not invent a WCAG maximum that does not exist.
    expect(advisory).not.toHaveTextContent(/wcag/i);
    expect(advisory).not.toHaveTextContent(/violat/i);
    expect(advisory).not.toHaveTextContent(/1\.1\.1/);
    // Advisory tells the author what to do, not only that something is long.
    expect(advisory).toHaveTextContent(/shorten|consider|cut/i);
  });

  it('does not show a length advisory for a draft under the recommended maximum [A11Y-34][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(underThresholdDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(underThresholdDraft);

    // [TEST-15] discrimination: goes red if the advisory always renders — a
    // checker that always warns is not a checker.
    expect(queryVisibleLengthAdvisory()).toBeNull();
  });

  it('treats exactly the recommended maximum as within bounds and threshold+1 as over [A11Y-34][S2c-3c][boundary]', async () => {
    // Boundary decision (exclusive over): length > RECOMMENDED warns;
    // length === RECOMMENDED does not. Pin both sides of the edge.
    describeMock.mockResolvedValueOnce(sampleResponse(atThresholdDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(atThresholdDraft);
    expect(queryVisibleLengthAdvisory()).toBeNull();

    // Fresh surface for the over side (reset via Dismiss → Suggest).
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    await screen.findByRole('button', { name: /suggest alt text/i });
    describeMock.mockResolvedValueOnce(sampleResponse(overThresholdDraft));
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(overThresholdDraft);

    // Word-boundary / full-string pins: '126' and '125' both appear inside '1260'
    // under a ×10 magnitude bug, so bare substring matchers stayed green [S3-BR-02].
    const advisory = getVisibleLengthAdvisory();
    expect(advisory.textContent).toBe(formatAltLengthAdvisory(RECOMMENDED_ALT_TEXT_MAX_LENGTH + 1));
  });

  it('re-evaluates the length advisory live as the author types in edit mode [A11Y-34][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(underThresholdDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);

    // Starts under — no advisory on the commit candidate.
    expect(queryVisibleLengthAdvisory()).toBeNull();

    // Type past the threshold: notice must appear for the string the author would commit.
    fireEvent.change(field, { target: { value: overThresholdDraft } });
    expect(getVisibleLengthAdvisory()).toBeInTheDocument();
    expect(getVisibleLengthAdvisory().textContent).toBe(
      formatAltLengthAdvisory(RECOMMENDED_ALT_TEXT_MAX_LENGTH + 1),
    );

    // Trim back under: notice must disappear (live re-evaluation, not one-shot).
    fireEvent.change(field, { target: { value: underThresholdDraft } });
    expect(queryVisibleLengthAdvisory()).toBeNull();

    // [TEST-15] discrimination: goes red if the check only runs on generation
    // (editDraft ignored) or only once (no re-eval on change).
  });

  it('keeps Accept enabled while the length advisory is showing [A11Y-36][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(longGeneratedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(longGeneratedDraft);
    expect(getVisibleLengthAdvisory()).toBeInTheDocument();

    // [TEST-15] discrimination: goes red if Accept is gated on length — a
    // checker that refuses to let the author proceed is worse than no check.
    // Long alt text is sometimes right; [A11Y-36] keeps accept/modify/reject
    // with the author.
    expect(screen.getByRole('button', { name: /^accept$/i })).not.toBeDisabled();
  });

  it('keeps Save enabled while the length advisory is showing in edit mode [A11Y-36][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(underThresholdDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);
    fireEvent.change(field, { target: { value: overThresholdDraft } });
    expect(getVisibleLengthAdvisory()).toBeInTheDocument();

    // [TEST-15] discrimination: goes red if Save is gated on length.
    expect(screen.getByRole('button', { name: /^save alt text$/i })).not.toBeDisabled();
  });

  it('references the length advisory from the edit textarea aria-describedby [a11y][A11Y-34][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(longGeneratedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);

    const describedBy = field.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const descriptionText = (describedBy ?? '')
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    // [TEST-15] discrimination: goes red if editDescribedBy is not extended with
    // the advisory id — sighted authors see the notice; SR authors only get
    // disclosure. Composition must keep the disclosure (and error when set).
    expect(descriptionText).toMatch(/drafted by ai/i);
    expect(descriptionText).toMatch(/recommended maximum/i);
    // Anchored digit pin — bare /200/ matches inside 2000 [S3-BR-02][TEST-15].
    expect(descriptionText).toMatch(/\b200\b/);
    expect(descriptionText).not.toMatch(/\b2000\b/);
  });

  it('keeps the save-error id in aria-describedby alongside the length advisory [a11y][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(longGeneratedDraft));
    correctMock.mockRejectedValueOnce(
      new Error(
        'Request to /wp-json/acx/v1/recognition/describe-history/42/correction failed (502): <html>proxy-internal-detail</html>',
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));
    await screen.findByRole('alert');

    const field = screen.getByLabelText(/edit draft alt text/i);
    const describedBy = field.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const descriptionText = (describedBy ?? '')
      .split(/\s+/)
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    // [TEST-15] discrimination: goes red if length advisory *replaces*
    // editDescribedBy instead of extending it — error id drops out of the list.
    expect(descriptionText).toMatch(/drafted by ai/i);
    expect(descriptionText).toMatch(/recommended maximum/i);
    expect(descriptionText).toMatch(/could not save|couldn.?t save|unable to save/i);
  });

  it('announces the length advisory once via the existing polite status region when a long draft lands [a11y][A11Y-19][S2c-3c]', async () => {
    describeMock.mockResolvedValue(sampleResponse(longGeneratedDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(longGeneratedDraft);

    const status = screen.getByTestId('media-alt-suggest-status');
    // Composed with or following the ready cue — SR users get the numbers without
    // a second live region ([A11Y-19] / BR-32 / BR-37).
    // Full-string pin: substring /200/ stayed green under length*10 [S3-BR-02].
    await waitFor(() => {
      expect(status.textContent).toBe(formatOverLengthReadyAnnouncement(200));
    });
    // Exactly one role="status" in this component's output on the over-length path.
    // [TEST-15] discrimination: goes red if a second live region is added for the
    // advisory (e.g. role="status" on the notice) or if announceStatus is skipped
    // for long drafts.
    expect(screen.getAllByRole('status')).toHaveLength(1);
    // Not an alert — assertive channel is for save failures.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('announces length advisory once on threshold crossing while typing — not every keystroke [WBUX-5-S2C4A-BR-01]', async () => {
    // Visible advisory stays keystroke-live; only the polite announcement is
    // crossing-gated. A region that fires per character is worse than silence.
    describeMock.mockResolvedValue(sampleResponse(underThresholdDraft));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);
    const status = screen.getByTestId('media-alt-suggest-status');

    // Cross under → over: one announcement with actual length + threshold.
    fireEvent.change(field, { target: { value: overThresholdDraft } });
    expect(getVisibleLengthAdvisory()).toBeInTheDocument();
    await waitFor(() => {
      expect(status.textContent).toBe(formatAltLengthAdvisory(RECOMMENDED_ALT_TEXT_MAX_LENGTH + 1));
    });
    const overMessage = status.textContent ?? '';
    const overSeq = status.getAttribute('data-announce-seq');

    // Still over, longer: must NOT re-announce (one-shot on crossing only).
    const longerStillOver = overThresholdDraft + 'Z';
    fireEvent.change(field, { target: { value: longerStillOver } });
    // Visible advisory re-evaluates live (keystroke-live UI).
    expect(getVisibleLengthAdvisory().textContent).toBe(formatAltLengthAdvisory(longerStillOver.length));
    // Polite region must not fire again for a same-side keystroke.
    expect(status.textContent).toBe(overMessage);
    expect(status.getAttribute('data-announce-seq')).toBe(overSeq);

    // Cross over → under: announce once that we are within bounds.
    fireEvent.change(field, { target: { value: underThresholdDraft } });
    expect(queryVisibleLengthAdvisory()).toBeNull();
    await waitFor(() => {
      expect(status).toHaveTextContent(/within|recommended maximum/i);
      expect(status).not.toHaveTextContent(String(RECOMMENDED_ALT_TEXT_MAX_LENGTH + 1));
    });
    const underMessage = status.textContent ?? '';
    const underSeq = status.getAttribute('data-announce-seq');

    // Still under, shorter: must NOT re-announce.
    fireEvent.change(field, { target: { value: underThresholdDraft.slice(0, 10) } });
    expect(status.textContent).toBe(underMessage);
    expect(status.getAttribute('data-announce-seq')).toBe(underSeq);

    // Visible advisory element must not itself be a second live region.
    fireEvent.change(field, { target: { value: overThresholdDraft } });
    const advisory = getVisibleLengthAdvisory();
    expect(advisory).not.toHaveAttribute('role', 'status');
    expect(advisory).not.toHaveAttribute('aria-live');
    expect(screen.getAllByRole('status')).toHaveLength(1);
  });

  it('exports a single named recommended-max constant used as the threshold [S2c-3c]', () => {
    // [TEST-15] discrimination: goes red if the literal is scattered / the export
    // is dropped — callers and tests share one named source of truth.
    expect(RECOMMENDED_ALT_TEXT_MAX_LENGTH).toBe(125);
    expect(Number.isInteger(RECOMMENDED_ALT_TEXT_MAX_LENGTH)).toBe(true);
  });

  it('pins length formatter copy with argument order (draft length first, max second) [S6-A-07][TEST-15]', () => {
    // Literal-copy pins: comparisons against formatAltLengthAdvisory(n) itself move
    // with an in-formatter %1$d/%2$d swap and stay green. These strings name the
    // business order: actual draft length is 200; recommended maximum is 125.
    expect(formatAltLengthAdvisory(200)).toBe(
      'This draft is 200 characters. The recommended maximum is 125 characters so screen readers can convey the description without excessive length. Consider shortening it before saving.',
    );
    expect(formatOverLengthReadyAnnouncement(200)).toBe(
      'Draft ready. Review before saving. This draft is 200 characters; recommended maximum is 125. Consider shortening it.',
    );
  });

  it('enqueues exactly one correction for two same-tick Accept activations [S2C3A-BR-16]', async () => {
    // disabled={isAccepting} only paints after the next render. fireEvent.click
    // alone flushes a render between clicks and hits disabled — proving nothing.
    // Same-tick route (BR-81 pattern): two native clicks inside one act so React
    // batches and the disabled attribute never lands between them.
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    const accept = await screen.findByRole('button', { name: /accept/i });

    act(() => {
      accept.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      accept.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    await waitFor(() => expect(correctMock.mock.calls.length).toBeGreaterThanOrEqual(1));
    // Brief settle so a second in-flight call can register if the guard is missing.
    await new Promise((resolve) => setTimeout(resolve, 50));
    // [TEST-15] discrimination: goes red if the acceptingRef guard is removed
    // from accept() — both activations enqueue a correction before isAccepting paints.
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, draft);
  });

  it('enqueues exactly one correction for two same-tick Save activations [S2C3A-BR-16]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    const save = screen.getByRole('button', { name: /^save alt text$/i });

    act(() => {
      save.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      save.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    await waitFor(() => expect(correctMock.mock.calls.length).toBeGreaterThanOrEqual(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, editedDraft);
  });

  it('refuses Accept when committedAlt moved under a sticky draft [S2c-4b-i]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    const { client, rerender } = renderSuggest(
      <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Existing alt" />,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // Sibling committed while draft was sticky — prop updates to the new truth.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Sibling committed this." />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/changed/i);
    expect(correctMock).not.toHaveBeenCalled();
    // Draft kept; Dismiss remains reachable.
    expect(screen.getByText(draft)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).not.toBeDisabled();
  });

  it('does not write when onCommitStart refuses the lock claim [S2c-4b-ii BR-01]', async () => {
    // WBUX-5-S2C4B-BR-05: a refused claim must raise a distinct assertive message
    // (not silent, not ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE). Headline [TEST-06].
    // Predict RED: no role=alert, or alert text equals the CAS conflict copy.
    describeMock.mockResolvedValue(sampleResponse());
    const onCommitStart = vi.fn((): boolean => false);
    renderSuggest(
      <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Existing alt" onCommitStart={onCommitStart} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    expect(onCommitStart).toHaveBeenCalledTimes(1);
    expect(correctMock).not.toHaveBeenCalled();
    // Draft kept; Dismiss remains reachable [rg-003].
    expect(screen.getByText(draft)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).not.toBeDisabled();

    // [TEST-15] discrimination: passes only after a claim-refusal alert exists
    // with copy distinct from the CAS "changed while you were reviewing" message.
    const alert = await screen.findByRole('alert');
    expect(alert.textContent ?? '').not.toBe(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);
    expect(alert).toHaveTextContent(/try again|busy|in progress|wait/i);
    expect(alert).not.toHaveTextContent(/changed while you were reviewing/i);
  });

  it('does not write when onCommitStart refuses the lock claim on Save edit [S2c-4b-ii BR-01][WBUX-5-S2C4B-BR-05]', async () => {
    // Third call site (saveEdit). Same assertion contract as Accept refusal.
    describeMock.mockResolvedValue(sampleResponse());
    const onCommitStart = vi.fn((): boolean => false);
    renderSuggest(
      <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Existing alt" onCommitStart={onCommitStart} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    fireEvent.change(await screen.findByLabelText(/edit draft alt text/i), {
      target: { value: editedDraft },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save alt text$/i }));

    expect(onCommitStart).toHaveBeenCalledTimes(1);
    expect(correctMock).not.toHaveBeenCalled();
    // Buffer kept; Cancel remains reachable [rg-003].
    expect(screen.getByRole('textbox', { name: /edit draft alt text/i })).toHaveValue(editedDraft);
    expect(screen.getByRole('button', { name: /cancel edit/i })).not.toBeDisabled();

    const alert = await screen.findByRole('alert');
    expect(alert.textContent ?? '').not.toBe(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);
    expect(alert).toHaveTextContent(/try again|busy|in progress|wait/i);
    expect(alert).not.toHaveTextContent(/changed while you were reviewing/i);
  });

  it('does not clear a pre-existing conflict message when onCommitStart refuses [WBUX-5-S2C4B-BR-05][RLSE-05]', async () => {
    // setConflictMessage(null) must run only after a successful claim — a refusal
    // must not wipe a warning the operator has not read yet.
    // [TEST-15] discrimination: goes RED if clear is still above the claim.
    describeMock.mockResolvedValue(sampleResponse());
    const onCommitStart = vi.fn((): boolean => false);
    const { client, rerender } = renderSuggest(
      <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Existing alt" onCommitStart={onCommitStart} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    // Trigger a genuine CAS conflict first so a conflict message is on screen.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltSuggest isDecorative={false}
          mediaId={42}
          committedAlt="Sibling committed this."
          onCommitStart={onCommitStart}
        />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    const casAlert = await screen.findByRole('alert');
    expect(casAlert).toHaveTextContent(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);

    // Restore committedAlt so CAS would pass, then refuse the lock claim.
    // The CAS message must survive the refused claim (clear only after claim succeeds).
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Existing alt" onCommitStart={onCommitStart} />
      </QueryClientProvider>,
    );
    // Baseline was captured at generate as "Existing alt"; prop is again "Existing alt"
    // so CAS passes and we reach the claim — which refuses.
    // Note: after the CAS refusal, baseline is still "Existing alt". Good.
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    expect(onCommitStart).toHaveBeenCalled();
    expect(correctMock).not.toHaveBeenCalled();
    // Pre-existing CAS warning still on screen — must not be wiped by the refusal.
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE);
  });

  // ---------------------------------------------------------------------------
  // WBUX-5-S2C3C-BR-01 — mark decorative (front-end half, slice S2c-3c)
  // ---------------------------------------------------------------------------

  it('marks an image decorative with empty alt_text and decorative:true [WBUX-5-S2C3C-BR-01][TEST-06]', async () => {
    // Headline: the deliberate decorative control must issue both wire signals.
    // Predict RED: no control matching /decorative|screen reader/i, or control
    // present but correctMock never called with ('', { decorative: true }).
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem(''));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    const decorativeControl = screen.getByRole('button', {
      name: /decorative|screen reader|announce nothing|skip/i,
    });
    fireEvent.click(decorativeControl);

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    // [TEST-15] discrimination: goes RED if decorative is omitted, if alt_text
    // is non-empty, or if the ordinary Accept path is reused without the flag.
    expect(correctMock).toHaveBeenCalledWith(42, '', { decorative: true });
  });

  it('does not send decorative:true when an ordinary empty Save is attempted [WBUX-5-S2C3C-BR-01]', async () => {
    // The :311-312 non-empty gates protect Accept/Save. Clearing the box and
    // hitting Save must not become an ambiguous "mark decorative" wire signal.
    // [TEST-15] discrimination: goes RED if saveEdit (or Accept) sends
    // decorative:true for an empty ordinary commit.
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^edit draft$/i }));
    const field = await screen.findByLabelText(/edit draft alt text/i);
    fireEvent.change(field, { target: { value: '' } });

    const save = screen.getByRole('button', { name: /^save alt text$/i });
    expect(save).toBeDisabled();
    // fireEvent still synthesises click on disabled controls in jsdom — assert
    // the handler does not issue a decorative correction either way.
    fireEvent.click(save);

    expect(correctMock).not.toHaveBeenCalled();
    // If a future regression re-enables empty Save and somehow writes, it must not
    // be a decorative mark — no call may carry decorative:true.
    const decorativeCalls = correctMock.mock.calls.filter((call) => {
      const options = call[2];
      return (
        options != null &&
        typeof options === 'object' &&
        Object.prototype.hasOwnProperty.call(options, 'decorative') &&
        Reflect.get(options, 'decorative') === true
      );
    });
    expect(decorativeCalls).toHaveLength(0);
  });

  it('surfaces a 400 decorative contradiction on the assertive channel and keeps the draft [WBUX-5-S2C3C-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockImplementation(() =>
      Promise.reject(
        new Error(
          'Request to .../correction failed (400): {"code":"description_correction_failed","message":"Decorative images must have empty alt text.","data":{"status":400}}',
        ),
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    const decorativeBtn = screen.getByRole('button', {
      name: /decorative|screen reader|announce nothing|skip/i,
    });
    decorativeBtn.focus();
    fireEvent.click(decorativeBtn);
    // Stands in for the browser blurring the control isMarkingDecorative just disabled
    // (same pattern as Accept focus-restore [WBUX-5-S2C3A-BR-18]).
    parkFocusOnBody();

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    const alert = await screen.findByRole('alert');
    // Prefer server message when structured; never invent a silent success.
    // [TEST-15] discrimination: goes RED if the failure is silent or only polite.
    expect(alert).toHaveTextContent(/decorative images must have empty alt text/i);
    // Draft kept — operator can recover without regenerating.
    expect(screen.getByText(draft)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).not.toBeDisabled();
    // Focus returns to the decorative control that failed — not Accept (which
    // would commit the AI draft the operator deliberately avoided) [S6-A-05][A11Y-11].
    // Against baseline this fails with focus on Accept.
    expect(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    ).toHaveFocus();
  });

  it('gives the decorative control an accessible name and keeps it keyboard-reachable [WBUX-5-S2C3C-BR-01][A11Y-15]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    const control = screen.getByRole('button', {
      name: /decorative|screen reader|announce nothing|skip/i,
    });
    // Real button with a non-empty accessible name; not aria-hidden; not disabled
    // while idle (so Tab can reach it).
    expect(buttonAccessibleName(control).length).toBeGreaterThan(0);
    expect(control).not.toHaveAttribute('aria-hidden', 'true');
    expect(control).not.toBeDisabled();
    control.focus();
    expect(control).toHaveFocus();
  });

  it('disables the decorative control while a commit is in flight [WBUX-5-S2C3C-BR-01]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    expect(await screen.findByRole('button', { name: /accepting draft/i })).toBeDisabled();

    // Same native-disabled discipline as Accept/Save (useFocusPark / BR-13/56).
    expect(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    ).toBeDisabled();
  });

  it('keeps Accept labelled Accept (disabled) while Mark as decorative is in flight [S6-A-04][INT-08]', async () => {
    // Shared isAccepting/isPending must not relabel Accept to "Accepting draft..."
    // when the operator deliberately chose decorative instead.
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockReturnValue(new Promise<DescriptionHistoryItem>(() => undefined));
    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );
    expect(await screen.findByRole('button', { name: /marking as decorative/i })).toBeDisabled();

    // Accept stays named Accept (disabled), never "Accepting draft...".
    expect(screen.getByRole('button', { name: /^accept$/i })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /accepting draft/i })).not.toBeInTheDocument();
  });

  it('CAS baseline at draft arrival tracks live committedAlt, not click-time closure [S2c-4b-ii BR-02]', async () => {
    // generate onSuccess must read the committed value as of draft arrival via
    // committedAltRef (effect-mirrored). A click-time closure over the prop would
    // pin "At click" and refuse Accept after the prop moved during generate.
    let resolveDescribe!: (value: VisualFactsResponse) => void;
    describeMock.mockReturnValue(
      new Promise<VisualFactsResponse>((resolve) => {
        resolveDescribe = resolve;
      }),
    );
    correctMock.mockResolvedValue(sampleHistoryItem(draft));
    const { client, rerender } = renderSuggest(
      <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="At click" />,
    );

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    expect(await screen.findByRole('button', { name: /generating/i })).toBeDisabled();

    // Sibling (or cache) updates committed alt while generation is in flight.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt="Arrived during generate" />
      </QueryClientProvider>,
    );

    resolveDescribe(sampleResponse());
    await screen.findByText(draft);

    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(42, draft);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // S7-BR-01 / HARM-BR-02 — decorative mark must reconcile workbench cache
  // ---------------------------------------------------------------------------

  it('patches workbench cache to empty alt + complete after Mark as decorative [S7-BR-01][HARM-BR-02]', async () => {
    // Headline defect: markDecorative awaited correctDescriptionHistoryItem then
    // only reset/announce — patchWorkbenchRowAlt and invalidateMediaStats never
    // ran, so the co-mounted row kept altText 'Bridge at dusk' / status complete
    // while the server held alt='' + decorative marker.
    //
    // [TEST-15] discrimination: goes RED if success still bypasses the hook's
    // reconciliation (cache stays prior alt) or if status derives from alt alone
    // (empty → 'missing' while class-api.php:338 says decorative → 'complete').
    const priorAlt = 'Bridge at dusk';
    correctMock.mockResolvedValue(sampleHistoryItem('', true));
    const { client } = renderLiveAltRow(priorAlt, 'complete');

    // Precondition: InlineEditor shows the committed prior alt (stale after defect).
    expect(screen.getByText(priorAlt)).toBeInTheDocument();
    expect(screen.getByTestId('live-row-status')).toHaveTextContent('complete');
    expect(cachedRow(client)?.altText).toBe(priorAlt);
    expect(cachedRow(client)?.status).toBe('complete');

    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(42, '', { decorative: true });

    // Cache contract: empty alt normalizes to null (class-api.php:346 emits null,
    // never ''); decorative:true → complete (class-api.php:338).
    await waitFor(() => {
      expect(cachedRow(client)?.altText).toBeNull();
      expect(cachedRow(client)?.status).toBe('complete');
    });

    // Integration symptom (HARM-BR-02): row no longer renders the destroyed alt.
    await waitFor(() => {
      expect(screen.queryByText(priorAlt)).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('live-row-status')).toHaveTextContent('complete');
    // Success still announced — reconciliation must not silence the path.
    await waitFor(() => {
      expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(/marked as decorative/i);
    });
  });

  it('derives workbench status from alt OR decorative (two-fact rule) [class-api.php:338][TEST-15]', async () => {
    // Triple: decorative empty-alt → complete; non-empty alt → complete;
    // non-decorative empty-alt result → missing. Neither alt-only nor
    // decorative-only rule passes all three.

    // 1) Decorative success with empty alt → complete.
    // Seed status=missing so waitFor observes a real transition to complete
    // (seeding complete made the gate true on the first synchronous check).
    correctMock.mockResolvedValueOnce(sampleHistoryItem('', true));
    const decorativeCase = renderLiveAltRow('Prior decorative', 'missing');
    expect(cachedRow(decorativeCase.client)?.status).toBe('missing');
    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );
    await waitFor(() => {
      expect(cachedRow(decorativeCase.client)?.status).toBe('complete');
      expect(cachedRow(decorativeCase.client)?.altText).toBeNull();
      expect(cachedRow(decorativeCase.client)?.isDecorative).toBe(true);
    });
    decorativeCase.unmount();

    // 2) Ordinary Accept with non-empty alt → complete
    describeMock.mockResolvedValueOnce(sampleResponse());
    correctMock.mockResolvedValueOnce(sampleHistoryItem(draft));
    const clientAlt = buildClient();
    const initialAlt = seedWorkbenchRow(clientAlt, null, 'missing');
    const altCase = render(
      <QueryClientProvider client={clientAlt}>
        <LiveWorkbenchAltRow initial={initialAlt} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await waitFor(() => {
      expect(cachedRow(clientAlt)?.altText).toBe(draft);
      expect(cachedRow(clientAlt)?.status).toBe('complete');
    });
    altCase.unmount();

    // 3) PARTIAL after decorative attempt (marker not stored, empty stored alt)
    // → missing. Discriminates against a decorative-only rule that would mark
    // every decorative-flagged request complete even when the marker failed.
    const partialMessage =
      'Alt text was saved, but the decorative marker could not be stored. Please try again.';
    correctMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: '' , is_decorative: false },
        })}`,
      ),
    );
    const partialCase = renderLiveAltRow('Prior partial', 'complete');
    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );
    await waitFor(() => {
      expect(cachedRow(partialCase.client)?.altText).toBeNull();
      expect(cachedRow(partialCase.client)?.status).toBe('missing');
    });
    partialCase.unmount();
  });

  it('allows decorative retry after PARTIAL without false CAS conflict [S6-A-02][rg-002]', async () => {
    // Suggest → draft captures CAS baseline as prior alt. PARTIAL reconciles
    // cache to empty; without re-seeding baseline, a second Mark as decorative
    // is refused as a sibling conflict while the server asked to retry.
    const priorAlt = 'Prior for retry';
    const partialMessage =
      'Alt text was saved, but the decorative marker could not be stored. Please try again.';
    correctMock
      .mockRejectedValueOnce(
        new Error(
          `Request to /correction failed (500): ${JSON.stringify({
            code: 'description_correction_partial',
            message: partialMessage,
            data: { status: 500, stored_alt_text: '' , is_decorative: false },
          })}`,
        ),
      )
      .mockResolvedValueOnce(sampleHistoryItem(''));
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveAltRow(priorAlt, 'complete');

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/decorative marker could not be stored/i);
    // PARTIAL rewrote the cache; committedAlt prop is now null/empty.
    await waitFor(() => {
      expect(cachedRow(client)?.altText).toBeNull();
    });

    // Second attempt must reach the wire — not the false sibling-conflict branch.
    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(ALT_SUGGEST_COMMIT_CONFLICT_MESSAGE)).not.toBeInTheDocument();
  });

  it('reconciles cache from stored_alt_text on decorative PARTIAL failure [S7-BR-02]', async () => {
    // Server can blank alt (verified write) then refuse the decorative marker,
    // returning description_correction_partial + stored_alt_text ''. The
    // decorative bypass only setConflictMessage and left the cache on 'Prior'.
    //
    // [TEST-15] discrimination: goes RED if PARTIAL is ignored on the decorative
    // catch (cache stays 'Prior') or if the assertive alert is swallowed.
    const priorAlt = 'Prior';
    const partialMessage =
      'Alt text was saved, but the decorative marker could not be stored. Please try again.';
    correctMock.mockRejectedValueOnce(
      new Error(
        `Request to /correction failed (500): ${JSON.stringify({
          code: 'description_correction_partial',
          message: partialMessage,
          data: { status: 500, stored_alt_text: '' , is_decorative: false },
        })}`,
      ),
    );
    const { client } = renderLiveAltRow(priorAlt, 'complete');

    expect(cachedRow(client)?.altText).toBe(priorAlt);
    expect(screen.getByText(priorAlt)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: /decorative|screen reader|announce nothing|skip/i }),
    );

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(42, '', { decorative: true });

    // Cache must reflect the verified blank write even though the mark failed.
    // Empty stored_alt_text normalizes to null (class-api.php:346 contract).
    await waitFor(() => {
      expect(cachedRow(client)?.altText).toBeNull();
      expect(cachedRow(client)?.status).toBe('missing');
    });

    // Assertive alert must surface the server PARTIAL message exclusively —
    // only it tells the operator the alt WAS written and destroyed. Alternation
    // with the generic fallback accepted the failure mode [S6-A-06][TEST-15].
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(partialMessage);
    expect(alert).not.toHaveTextContent(/could not mark as decorative/i);
    // Live row no longer advertises the destroyed prior alt.
    await waitFor(() => {
      expect(screen.queryByText(priorAlt)).not.toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // A-02 — un-mark decorative (inverse control at both render sites)
  // ---------------------------------------------------------------------------

  it('shows un-mark control only when isDecorative at the idle (no-draft) site [A-02][INT-06]', () => {
    // Idle branch is the second render site (Suggest + decorative, no draft).
    // [TEST-15]: goes RED if MARK_DECORATIVE_LABEL is shown when isDecorative,
    // or if UNMARK_DECORATIVE_LABEL appears when not marked.
    const { unmount } = renderSuggest(
      <MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />,
    );
    expect(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: MARK_DECORATIVE_LABEL })).not.toBeInTheDocument();
    unmount();

    renderSuggest(<MediaAltSuggest isDecorative={false} mediaId={42} committedAlt={null} />);
    expect(screen.getByRole('button', { name: MARK_DECORATIVE_LABEL })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: UNMARK_DECORATIVE_LABEL })).not.toBeInTheDocument();
  });

  it('shows un-mark control at the draft review site when isDecorative [A-02][INT-06]', async () => {
    // Draft branch is the first render site (Accept / Edit / decorative / Dismiss).
    describeMock.mockResolvedValue(sampleResponse());
    renderSuggest(<MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    expect(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: MARK_DECORATIVE_LABEL })).not.toBeInTheDocument();
  });

  it('un-mark posts decorative:false with empty alt from the idle site [A-02][INT-09]', async () => {
    // [TEST-15]: goes RED if un-mark still posts decorative:true, omits the
    // flag, or sends a non-empty alt.
    correctMock.mockResolvedValue(sampleHistoryItem('', false));
    renderSuggest(<MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(42, '', { decorative: false });
  });

  it('un-mark posts decorative:false with empty alt from the draft review site [A-02]', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    correctMock.mockResolvedValue(sampleHistoryItem('', false));
    renderSuggest(<MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    fireEvent.click(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(42, '', { decorative: false });
  });

  it('un-mark with a real committedAlt preserves that alt in the request [data-loss][TEST-15]', async () => {
    // Precondition: a row can hold non-empty alt AND isDecorative true (server
    // partial-failure / existing PHP fixture). Un-mark must clear the marker
    // only — not blank the description. Against current code this fails with
    // altText: '' because toggleDecorative always sends empty alt on both arms.
    const committed = 'A stone bridge over a calm river at dusk.';
    correctMock.mockResolvedValue(sampleHistoryItem(committed, false));
    renderSuggest(
      <MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={committed} />,
    );

    fireEvent.click(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL }));

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(correctMock).toHaveBeenCalledWith(42, committed, { decorative: false });
  });

  it('surfaces un-mark failure on the assertive channel and returns focus to the control [A-02][A11Y-11]', async () => {
    // Success path is covered; onError for un-mark was unpinned — alert copy
    // and focus restore both untested. Mirror the mark-failure pattern.
    correctMock.mockImplementation(() =>
      Promise.reject(
        new Error(
          'Request to .../correction failed (500): {"code":"description_correction_failed","message":"Could not clear the decorative marker.","data":{"status":500}}',
        ),
      ),
    );
    renderSuggest(<MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />);

    const unmarkBtn = screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL });
    unmarkBtn.focus();
    fireEvent.click(unmarkBtn);
    parkFocusOnBody();

    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    const alert = await screen.findByRole('alert');
    // Prefer server message when structured; fallback is un-mark-specific.
    expect(alert).toHaveTextContent(/could not clear the decorative marker/i);
    expect(
      screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL }),
    ).toHaveFocus();
  });

  it('keeps the un-mark busy label when isDecorative flips mid-flight [A11Y-02][TEST-15]', async () => {
    // toggleDecorative captures direction for announceStatus, but busy button /
    // host labels read live isDecorative. A cache patch (or parent re-render)
    // can flip the prop while isMarkingDecorative is still true — AT then hears
    // the opposite operation. Hold the mutation pending and flip the prop.
    let resolveCorrect!: (value: DescriptionHistoryItem) => void;
    correctMock.mockReturnValue(
      new Promise<DescriptionHistoryItem>((resolve) => {
        resolveCorrect = resolve;
      }),
    );
    const client = buildClient();
    const { rerender } = renderSuggest(
      <MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />,
      client,
    );

    fireEvent.click(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL }));
    expect(await screen.findByRole('button', { name: /removing decorative mark/i })).toBeDisabled();

    // Mid-flight: parent re-renders with isDecorative false (success-path cache
    // patch shape) while the local busy flag is still set.
    rerender(
      <QueryClientProvider client={client}>
        <MediaAltSuggest isDecorative={false} mediaId={42} committedAlt={null} />
      </QueryClientProvider>,
    );

    // [TEST-15]: live-prop labels flip to "Marking as decorative…" — wrong direction.
    expect(screen.getByRole('button', { name: /removing decorative mark/i })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /marking as decorative/i })).not.toBeInTheDocument();

    resolveCorrect(sampleHistoryItem('', false));
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
  });

  it('announces un-mark success pointing at the missing-alt to-do list [A-02][INT-06]', async () => {
    correctMock.mockResolvedValue(sampleHistoryItem('', false));
    renderSuggest(<MediaAltSuggest isDecorative={true} mediaId={42} committedAlt={null} />);

    fireEvent.click(screen.getByRole('button', { name: UNMARK_DECORATIVE_LABEL }));

    await waitFor(() => {
      expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(
        UNMARK_DECORATIVE_SUCCESS_MESSAGE,
      );
    });
    expect(screen.getByTestId('media-alt-suggest-status')).toHaveTextContent(/to-do list|missing/i);
  });
});
