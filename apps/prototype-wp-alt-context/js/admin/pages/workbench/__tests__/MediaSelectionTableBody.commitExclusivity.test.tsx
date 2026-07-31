/**
 * S2c-4b-i co-mounting proofs: compare-and-swap on committed alt + in-flight
 * exclusivity between MediaAltInlineEditor and MediaAltSuggest on one row.
 *
 * Isolated component tests cannot express "the sibling committed underneath me"
 * — these mount MediaSelectionTableBody with items driven from the workbench
 * cache so useCorrectMediaAlt's row patch is live committed truth.
 */
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { correctDescriptionHistoryItem, describeMedia } from '../../../api/describeApi';
import type { DescriptionHistoryItem, VisualFactsResponse } from '../../../api/describeApi';
import { queryKeys } from '../../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../../api/workbenchMediaApi';
import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { MediaSelectionTableBody, useRowCommitLock } from '../MediaSelectionTableBody';

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
const operatorAlt = 'Operator-authored alt that must not be overwritten.';
const existingAlt = 'Existing alt';

const workbenchKey = queryKeys.media.workbenchPage({ page: 1, perPage: 20, status: 'missing' });

const seedItem = (altText: string | null = existingAlt): WorkbenchMediaItem => ({
  id: 42,
  title: 'Bridge',
  status: altText && altText.trim() !== '' ? 'complete' : 'missing',
  thumbnailUrl: null,
  altText,
  isDecorative: false,
  editUrl: null,
  tags: [],
  mimeType: 'image/jpeg',
  dimensions: { width: 800, height: 600 },
  updatedAt: '2026-07-28T12:00:00Z',
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

const successItem = (mediaId: number, altText: string): DescriptionHistoryItem =>
  ({
    media_id: mediaId,
    title: 'Bridge',
    mime_type: 'image/jpeg',
    current_alt_text: altText,
    generated_alt_text: null,
    provenance: null,
    human_edit: { alt_text: altText, edited_at: '2026-07-28 12:00:00', user_id: 7 },
    run_status: null,
  }) as unknown as DescriptionHistoryItem;

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

/**
 * Real row surface with items observed from the workbench cache so a successful
 * correction (editor or Suggest) re-renders both surfaces with live item.altText.
 */
const LiveWorkbenchRow = ({ initialItem }: { initialItem: WorkbenchMediaItem }): ReactElement => {
  // Query key is the workbench page only — patches from useCorrectMediaAlt
  // update that cache entry. initialItem seeds once via initialData / setQueryData;
  // it is not a key dependency (would force remounts on every parent render).
  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- seed only; live truth is cache patches
  const { data } = useQuery({
    queryKey: workbenchKey,
    queryFn: (): Promise<WorkbenchMediaResponse> =>
      Promise.resolve({ items: [initialItem], total: 1, totalPages: 1 }),
    initialData: { items: [initialItem], total: 1, totalPages: 1 },
    staleTime: Infinity,
  });
  const items = data?.items ?? [];
  return (
    <table>
      <tbody>
        <MediaSelectionTableBody
          items={items}
          isLoading={false}
          detailIsLoading={false}
          onToggleRow={() => undefined}
          selection={{}}
        />
      </tbody>
    </table>
  );
};

const renderLiveRow = (initialItem: WorkbenchMediaItem = seedItem()) => {
  const client = buildClient();
  client.setQueryData<WorkbenchMediaResponse>(workbenchKey, {
    items: [initialItem],
    total: 1,
    totalPages: 1,
  });
  const view = render(
    <QueryClientProvider client={client}>
      <LiveWorkbenchRow initialItem={initialItem} />
    </QueryClientProvider>,
  );
  return { client, ...view };
};

const cachedAlt = (client: QueryClient): string | null | undefined =>
  client.getQueryData<WorkbenchMediaResponse>(workbenchKey)?.items.find((i) => i.id === 42)?.altText;

describe('MediaSelectionTableBody — commit exclusivity [S2c-4b-i]', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    correctMock.mockImplementation((mediaId, altText) => Promise.resolve(successItem(mediaId, altText)));
  });

  it('[TEST-06] headline: generate draft, save different text via editor, Accept refuses and keeps operator text', async () => {
    // Predicted RED (pre-CAS): Accept stays enabled, commits the stale AI draft
    // over the operator's just-saved text — correctMock called a second time
    // with `draft`, and cached altText becomes the draft.
    // Expected RED message shape:
    //   expect(correctMock).toHaveBeenCalledTimes(1) // received 2
    //   and/or expect(cachedAlt).toBe(operatorAlt) // received draft
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    expect(screen.getByRole('button', { name: /^accept$/i })).not.toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(cachedAlt(client)).toBe(operatorAlt));
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, operatorAlt);

    // Stale Accept is still present with the AI draft — must not overwrite.
    expect(screen.getByText(draft)).toBeInTheDocument();
    const accept = screen.getByRole('button', { name: /^accept$/i });
    expect(accept).not.toBeDisabled();
    fireEvent.click(accept);

    // Refusal: no second write; cache keeps the operator value.
    await screen.findByRole('alert');
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).not.toHaveBeenCalledWith(42, draft);
    expect(cachedAlt(client)).toBe(operatorAlt);
    // Draft kept so the operator can decide; Dismiss remains reachable.
    expect(screen.getByText(draft)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /dismiss/i })).not.toBeDisabled();
    // Assertive channel (not the polite row region).
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/changed/i);
    expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
  });

  it('mirror: Accept a draft, then inline editor open buffer refuses to overwrite', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveRow(seedItem(existingAlt));

    // Open editor first so its buffer can outlive Accept (S2A-BR-03 ignores prop
    // while open). Baseline is existingAlt at open.
    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: 'Stale open buffer that must not clobber Accept.' },
    });

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    await waitFor(() => expect(cachedAlt(client)).toBe(draft));
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, draft);

    // Editor still open with older buffer — Save must refuse.
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await screen.findByRole('alert');
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(cachedAlt(client)).toBe(draft);
    // Buffer kept; Cancel remains reachable.
    expect(screen.getByRole('textbox', { name: /^alt text$/i })).toHaveValue(
      'Stale open buffer that must not clobber Accept.',
    );
    expect(screen.getByRole('button', { name: /cancel/i })).not.toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent(/changed/i);
  });

  it('in-flight exclusivity: editor save pending disables Suggest Accept; settles re-enables', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    let resolveCorrection!: (value: DescriptionHistoryItem) => void;
    correctMock.mockReturnValueOnce(
      new Promise<DescriptionHistoryItem>((resolve) => {
        resolveCorrection = resolve;
      }),
    );
    renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled());
    // Peer commit control must not be actionable while editor write is in flight.
    expect(screen.getByRole('button', { name: /^accept$/i })).toBeDisabled();

    resolveCorrection(successItem(42, operatorAlt));
    await waitFor(() => expect(screen.queryByRole('button', { name: /saving/i })).not.toBeInTheDocument());
    // After settle, Accept is actionable again (CAS may still refuse — but the
    // control itself must not stay permanently unreachable [rg-003]).
    // After editor saved, Accept will CAS-refuse if clicked; disabled only for
    // empty draft. Control must be enabled.
    await waitFor(() => expect(screen.getByRole('button', { name: /^accept$/i })).not.toBeDisabled());
  });

  it('in-flight exclusivity: Suggest Accept pending disables editor Save; settles re-enables', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    let resolveCorrection!: (value: DescriptionHistoryItem) => void;
    correctMock.mockReturnValueOnce(
      new Promise<DescriptionHistoryItem>((resolve) => {
        resolveCorrection = resolve;
      }),
    );
    renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    await waitFor(() => expect(screen.getByRole('button', { name: /accepting draft/i })).toBeDisabled());
    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled();

    resolveCorrection(successItem(42, draft));
    await waitFor(() => expect(screen.queryByRole('button', { name: /accepting draft/i })).not.toBeInTheDocument());
    // Editor still open; Save must become actionable again after peer settles.
    await waitFor(() => expect(screen.getByRole('button', { name: /^save$/i })).not.toBeDisabled());
  });

  it('discrimination: normal Accept with no interleaved commit still writes and announces', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    await waitFor(() => expect(cachedAlt(client)).toBe(draft));
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, draft);
    await waitFor(() => {
      expect(screen.getByTestId('media-selection-row-status')).toHaveTextContent('Alt text saved.');
    });
  });

  it('discrimination: normal inline save with no interleaved commit still writes and announces', async () => {
    const { client } = renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(cachedAlt(client)).toBe(operatorAlt));
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, operatorAlt);
    await waitFor(() => {
      expect(screen.getByTestId('media-selection-row-status')).toHaveTextContent('Alt text saved.');
    });
  });

  it('discrimination: after Suggest refusal, Dismiss then regenerate+Accept succeeds', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(cachedAlt(client)).toBe(operatorAlt));

    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await screen.findByRole('alert');
    expect(correctMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    await screen.findByRole('button', { name: /suggest alt text/i });

    const freshDraft = 'Fresh draft after resolve.';
    describeMock.mockResolvedValue(sampleResponse(freshDraft));
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(freshDraft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));

    await waitFor(() => expect(cachedAlt(client)).toBe(freshDraft));
    expect(correctMock).toHaveBeenCalledTimes(2);
    expect(correctMock).toHaveBeenLastCalledWith(42, freshDraft);
  });

  it('discrimination: after editor refusal, Cancel then re-edit+Save succeeds', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: 'Buffer that will be refused.' },
    });

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await waitFor(() => expect(cachedAlt(client)).toBe(draft));

    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await screen.findByRole('alert');
    expect(correctMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole('textbox', { name: /^alt text$/i })).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(cachedAlt(client)).toBe(operatorAlt));
    expect(correctMock).toHaveBeenCalledTimes(2);
    expect(correctMock).toHaveBeenLastCalledWith(42, operatorAlt);
  });

  it('exactly one polite region after a CAS refusal (assertive only for the block)', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    const { client } = renderLiveRow(seedItem(existingAlt));

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: operatorAlt },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(cachedAlt(client)).toBe(operatorAlt));

    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await screen.findByRole('alert');

    expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
    // Refusal must not be routed into the polite region.
    expect(screen.getByTestId('media-selection-row-status')).not.toHaveTextContent(/changed/i);
  });
});

