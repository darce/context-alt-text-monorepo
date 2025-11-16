import { fireEvent, render, screen } from '@testing-library/react';
import { act } from 'react';
import userEvent from '@testing-library/user-event';
import { ClusterDrawer, ClusterGallery } from '../RosterPage';
import type { ClusterSummary } from '../../api/recognitionApi';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: Array<string | number>) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

const makeCluster = (overrides: Partial<ClusterSummary> = {}): ClusterSummary => ({
  id: 'cluster-1',
  label: 'cluster-1',
  identity_count: 2,
  face_count: 2,
  member_ids: ['1', '2'],
  representative_identity: {
    media_id: 1,
    bbox: { x: 0, y: 0, width: 10, height: 10 },
  },
  representative_face: {
    media_id: 1,
    bbox: { x: 0, y: 0, width: 10, height: 10 },
  },
  sample_identities: [],
  sample_faces: [],
  ...overrides,
});

describe('ClusterGallery', () => {
  it('describes empty states', () => {
    render(
      <ClusterGallery
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
      />
    );

    expect(screen.getByText(/No clusters have been created yet/i)).toBeInTheDocument();
  });

  it('notifies when user selects a cluster card', async () => {
    const onSelect = vi.fn();
    const cluster = makeCluster();

    render(
      <ClusterGallery
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
      />
    );

    await userEvent.click(screen.getByRole('button', { name: /cluster-1/ }));
    expect(onSelect).toHaveBeenCalledWith(cluster);
  });

  it('invokes drop handler when a face is dropped on another cluster', () => {
    const onDropFace = vi.fn();
    const clusterA = makeCluster({
      sample_identities: [
        {
          id: 'identity-1',
          media_id: 10,
          similarity: 0.9,
          confidence: 0.9,
          bbox: { x: 0, y: 0, width: 20, height: 20 },
        },
      ],
    });
    const clusterB = makeCluster({ id: 'cluster-2', label: 'cluster-2' });

    render(
      <ClusterGallery
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
      />
    );

    const draggable = screen.getByLabelText(/Move identity from media 10/);
    fireEvent.dragStart(draggable);
    const target = screen.getByRole('button', { name: /cluster-2/ });
    fireEvent.dragOver(target);
    fireEvent.drop(target);

    expect(onDropFace).toHaveBeenCalledWith('cluster-2');
  });
});

describe('ClusterDrawer', () => {
  it('renders metadata and close handler', async () => {
    const onClose = vi.fn();
    render(
      <ClusterDrawer
        cluster={makeCluster()}
        mediaMap={{}}
        onClose={onClose}
        onRescanCluster={vi.fn()}
        isRescanning={false}
        onCommitCluster={vi.fn()}
        isCommitting={false}
        rosterEntries={[]}
        onFaceDragStart={vi.fn()}
        onFaceDragEnd={vi.fn()}
        onDropTargetChange={vi.fn()}
        onDropFace={vi.fn()}
        dropTarget={null}
        isDragging={false}
        onDiscardDrop={vi.fn()}
      />
    );

    expect(screen.getByText(/cluster-1/)).toBeInTheDocument();
    const closeButton = screen.getByRole('button', { name: /Close/i });
    await userEvent.click(closeButton);
    expect(onClose).toHaveBeenCalled();
  });

  it('commits to an existing roster entry', async () => {
    const commit = vi.fn();
    await act(async () => {
      render(
        <ClusterDrawer
          cluster={makeCluster()}
          mediaMap={{}}
          onClose={vi.fn()}
          onRescanCluster={vi.fn()}
          isRescanning={false}
          onCommitCluster={commit}
          isCommitting={false}
          rosterEntries={[{ id: 1, name: 'Ada', tags: [], cluster_count: 0, updated_at: new Date().toISOString() }]}
          onFaceDragStart={vi.fn()}
          onFaceDragEnd={vi.fn()}
          onDropTargetChange={vi.fn()}
          onDropFace={vi.fn()}
          dropTarget={null}
          isDragging={false}
          onDiscardDrop={vi.fn()}
        />
      );
    });

    await act(async () => {
      await userEvent.selectOptions(screen.getByLabelText(/Commit to roster entry/i), ['1']);
      const commitButton = screen.getByRole('button', { name: /Commit to roster entry/i });
      await userEvent.click(commitButton);
    });

    expect(commit).toHaveBeenCalledWith(expect.any(Object), { rosterEntryId: 1 });
  });
});
