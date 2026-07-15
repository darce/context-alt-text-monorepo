import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { DescribeRunProgress } from '../../../hooks/useDescribeRunProgress';
import { BulkDescribeCta } from '../MediaSelection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
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

  it('disables submit with offline reason when remoteActionDisabled', async () => {
    const onSubmit = vi.fn();
    render(
      <BulkDescribeCta
        {...baseProps}
        onSubmit={onSubmit}
        remoteActionDisabled
        remoteActionAriaDisabled
        remoteActionTitle="Unavailable while the recognition service is offline"
      />,
    );

    const button = screen.getByRole('button', { name: 'Describe selected' });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('title', 'Unavailable while the recognition service is offline');
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(button);
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
        remoteActionDisabled
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