/**
 * BR-01: beginCommit exclusivity lives in the state transition, not in callers.
 * Unreachable via the two real UI surfaces (both refuse when peerCommitPending),
 * so a third simulated claimant exercises the lock directly via useRowCommitLock.
 *
 * [TEST-15] discrimination: goes RED if beginCommit is restored to unconditional
 * setCommitOwner(owner) — the second claim would return true and steal the lock.
 */
describe('MediaSelectionTableBody — beginCommit compare-and-set [S2c-4b-ii BR-01]', () => {
  it('refuses a second claim while a lock is held; end is compare-and-clear', () => {
    const { result } = renderHook(() => useRowCommitLock());

    let firstClaim = false;
    let secondClaim = false;
    act(() => {
      firstClaim = result.current.beginCommit('editor');
    });
    expect(firstClaim).toBe(true);
    expect(result.current.commitOwner).toBe('editor');

    act(() => {
      // Third simulated claimant — not editor, not the peer guard path.
      secondClaim = result.current.beginCommit('suggest');
    });
    // Unconditional beginCommit would return true and set owner to 'suggest'.
    expect(secondClaim).toBe(false);
    expect(result.current.commitOwner).toBe('editor');

    act(() => {
      // Wrong owner must not clear (compare-and-clear).
      result.current.endCommit('suggest');
    });
    expect(result.current.commitOwner).toBe('editor');

    act(() => {
      result.current.endCommit('editor');
    });
    expect(result.current.commitOwner).toBeNull();

    let reclaimed = false;
    act(() => {
      reclaimed = result.current.beginCommit('suggest');
    });
    expect(reclaimed).toBe(true);
    expect(result.current.commitOwner).toBe('suggest');
  });
});
