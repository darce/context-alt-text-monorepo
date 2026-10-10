/**
 * S2c-4b-i co-mounting proofs: compare-and-swap on committed alt + in-flight
 * exclusivity between MediaAltInlineEditor and MediaAltSuggest on one row.
 *
 * Isolated component tests cannot express "the sibling committed underneath me"
 * — these mount MediaSelectionTableBody with items driven from the workbench
 * cache so useCorrectMediaAlt's row patch is live committed truth.
 */
import { useQuery } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  correctDescriptionHistoryItem,
  describeMedia,
  DESCRIPTION_CORRECTION_CODE,
  fetchDescriptionHistory,
} from '../../../api/describeApi';
import type { DescriptionHistoryItem, VisualFactsResponse } from '../../../api/describeApi';
import { queryKeys } from '../../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../../api/workbenchMediaApi';
import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { buildTestQueryClient, createQueryWrapper } from '../../../test-utils/queryClient';
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
    fetchDescriptionHistory: vi.fn(),
  };
});

const describeMock = vi.mocked(describeMedia);
const correctMock = vi.mocked(correctDescriptionHistoryItem);
const historyMock = vi.mocked(fetchDescriptionHistory);

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
  tier: 'provisional_cpu',
  result_generation: 1,
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
    queryFn: (): Promise<WorkbenchMediaResponse> => Promise.resolve({ items: [initialItem], total: 1, totalPages: 1 }),
    initialData: { items: [initialItem], total: 1, totalPages: 1 },
    staleTime: Infinity,
  });
  const items = data?.items ?? [];
  return (
    <table>
      <tbody>
        <MediaSelectionTableBody
          onClearSearch={vi.fn()}
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
  const client = buildTestQueryClient();
  client.setQueryData<WorkbenchMediaResponse>(workbenchKey, {
    items: [initialItem],
    total: 1,
    totalPages: 1,
  });
  const QueryWrapper = createQueryWrapper(client);
  const view = render(
    <QueryWrapper>
      <LiveWorkbenchRow initialItem={initialItem} />
    </QueryWrapper>,
  );
  return { client, ...view };
};

const cachedAlt = (client: QueryClient): string | null | undefined =>
  client.getQueryData<WorkbenchMediaResponse>(workbenchKey)?.items.find((i) => i.id === 42)?.altText;

