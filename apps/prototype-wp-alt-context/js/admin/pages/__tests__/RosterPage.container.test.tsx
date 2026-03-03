import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import type { ClusterSummary } from '../../api/recognition';
import { useRecognitionCluster, useRecognitionClusters } from '../../hooks/useRecognitionHooks';
import { useRosterEntries } from '../../hooks/useRosterHooks';
import { RosterPage } from '../RosterPage';
import { useClusterActions } from '../roster/hooks/useClusterActions';
import { useClusterDragDrop } from '../roster/hooks/useClusterDragDrop';
import { useClusterMediaMap } from '../roster/hooks/useClusterMediaMap';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

vi.mock('../../hooks/useRecognitionHooks', () => ({
  useRecognitionClusters: vi.fn(),
  useRecognitionCluster: vi.fn(),
}));

vi.mock('../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
}));

vi.mock('../roster/hooks/useClusterMediaMap', () => ({
  useClusterMediaMap: vi.fn(),
}));

vi.mock('../roster/hooks/useClusterDragDrop', () => ({
  useClusterDragDrop: vi.fn(),
}));

vi.mock('../roster/hooks/useClusterActions', () => ({
  useClusterActions: vi.fn(),
}));

const makeCluster = (overrides: Partial<ClusterSummary> = {}): ClusterSummary => ({
  id: 'cluster-1',
  label: 'Cluster One',
  identity_count: 2,
  member_ids: ['identity-1', 'identity-2'],
  representative_identity: {
    media_id: 10,
    bbox: { x: 0, y: 0, width: 10, height: 10 },
  },
  sample_identities: [
    {
      identity_id: 'identity-1',
      media_id: 10,
      similarity: 0.91,
      confidence: 0.94,
      bbox: { x: 0, y: 0, width: 10, height: 10 },
    },
  ],
  ...overrides,
});

describe('RosterPage route container', () => {
  const mockedUseRecognitionClusters = vi.mocked(useRecognitionClusters);
  const mockedUseRecognitionCluster = vi.mocked(useRecognitionCluster);
  const mockedUseRosterEntries = vi.mocked(useRosterEntries);
  const mockedUseClusterMediaMap = vi.mocked(useClusterMediaMap);
  const mockedUseClusterDragDrop = vi.mocked(useClusterDragDrop);
  const mockedUseClusterActions = vi.mocked(useClusterActions);

  const dragDropState = {
    dragPayload: null,
    dropTarget: null,
    isDragging: false,
    handleFaceDragStart: vi.fn(),
    handleFaceDragEnd: vi.fn(),
    handleDropTargetChange: vi.fn(),
    resetDragState: vi.fn(),
  };

  const clusterActionState = {
    reassignMutation: { mutate: vi.fn() },
    rescanMutation: { mutate: vi.fn(), isPending: false },
    commitMutation: { mutate: vi.fn(), isPending: false },
    statusMessage: null,
    errorMessage: null,
    resetAll: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, '', '/wp-admin/admin.php?page=alt-context-roster');

    const cluster = makeCluster();

    mockedUseRecognitionClusters.mockReturnValue({
      data: [cluster],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useRecognitionClusters>);

    mockedUseRecognitionCluster.mockReturnValue({
      data: cluster,
      isLoading: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useRecognitionCluster>);

    mockedUseRosterEntries.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useRosterEntries>);

    mockedUseClusterMediaMap.mockReturnValue({});
    mockedUseClusterDragDrop.mockReturnValue(dragDropState as unknown as ReturnType<typeof useClusterDragDrop>);
    mockedUseClusterActions.mockReturnValue(clusterActionState as unknown as ReturnType<typeof useClusterActions>);
  });

  it('[PAG-M3] bootstraps active tab from the query string', () => {
    render(
      <MemoryRouter initialEntries={['/?tab=clusters']}>
        <RosterPage />
      </MemoryRouter>
    );

    expect(screen.getByRole('tab', { name: 'Clusters' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Entries' })).toHaveAttribute('aria-selected', 'false');
  });

  it('[PAG-M3] opens and closes the cluster drawer from the grid', async () => {
    render(
      <MemoryRouter>
        <RosterPage />
      </MemoryRouter>
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Clusters' }));
    await userEvent.click(screen.getByRole('button', { name: /Cluster One/i }));

    expect(screen.getByRole('button', { name: /^Close$/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Commit to roster entry/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^Close$/i }));

    expect(screen.queryByRole('combobox', { name: /Commit to roster entry/i })).not.toBeInTheDocument();
    expect(clusterActionState.resetAll).toHaveBeenCalledTimes(1);
    expect(dragDropState.resetDragState).toHaveBeenCalledTimes(1);
  });
});
