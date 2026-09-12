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
const runItemContract = { tier: 'final_gpu', result_generation: 1 } as const;

const mixedItems = {
  run_id: 'run-abc',
  items: [
    {
      media_id: 71,
      status: 'completed',
      alt_text_draft: 'A red flower.',
      caption: 'A flower.',
      provenance: null,
      existing_alt: false,
    },
    {
      media_id: 90,
      status: 'completed',
      alt_text_draft: 'A blue car.',
      caption: 'A car.',
      provenance: null,
      existing_alt: false,
    },
    {
      media_id: 70,
      status: 'completed',
      alt_text_draft: 'A stone bridge.',
      caption: 'A bridge.',
      provenance: null,
      existing_alt: true,
    },
    { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
  ].map((item) => ({ ...item, ...runItemContract })),
};

/** Post-partial refetch: alt landed so existing_alt is true for the written rows. */
const afterPartialItems = {
  run_id: 'run-abc',
  items: [
    {
      media_id: 71,
      status: 'completed',
      alt_text_draft: 'A red flower.',
      caption: 'A flower.',
      provenance: null,
      existing_alt: true,
    },
    {
      media_id: 90,
      status: 'completed',
      alt_text_draft: 'A blue car.',
      caption: 'A car.',
      provenance: null,
      existing_alt: true,
    },
    {
      media_id: 70,
      status: 'completed',
      alt_text_draft: 'A stone bridge.',
      caption: 'A bridge.',
      provenance: null,
      existing_alt: true,
    },
    { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
  ].map((item) => ({ ...item, ...runItemContract })),
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

  it('keeps per-item tiers and naming visible across safe, overwrite, no-draft and partial buckets', async () => {
    const items = mixedItems.items.map((item, index) => ({
      ...item,
      tier: index === 0 ? ('final_gpu' as const) : index === 3 ? null : ('provisional_cpu' as const),
      provenance: { naming: { status: 'disabled' as const, realizer: null, names_applied: [] } },
    }));
    fetchItemsMock.mockResolvedValue({ run_id: 'run-abc', items });
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
    const expectTier = (id: number, label: string) => {
      const badge = screen.getByTestId(`acx-run-apply-tier-${id}`);
      expect(badge).toHaveTextContent(label);
      expect(within(badge.closest('li')!).getByText('No names (disabled)')).toBeInTheDocument();
    };
    expectTier(71, 'Compute tier: Final (GPU)');
    expectTier(90, 'Compute tier: Provisional (CPU)');
    expectTier(70, 'Compute tier: Provisional (CPU)');
    expectTier(72, 'Compute tier: Unknown');
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.getByRole('link', { name: 'Back to full history' })).toHaveAttribute('href', '#/description-history');
    fireEvent.click(screen.getByRole('button', { name: 'Apply all 2 without alt text' }));
    await screen.findByText(/Media 90 — needs history completion/);
    expectTier(90, 'Compute tier: Provisional (CPU)');
    expect(applyMock).toHaveBeenCalledWith('run-abc', []);
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  });

  it.each([null, 'future_tier'])('does not infer a final tier for a no-draft item with tier %s', async (tier) => {
    fetchItemsMock.mockResolvedValue({
      run_id: 'run-abc',
      items: [{ ...mixedItems.items[3], tier: tier as (typeof mixedItems.items)[number]['tier'] }],
    });
    renderView();
    expect(await screen.findByText('Compute tier: Unknown')).toBeInTheDocument();
    expect(screen.queryByText('Compute tier: Final (GPU)')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apply/ })).not.toBeInTheDocument();
  });

  it('renders each supported naming provenance status and hides absent naming metadata', async () => {
    fetchItemsMock.mockResolvedValue({
      run_id: 'run-naming',
      items: [
        {
          media_id: 81,
          status: 'completed',
          alt_text_draft: 'Ada and Bea stand by a window.',
          caption: 'Two people by a window.',
          provenance: {
            naming: {
              status: 'applied',
              realizer: 'positional_fallback',
              names_applied: ['Ada', 'Bea'],
            },
          },
          ...runItemContract,
          existing_alt: false,
        },
        {
          media_id: 82,
          status: 'completed',
          alt_text_draft: 'A person by a window.',
          caption: 'A person by a window.',
          provenance: {
            naming: { status: 'disabled', realizer: null, names_applied: [] },
          },
          ...runItemContract,
          existing_alt: false,
        },
        {
          media_id: 83,
          status: 'completed',
          alt_text_draft: 'A person by a window.',
          caption: 'Another person by a window.',
          provenance: {
            naming: { status: 'skipped_budget', realizer: null, names_applied: [] },
          },
          ...runItemContract,
          existing_alt: false,
        },
        {
          media_id: 84,
          status: 'completed',
          alt_text_draft: null,
          caption: null,
          provenance: {
            naming: { status: 'no_faces', realizer: null, names_applied: [] },
          },
          ...runItemContract,
          existing_alt: false,
        },
        {
          media_id: 85,
          status: 'completed',
          alt_text_draft: 'A landscape.',
          caption: 'A landscape.',
          provenance: null,
          ...runItemContract,
          existing_alt: false,
        },
        {
          media_id: 86,
          status: 'completed',
          alt_text_draft: 'Ada stands by a window.',
          caption: 'A person by a window.',
          provenance: {
            naming: { status: 'applied', realizer: 'grounded', names_applied: ['Ada'] },
          },
          ...runItemContract,
          existing_alt: false,
        },
      ],
    });

    renderView('run-naming');

    expect(await screen.findByText('Ada and Bea stand by a window.')).toBeInTheDocument();
    expect(screen.getByText('Names: Ada, Bea · positional')).toBeInTheDocument();
    expect(screen.getByText('No names (disabled)')).toBeInTheDocument();
    expect(screen.getByText('Names skipped (time budget)')).toBeInTheDocument();
    expect(screen.getByText('No faces')).toBeInTheDocument();
    expect(screen.getByText('Names: Ada · grounded')).toBeInTheDocument();
    expect(screen.queryByTestId('acx-run-apply-naming-85')).not.toBeInTheDocument();

    const positionalBadge = screen.getByTestId('acx-run-apply-naming-81');
    expect(positionalBadge).toHaveAttribute('aria-label', 'Names were applied using positional fallback.');
    expect(positionalBadge).toHaveAttribute('title', 'Names were applied using positional fallback.');
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
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    // [TEST-15] discrimination: goes red if partial rows are dropped from the
    // summary (count-only copy hid which rows needed a retry). Uses itemHeading
    // plus media id so colliding captions stay distinct. [BR-90d][BR-111]
    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent(/Applied 1 descriptions/);
    expect(status).toHaveTextContent(
      /1 had alt text saved \(A car\. \(Media 90\)\); apply again so they appear in history/,
    );

    // Partial retry is actionable without ticking overwrite checkboxes.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled(),
    );
    // Safe panel swaps to history-completion language — not the empty "safe" lie. [BR-90a]
    expect(screen.getByRole('heading', { level: 2, name: /need history completion/ })).toBeInTheDocument();
    expect(screen.getByText(/Media 90 — needs history completion \(no overwrite\)/)).toBeInTheDocument();
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
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue(afterPartialItems);
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
    expect(status).toHaveTextContent(/Media 90/);
    expect(screen.getByRole('alert')).toHaveTextContent(/History is still incomplete/);
    expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled();
    expect(screen.getByText(/Media 90 — needs history completion \(no overwrite\)/)).toBeInTheDocument();
  });

  it('mounts the status live region before any apply result arrives [BR-87][A11Y-21]', async () => {
    renderView();
    // Region is present from first paint (including loading) so ATs track it;
    // first result only mutates content (mount-then-mutate). [BR-117]
    const status = await screen.findByTestId('acx-run-apply-status');
    expect(status).toHaveAttribute('role', 'status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();

    await screen.findByText('A red flower.');
    // Same DOM node survives load → ready. [BR-117]
    expect(screen.getByTestId('acx-run-apply-status')).toBe(status);
  });

  it('preserves live-region element identity across apply result updates [BR-117][A11Y-21]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue(afterPartialItems);
    renderView();
    const status = await screen.findByTestId('acx-run-apply-status');
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));
    await waitFor(() => expect(status).toHaveTextContent(/had alt text saved/));
    expect(screen.getByTestId('acx-run-apply-status')).toBe(status);
  });

  it('acknowledges successful history recovery after a prior partial [BR-90b][BR-120]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue(afterPartialItems);
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

    // [BR-120][TEST-15]: success must clear the recovered id from outstanding.
    // Goes RED if onApplySuccess unions prior ids with data.partial instead of
    // replacing — retry primary, history-completion heading, and write count
    // would keep counting media 90 forever.
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Apply again to complete history for 1/ })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole('heading', { level: 2, name: /need history completion/ })).not.toBeInTheDocument();
    // Write count no longer includes the recovered id (0 selected overwrites).
    expect(screen.getByRole('button', { name: /Apply 0 descriptions/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apply 1 descriptions/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Media 90 — needs history completion/)).not.toBeInTheDocument();
  });

  it('does not announce history complete when a prior partial clears into skipped [BR-103][RLSE-05]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 1/ })).toBeEnabled(),
    );

    // Recovery attempt: server moves partial 90 into skipped_existing (recovery
    // marker absent / stored alt no longer equals draft) — not applied.
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [],
      partial: [],
      skipped_existing: [70, 71, 90],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    fireEvent.click(screen.getByRole('button', { name: /Apply again to complete history for 1/ }));

    const status = await screen.findByRole('status');
    await waitFor(() => expect(status).toHaveTextContent(/History is still incomplete/));
    expect(status).toHaveTextContent(/Media 90/);
    expect(status).toHaveTextContent(/Skipped 3 with existing alt text/);
    expect(status).not.toHaveTextContent(/History is now complete/);
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
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue(afterPartialItems);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    const status = await screen.findByRole('status');
    await waitFor(() => expect(status).toHaveTextContent(/had alt text saved/));
    expect(status).not.toHaveTextContent(/Applied 0 descriptions/);
  });

  it('caps long partial id lists and uses item headings with media ids [BR-90d][BR-111]', async () => {
    const manyPartialIds = [11, 12, 13, 14, 15, 16, 17];
    const manyItems = {
      run_id: 'run-many',
      items: manyPartialIds.map((id) => ({
        media_id: id,
        status: 'completed' as const,
        alt_text_draft: `Draft ${id}`,
        caption: `Caption ${id}`,
        provenance: null,
        ...runItemContract,
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
        ...runItemContract,
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
    expect(status).toHaveTextContent(/Caption 11 \(Media 11\)/);
    expect(status).toHaveTextContent(/Caption 15 \(Media 15\)/);
    // Sixth and seventh headings are folded into "and 2 more".
    expect(status).not.toHaveTextContent(/Caption 16/);
  });

  it('surfaces media ids alongside colliding captions on partial rows [BR-111]', async () => {
    const colliding = {
      run_id: 'run-collide',
      items: [
        {
          media_id: 11,
          status: 'completed' as const,
          alt_text_draft: 'Draft A',
          caption: 'Untitled',
          provenance: null,
          existing_alt: false,
        },
        {
          media_id: 12,
          status: 'completed' as const,
          alt_text_draft: 'Draft B',
          caption: 'Untitled',
          provenance: null,
          existing_alt: false,
        },
        {
          media_id: 13,
          status: 'completed' as const,
          alt_text_draft: 'Draft C',
          caption: 'Untitled',
          provenance: null,
          existing_alt: false,
        },
      ].map((item) => ({ ...item, ...runItemContract })),
    };
    const afterCollide = {
      run_id: 'run-collide',
      items: colliding.items.map((item) => ({ ...item, existing_alt: true })),
    };
    fetchItemsMock.mockResolvedValueOnce(colliding).mockResolvedValue(afterCollide);
    applyMock.mockResolvedValue({
      run_id: 'run-collide',
      applied: [],
      partial: [11, 12, 13],
      skipped_existing: [],
      skipped_no_draft: [],
      skipped_invalid: [],
      failed: [],
    });
    renderView('run-collide');
    await screen.findByText('Draft A');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 3 without alt text/ }));

    const status = await screen.findByRole('status');
    await waitFor(() => expect(status).toHaveTextContent(/had alt text saved/));
    // Labels must carry media ids — three "Untitled" alone is unusable.
    expect(status).toHaveTextContent(/Untitled \(Media 11\)/);
    expect(status).toHaveTextContent(/Untitled \(Media 12\)/);
    expect(status).toHaveTextContent(/Untitled \(Media 13\)/);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Apply again to complete history for 3/ })).toBeEnabled(),
    );
    expect(screen.getByText(/Media 11 — needs history completion \(no overwrite\)/)).toBeInTheDocument();
    expect(screen.getByText(/Media 12 — needs history completion \(no overwrite\)/)).toBeInTheDocument();
    expect(screen.getByText(/Media 13 — needs history completion \(no overwrite\)/)).toBeInTheDocument();
  });

  it('exposes a reachable reason when nothing is selected without natively disabling [BR-90e][BR-105][A11Y-24]', async () => {
    fetchItemsMock.mockResolvedValue({
      run_id: 'run-overwrite-only',
      items: [
        {
          media_id: 70,
          status: 'completed',
          alt_text_draft: 'A stone bridge.',
          caption: 'A bridge.',
          provenance: null,
          ...runItemContract,
          existing_alt: true,
        },
      ],
    });
    renderView('run-overwrite-only');
    await screen.findByText('A stone bridge.');

    const button = screen.getByRole('button', { name: /Apply 0 descriptions/ });
    // Idle nothing-selected: focusable, aria-disabled, reason via describedby.
    // Native disabled would drop the control from AT perception. [A11Y-24]
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    const describedBy = button.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const reason = document.getElementById(describedBy ?? '');
    expect(reason).toHaveTextContent(/Nothing selected to apply/);
    // Click must not fire the mutation while nothing is selected.
    fireEvent.click(button);
    expect(applyMock).not.toHaveBeenCalled();
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
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockResolvedValue({
      run_id: 'run-abc',
      items: [
        {
          media_id: 71,
          status: 'completed',
          alt_text_draft: 'A red flower.',
          caption: 'A flower.',
          provenance: null,
          existing_alt: true,
        },
        {
          media_id: 90,
          status: 'completed',
          alt_text_draft: 'A blue car.',
          caption: 'A car.',
          provenance: null,
          existing_alt: true,
        },
        {
          media_id: 70,
          status: 'completed',
          alt_text_draft: 'A stone bridge.',
          caption: 'A bridge.',
          provenance: null,
          existing_alt: true,
        },
        { media_id: 72, status: 'failed', alt_text_draft: null, caption: null, provenance: null, existing_alt: false },
      ].map((item) => ({ ...item, ...runItemContract })),
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

  it('does not double-count an outstanding partial while items refetch is stale [BR-110]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    // Hold the post-apply items refetch unresolved so existing_alt stays false
    // for written rows — the stale window that previously double-counted 90.
    let resolveRefetch: ((value: typeof afterPartialItems) => void) | undefined;
    const refetchPromise = new Promise<typeof afterPartialItems>((resolve) => {
      resolveRefetch = resolve;
    });
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockImplementationOnce(() => refetchPromise);
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    // Stale window: outstanding 90 set immediately; items still pre-write so
    // existing_alt is false for both 71 and 90. Without the fix, 90 sits in
    // withoutAlt AND outstanding → totalWriteCount 3. With the fix: withoutAlt
    // drops 90, count is 1 (stale 71) + 1 (partial 90) = 2 — never 3.
    await waitFor(() => expect(screen.getByRole('button', { name: /Apply 2 descriptions/ })).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Apply 3 descriptions/ })).not.toBeInTheDocument();
    // Media 90 listed once as history-completion, not also as a plain safe row.
    expect(screen.getAllByText(/Media 90 — needs history completion \(no overwrite\)/)).toHaveLength(1);
    const plainMediaNinety = screen.queryAllByText((_, node) => node?.textContent === 'Media 90');
    expect(plainMediaNinety.filter((el) => el.classList?.contains('acx-run-apply__media-id'))).toHaveLength(0);
    // 71 remains in the safe list under the stale items snapshot (not an
    // undercount concern — do not invent a fix for fully-applied ids here).
    expect(screen.getByText('A red flower.')).toBeInTheDocument();
    expect(screen.getByText(/These images have no alt text yet, so their drafts apply safely/)).toBeInTheDocument();

    // Unblock refetch so the suite does not leak.
    resolveRefetch?.(afterPartialItems);
    await waitFor(() => expect(fetchItemsMock).toHaveBeenCalledTimes(2));
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
    await waitFor(() => expect(screen.getByLabelText(/Overwrite existing alt text for media 70/)).not.toBeChecked());

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
      items: [
        {
          media_id: 5,
          status: 'failed',
          alt_text_draft: null,
          caption: null,
          provenance: null,
          ...runItemContract,
          existing_alt: false,
        },
      ],
    });

    renderView('run-empty');

    expect(await screen.findByText('No drafts from this run can be applied.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Apply all/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to Description Runs' })).toHaveAttribute(
      'href',
      '#/description-history',
    );
  });

  it('shows an error state with retry when items fail to load', async () => {
    fetchItemsMock.mockRejectedValue(new Error('boom'));

    renderView();

    expect(await screen.findByText('Could not load this run’s drafts.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    // Live region still mounted on the items-error branch. [BR-117]
    expect(screen.getByTestId('acx-run-apply-status')).toBeInTheDocument();
  });

  it('keeps recovery affordance when post-apply items refetch fails [BR-127][INT-11]', async () => {
    applyMock.mockResolvedValue({
      run_id: 'run-abc',
      applied: [71],
      partial: [90],
      skipped_existing: [70],
      skipped_no_draft: [72],
      skipped_invalid: [],
      failed: [],
    });
    // Initial load succeeds; post-apply invalidate/refetch rejects (502).
    fetchItemsMock.mockResolvedValueOnce(mixedItems).mockRejectedValue(new Error('502'));
    renderView();
    await screen.findByText('A red flower.');

    fireEvent.click(screen.getByRole('button', { name: /Apply all 2 without alt text/ }));

    // Recovery must remain reachable despite the items *read* failure.
    // Retained pre-refetch items keep 71 in withoutAlt, so the primary is the
    // union label — not the cold load-error panel, and not a lost recovery.
    await waitFor(() =>
      expect(screen.getByText(/Media 90 — needs history completion \(no overwrite\)/)).toBeInTheDocument(),
    );
    expect(screen.getByTestId('acx-run-apply-status')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(/Media 90/);
    expect(screen.getByRole('status')).toHaveTextContent(/apply again so they appear in history/);
    // Primary still offers the outstanding partial write (union with stale safe).
    expect(screen.getByRole('button', { name: /Apply 2 descriptions/ })).toBeEnabled();
    // Must not collapse to the cold load-error panel.
    expect(screen.queryByText('Could not load this run’s drafts.')).not.toBeInTheDocument();
  });
});