describe('MediaSelectionTableBody — commit exclusivity [S2c-4b-i]', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    correctMock.mockImplementation((mediaId, altText) => Promise.resolve(successItem(mediaId, altText)));
    historyMock.mockResolvedValue({ items: [], total: 0 });
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

describe('MediaSelectionTableBody — queue commit ownership [GTMBURST-ADMIN-01]', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    correctMock.mockImplementation((mediaId, altText) => Promise.resolve(successItem(mediaId, altText)));
    historyMock.mockResolvedValue({
      items: [{ ...successItem(42, existingAlt), generated_alt_text: draft, human_edit: null }],
      total: 1,
    });
  });

  const queueAction = async (action: 'Accept' | 'Edit-save'): Promise<HTMLElement> => {
    await screen.findByRole('button', { name: 'Accept draft for Bridge' });
    if (action === 'Edit-save') {
      fireEvent.click(screen.getByRole('button', { name: 'Edit draft for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: 'Edit draft alt text' }), {
        target: { value: 'Reviewed queue draft.' },
      });
      return screen.getByRole('button', { name: 'Save alt text' });
    }
    return screen.getByRole('button', { name: 'Accept draft for Bridge' });
  };

  it.each(['Accept', 'Edit-save'] as const)(
    '[TEST-06] editor-first: queue %s cannot start a competing correction',
    async (action) => {
      // Predicted RED: QueueDraftCell receives no peer lock, so its commit
      // control stays enabled and a click starts a second correction.
      let resolveCorrection!: (value: DescriptionHistoryItem) => void;
      correctMock.mockReturnValueOnce(
        new Promise<DescriptionHistoryItem>((resolve) => {
          resolveCorrection = resolve;
        }),
      );
      renderLiveRow();
      const queueCommit = await queueAction(action);

      fireEvent.click(screen.getByRole('button', { name: 'Edit alt text for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
        target: { value: operatorAlt },
      });
      fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
      await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));

      try {
        expect(queueCommit).toBeDisabled();
        fireEvent.click(queueCommit);
        expect(correctMock).toHaveBeenCalledTimes(1);
      } finally {
        await act(async () => {
          resolveCorrection(successItem(42, operatorAlt));
          await Promise.resolve();
        });
      }
      await waitFor(() => expect(queueCommit).not.toBeDisabled());
    },
  );

  it.each(['Accept', 'Edit-save'] as const)(
    'queue-first: queue %s prevents the human editor from committing until settle',
    async (action) => {
      // Predicted RED: queue writes do not claim the row lock, leaving human
      // Save enabled while the queue correction is unresolved.
      let resolveCorrection!: (value: DescriptionHistoryItem) => void;
      correctMock.mockReturnValueOnce(
        new Promise<DescriptionHistoryItem>((resolve) => {
          resolveCorrection = resolve;
        }),
      );
      renderLiveRow();
      const queueCommit = await queueAction(action);
      fireEvent.click(screen.getByRole('button', { name: 'Edit alt text for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
        target: { value: operatorAlt },
      });
      fireEvent.click(queueCommit);
      await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));

      const humanSave = screen.getByRole('button', { name: /^save$/i });
      try {
        expect(humanSave).toBeDisabled();
        fireEvent.click(humanSave);
        expect(correctMock).toHaveBeenCalledTimes(1);
      } finally {
        await act(async () => {
          resolveCorrection(successItem(42, action === 'Accept' ? draft : 'Reviewed queue draft.'));
          await Promise.resolve();
        });
      }
      await waitFor(() => expect(humanSave).not.toBeDisabled());
      expect(screen.getByRole('textbox', { name: /^alt text$/i })).toHaveValue(operatorAlt);
    },
  );

  it.each(['Accept', 'Edit-save'] as const)(
    'after human save and refetch: stale queue %s refuses and preserves the draft',
    async (action) => {
      // Predicted RED: once the editor settles, queue applyText still accepts
      // the old draft and overwrites the human alt instead of reporting change.
      const { client } = renderLiveRow();
      await screen.findByRole('button', { name: 'Accept draft for Bridge' });
      fireEvent.click(screen.getByRole('button', { name: 'Edit alt text for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
        target: { value: operatorAlt },
      });
      fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
      await waitFor(() => expect(cachedAlt(client)).toBe(operatorAlt));
      await waitFor(() => expect(screen.queryByRole('button', { name: /saving/i })).not.toBeInTheDocument());

      // A later cache refresh with the same committed human alt must not
      // silently rebase the queue draft's original observed baseline.
      await act(async () => {
        client.setQueryData<WorkbenchMediaResponse>(workbenchKey, {
          items: [seedItem(operatorAlt)],
          total: 1,
          totalPages: 1,
        });
        await client.invalidateQueries({ queryKey: ['description-history'] });
      });
      fireEvent.click(await queueAction(action));

      expect(await screen.findByRole('alert')).toHaveTextContent(/changed/i);
      expect(correctMock).toHaveBeenCalledTimes(1);
      expect(cachedAlt(client)).toBe(operatorAlt);
      if (action === 'Edit-save') {
        expect(screen.getByRole('textbox', { name: 'Edit draft alt text' })).toHaveValue('Reviewed queue draft.');
        fireEvent.click(screen.getByRole('button', { name: 'Cancel edit' }));
        expect(screen.getByRole('button', { name: 'Edit draft for Bridge' })).toHaveFocus();
      } else {
        expect(screen.getByText(draft)).toBeInTheDocument();
      }
      expect(screen.getByRole('button', { name: 'Dismiss' })).not.toBeDisabled();
      expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
    },
  );

  it('healthy queue Accept with unchanged committed alt still writes once', async () => {
    const { client } = renderLiveRow();
    fireEvent.click(await queueAction('Accept'));

    await waitFor(() => expect(cachedAlt(client)).toBe(draft));
    expect(correctMock).toHaveBeenCalledTimes(1);
    expect(correctMock).toHaveBeenCalledWith(42, draft);
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Accept draft for Bridge' })).not.toBeInTheDocument(),
    );
  });

  it.each(['editor', 'queue'] as const)(
    '%s-first: same-tick queue/editor clicks start only one correction',
    async (first) => {
      let resolveCorrection!: (value: DescriptionHistoryItem) => void;
      correctMock.mockReturnValueOnce(
        new Promise<DescriptionHistoryItem>((resolve) => {
          resolveCorrection = resolve;
        }),
      );
      const { client } = renderLiveRow();
      const queueCommit = await queueAction('Accept');
      fireEvent.click(screen.getByRole('button', { name: 'Edit alt text for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), { target: { value: operatorAlt } });
      const humanSave = screen.getByRole('button', { name: /^save$/i });
      act(() => {
        // Native clicks in one batch bypass the next-paint peer disabled guard.
        (first === 'editor' ? humanSave : queueCommit).click();
        (first === 'editor' ? queueCommit : humanSave).click();
      });
      await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
      const savedAlt = first === 'editor' ? operatorAlt : draft;
      expect(correctMock).toHaveBeenCalledWith(42, savedAlt);
      await act(async () => {
        resolveCorrection(successItem(42, savedAlt));
        await Promise.resolve();
      });
      await waitFor(() => expect(cachedAlt(client)).toBe(savedAlt));
      expect(correctMock).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['Accept', 'Edit-save'] as const)(
    'failed queue %s releases the row and keeps draft/error/focus',
    async (action) => {
      let rejectCorrection!: (error: Error) => void;
      correctMock.mockReturnValueOnce(
        new Promise<DescriptionHistoryItem>((_resolve, reject) => {
          rejectCorrection = reject;
        }),
      );
      renderLiveRow();
      const queueCommit = await queueAction(action);
      fireEvent.click(screen.getByRole('button', { name: 'Edit alt text for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), { target: { value: operatorAlt } });
      fireEvent.click(queueCommit);
      await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
      const humanSave = screen.getByRole('button', { name: /^save$/i });
      expect(humanSave).toBeDisabled();

      await act(async () => {
        rejectCorrection(new Error(JSON.stringify({ code: 'correction_failed', message: 'Correction unavailable' })));
        await Promise.resolve();
      });
      expect(await screen.findByRole('alert')).toHaveTextContent('Correction unavailable');
      await waitFor(() => expect(humanSave).not.toBeDisabled());
      if (action === 'Edit-save') {
        const field = screen.getByRole('textbox', { name: 'Edit draft alt text' });
        expect(field).toHaveValue('Reviewed queue draft.');
        expect(field).toHaveFocus();
        expect(field).toHaveAttribute('aria-describedby', screen.getByRole('alert').id);
      } else {
        expect(screen.getByText(draft)).toBeInTheDocument();
        expect(queueCommit).toHaveFocus();
      }
      fireEvent.click(humanSave);
      await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(2));
      expect(correctMock).toHaveBeenLastCalledWith(42, operatorAlt);
      // The human save must not erase the queue's unread correction error.
      expect(screen.getByRole('alert')).toHaveTextContent('Correction unavailable');
    },
  );

  it.each(['queue', 'suggest'] as const)('%s-first: queue and Suggest share the exclusive row lock', async (first) => {
    describeMock.mockResolvedValue(sampleResponse('Fresh inline suggestion.'));
    let rejectCorrection!: (error: Error) => void;
    correctMock.mockReturnValueOnce(
      new Promise<DescriptionHistoryItem>((_resolve, reject) => {
        rejectCorrection = reject;
      }),
    );
    renderLiveRow();
    const queueCommit = await queueAction('Accept');
    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText('Fresh inline suggestion.');
    const suggestCommit = screen.getByRole('button', { name: /^accept$/i });
    const firstCommit = first === 'queue' ? queueCommit : suggestCommit;
    const secondCommit = first === 'queue' ? suggestCommit : queueCommit;
    fireEvent.click(firstCommit);
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
    expect(secondCommit).toBeDisabled();
    fireEvent.click(secondCommit);
    expect(correctMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      rejectCorrection(new Error('Correction unavailable'));
      await Promise.resolve();
    });
    await waitFor(() => expect(secondCommit).not.toBeDisabled());
    fireEvent.click(secondCommit);
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(2));
    expect(correctMock).toHaveBeenLastCalledWith(42, first === 'queue' ? 'Fresh inline suggestion.' : draft);
  });

  it('a queue partial write preserves the reviewed buffer and allows retry against reconciled alt', async () => {
    const { client } = renderLiveRow();
    const queueCommit = await queueAction('Edit-save');
    correctMock.mockRejectedValueOnce(
      new Error(
        JSON.stringify({
          code: DESCRIPTION_CORRECTION_CODE.PARTIAL,
          message: 'Alt was saved but correction history failed.',
          data: { status: 500, stored_alt_text: 'Reviewed queue draft.', is_decorative: false },
        }),
      ),
    );
    fireEvent.click(queueCommit);
    await screen.findByRole('alert');
    await waitFor(() => expect(cachedAlt(client)).toBe('Reviewed queue draft.'));
    const field = screen.getByRole('textbox', { name: 'Edit draft alt text' });
    expect(field).toHaveValue('Reviewed queue draft.');
    expect(field).toHaveFocus();
    fireEvent.click(screen.getByRole('button', { name: 'Save alt text' }));
    await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it.each(['success', 'failure'] as const)(
    'queue removal during a pending %s releases only when the write settles',
    async (outcome) => {
      let resolveCorrection!: (value: DescriptionHistoryItem) => void;
      let rejectCorrection!: (error: Error) => void;
      correctMock.mockReturnValueOnce(
        new Promise<DescriptionHistoryItem>((resolve, reject) => {
          resolveCorrection = resolve;
          rejectCorrection = reject;
        }),
      );
      const { client } = renderLiveRow();
      const queueCommit = await queueAction('Accept');
      fireEvent.click(screen.getByRole('button', { name: 'Edit alt text for Bridge' }));
      fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), { target: { value: operatorAlt } });
      fireEvent.click(queueCommit);
      await waitFor(() => expect(correctMock).toHaveBeenCalledTimes(1));
      const humanSave = screen.getByRole('button', { name: /^save$/i });
      expect(humanSave).toBeDisabled();

      // A history refetch can remove just the queue cell while the row stays mounted.
      historyMock.mockResolvedValue({ items: [], total: 0 });
      await act(async () => {
        await client.invalidateQueries({ queryKey: ['description-history'] });
      });
      await waitFor(() => expect(queueCommit).not.toBeInTheDocument());
      expect(humanSave).toBeDisabled();
      fireEvent.click(humanSave);
      expect(correctMock).toHaveBeenCalledTimes(1);
      await act(async () => {
        if (outcome === 'success') {
          resolveCorrection(successItem(42, draft));
        } else {
          rejectCorrection(new Error('Correction unavailable'));
        }
        await Promise.resolve();
      });
      await waitFor(() => expect(humanSave).not.toBeDisabled());
      expect(screen.getByRole('textbox', { name: /^alt text$/i })).toHaveValue(operatorAlt);
    },
  );
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
  it('a late queue release cannot clear a later editor claim', () => {
    const { result } = renderHook(() => useRowCommitLock());
    act(() => {
      expect(result.current.beginCommit('queue')).toBe(true);
      expect(result.current.beginCommit('editor')).toBe(false);
      result.current.endCommit('suggest');
    });
    expect(result.current.commitOwner).toBe('queue');
    act(() => {
      result.current.endCommit('queue');
      expect(result.current.beginCommit('editor')).toBe(true);
      result.current.endCommit('queue');
    });
    expect(result.current.commitOwner).toBe('editor');
  });

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
