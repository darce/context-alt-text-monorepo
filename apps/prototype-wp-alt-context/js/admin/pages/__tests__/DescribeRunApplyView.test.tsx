import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DescribeRunApplyView } from '../DescribeRunApplyView';
import { applyDescribeRunDrafts, fetchDescribeRunItems } from '../../api/describeApi';

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

vi.mock('../../api/describeApi', async () => {
  const actual = await vi.importActual<typeof import('../../api/describeApi')>('../../api/describeApi');
  return { ...actual, fetchDescribeRunItems: vi.fn(), applyDescribeRunDrafts: vi.fn() };
});

const fetchItemsMock = vi.mocked(fetchDescribeRunItems);
const applyMock = vi.mocked(applyDescribeRunDrafts);

const mixedItems = {
  run_id: 'run-abc',
  items: [
    { media_id: 71, status: 'completed', alt_text_draft: 'A red flower.', caption: 'A flower.', provenance: null, existing_alt: false },
    { media_id: 90, status: 'completed', alt_text_draft: 'A blue car.', caption: 'A car.', provenance: null, existing_alt: false },
    { media_id: 70, status: 'completed', alt_text_draft: 'A stone bridge.', caption: 'A bridge.', provenance: null, existing_alt: true },
    { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
  ],
};

/** Post-partial refetch: alt landed so existing_alt is true for the written rows. */
const afterPartialItems = {
  run_id: 'run-abc',
  items: [
    { media_id: 71, status: 'completed', alt_text_draft: 'A red flower.', caption: 'A flower.', provenance: null, existing_alt: true },
    { media_id: 90, status: 'completed', alt_text_draft: 'A blue car.', caption: 'A car.', provenance: null, existing_alt: true },
    { media_id: 70, status: 'completed', alt_text_draft: 'A stone bridge.', caption: 'A bridge.', provenance: null, existing_alt: true },
    { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
  ],
};

const renderView = (runId = 'run-abc') => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <DescribeRunApplyView runId={runId} />
    </QueryClientProvider>,
  );
};

