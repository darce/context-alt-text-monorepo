import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React, { useMemo, useState } from 'react';

import type { BulkMergeFailure } from '../hooks/useClusterActions';
import { BulkActionBar } from '../BulkActionBar';
import { ConfirmDialog } from '../ConfirmDialog';
import { useRosterBulkConfirmation } from '../useRosterBulkConfirmation';

// Controllable _n mock: default English binary; S2-BR-02 forces plural for count===1.
// Spy so tests can assert the real count is passed (not collapsed to 1-or-2).
const nMock = vi.hoisted(() => ({ forcePlural: false }));

const i18nMocks = vi.hoisted(() => ({
  _n: vi.fn((single: string, plural: string, count: number) => {
    if (nMock.forcePlural) {
      return plural;
    }
    return count === 1 ? single : plural;
  }),
}));

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: i18nMocks._n,
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

/** Wires BulkActionBar + ConfirmDialog through useRosterBulkConfirmation (NeedsAssignment shape). */
const BulkConfirmHarness = ({
  mergeAsync,
}: {
  mergeAsync: (payload: { clusterIds: string[] }) => Promise<unknown>;
}): React.JSX.Element => {
  const [mergeFailure, setMergeFailure] = useState<BulkMergeFailure | null>(null);
  const selection = useMemo(
    () => ({
      selectedIds: new Set(['cluster-a', 'cluster-b', 'cluster-c']),
      count: 3,
    }),
    [],
  );

  const bulkMergeMutation = useMemo(
    () => ({
      isPending: false,
      mutateAsync: async (payload: { clusterIds: string[] }) => {
        try {
          return await mergeAsync(payload);
        } catch (err) {
          // Mirror useClusterActions mid-sequence failure: surface alert while mutation rejects.
          setMergeFailure({
            failedClusterId: 'cluster-b',
            message: 'Merge failed for cluster cluster-b.',
            remainingClusterIds: ['cluster-a', 'cluster-b', 'cluster-c'],
          });
          throw err;
        }
      },
    }),
    [mergeAsync],
  );

  const bulkDismissMutation = useMemo(
    () => ({
      isPending: false,
      mutateAsync: vi.fn().mockResolvedValue(undefined),
    }),
    [],
  );

  const {
    confirmAction,
    setConfirmAction,
    handleBulkMerge,
    handleBulkDismiss,
    handleConfirm,
    handleConfirmOpenChange,
    confirmDialogCopy,
  } = useRosterBulkConfirmation({
    selection,
    bulkMergeMutation,
    bulkDismissMutation,
  });

  return (
    <>
      <BulkActionBar
        count={selection.count}
        onMerge={handleBulkMerge}
        onDismiss={handleBulkDismiss}
        onClear={vi.fn()}
        mergeFailure={mergeFailure}
        onRetryMerge={vi.fn()}
        onDismissFailure={() => setMergeFailure(null)}
      />
      {confirmDialogCopy ? (
        <ConfirmDialog
          open={confirmAction !== null}
          onOpenChange={handleConfirmOpenChange}
          onConfirm={handleConfirm}
          onCancel={() => setConfirmAction(null)}
          title={confirmDialogCopy.title}
          description={confirmDialogCopy.description}
          confirmLabel={confirmDialogCopy.confirmLabel}
        />
      ) : null}
    </>
  );
};

