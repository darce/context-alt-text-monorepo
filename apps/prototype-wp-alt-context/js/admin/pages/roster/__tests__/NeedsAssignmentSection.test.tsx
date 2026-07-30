import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ClusterSummary } from '../../../api/recognition';
import { createMockMutation } from '../../../test-utils/mockHooks';
import { NeedsAssignmentSection } from '../NeedsAssignmentSection';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format
      .replace(/%\d+\$[sd]/g, () => String(args[index++]))
      .replace(/%[sd]/g, () => String(args[index++]));
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

    const merge = screen.getByRole('button', { name: 'Merge 2 clusters' });
    expect(merge).toBeEnabled();

    await userEvent.click(merge);
    // Confirm dialog confirm label stays short "Merge" — exact match, distinct from bar.
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('button', { name: /^Merge$/ })).toBeInTheDocument();
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

    const merge = screen.getByRole('button', { name: 'Merge 0 clusters' });
    const dismiss = screen.getByRole('button', { name: 'Dismiss 0 clusters' });
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
    // cluster= dropped (jobId precedent): workbench has no cluster reader.
    expect(link).toHaveAttribute('href', '#/workbench?tab=scan&rq=assignment.all.0');
    expect(link.getAttribute('href')).not.toContain('cluster=');
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

  it('scopes rail bulk merge to unlabeled ids — labeled selections elsewhere are not swept in', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    // baseActions is typed `as never`; rebuild rather than spreading never.
    const actions = {
      bulkMergeMutation: createMockMutation<void, Error, { clusterIds: string[] }>({
        mutate: vi.fn(),
        mutateAsync,
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

    // Mixed selection: two unlabeled + one labeled id selected elsewhere on the page.
    const selection = {
      ...baseSelection,
      selectedIds: new Set(['cluster-u1', 'cluster-u2', 'cluster-labeled']),
      count: 3,
      isSelected: vi.fn(
        (id: string) => id === 'cluster-u1' || id === 'cluster-u2' || id === 'cluster-labeled',
      ),
    };

    render(
      <NeedsAssignmentSection
        clusters={[
          makeCluster({ id: 'cluster-u1', label: '' }),
          makeCluster({ id: 'cluster-u2', label: '' }),
          makeCluster({ id: 'cluster-labeled', label: 'Ada' }),
        ]}
        selection={selection}
        actions={actions}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        onOpenCluster={vi.fn()}
      />,
    );

    // Rail BulkActionBar count is intersection size (2), not page-wide selection (3).
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    expect(screen.queryByText('3 selected')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Merge 2 clusters' }));
    // Confirm dialog describes rail-scoped count (bar also says "Merge 2 clusters" now).
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Are you sure you want to merge 2 clusters/i)).toBeInTheDocument();

    // Confirm the merge — dialog confirm label is bare "Merge" (exact; distinct from bar).
    await userEvent.click(within(dialog).getByRole('button', { name: /^Merge$/ }));

    expect(mutateAsync).toHaveBeenCalledTimes(1);
    const payload = mutateAsync.mock.calls[0][0] as { clusterIds: string[] };
    expect(payload.clusterIds).toEqual(expect.arrayContaining(['cluster-u1', 'cluster-u2']));
    expect(payload.clusterIds).toHaveLength(2);
    expect(payload.clusterIds).not.toContain('cluster-labeled');
  });
});
