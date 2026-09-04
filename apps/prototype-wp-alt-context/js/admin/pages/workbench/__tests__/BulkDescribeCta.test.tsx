import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import type { DescribeRunResponse } from '../../../api/describeApi';
import { _resetCooldownForTests, openCooldown } from '../../../utils/recognitionCooldown';
import { BulkDescribeCta } from '../MediaSelection';

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

const baseProps = {
  selectedCount: 2,
  isSubmitting: false,
  isCancelling: false,
  isRunning: false,
  runId: null as string | null,
  progress: idleProgress,
  isPanelVisible: false,
  errorMessage: null as string | null,
  onSubmit: vi.fn(),
  onCancel: vi.fn(),
  onDismiss: vi.fn(),
  onRetryPolling: vi.fn(),
};

describe('BulkDescribeCta state matrix (A11Y-24)', () => {
  afterEach(() => {
    _resetCooldownForTests();
  });

  // empty / loading / error fill gaps left by the offline column (Slice 2).
  it('keeps the submit primary reachable at zero selection: aria-disabled + reason, never HTML disabled (rg-003 / A11Y-11 / A11Y-24)', () => {
    render(<BulkDescribeCta {...baseProps} selectedCount={0} />);

    const button = screen.getByRole('button', { name: 'Describe selected' });
    // rg-003: reachable from the zero state — still in the tab order.
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    // A11Y-04 (2.5.3): visible text matches the accessible name at zero selection.
    expect(button).toHaveTextContent('Describe selected');
    // The hold reason must be reachable from the focusable control.
    const reasonIds = (button.getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean);
    expect(reasonIds.length).toBeGreaterThan(0);
    const reasonText = reasonIds
      .map((id) => document.getElementById(id)?.textContent ?? '')
      .join(' ');
    expect(reasonText).toContain('Select at least one media item to describe.');
  });

  it('no-ops activation at zero selection instead of starting a run (rg-003 hold, not a silent submit)', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps} selectedCount={0} onSubmit={onSubmit} />);

    await userEvent.click(screen.getByRole('button', { name: 'Describe selected' }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits normally once a row is selected (the hold releases)', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps} selectedCount={3} onSubmit={onSubmit} />);

    const button = screen.getByRole('button', { name: 'Describe selected' });
    expect(button).not.toHaveAttribute('aria-disabled');
    expect(button).not.toHaveAttribute('aria-describedby');
    await userEvent.click(button);

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('shows loading label and disables submit while submitting', () => {
    render(<BulkDescribeCta {...baseProps} isSubmitting />);

    expect(screen.getByRole('button', { name: 'Starting describe run…' })).toBeDisabled();
  });

  it('surfaces submit error message when present', () => {
    render(<BulkDescribeCta {...baseProps} errorMessage="Describe service unavailable" />);

    expect(screen.getByText('Describe service unavailable')).toBeInTheDocument();
  });

  it('announces submit errors with role=alert so they are not colour-only (BR-143 / A11Y-21 / A11Y-24)', () => {
    // Stranded-run notice from formatBulkDescribeErrorMessage: text must be
    // exposed via an assertive live region, not a bare coloured span [sr-004].
    const strandedNotice =
      'Failed to store describe run media membership. The describe run run-stranded-42 is already running upstream but cannot be applied on this site. Note the run id and retry or contact support — do not start another run for the same items.';
    render(<BulkDescribeCta {...baseProps} errorMessage={strandedNotice} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('run-stranded-42');
    expect(alert).toHaveTextContent('already running upstream');
    expect(alert.className).toContain('acx-media-selection__bulk-describe-error');
  });

  it('gates submit with aria-disabled + a reason when offline (§7: never HTML disabled)', () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps}
        onSubmit={onSubmit}
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    const button = screen.getByRole('button', { name: 'Describe selected' });
    // §7 offline row: still focusable (not HTML disabled), reason reachable.
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    const reasonId = button.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId ?? '')).toHaveTextContent(
      'Unavailable while the recognition service is offline',
    );
    // The onSubmit prop itself guards offline in the container (if (offline) return).
  });

  it('marks the SUBMIT BUTTON (not a neutral wrapper) as the accent primary when it owns the footer accent (§7 / BR-73)', () => {
    const { rerender, container } = render(<BulkDescribeCta {...baseProps} accentPrimary />);
    const marked = container.querySelectorAll('[data-acx-accent-primary]');
    expect(marked).toHaveLength(1);
    // BR-73: the marker sits on the actually-accent-styled submit button — never the
    // wrapper div — and the accent chrome class rides with it.
    const button = screen.getByRole('button', { name: 'Describe selected' });
    expect(marked[0]).toBe(button);
    expect(button.className).toContain('acx-accent-primary-action');

    rerender(<BulkDescribeCta {...baseProps} accentPrimary={false} />);
    expect(container.querySelectorAll('[data-acx-accent-primary]')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Describe selected' }).className).not.toContain(
      'acx-accent-primary-action',
    );
  });

  it('offline never HTML-disables even at zero selection — reason stays reachable (§7 / BR-74)', () => {
    render(
      <BulkDescribeCta
        {...baseProps}
        selectedCount={0}
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    const button = screen.getByRole('button', { name: 'Describe selected' });
    // Airplane-mode reload at zero selection: focusable (not HTML disabled), reason reachable.
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    // Offline AND zero selection: BOTH reasons are joined onto the one control, so
    // neither hold is silently dropped when the other applies (A11Y-24 state matrix).
    const reasonIds = (button.getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean);
    expect(reasonIds.length).toBe(2);
    const reasonText = reasonIds.map((id) => document.getElementById(id)?.textContent ?? '').join(' ');
    expect(reasonText).toContain('Unavailable while the recognition service is offline');
    expect(reasonText).toContain('Select at least one media item to describe.');
  });

  it('does not fire onSubmit when clicked while offline-gated (§7 / BR-76)', async () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps}
        onSubmit={onSubmit}
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Describe selected' }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('enables submit when online with selection', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps} onSubmit={onSubmit} />);

    const button = screen.getByRole('button', { name: 'Describe selected' });
    expect(button).not.toBeDisabled();
    await userEvent.click(button);
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('announces a frozen-progress waiting state instead of an error dead-end (BR-07 / A11Y-21)', () => {
    const runningRun = {
      run_id: 'run-1',
      status: 'running',
      completed: 2,
      failed: 0,
      skipped: 0,
      total: 4,
      eta_seconds: 30,
    } as DescribeRunResponse;
    const progress = {
      ...idleProgress,
      run: runningRun,
      status: 'running',
      isFrozen: true,
      isPolling: true,
      progressFraction: 0.5,
      stalledForSeconds: null,
    } as DescribeRunProgress;

    render(<BulkDescribeCta {...baseProps} isRunning runId="run-1" progress={progress} isPanelVisible />);

    const notice = screen.getByText(/Waiting for the service — progress updates paused/);
    // Announced via the surrounding polite live region, not a visual-only hint.
    expect(notice.closest('[role="status"]')).not.toBeNull();
    // The frozen state keeps the last-known progress visible — no error dead-end.
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('announces the shared recognition cooldown with its remaining window', () => {
    openCooldown(30);
    const runningRun = {
      run_id: 'run-1',
      status: 'running',
      completed: 1,
      failed: 0,
      skipped: 0,
      total: 4,
      eta_seconds: 60,
    } as DescribeRunResponse;
    const progress = {
      ...idleProgress,
      run: runningRun,
      status: 'running',
      isFrozen: false,
      isPolling: true,
      progressFraction: 0.25,
      stalledForSeconds: null,
    } as DescribeRunProgress;

    render(<BulkDescribeCta {...baseProps} isRunning runId="run-1" progress={progress} isPanelVisible />);

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
        {...baseProps}
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
    const completeRun = {
      tenant_id: 'tenant',
      run_id: 'run-42',
      status: 'completed',
      phase: 'complete',
      completed: 12,
      failed: 0,
      skipped: 0,
      total: 12,
      cancel_requested: false,
      eta_seconds: null,
      gpu_state: null,
    } as DescribeRunResponse;
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
        {...baseProps}
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
    const warmingRun = {
      tenant_id: 'tenant',
      run_id: 'run-1',
      status: 'running',
      phase: 'warming',
      completed: 0,
      failed: 0,
      skipped: 0,
      total: 12,
      cancel_requested: false,
      eta_seconds: null,
      gpu_state: null,
    } as DescribeRunResponse;
    const progress = {
      ...idleProgress,
      run: warmingRun,
      status: 'running',
      isTerminal: false,
      isPolling: true,
    } as DescribeRunProgress;

    render(<BulkDescribeCta {...baseProps} isRunning runId="run-1" progress={progress} isPanelVisible />);

    expect(screen.getAllByRole('button', { name: 'Cancel describe run' })).toHaveLength(1);
  });
});
