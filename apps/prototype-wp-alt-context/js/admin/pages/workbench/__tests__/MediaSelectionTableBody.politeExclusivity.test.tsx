/**
 * S2c-4a co-mounting proofs: one polite live region per media row with
 * last-writer-wins announce and compare-and-clear ownership.
 *
 * Isolated component tests cannot express "both regions hold text at once" —
 * these mount MediaSelectionTableBody (the real row surface) so the defect and
 * the naive-lift trap are both observable.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { correctDescriptionHistoryItem, describeMedia } from '../../../api/describeApi';
import type { VisualFactsResponse } from '../../../api/describeApi';
import type { WorkbenchMediaItem } from '../../../hooks/useWorkbenchMedia';
import { MediaSelectionTableBody } from '../MediaSelectionTableBody';
import { RECOMMENDED_ALT_TEXT_MAX_LENGTH } from '../MediaAltSuggest';

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

const mediaItem: WorkbenchMediaItem = {
  id: 42,
  title: 'Bridge',
  status: 'missing',
  thumbnailUrl: null,
  altText: 'Existing alt',
  isDecorative: false,
  editUrl: null,
  tags: [],
  mimeType: 'image/jpeg',
  dimensions: { width: 800, height: 600 },
  updatedAt: '2026-07-28T12:00:00Z',
};

const buildClient = () =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

const renderRow = (element: ReactElement, client = buildClient()) => ({
  client,
  ...render(<QueryClientProvider client={client}>{element}</QueryClientProvider>),
});

const renderMediaRow = () =>
  renderRow(
    <table>
      <tbody>
        <MediaSelectionTableBody
          onClearSearch={vi.fn()}
          items={[mediaItem]}
          isLoading={false}
          detailIsLoading={false}
          onToggleRow={() => undefined}
          selection={{}}
        />
      </tbody>
    </table>,
  );

/**
 * Every polite live region on the row: aria-live="polite" is load-bearing even
 * without role="status" (detail-meta was a live region with only aria-live).
 * role="alert" uses aria-live="assertive" and is intentionally excluded.
 */
const getPoliteLiveRegions = (): HTMLElement[] =>
  Array.from(document.querySelectorAll<HTMLElement>('[aria-live="polite"]'));

