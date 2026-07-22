import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterSummary } from '../../../api/recognition';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { NeedsAssignmentSection } from '../NeedsAssignmentSection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

const makeCluster = (overrides: Partial<ClusterSummary> = {}): ClusterSummary => ({
  id: 'cluster-1',
  label: '',
  identity_count: 2,
  member_ids: ['identity-1'],
  representative_identity: {
    media_id: 10,
    bbox: { x: 0, y: 0, width: 10, height: 10 },
  },
  sample_identities: [],
  ...overrides,
});

const baseSelection = {
  selectedIds: new Set<string>(),
  toggle: vi.fn(),
  selectRange: vi.fn(),
  selectAll: vi.fn(),
  retainVisible: vi.fn(),
  clear: vi.fn(),
  isAllSelected: vi.fn(() => false),
  isSelected: vi.fn(() => false),
  count: 0,
};

const baseActions = {
  bulkMergeMutation: createMockMutation<void, Error, { clusterIds: string[] }>({
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  }),
  bulkDismissMutation: createMockMutation<void, Error, { clusterIds: string[] }>({
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  }),
  bulkMergeProgress: null,
  bulkMergeFailure: null,
  clearBulkMergeFailure: vi.fn(),
} as never;

describe('NeedsAssignmentSection rail mount discrimination (E21-9 Slice 5b)', () => {
  it('enables bulk controls when unlabeled fixtures are present', async () => {
    const selection = {
      ...baseSelection,
      selectedIds: new Set(['cluster-u1', 'cluster-u2']),
      count: 2,
      isSelected: vi.fn((id: string) => id === 'cluster-u1' || id === 'cluster-u2'),
    };

    render(
      <NeedsAssignmentSection
        clusters={[
          makeCluster({ id: 'cluster-u1', label: '' }),
          makeCluster({ id: 'cluster-u2', label: '   ' }),
          makeCluster({ id: 'cluster-labeled', label: 'Ada' }),
        ]}
        selection={selection}
        actions={baseActions}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        onOpenCluster={vi.fn()}
      />,
    );

    const section = screen.getByTestId('needs-assignment-section');
    expect(within(section).getByRole('heading', { name: /Needs assignment/i })).toBeInTheDocument();
    expect(screen.getByTestId('needs-assignment-count')).toHaveTextContent('2 unlabeled');
    expect(screen.getByTestId('needs-assignment-list').children).toHaveLength(2);

    const merge = screen.getByRole('button', { name: /^Merge$/i });
    expect(merge).toBeEnabled();

    await userEvent.click(merge);
    // Confirm dialog appears for merge.
    expect(await screen.findByRole('button', { name: /^Merge$/i })).toBeInTheDocument();
  });

  it('renders disabled-with-reason bulk controls when only labeled clusters exist (zero unlabeled)', () => {
    render(
      <NeedsAssignmentSection
        clusters={[makeCluster({ id: 'cluster-labeled', label: 'Ada' })]}
        selection={baseSelection}
        actions={baseActions}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        onOpenCluster={vi.fn()}
      />,
    );

    expect(screen.getByTestId('needs-assignment-section')).toBeInTheDocument();
    expect(screen.getByTestId('needs-assignment-zero')).toHaveTextContent(/No unlabeled clusters need assignment/i);

    const merge = screen.getByRole('button', { name: /^Merge$/i });
    const dismiss = screen.getByRole('button', { name: /^Dismiss$/i });
    expect(merge).toBeDisabled();
    expect(dismiss).toBeDisabled();
    expect(merge).toHaveAttribute('title', expect.stringMatching(/No unlabeled/i));
  });

  it('deep-links each unlabeled cluster to the workbench review queue', () => {
    render(
      <NeedsAssignmentSection
        clusters={[makeCluster({ id: 'cluster-deep', label: '' })]}
        selection={baseSelection}
        actions={baseActions}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        onOpenCluster={vi.fn()}
      />,
    );

    const link = screen.getByRole('link', { name: /Review in workbench/i });
    expect(link).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&rq=assignment.all.0&cluster=cluster-deep',
    );
  });

  it('opens the local drawer when the cluster row is activated', async () => {
    const onOpenCluster = vi.fn();
    const cluster = makeCluster({ id: 'cluster-open', label: '' });

    render(
      <NeedsAssignmentSection
        clusters={[cluster]}
        selection={baseSelection}
        actions={baseActions}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        onOpenCluster={onOpenCluster}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /Cluster cluster-/i }));
    expect(onOpenCluster).toHaveBeenCalledWith(cluster);
  });
});
