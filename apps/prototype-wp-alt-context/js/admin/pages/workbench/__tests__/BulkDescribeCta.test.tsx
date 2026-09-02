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
    return fmt.replace(/%[sd]/g, () => String(args[i++]));
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
  it('disables submit in empty selection state (zero selection)', () => {
    render(<BulkDescribeCta {...baseProps} selectedCount={0} />);

    expect(screen.getByRole('button', { name: 'Describe selected' })).toBeDisabled();
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
    const { rerender, container } = render(<BulkDescribeCta {...baseProps} accentPrimary />);
    const marked = container.querySelectorAll('[data-acx-accent-primary]');
    expect(marked).toHaveLength(1);
    // BR-73: the marker sits on the actually-accent-styled submit button — never the
    // wrapper div — and the accent chrome class rides with it.
    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
    expect(marked[0]).toBe(button);
    expect(button.className).toContain('acx-accent-primary-action');

    rerender(<BulkDescribeCta {...baseProps} accentPrimary={false} />);
    expect(container.querySelectorAll('[data-acx-accent-primary]')).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Describe 2 selected' }).className).not.toContain(
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
    const reasonIds = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
    expect(reasonIds.length).toBeGreaterThan(0);
    expect(
      reasonIds.some(
        (id) =>
          document.getElementById(id)?.textContent ===
          'Unavailable while the recognition service is offline',
      ),
    ).toBe(true);
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

    await userEvent.click(screen.getByRole('button', { name: 'Describe 2 selected' }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('enables submit when online with selection', async () => {
    const onSubmit = vi.fn();
    render(<BulkDescribeCta {...baseProps} onSubmit={onSubmit} />);

    const button = screen.getByRole('button', { name: 'Describe 2 selected' });
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
});
