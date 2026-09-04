import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import type { DescribeRunResponse } from '../../../api/describeApi';
import { _resetCooldownForTests, openCooldown } from '../../../utils/recognitionCooldown';
import { BulkDescribeCta, MediaSelection } from '../MediaSelection';
import { RECOGNITION_POLICY } from '../mediaFooterCtaState';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (fmt: string, ...args: (string | number)[]) => {
    let i = 0;
    return fmt.replace(/%\d+\$[sd]/g, () => String(args[i++])).replace(/%[sd]/g, () => String(args[i++]));
  },
}));

vi.mock('../BulkDescribeReviewLink', () => ({
  BulkDescribeReviewLink: () => null,
}));

// WBUX6-W4-H-01: these fixtures were partial object literals widened with
// `as DescribeRunResponse`, which silently absorbs every field the contract
// later adds -- `recognition_enabled` became required and not one of the four
// call sites went red. The factory returns a COMPLETE response, so a new
// required field breaks compilation here instead of shipping an untested shape.
const describeRun = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-1',
  status: 'running',
  phase: 'describing',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 4,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: null,
  recognition_enabled: true,
  ...overrides,
});

const idleProgress = {
  status: null,
  run: null,
  isTerminal: false,
  isError: false,
  isPolling: false,
  etaSeconds: null,
  progressFraction: 0,
  retry: vi.fn(),
} as unknown as DescribeRunProgress;

/**
 * WBUX6-W3-L1-03: a FACTORY, not a shared module-level object. A single `vi.fn()`
 * reused across every case lets call counts accumulate across tests — one
 * `toHaveBeenCalledTimes` away from a false green [TEST-15 lexicons/engineering.md:396].
 * Fresh spies per render remove the hazard by construction rather than relying on a
 * reset hook that a future case can forget.
 */
const baseProps = () => ({
  selectedCount: 2,
  isSubmitting: false,
  isCancelling: false,
  isRunning: false,
  runId: null as string | null,
  progress: idleProgress,
  isPanelVisible: false,
  errorMessage: null as string | null,
  isIdentifying: false,
  // A resolved, production-reachable policy. The old default paired
  // `isSettingsPending: false` with an unknown policy — a state the container could
  // never produce, so the matrix was asserted against an impossible config.
  recognitionPolicy: RECOGNITION_POLICY.OFF,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
  onDismiss: vi.fn(),
  onRetryPolling: vi.fn(),
});

/** The aria-describedby targets currently wired to a control, in DOM-id order. */
const describedIds = (button: HTMLElement): string[] =>
  (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);

/** Concatenated text of every aria-describedby target, for reason-reachability asserts. */
const describedText = (button: HTMLElement): string =>
  describedIds(button)
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ');

