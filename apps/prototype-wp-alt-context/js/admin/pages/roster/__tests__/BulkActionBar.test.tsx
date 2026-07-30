import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { BulkActionBar } from '../BulkActionBar';

// Controllable _n mock: default English binary; S2-BR-02 forces plural for count===1.
const nMock = vi.hoisted(() => ({ forcePlural: false }));

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => {
    if (nMock.forcePlural) {
      return plural;
    }
    return count === 1 ? single : plural;
  },
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
    // Production: 3 selected clusters → total = sourceIds.length = 2
    render(
      <BulkActionBar
        count={3}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        isMerging
        mergeProgress={{ current: 1, total: 2 }}
      />,
    );

    const status = screen.getByRole('status');
    // Progress counts source merge steps, not selected clusters.
    expect(status).toHaveTextContent(/Merging source 1 of 2/i);
    expect(status).not.toHaveTextContent(/Merging 1 of 3/i);
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

    it('progress Merging source N of M… uses source-step totals (S2-BR-01 / S2-BR-03)', () => {
      // Production progress for 3 selected clusters: total = sourceIds.length = 2.
      // Must not reuse idle cluster-count phrasing ("Merge 3 clusters") or claim
      // "Merging 1 of 3…" (selection size as step total).
      render(
        <BulkActionBar
          count={3}
          {...defaultProps}
          isMerging
          mergeProgress={{ current: 1, total: 2 }}
        />,
      );

      const merge = screen.getByRole('button', { name: 'Merging source 1 of 2…' });
      expect(merge).toBeDisabled();
      expect(screen.getByRole('status')).toHaveTextContent('Merging source 1 of 2…');
      // Not the idle cluster-count phrasing, and not selection size as denominator.
      expect(screen.queryByRole('button', { name: 'Merging 1 of 3…' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Merging 3 clusters…' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Merge 3 clusters' })).not.toBeInTheDocument();
    });

    it('Dismissing… state includes count and cluster object', () => {
      render(<BulkActionBar count={1} {...defaultProps} isDismissing />);

      expect(screen.getByRole('button', { name: 'Dismissing 1 cluster…' })).toBeDisabled();
    });
  });

  describe('pluralisation follows _n (S2-BR-02)', () => {
    afterEach(() => {
      nMock.forcePlural = false;
    });

    it('labels use the form _n selects even when count === 1 would be English-singular', () => {
      // Force _n to always return the plural form so a local
      // `count === 1 ? singular : plural` ternary cannot satisfy the labels.
      nMock.forcePlural = true;

      render(<BulkActionBar count={1} {...defaultProps} />);

      // _n chose plural; labels must follow that choice, not a local English ternary.
      expect(screen.getByRole('button', { name: 'Merge 1 clusters' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Dismiss 1 clusters' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Merge 1 cluster' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Dismiss 1 cluster' })).not.toBeInTheDocument();
    });

    it('in-flight labels also follow _n form choice at count === 1', () => {
      nMock.forcePlural = true;

      const { rerender } = render(<BulkActionBar count={1} {...defaultProps} isMerging />);
      expect(screen.getByRole('button', { name: 'Merging 1 clusters…' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Merging 1 cluster…' })).not.toBeInTheDocument();

      rerender(<BulkActionBar count={1} {...defaultProps} isDismissing />);
      expect(screen.getByRole('button', { name: 'Dismissing 1 clusters…' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Dismissing 1 cluster…' })).not.toBeInTheDocument();
    });
  });
});