describe('MediaSelectionTableBody — one polite region per row [S2c-4a]', () => {
  beforeEach(() => {
    vi.resetAllMocks();
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

  it('[TEST-06] co-mount: Suggest draft then editor save → exactly one polite region holds the later cue', async () => {
    // Operator sequence 1: Suggest a draft, neither Accept nor Dismiss (sticky
    // "Draft ready…"), then Edit+Save on the sibling inline editor.
    // Predicted RED (pre-lift): getPoliteLiveRegions().length === 3 (editor +
    // suggest + detail-meta) and both "Draft ready" and "Alt text saved." present.
    describeMock.mockResolvedValue(sampleResponse());
    renderMediaRow();

    // Quiet mount: one empty polite region, no cue text yet.
    const politeAtMount = getPoliteLiveRegions();
    expect(politeAtMount).toHaveLength(1);
    expect(politeAtMount[0]).toHaveTextContent('');

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    await waitFor(() => {
      expect(getPoliteLiveRegions()[0]).toHaveTextContent(/ready/i);
    });

    // Editor save while Suggest still owns a sticky ready cue.
    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: 'A human-authored alt from the inline editor.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(getPoliteLiveRegions()[0]).toHaveTextContent('Alt text saved.');
    });

    // Exactly one polite region on the row; last-writer-wins — ready cannot coexist.
    const polite = getPoliteLiveRegions();
    expect(polite).toHaveLength(1);
    expect(polite[0]).toHaveTextContent('Alt text saved.');
    expect(polite[0]).not.toHaveTextContent(/ready/i);
    // detail-meta must not be a live region (metadata loading is not an operator result).
    const detailMeta = document.querySelector('.acx-media-selection__detail-meta');
    expect(detailMeta).not.toBeNull();
    expect(detailMeta).not.toHaveAttribute('aria-live');
  });

  it('ownership: editor blur-retirement cannot clear a Suggest-owned message', async () => {
    // Naive lift trap: shared string + unconditional clear lets the editor's
    // idle blur wipe "Draft ready…" that Suggest still owns.
    describeMock.mockResolvedValue(sampleResponse());
    renderMediaRow();

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(draft);
    const rowStatus = getPoliteLiveRegions()[0];
    await waitFor(() => expect(rowStatus).toHaveTextContent(/ready/i));

    // Focus the editor surface, then blur it outward while idle (triggers the
    // editor's handleContainerBlur retirement path). relatedTarget is required
    // under jsdom so the blur handler sees an exit.
    const editAlt = screen.getByRole('button', { name: /edit alt text/i });
    editAlt.focus();
    const elsewhere = document.createElement('button');
    document.body.appendChild(elsewhere);
    fireEvent.blur(editAlt, { relatedTarget: elsewhere });
    elsewhere.remove();

    // Suggest still owns the cue — compare-and-clear must leave it alone.
    expect(rowStatus).toHaveTextContent(/ready/i);
    expect(rowStatus).not.toBeEmptyDOMElement();
  });

  it('discrimination: editor save still announces through the row region', async () => {
    renderMediaRow();
    const status = getPoliteLiveRegions()[0];
    expect(status).toHaveTextContent('');

    fireEvent.click(screen.getByRole('button', { name: /edit alt text/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /^alt text$/i }), {
      target: { value: 'Saved via lifted region.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => expect(status).toHaveTextContent('Alt text saved.'));
    // Same node mutated, not remounted.
    expect(getPoliteLiveRegions()[0]).toBe(status);
  });

  it('discrimination: generated draft announces ready (+ length when over) on the stable row region', async () => {
    const longDraft = 'A'.repeat(200);
    describeMock.mockResolvedValue(sampleResponse(longDraft));
    renderMediaRow();
    const status = getPoliteLiveRegions()[0];
    expect(status).toHaveTextContent('');

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await screen.findByText(longDraft);

    await waitFor(() => {
      expect(status).toHaveTextContent(/ready/i);
      expect(status).toHaveTextContent(/200/);
      expect(status).toHaveTextContent(String(RECOMMENDED_ALT_TEXT_MAX_LENGTH));
    });
    expect(getPoliteLiveRegions()[0]).toBe(status);
    expect(getPoliteLiveRegions()).toHaveLength(1);
  });

  it('discrimination: region present empty while quiet and stable across idle → busy → idle', async () => {
    describeMock.mockResolvedValue(sampleResponse());
    renderMediaRow();

    const status = getPoliteLiveRegions()[0];
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toHaveTextContent('');

    fireEvent.click(screen.getByRole('button', { name: /suggest alt text/i }));
    await waitFor(() => expect(status).toHaveTextContent(/generating|ready/i));
    await screen.findByText(draft);
    await waitFor(() => expect(status).toHaveTextContent(/ready/i));

    // Accept → saved → idle Suggest control; same node.
    fireEvent.click(screen.getByRole('button', { name: /^accept$/i }));
    await waitFor(() => expect(status).toHaveTextContent(/saved/i));
    await screen.findByRole('button', { name: /suggest alt text/i });

    // Retire via Suggest blur while idle.
    const suggestBtn = screen.getByRole('button', { name: /suggest alt text/i });
    const elsewhere = document.createElement('button');
    document.body.appendChild(elsewhere);
    fireEvent.blur(suggestBtn, { relatedTarget: elsewhere });
    elsewhere.remove();
    await waitFor(() => expect(status).toHaveTextContent(''));

    expect(getPoliteLiveRegions()[0]).toBe(status);
  });

  it('detail-meta is not a live region after chips load', () => {
    renderMediaRow();
    const detailMeta = document.querySelector('.acx-media-selection__detail-meta');
    expect(detailMeta).not.toBeNull();
    expect(detailMeta).not.toHaveAttribute('aria-live');
    // Chips still render as metadata.
    expect(detailMeta).toHaveTextContent(/image\/jpeg/i);
  });
});
