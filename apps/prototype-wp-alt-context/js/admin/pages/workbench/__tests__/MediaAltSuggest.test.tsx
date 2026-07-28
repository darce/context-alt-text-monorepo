import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
});