describe('DescribeRunApplyView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchItemsMock.mockResolvedValue(mixedItems);
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71, 90],
      partial: [],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
  });

  it('buckets drafts and offers a primary apply for the no-existing-alt group', async () => {
    renderView();

    expect(await screen.findByText('A red flower.')).toBeInTheDocument();
    expect(screen.getByText('A blue car.')).toBeInTheDocument();
    // Primary CTA counts only the safe (no existing alt) drafts.
    expect(screen.getByRole('button', { name: /Apply all 2 without alt text/ })).toBeInTheDocument();
    // The existing-alt draft is bucketed separately behind an overwrite opt-in.
    expect(screen.getByText('A stone bridge.')).toBeInTheDocument();
    expect(screen.getByLabelText(/Overwrite existing alt text for media 70/)).toBeInTheDocument();
  });

  it('applies the safe bucket with no overwrites by default', async () => {
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    await waitFor(() => expect(applyMock).toHaveBeenCalledWith('run-abc', []));
    // Happy path: applied count is honest; empty partial must not invent a line.
    expect(await screen.findByText(/Applied 2/)).toBeInTheDocument();
    expect(screen.queryByText(/had alt text saved/)).not.toBeInTheDocument();
  });

  it('surfaces partial apply ids so operators know alt is live but history is missing [RLSE-05]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    // After apply, items refetch with existing_alt true (alt landed) so the
    // safe bucket empties — partial recovery must still enable Apply again.
    fetchItemsMock
      .mockResolvedValueOnce(mixedItems)
      .mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    // [TEST-15] discrimination: goes red if partial rows are dropped from the
    // summary (count-only copy hid which rows needed a retry). Uses itemHeading
    // (caption "A car.") rather than a bare media id. [BR-90d]
    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(/Applied 1 descriptions/);
    expect(status).toHaveTextContent(
      /1 had alt text saved \(A car\.\); apply again so they appear in history/,
    );

    // Partial retry is actionable without ticking overwrite checkboxes.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled(),
    );
    // Safe panel swaps to history-completion language — not the empty "safe" lie. [BR-90a]
    expect(screen.getByRole('heading', { level: 2, name: /need history completion/ })).toBeInTheDocument();
    expect(screen.getByText(/needs history completion \(no overwrite\)/)).toBeInTheDocument();
    expect(
      screen.queryByText(/These images have no alt text yet, so their drafts apply safely/),
    ).not.toBeInTheDocument();

    applyMock.mockClear();
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [90],
      partial: [],
      skipped_existing: [70, 71],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fireEvent.click(screen.getByRole('button', { name: /Apply again to complete history for 1/ }));
    await waitFor(() => expect(applyMock).toHaveBeenCalledWith('run-abc', []));
  });

  it('keeps the partial recovery affordance when a retry fails [BR-85][INT-11]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock
      .mockResolvedValueOnce(mixedItems)
      .mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled(),
    );

    // Failed retry must not erase outstanding partials or disable the primary.
    applyMock.mockRejectedValueOnce(new Error('network'));
    fireEvent.click(screen.getByRole('button', { name: /Apply again to complete history for 1/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not apply the run drafts/);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/apply again so they appear in history/);
    expect(status).toHaveTextContent(/A car\./);
    expect(screen.getByRole('alert')).toHaveTextContent(/History is still incomplete/);
    expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled();
    expect(screen.getByText(/needs history completion \(no overwrite\)/)).toBeInTheDocument();
  });

  it('mounts the status live region before any apply result arrives [BR-87][A11Y-21]', async () => {
    renderView();
    await screen.findByText('A red flower.');

    // Region is present with empty text so ATs track it; first result only
    // mutates content (mount-then-mutate). Goes red if gated on isSuccess.
    const status = screen.getByTestId('acx-run-apply-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();
  });

  it('acknowledges successful history recovery after a prior partial [BR-90b]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock
      .mockResolvedValueOnce(mixedItems)
      .mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled(),
    );

    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [90],
      partial: [],
      skipped_existing: [70, 71],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fireEvent.click(screen.getByRole('button', { name: /Apply again to complete history for 1/ }));

    const status = await screen.findByRole('status');
    await waitFor(() =>
      expect(status).toHaveTextContent(/History is now complete for items that needed a second apply/),
    );
    expect(status).toHaveTextContent(/Applied 1 descriptions/);
  });

  it('omits the applied sentence when every write was partial [BR-90c]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [],
      partial: [71, 90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock
      .mockResolvedValueOnce(mixedItems)
      .mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    const status = await screen.findByRole('status');
    await waitFor(() => expect(status).toHaveTextContent(/had alt text saved/));
    expect(status).not.toHaveTextContent(/Applied 0 descriptions/);
  });

  it('caps long partial id lists and uses item headings [BR-90d]', async () => {
    const manyPartialIds = [11, 12, 13, 14, 15, 16, 17];
    const manyItems = {
      run_id: 'run-many',
      items: manyPartialIds.map((id) => ({
        media_id: id,
        status: 'completed' as const,
        alt_text_draft: `Draft ${id}`,
        caption: `Caption ${id}`,
        provenance: null,
        existing_alt: false,
      })),
    };
    const afterMany = {
      run_id: 'run-many',
      items: manyPartialIds.map((id) => ({
        media_id: id,
        status: 'completed' as const,
        alt_text_draft: `Draft ${id}`,
        caption: `Caption ${id}`,
        provenance: null,
        existing_alt: true,
      })),
    };
    fetchItemsMock.mockResolvedValueOnce(manyItems).mockResolvedValue(afterMany);
    applyMock.mockResolvedValue({
      run_id: 'run-many',
      applied: [],
      partial: manyPartialIds,
      skipped_existing: [],
      skipped_no_draft: [],
      skipped_invalid: [],
      failed: [],
    });
    renderView('run-many');
    await screen.findByText('Draft 11');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 7 without alt text/ }));

    const status = await screen.findByRole('status');
    await waitFor(() => expect(status).toHaveTextContent(/and 2 more/));
    expect(status).toHaveTextContent(/Caption 11/);
    expect(status).toHaveTextContent(/Caption 15/);
    // Sixth and seventh headings are folded into "and 2 more".
    expect(status).not.toHaveTextContent(/Caption 16/);
  });

  it('exposes an accessible reason when the primary apply control is disabled [BR-90e]', async () => {
    fetchItemsMock.mockResolvedValue({
      run_id: 'run-overwrite-only',
      items: [
        {
          media_id: 70,
          status: 'completed',
          alt_text_draft: 'A stone bridge.',
          caption: 'A bridge.',
          provenance: null,
          existing_alt: true,
        },
      ],
    });
    renderView('run-overwrite-only');
    await screen.findByText('A stone bridge.');

    const button = screen.getByRole('button', { name: /Apply 0 descriptions/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    const describedBy = button.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const reason = document.getElementById(describedBy ?? '');
    expect(reason).toHaveTextContent(/Nothing selected to apply/);
  });

  it('labels the union of safe selections and outstanding partial completions [BR-91]', async () => {
    // After a partial on 71, operator selects unrelated overwrite 70 — server
    // still completes 71 implicitly, so the label must count both. [BR-91]
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [90],
      partial: [71],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock
      .mockResolvedValueOnce(mixedItems)
      .mockResolvedValue({
        run_id: 'run-abc',
        items: [
          { media_id: 71, status: 'completed', alt_text_draft: 'A red flower.', caption: 'A flower.', provenance: null, existing_alt: true },
          { media_id: 90, status: 'completed', alt_text_draft: 'A blue car.', caption: 'A car.', provenance: null, existing_alt: true },
          { media_id: 70, status: 'completed', alt_text_draft: 'A stone bridge.', caption: 'A bridge.', provenance: null, existing_alt: true },
          { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
        ],
      });
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled(),
    );

    // Select overwrite for media 70 (not the outstanding partial 71).
    fireEvent.click(screen.getByLabelText(/Overwrite existing alt text for media 70/));
    // Union: 1 overwrite + 1 outstanding partial = 2 (not "Apply 1").
    expect(screen.getByRole('button', { name: /Apply 2 descriptions/ })).toBeEnabled();
    expect(screen.queryByRole('button', { name: /^Apply 1 descriptions$/ })).not.toBeInTheDocument();
  });

  it('includes checked existing-alt items in the overwrite list', async () => {
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByLabelText(/Overwrite existing alt text for media 70/));
    // The primary label reflects the added overwrite.
    fireEvent.click(screen.getByRole('button', { name: /Apply 3 descriptions/ }));

    await waitFor(() => expect(applyMock).toHaveBeenCalledWith('run-abc', [70]));
  });

  it('clears checked overwrites after a successful apply so a second apply cannot re-clobber', async () => {
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByLabelText(/Overwrite existing alt text for media 70/));
    expect(screen.getByLabelText(/Overwrite existing alt text for media 70/)).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: /Apply 3 descriptions/ }));

    await waitFor(() => expect(applyMock).toHaveBeenCalledWith('run-abc', [70]));

    // After the write lands the overwrite selection resets, so the checkbox is
    // unchecked and a repeat apply sends the safe bucket only ([] overwrites).
    await waitFor(() =>
      expect(screen.getByLabelText(/Overwrite existing alt text for media 70/)).not.toBeChecked(),
    );

    applyMock.mockClear();
    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));
    await waitFor(() => expect(applyMock).toHaveBeenCalledWith('run-abc', []));
  });

  it('starts a fresh runId with no checked overwrites', async () => {
    const { unmount } = renderView('run-abc');
    await screen.findByText('A red flower.');
    fireEvent.click(screen.getByLabelText(/Overwrite existing alt text for media 70/));
    expect(screen.getByLabelText(/Overwrite existing alt text for media 70/)).toBeChecked();
    unmount();

    // A different run gets a fresh mount (DescriptionHistoryPage keys on runId),
    // so no overwrite selection carries across the ?run= deep link.
    renderView('run-def');
    await screen.findByText('A red flower.');
    expect(screen.getByLabelText(/Overwrite existing alt text for media 70/)).not.toBeChecked();
  });

  it('lists items with no usable draft as skipped and never applies them', async () => {
    renderView();
    await screen.findByText('A red flower.');

    const noDraft = screen.getByTestId('acx-run-apply-no-draft');
    expect(within(noDraft).getByText(/media 72/i)).toBeInTheDocument();
  });

  it('shows a zero state when the run has no applicable drafts', async () => {
    fetchItemsMock.mockResolvedValue({
      run_id: 'run-empty',
      items: [{ media_id: 5, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false }],
    });

    renderView('run-empty');

    expect(await screen.findByText('No drafts from this run can be applied.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apply all/ })).not.toBeInTheDocument();
  });

  it('shows an error state with retry when items fail to load', async () => {
    fetchItemsMock.mockRejectedValue(new Error('boom'));

    renderView();

    expect(await screen.findByText('Could not load this run’s drafts.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
