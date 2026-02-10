import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ClusterDrawerPanel } from '../roster/ClusterDrawerPanel';
import { ClusterGrid } from '../roster/ClusterGrid';
import type { ClusterSummary } from '../../api/recognition';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

vi.mock('../../../components/ui/combobox', () => ({
  Combobox: ({
    options,
    value,
    onSelect,
    ariaLabel,
    id,
  }: {
    options: { value: string; label: string }[];
    value?: string;
    onSelect?: (nextValue: string) => void;
    ariaLabel?: string;
    id?: string;
  }) => (
    <select
      id={id}
      aria-label={ariaLabel}
      value={value ?? ''}
      onChange={(event) => onSelect?.(event.target.value)}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

const makeCluster = (overrides: Partial<ClusterSummary> = {}): ClusterSummary => ({
  id: 'cluster-1',
  label: 'cluster-1',
  identity_count: 2,
  member_ids: ['1', '2'],
  representative_identity: {
    media_id: 1,
    bbox: { x: 0, y: 0, width: 10, height: 10 },
  },
  sample_identities: [],
  ...overrides,
});

describe('ClusterGrid', () => {
  it('describes empty states', () => {
    render(
      <ClusterGrid
        clusters={[]}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        mediaMap={{}}
        onSelectCluster={vi.fn()}
        onIdentityDragStart={vi.fn()}
        onFaceDragEnd={vi.fn()}
        onDropTargetChange={vi.fn()}
        onDropFace={vi.fn()}
        dropTarget={null}
        isDragging={false}
      />,
    );

    expect(screen.getByText(/No clusters have been created yet/i)).toBeInTheDocument();
  });

  it('notifies when user selects a cluster card', async () => {
    const onSelect = vi.fn();
    const cluster = makeCluster();

    render(
      <ClusterGrid
        clusters={[cluster]}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        mediaMap={{}}
        onSelectCluster={onSelect}
        onIdentityDragStart={vi.fn()}
        onFaceDragEnd={vi.fn()}
        onDropTargetChange={vi.fn()}
        onDropFace={vi.fn()}
        dropTarget={null}
        isDragging={false}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /cluster-1/ }));
    expect(onSelect).toHaveBeenCalledWith(cluster);
  });

  it('invokes drop handler when a face is dropped on another cluster', () => {
    const onDropFace = vi.fn();
    const clusterA = makeCluster({
      sample_identities: [
        {
          identity_id: 'identity-1',
          media_id: 10,
          similarity: 0.9,
          confidence: 0.9,
          bbox: { x: 0, y: 0, width: 20, height: 20 },
        },
      ],
    });
    const clusterB = makeCluster({ id: 'cluster-2', label: 'cluster-2' });

    render(
      <ClusterGrid
        clusters={[clusterA, clusterB]}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
        mediaMap={{}}
        onSelectCluster={vi.fn()}
        onIdentityDragStart={vi.fn()}
        onFaceDragEnd={vi.fn()}
        onDropTargetChange={vi.fn()}
        onDropFace={onDropFace}
        dropTarget={null}
        isDragging
      />,
    );

    const draggable = screen.getByLabelText(/Move identity from media 10/);
    fireEvent.dragStart(draggable);
    const target = screen.getByRole('button', { name: /cluster-2/ });
    fireEvent.dragOver(target);
    fireEvent.drop(target);

    expect(onDropFace).toHaveBeenCalledWith('cluster-2');
  });
});

describe('ClusterDrawerPanel', () => {
  it('renders metadata and close handler', async () => {
    const onClose = vi.fn();
    render(
      <ClusterDrawerPanel
        cluster={makeCluster()}
        identities={[]}
        mediaMap={{}}
        onClose={onClose}
        onRescanCluster={vi.fn()}
        isRescanning={false}
        onCommitCluster={vi.fn()}
        isCommitting={false}
        rosterEntries={[]}
        isDetailLoading={false}
        onFaceDragStart={vi.fn()}
        onFaceDragEnd={vi.fn()}
        onDropTargetChange={vi.fn()}
        dropTarget={null}
        isDragging={false}
        onDiscardDrop={vi.fn()}
      />,
    );

    expect(screen.getByText(/cluster-1/)).toBeInTheDocument();
    const closeButton = screen.getByRole('button', { name: /Close/i });
    await userEvent.click(closeButton);
    expect(onClose).toHaveBeenCalled();
  });

  it('[ACX-4130-G7-ROSTER] commits to an existing roster entry', async () => {
    const onCommitCluster = vi.fn();
    const cluster = makeCluster();

    render(
      <ClusterDrawerPanel
        cluster={cluster}
        identities={[]}
        mediaMap={{}}
        onClose={vi.fn()}
        onRescanCluster={vi.fn()}
        isRescanning={false}
        onCommitCluster={onCommitCluster}
        isCommitting={false}
        rosterEntries={[
          {
            id: 42,
            name: 'Alex Carter',
            tags: ['event'],
            cluster_count: 3,
            updated_at: '2026-01-01T00:00:00Z',
          },
        ]}
        isDetailLoading={false}
        onFaceDragStart={vi.fn()}
        onFaceDragEnd={vi.fn()}
        onDropTargetChange={vi.fn()}
        dropTarget={null}
        isDragging={false}
        onDiscardDrop={vi.fn()}
      />,
    );

    const entrySelect = screen.getByRole('combobox', { name: /Commit to roster entry/i });
    await userEvent.selectOptions(entrySelect, '42');

    const commitButton = screen.getByRole('button', { name: /^Commit to roster entry$/i });
    expect(commitButton).toBeEnabled();

    await userEvent.click(commitButton);
    expect(onCommitCluster).toHaveBeenCalledWith(cluster, { rosterEntryId: 42 });
  });
});
