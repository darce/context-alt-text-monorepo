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

const defaultProps = {
  onMerge: vi.fn(),
  onDismiss: vi.fn(),
  onClear: vi.fn(),
};

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

    const merge = screen.getByRole('button', { name: /^Merge 0 clusters$/i });
    const dismiss = screen.getByRole('button', { name: /^Dismiss 0 clusters$/i });
    expect(merge).toBeDisabled();
    expect(dismiss).toBeDisabled();
    expect(merge).toHaveAttribute('title', 'No unlabeled clusters need assignment');
  });

  describe('accessible names name count + cluster object (INT-06 / A11Y-04)', () => {
    it('count === 0: both disabled, names still parse with object', () => {
      render(<BulkActionBar count={0} {...defaultProps} />);

      const merge = screen.getByRole('button', { name: 'Merge 0 clusters' });
      const dismiss = screen.getByRole('button', { name: 'Dismiss 0 clusters' });
      expect(merge).toBeDisabled();
      expect(dismiss).toBeDisabled();
    });

    it('count === 1: Merge disabled (threshold), Dismiss enabled and singular', () => {
      render(<BulkActionBar count={1} {...defaultProps} />);

      // Decision: disabled Merge still reports the real selection ("Merge 1 cluster").
      const merge = screen.getByRole('button', { name: 'Merge 1 cluster' });
      const dismiss = screen.getByRole('button', { name: 'Dismiss 1 cluster' });
      expect(merge).toBeDisabled();
      expect(dismiss).toBeEnabled();
    });

    it('count === 3: both enabled, both named plural with the right number', () => {
      render(<BulkActionBar count={3} {...defaultProps} />);

      const merge = screen.getByRole('button', { name: 'Merge 3 clusters' });
      const dismiss = screen.getByRole('button', { name: 'Dismiss 3 clusters' });
      expect(merge).toBeEnabled();
      expect(dismiss).toBeEnabled();
    });

    it('accessible name tracks count — different counts produce different names', () => {
      const { rerender } = render(<BulkActionBar count={2} {...defaultProps} />);
      expect(screen.getByRole('button', { name: 'Merge 2 clusters' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Dismiss 2 clusters' })).toBeInTheDocument();

      rerender(<BulkActionBar count={5} {...defaultProps} />);
      expect(screen.getByRole('button', { name: 'Merge 5 clusters' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Dismiss 5 clusters' })).toBeInTheDocument();
      // Hardcoded single string cannot pass both counts.
      expect(screen.queryByRole('button', { name: 'Merge 2 clusters' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Dismiss 2 clusters' })).not.toBeInTheDocument();
    });

    it('pins merge threshold at count < 2 (not flattened to count < 1)', () => {
      const { rerender } = render(<BulkActionBar count={1} {...defaultProps} />);
      expect(screen.getByRole('button', { name: 'Merge 1 cluster' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Dismiss 1 cluster' })).toBeEnabled();

      rerender(<BulkActionBar count={2} {...defaultProps} />);
      expect(screen.getByRole('button', { name: 'Merge 2 clusters' })).toBeEnabled();
      expect(screen.getByRole('button', { name: 'Dismiss 2 clusters' })).toBeEnabled();
    });
  });

  describe('in-flight labels keep the object', () => {
    it('simple Merging… state includes count and cluster object', () => {
      render(<BulkActionBar count={3} {...defaultProps} isMerging />);

      expect(screen.getByRole('button', { name: 'Merging 3 clusters…' })).toBeDisabled();
    });

    it('progress Merging N of M… is preserved on the control and live region', () => {
      render(
        <BulkActionBar
          count={3}
          {...defaultProps}
          isMerging
          mergeProgress={{ current: 2, total: 3 }}
        />,
      );

      expect(screen.getByRole('button', { name: 'Merging 2 of 3…' })).toBeDisabled();
      expect(screen.getByRole('status')).toHaveTextContent('Merging 2 of 3…');
    });

    it('Dismissing… state includes count and cluster object', () => {
      render(<BulkActionBar count={1} {...defaultProps} isDismissing />);

      expect(screen.getByRole('button', { name: 'Dismissing 1 cluster…' })).toBeDisabled();
    });
  });
});
