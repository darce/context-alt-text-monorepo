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
    expect(screen.queryByText(/had alt text saved; apply again/)).not.toBeInTheDocument();
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
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    // [TEST-15] discrimination: goes red if the partial bucket line is deleted
    // from the summary — partial ids vanish from every count (same silent
    // failure the PHP partial bucket was introduced to remove).
    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(/Applied 1 descriptions/);
    expect(status).toHaveTextContent(/1 had alt text saved; apply again so they appear in history/);
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