describe('BulkDescribeCta state matrix (A11Y-24)', () => {
  afterEach(() => {
    _resetCooldownForTests();
    vi.clearAllMocks();
  });

  // empty / loading / error fill gaps left by the offline column (Slice 2).
  it('keeps the submit primary reachable at zero selection: aria-disabled + reason, never HTML disabled (rg-003 / A11Y-11 / A11Y-24)', () => {
    render(<BulkDescribeCta {...baseProps()} selectedCount={0} />);

    const button = screen.getByRole('button', { name: 'Describe selected' });
    // rg-003: reachable from the zero state — still in the tab order.
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    // A11Y-04 (2.5.3): visible text IS the accessible name at zero selection.
    expect(button).toHaveTextContent('Describe selected');
    // The hold reason must be reachable from the focusable control.
    expect(describedText(button)).toContain('Select at least one media item to describe.');
  });

  it('no-ops activation at zero selection instead of starting a run (rg-003 hold, not a silent submit)', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps()} selectedCount={0} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole('button', { name: 'Describe selected' }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits normally once a row is selected (the hold releases)', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps()} selectedCount={3} onSubmit={onSubmit} />);

    const button = screen.getByRole('button', { name: 'Describe 3 selected' });
    expect(button).not.toHaveAttribute('aria-disabled');
    // Only the standing recognition disclosure remains described; the zero-selection
    // hold reason must be gone, or the reason would outlive the hold it explains.
    expect(describedIds(button)).toHaveLength(1);
    expect(describedText(button)).not.toContain('Select at least one media item to describe.');
    await userEvent.click(button);

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('keeps identifying primary focusable with aria-disabled, live status, and Cancel', async () => {
    const onCancel = vi.fn();
    render(<BulkDescribeCta {...baseProps()} isIdentifying onCancel={onCancel} />);

    const button = screen.getByRole('button', { name: 'Identifying people…' });
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(describedIds(button).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('status').some((node) => node.textContent === 'Identifying people…')).toBe(true);

    // WBUX6-W4-R-02: while identifying, this control aborts the SCAN — there is no
    // describe run yet — so its visible text must say so [INT-06 interaction-ux.md:163]
    // [A11Y-04 accessibility.md:72]. The old assertion pinned the wrong operation.
    expect(screen.queryByRole('button', { name: 'Cancel describe run' })).not.toBeInTheDocument();
    // One Cancel control spans both waits — the label varies, the control does not.
    expect(screen.getAllByRole('button', { name: /^Cancel / })).toHaveLength(1);
    const cancel = screen.getByRole('button', { name: 'Cancel people identification' });
    expect(cancel).not.toBeDisabled();
    await userEvent.click(cancel);
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('does not fire onSubmit when clicked while identifying (no double-start)', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps()} isIdentifying onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole('button', { name: 'Identifying people…' }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('holds submit with a loading label while settings are pending (still focusable)', async () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps()}
        recognitionPolicy={RECOGNITION_POLICY.LOADING}
        onSubmit={onSubmit}
      />,
    );

    const button = screen.getByRole('button', { name: 'Loading settings…' });
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(button);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('shows loading label and disables submit while submitting', () => {
    render(<BulkDescribeCta {...baseProps()} isSubmitting />);

    expect(screen.getByRole('button', { name: 'Starting describe run…' })).toBeDisabled();
  });

  it('surfaces submit error message when present', () => {
    render(<BulkDescribeCta {...baseProps()} errorMessage="Describe service unavailable" />);

    expect(screen.getByText('Describe service unavailable')).toBeInTheDocument();
  });

  it('announces submit errors with role=alert so they are not colour-only (BR-143 / A11Y-21 / A11Y-24)', () => {
    // Stranded-run notice from formatBulkDescribeErrorMessage: text must be
    // exposed via an assertive live region, not a bare coloured span [sr-004].
    const strandedNotice =
      'Failed to store describe run media membership. The describe run run-stranded-42 is already running upstream but cannot be applied on this site. Note the run id and retry or contact support — do not start another run for the same items.';
    render(<BulkDescribeCta {...baseProps()} errorMessage={strandedNotice} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('run-stranded-42');
    expect(alert).toHaveTextContent('already running upstream');
    expect(alert.className).toContain('acx-media-selection__bulk-describe-error');
  });

  it('gates submit with aria-disabled + a reason when offline (§7: never HTML disabled)', () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps()}
        onSubmit={onSubmit}
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    // §7 offline row: still focusable (not HTML disabled), reason reachable.
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    const reasonIds = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
    expect(reasonIds.length).toBeGreaterThan(0);
    expect(
      reasonIds.some(
        (id) =>
          document.getElementById(id)?.textContent ===
          'Unavailable while the recognition service is offline',
      ),
    ).toBe(true);
    // The onSubmit prop itself guards offline in the container (if (offline) return).
  });

  it('marks the SUBMIT BUTTON (not a neutral wrapper) as the accent primary when it owns the footer accent (§7 / BR-73)', () => {
    const { rerender, container } = render(<BulkDescribeCta {...baseProps()} accentPrimary />);
    const marked = container.querySelectorAll('[data-acx-accent-primary]');
    expect(marked).toHaveLength(1);
    // BR-73: the marker sits on the actually-accent-styled submit button — never the
    // wrapper div — and the accent chrome class rides with it.
    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    expect(marked[0]).toBe(button);
    expect(button.className).toContain('acx-accent-primary-action');

    rerender(<BulkDescribeCta {...baseProps()} accentPrimary={false} />);
    expect(container.querySelectorAll('[data-acx-accent-primary]')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Describe 2 selected' }).className).not.toContain(
      'acx-accent-primary-action',
    );
  });

  it('offline never HTML-disables even at zero selection — reason stays reachable (§7 / BR-74)', () => {
    render(
      <BulkDescribeCta
        {...baseProps()}
        selectedCount={0}
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    const button = screen.getByRole('button', { name: 'Describe selected' });
    // Airplane-mode reload at zero selection: focusable (not HTML disabled), reason reachable.
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    // Offline AND zero selection: BOTH holds are joined onto the one control alongside
    // the standing recognition disclosure, so neither reason is silently dropped when
    // the other applies (A11Y-24 state matrix).
    expect(describedIds(button)).toHaveLength(3);
    const reasonText = describedText(button);
    expect(reasonText).toContain('Unavailable while the recognition service is offline');
    expect(reasonText).toContain('Select at least one media item to describe.');
    expect(reasonText).toContain('People are not identified (recognition off)');
  });

  it('does not fire onSubmit when clicked while offline-gated (§7 / BR-76)', async () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps()}
        onSubmit={onSubmit}
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Describe 2 selected' }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  // WBUX6-W3-L1-03 discrimination pair: BOTH cases click the primary wired to the
  // FACTORY-DEFAULT onSubmit and assert exactly one call. With a shared module-level
  // spy the second case sees two calls and goes red — that is the false green this
  // fix removes [TEST-15 lexicons/engineering.md:396].
  it('gives each case its own default spies (pair 1 of 2)', async () => {
    const props = baseProps();
    render(<BulkDescribeCta {...props} />);
    await userEvent.click(screen.getByRole('button', { name: 'Describe 2 selected' }));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('gives each case its own default spies (pair 2 of 2)', async () => {
    const props = baseProps();
    render(<BulkDescribeCta {...props} />);
    await userEvent.click(screen.getByRole('button', { name: 'Describe 2 selected' }));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('enables submit when online with selection', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps()} onSubmit={onSubmit} />);

    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    expect(button).not.toBeDisabled();
    await userEvent.click(button);
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('announces a frozen-progress waiting state instead of an error dead-end (BR-07 / A11Y-21)', () => {
    const runningRun = describeRun({ completed: 2, total: 4, eta_seconds: 30 });
    const progress = {
      ...idleProgress,
      run: runningRun,
      status: 'running',
      isFrozen: true,
      isPolling: true,
      progressFraction: 0.5,
      stalledForSeconds: null,
    } as DescribeRunProgress;

    render(<BulkDescribeCta {...baseProps()} isRunning runId="run-1" progress={progress} isPanelVisible />);

    const notice = screen.getByText(/Waiting for the service — progress updates paused/);
    // Announced via the surrounding polite live region, not a visual-only hint.
    expect(notice.closest('[role="status"]')).not.toBeNull();
    // The frozen state keeps the last-known progress visible — no error dead-end.
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('announces the shared recognition cooldown with its remaining window', () => {
    openCooldown(30);
    const runningRun = describeRun({ completed: 1, total: 4, eta_seconds: 60 });
    const progress = {
      ...idleProgress,
      run: runningRun,
      status: 'running',
      isFrozen: false,
      isPolling: true,
      progressFraction: 0.25,
      stalledForSeconds: null,
    } as DescribeRunProgress;

    render(<BulkDescribeCta {...baseProps()} isRunning runId="run-1" progress={progress} isPanelVisible />);

    // The remaining window is visible but aria-hidden so the polite live region
    // is not re-announced every second (A11Y-21); the announced sentence stays
    // static while only the countdown ticks.
    const countdown = screen.getByText(/Retrying in 30s\./);
    expect(countdown).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('Waiting for the service — progress updates paused.')).toBeInTheDocument();
  });

  it('keeps cancel enabled while a run is active even when offline gate is set', async () => {
    const onCancel = vi.fn();
    const progress = {
      ...idleProgress,
      isTerminal: false,
      isError: false,
    } as DescribeRunProgress;

    render(
      <BulkDescribeCta
        {...baseProps()}
        isRunning
        runId="run-1"
        progress={progress}
        isPanelVisible
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
        onCancel={onCancel}
      />,
    );

    const cancel = screen.getByRole('button', { name: 'Cancel describe run' });
    expect(cancel).not.toBeDisabled();
    await userEvent.click(cancel);
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('Review drafts on COMPLETE is a run-history link even if onReviewDrafts is a no-op (WBUX-6 F1)', () => {
    const completeRun = describeRun({
      run_id: 'run-42',
      status: 'completed',
      phase: 'complete',
      completed: 12,
      total: 12,
    });
    const progress = {
      ...idleProgress,
      run: completeRun,
      status: 'completed',
      isTerminal: true,
      isPolling: false,
      progressFraction: 1,
    } as DescribeRunProgress;

    render(
      <BulkDescribeCta
        {...baseProps()}
        runId="run-42"
        progress={progress}
        isPanelVisible
        onReviewDrafts={() => {
          /* mutant: a no-op must not be the apply effector */
        }}
      />,
    );

    const reviewDrafts = screen.getByRole('link', { name: 'Review drafts' });
    expect(reviewDrafts).toHaveAttribute('href', '#/description-history?run=run-42');
  });

  it('shows exactly one Cancel describe run during warming (WBUX-6 F2)', () => {
    const warmingRun = describeRun({ phase: 'warming', total: 12 });
    const progress = {
      ...idleProgress,
      run: warmingRun,
      status: 'running',
      isTerminal: false,
      isPolling: true,
    } as DescribeRunProgress;

    render(<BulkDescribeCta {...baseProps()} isRunning runId="run-1" progress={progress} isPanelVisible />);

    expect(screen.getAllByRole('button', { name: 'Cancel describe run' })).toHaveLength(1);
  });
});

/**
 * WBUX6-MRG-05 (presentational half). The failed-probe state must not behave like the
 * pending one: the primary is actionable, carries its real label, and submits.
 */
describe('BulkDescribeCta — failed settings probe releases the primary (WBUX6-MRG-05)', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('does NOT hold the primary when the settings probe failed (fail open on a probe)', async () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps()}
        recognitionPolicy={RECOGNITION_POLICY.UNAVAILABLE}
        onSubmit={onSubmit}
      />,
    );

    // Not "Loading settings…" — the failure is terminal (`retry: false`), so that label
    // would be an unbounded wait with no degradation path [RES-13 engineering.md:124].
    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    expect(button).not.toBeDisabled();
    expect(button).not.toHaveAttribute('aria-disabled');
    await userEvent.click(button);
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('still holds the primary while the probe is genuinely unresolved (the hold is not just deleted)', async () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps()}
        recognitionPolicy={RECOGNITION_POLICY.LOADING}
        onSubmit={onSubmit}
      />,
    );

    const button = screen.getByRole('button', { name: 'Loading settings…' });
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(button);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('announces the submit round-trip in the polite live region (INT-08 wait state)', () => {
    // The submit POST natively disables the control and takes >1s. It is NOT
    // interruptible — submitBulkDescribeRun takes no abort signal and the upstream run
    // is created server-side — so INT-08 is satisfied with progress, not with a Cancel
    // that would strand a paid run (BR-143). See WBUX6-W3-L1-01.
    render(<BulkDescribeCta {...baseProps()} isSubmitting />);

    expect(
      screen.getAllByRole('status').some((node) => node.textContent === 'Starting describe run…'),
    ).toBe(true);
    // No abort is offered, and none must be faked: a Cancel with no run id is a dead control.
    expect(screen.queryByRole('button', { name: 'Cancel describe run' })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// WBUX6-MRG-05 (wiring half). The presentational cases above prove the CONTRACT;
// they cannot prove the CONTAINER hands the query's error state to it. Without this
// block, replacing `isError: settingsQuery.isError` with `false` in MediaSelection
// leaves every test green while the operator's primary hangs forever. `vi.mock` is
// hoisted, so these container mocks are installed before the module graph loads.
// ---------------------------------------------------------------------------

const { settingsProbe, describeMutate } = vi.hoisted(() => ({
  settingsProbe: { fail: false, recognitionEnabled: false },
  describeMutate: vi.fn(),
}));

const containerItem = (id: number) => ({
  id,
  title: `Photo ${id}`,
  altText: null,
  isDecorative: false,
  status: 'missing' as const,
  thumbnailUrl: null,
  mimeType: 'image/jpeg',
  editUrl: '#',
  updatedAt: '2026-01-01T00:00:00Z',
  dimensions: { width: 100, height: 100 },
  tags: [],
  identities: [],
});
const containerItems = [containerItem(11), containerItem(12)];

vi.mock('../../../api/settingsApi', () => ({
  fetchSettings: vi.fn(() =>
    settingsProbe.fail
      ? Promise.reject(new Error('settings endpoint exploded'))
      : Promise.resolve({ recognition_enabled: settingsProbe.recognitionEnabled }),
  ),
}));

vi.mock('../WorkbenchMediaContext', () => ({
  useWorkbenchMediaContext: () => ({
    selection: {
      selection: { '11': true, '12': true },
      selectedMedia: containerItems,
      toggleRow: vi.fn(),
      toggleAll: vi.fn(),
      isPageFullySelected: () => true,
    },
    filters: {
      searchQuery: '',
      statusFilter: 'all',
      currentPage: 1,
      perPage: 10,
      handleSearchChange: vi.fn(),
      clearSearch: vi.fn(),
      handleStatusChange: vi.fn(),
      setCurrentPage: vi.fn(),
      setPerPage: vi.fn(),
    },
    mediaQueue: {
      mediaQuery: {
        data: { items: containerItems, total: 2, totalPages: 1 },
        isPending: false,
        isFetching: false,
        isError: false,
        isSuccess: true,
        refetch: vi.fn(),
        itemsWithIdentities: containerItems,
        detailQuery: {
          data: { detailsByMedia: {}, limit: 100, total: 2, truncated: false },
          isPending: false,
          isLoading: false,
          isFetching: false,
          isError: false,
          refetch: vi.fn(),
        },
        identitiesQuery: { data: undefined, isLoading: false, isError: false, refetch: vi.fn() },
      },
      statusMessage: 'Showing 2 media items.',
      isStatusPending: false,
      detailTruncationNotice: null,
      hasIdentities: false,
    },
  }),
}));

vi.mock('../../../hooks/useBulkDescribe', () => ({
  useBulkDescribe: () => ({
    submit: { isPending: false, mutate: describeMutate, error: null },
    cancel: { isPending: false, mutate: vi.fn(), error: null },
    progress: {
      status: null,
      run: null,
      isTerminal: false,
      isError: false,
      isPolling: false,
      etaSeconds: null,
      progressFraction: 0,
      retry: vi.fn(),
      error: null,
      stalledForSeconds: null,
      isFrozen: false,
    },
    runId: null,
    errorMessage: null,
  }),
}));

vi.mock('../../../hooks/useSyncOffline', () => ({ useSyncOffline: () => false }));
vi.mock('../../../hooks/useRemoteActionGate', () => ({
  useRemoteActionGate: () => ({ title: undefined, 'aria-disabled': undefined }),
}));
vi.mock('../JobPipelineContext', () => ({
  useJobPipeline: () => ({
    scanRun: { isScanning: false, progress: null, jobId: null },
    scan: vi.fn(),
    scanAndWait: vi.fn(() => Promise.resolve()),
    cancelScan: vi.fn(),
    history: { activeJobIds: [] as string[] },
  }),
}));
vi.mock('../Panels', () => ({
  isClusteringActive: () => false,
  mediaEditUrl: (id: number) => `#edit-${id}`,
}));

const renderContainer = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MediaSelection />
    </QueryClientProvider>,
  );
};

describe('MediaSelection settings probe wiring (WBUX6-MRG-05)', () => {
  afterEach(() => {
    settingsProbe.fail = false;
    settingsProbe.recognitionEnabled = false;
    describeMutate.mockClear();
  });

  it('a FAILED settings query releases the hold and lets Describe run (no forever-wait)', async () => {
    settingsProbe.fail = true;
    renderContainer();

    // `retry: false` makes this failure terminal: before the fix the primary stayed on
    // "Loading settings…" and the disclosure on "Checking recognition settings…" forever
    // [RES-13 engineering.md:124][RLSE-04 :695][A11Y-24 accessibility.md:154].
    const button = await screen.findByRole('button', { name: 'Describe 2 selected' });
    await waitFor(() => expect(button).not.toHaveAttribute('aria-disabled'));
    // Two surfaces, wired end-to-end through the real container: the aria-describedby
    // disclosure and the separate polite live region (WBUX6-W4-B-02).
    expect(
      screen.getAllByText(/Recognition settings unavailable — describing without identifying people/),
    ).toHaveLength(2);
    expect(screen.queryByText(/Checking recognition settings/)).not.toBeInTheDocument();

    await userEvent.click(button);
    // Degraded path: describe proceeds with recognition treated as OFF.
    expect(describeMutate).toHaveBeenCalledWith([11, 12]);
  });

  it('a SUCCEEDING settings query still resolves to the real policy (the fix is not "always degrade")', async () => {
    renderContainer();

    const button = await screen.findByRole('button', { name: 'Describe 2 selected' });
    await waitFor(() =>
      expect(screen.getByText(/People are not identified \(recognition off\)/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Recognition settings unavailable/)).not.toBeInTheDocument();
    await userEvent.click(button);
    expect(describeMutate).toHaveBeenCalledWith([11, 12]);
  });

  // WBUX6-W4-H-01 residue: every container case above resolves the probe to
  // `recognition_enabled: false`, so nothing proved the container reads the flag
  // rather than hard-coding the OFF branch. The product default is ON
  // (`RecognitionPolicy::DEFAULT = true`), which is the disclosure operators
  // actually see, and a state the design does not exercise is a state the design
  // has not made [RLSE-04 lexicons/engineering.md:695].
  it('renders the ON disclosure when the probe reports recognition enabled (the flag is read, not assumed)', async () => {
    settingsProbe.recognitionEnabled = true;
    renderContainer();

    await screen.findByRole('button', { name: 'Describe 2 selected' });
    await waitFor(() => expect(screen.getByText(/Identifies people first \(AI\)/)).toBeInTheDocument());
    expect(screen.queryByText(/People are not identified \(recognition off\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Recognition settings unavailable/)).not.toBeInTheDocument();
  });
});
