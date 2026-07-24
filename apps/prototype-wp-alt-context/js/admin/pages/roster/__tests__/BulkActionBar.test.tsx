import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { BulkActionBar } from '../BulkActionBar';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format
      .replace(/%\d+\$[sd]/g, () => String(args[index++]))
      .replace(/%[sd]/g, () => String(args[index++]));
  },
}));

describe('BulkActionBar', () => {
  it('shows loading and disables merge action while merging', () => {
    render(
      <BulkActionBar
        count={3}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        isMerging
        isDismissing={false}
      />,
    );

    const mergeButton = screen.getByRole('button', { name: /merging/i });
    expect(mergeButton).toBeDisabled();
    expect(screen.getByRole('button', { name: /dismiss/i })).toBeDisabled();
  });

  it('exposes per-step progress via role=status live region', () => {
    render(
      <BulkActionBar
        count={3}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        isMerging
        mergeProgress={{ current: 2, total: 3 }}
      />,
    );

    const status = screen.getByRole('status');
    expect(status).toHaveTextContent(/Merging 2 of 3/i);
    expect(screen.getByTestId('bulk-merge-status')).toBe(status);
  });

  it('renders persistent role=alert failure with named cluster and retry', async () => {
    const onRetryMerge = vi.fn();
    const onDismissFailure = vi.fn();

    render(
      <BulkActionBar
        count={2}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        mergeFailure={{
          failedClusterId: 'cluster-abc',
          message: 'Merge failed for cluster cluster-.',
          remainingClusterIds: ['target', 'cluster-abc'],
        }}
        onRetryMerge={onRetryMerge}
        onDismissFailure={onDismissFailure}
      />,
    );

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/Merge failed/i);
    expect(screen.getByTestId('bulk-merge-failure')).toBe(alert);

    await userEvent.click(screen.getByRole('button', { name: /^Retry$/i }));
    expect(onRetryMerge).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: /Dismiss notice/i }));
    expect(onDismissFailure).toHaveBeenCalledTimes(1);
  });

  it('disables controls with reason when controlsDisabled (zero-state rail)', () => {
    render(
      <BulkActionBar
        count={0}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        controlsDisabled
        controlsDisabledReason="No unlabeled clusters need assignment"
      />,
    );

    const merge = screen.getByRole('button', { name: /^Merge$/i });
    const dismiss = screen.getByRole('button', { name: /^Dismiss$/i });
    expect(merge).toBeDisabled();
    expect(dismiss).toBeDisabled();
    expect(merge).toHaveAttribute('title', 'No unlabeled clusters need assignment');
  });
});