describe('BulkActionBar', () => {
  beforeEach(() => {
    i18nMocks._n.mockClear();
    nMock.forcePlural = false;
  });

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
    const { rerender } = render(
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
    // Exact unit noun + source-step denominator (not selection size).
    expect(status).toHaveTextContent('Merging source 1 of 2…');
    expect(screen.getByTestId('bulk-merge-status')).toBe(status);

    // Second pair: a wrong denominator or dropped unit noun cannot match both.
    rerender(
      <BulkActionBar
        count={4}
        onMerge={vi.fn()}
        onDismiss={vi.fn()}
        onClear={vi.fn()}
        isMerging
        mergeProgress={{ current: 2, total: 3 }}
      />,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Merging source 2 of 3…');
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
      // Exact accessible name must include the unit noun and the source-step total.
      // Two distinct pairs catch a dropped unit ("Merging 1 of 2…") and a wrong denominator.
      const { rerender } = render(
        <BulkActionBar
          count={3}
          {...defaultProps}
          isMerging
          mergeProgress={{ current: 1, total: 2 }}
        />,
      );

      expect(screen.getByRole('button', { name: 'Merging source 1 of 2…' })).toBeDisabled();
      expect(screen.getByRole('status')).toHaveTextContent('Merging source 1 of 2…');

      rerender(
        <BulkActionBar
          count={4}
          {...defaultProps}
          isMerging
          mergeProgress={{ current: 2, total: 3 }}
        />,
      );
      expect(screen.getByRole('button', { name: 'Merging source 2 of 3…' })).toBeDisabled();
      expect(screen.getByRole('status')).toHaveTextContent('Merging source 2 of 3…');
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

    it('passes the real selection count into _n (not collapsed to 1-or-2)', () => {
      // Collapse mutation `_n(..., count === 1 ? 1 : 2, ...)` yields correct English labels
      // for 0/2/3/5 and still satisfies forcePlural at count===1; only the argument proves
      // locales with a third plural form get the right msgid.
      const { rerender } = render(<BulkActionBar count={5} {...defaultProps} />);
      expect(i18nMocks._n).toHaveBeenCalledWith(
        'Merge %d cluster',
        'Merge %d clusters',
        5,
        'alt-context',
      );
      expect(i18nMocks._n).toHaveBeenCalledWith(
        'Dismiss %d cluster',
        'Dismiss %d clusters',
        5,
        'alt-context',
      );

      i18nMocks._n.mockClear();
      rerender(<BulkActionBar count={3} {...defaultProps} isMerging />);
      expect(i18nMocks._n).toHaveBeenCalledWith(
        'Merging %d cluster…',
        'Merging %d clusters…',
        3,
        'alt-context',
      );

      i18nMocks._n.mockClear();
      rerender(<BulkActionBar count={0} {...defaultProps} isDismissing />);
      expect(i18nMocks._n).toHaveBeenCalledWith(
        'Dismissing %d cluster…',
        'Dismissing %d clusters…',
        0,
        'alt-context',
      );
    });
  });

  describe('selection summary uses _n (S5-BR-04)', () => {
    it('renders singular at count 1 and plural at count 2 via _n with the real count', () => {
      const { rerender } = render(<BulkActionBar count={1} {...defaultProps} />);
      expect(screen.getByText('1 selected')).toBeInTheDocument();
      expect(i18nMocks._n).toHaveBeenCalledWith(
        '%d selected',
        '%d selected',
        1,
        'alt-context',
      );

      i18nMocks._n.mockClear();
      rerender(<BulkActionBar count={2} {...defaultProps} />);
      expect(screen.getByText('2 selected')).toBeInTheDocument();
      expect(i18nMocks._n).toHaveBeenCalledWith(
        '%d selected',
        '%d selected',
        2,
        'alt-context',
      );

      // Count above 2: collapse mutation (count === 1 ? 1 : 2) cannot pass this.
      i18nMocks._n.mockClear();
      rerender(<BulkActionBar count={5} {...defaultProps} />);
      expect(screen.getByText('5 selected')).toBeInTheDocument();
      expect(i18nMocks._n).toHaveBeenCalledWith(
        '%d selected',
        '%d selected',
        5,
        'alt-context',
      );
    });
  });

  describe('bulk merge confirmation (S5-BR-02)', () => {
    it('confirmation description names sequential merge, stop-on-failure, and partial commit', async () => {
      render(
        <BulkConfirmHarness mergeAsync={vi.fn().mockResolvedValue(undefined)} />,
      );

      await userEvent.click(screen.getByRole('button', { name: 'Merge 3 clusters' }));

      const dialog = screen.getByRole('dialog');
      const description = dialog.textContent ?? '';
      // Must state the real operation: one-by-one, stops on first failure, keeps earlier merges.
      expect(description).toMatch(/one (at a time|by one)/i);
      expect(description).toMatch(/fail/i);
      expect(description).toMatch(/(already[- ]merged|stay merged|kept)/i);
      // Baseline single-act "cannot be undone" sentence alone is not enough.
      expect(description).not.toMatch(/^Are you sure you want to merge 3 clusters\? This action cannot be undone\.$/);
    });

    it('closes the dialog on merge failure so the role=alert Retry UI is reachable', async () => {
      const mergeAsync = vi.fn().mockRejectedValue(new Error('mid-sequence merge failed'));
      render(<BulkConfirmHarness mergeAsync={mergeAsync} />);

      await userEvent.click(screen.getByRole('button', { name: 'Merge 3 clusters' }));
      expect(screen.getByRole('dialog')).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: /^Merge$/i }));

      await waitFor(() => {
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      });
      // Failure alert + Retry must be visible, not masked by DialogOverlay.
      expect(screen.getByRole('alert')).toBeVisible();
      expect(screen.getByRole('button', { name: /^Retry$/i })).toBeVisible();
    });
  });
});
