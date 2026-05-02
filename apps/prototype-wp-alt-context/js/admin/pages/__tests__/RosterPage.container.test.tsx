import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import type { AnalyzeResponse, ClusterListResponse, ClusterSummary } from '../../api/recognition';
import { useRecognitionCluster, useRecognitionClusters } from '../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useRosterEntries, useUpdatePerson } from '../../hooks/useRosterHooks';
import { useClusterSelection } from '../../hooks/useClusterSelection';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';
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
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));
vi.mock('../../hooks/useClusterSelection', () => ({
  useClusterSelection: vi.fn(),
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

const makeClusterListResponse = (overrides: Partial<ClusterListResponse> = {}): ClusterListResponse => ({
  clusters: [makeCluster()],
  limit: 20,
  total: 1,
  truncated: false,
  ...overrides,
});

describe('RosterPage route container', () => {
  const mockedUseRecognitionClusters = vi.mocked(useRecognitionClusters);
  const mockedUseRecognitionCluster = vi.mocked(useRecognitionCluster);
  const mockedUseRosterEntries = vi.mocked(useRosterEntries);
  const mockedUseCreatePerson = vi.mocked(useCreatePerson);
  const mockedUseUpdatePerson = vi.mocked(useUpdatePerson);
  const mockedUseDeletePerson = vi.mocked(useDeletePerson);
  const mockedUseClusterSelection = vi.mocked(useClusterSelection);
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
    reassignMutation: createMockMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
      mutate: vi.fn(),
    }),
    rescanMutation: createMockMutation<
      AnalyzeResponse[],
      Error,
      { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
    >({
      mutate: vi.fn(),
      isPending: false,
    }),
    commitMutation: createMockMutation<
      void,
      Error,
      { clusterId: string; rosterEntryId?: number; newEntryName?: string }
    >({
      mutate: vi.fn(),
      isPending: false,
    }),
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
    errorMessage: null,
    resetAll: vi.fn(),
  };
  const selectionState = {
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

  beforeEach(() => {
    vi.clearAllMocks();

    const cluster = makeCluster();

    mockedUseRecognitionClusters.mockReturnValue(
      createMockQuery({
        data: makeClusterListResponse({ clusters: [cluster] }),
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({
        data: cluster,
        isLoading: false,
        isError: false,
      }),
    );

    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
    mockedUseCreatePerson.mockReturnValue(
      createMockMutation({
        mutate: vi.fn(),
        isPending: false,
      }),
    );
    mockedUseUpdatePerson.mockReturnValue(
      createMockMutation({
        mutate: vi.fn(),
        isPending: false,
      }),
    );
    mockedUseDeletePerson.mockReturnValue(
      createMockMutation({
        mutate: vi.fn(),
        isPending: false,
      }),
    );
    mockedUseClusterSelection.mockReturnValue(selectionState);

    mockedUseClusterMediaMap.mockReturnValue({});
    mockedUseClusterDragDrop.mockReturnValue(dragDropState);
    mockedUseClusterActions.mockReturnValue(clusterActionState);
  });

  it('[PAG-M3] bootstraps active tab from the query string', () => {
    render(
      <MemoryRouter initialEntries={['/?tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('tab', { name: 'Clusters' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Entries' })).toHaveAttribute('aria-selected', 'false');
  });

  it('[PAG-M3] preserves entries tab bootstrap with personFilter=unassigned', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 7,
            name: 'Unassigned Person',
            tags: [],
            cluster_count: 0,
            updated_at: new Date().toISOString(),
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?tab=entries&personFilter=unassigned']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('tab', { name: 'Entries' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Clusters' })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByText('Filtered: Unassigned')).toBeInTheDocument();
    expect(screen.getByText('Showing unassigned people only.')).toBeInTheDocument();
    expect(screen.getByText('Unassigned Person')).toBeInTheDocument();
  });

  it('[PAG-M3] opens and closes the cluster drawer from the grid', async () => {
    render(
      <MemoryRouter>
        <RosterPage />
      </MemoryRouter>,
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

  it('surfaces a partial-state notice when the cluster list is truncated', () => {
    mockedUseRecognitionClusters.mockReturnValue(
      createMockQuery({
        data: makeClusterListResponse({
          clusters: [makeCluster()],
          total: 12,
          truncated: true,
        }),
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByText('Showing 1 of 12 clusters. Refine the list to review the remaining matches.')).toBeInTheDocument();
  });

  it('applies bulk merge action through confirm dialog', async () => {
    mockedUseClusterSelection.mockReturnValue({
      ...selectionState,
      selectedIds: new Set(['cluster-1', 'cluster-2', 'cluster-3']),
      count: 3,
    });

    render(
      <MemoryRouter>
        <RosterPage />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Clusters' }));
    await userEvent.click(screen.getByRole('button', { name: 'Merge' }));
    await userEvent.click(screen.getAllByRole('button', { name: /^Merge$/i }).at(-1)!);
    expect(clusterActionState.bulkMergeMutation.mutateAsync).toHaveBeenCalledWith({
      clusterIds: ['cluster-1', 'cluster-2', 'cluster-3'],
    });
  });

  it('applies bulk dismiss action through confirm dialog', async () => {
    mockedUseClusterSelection.mockReturnValue({
      ...selectionState,
      selectedIds: new Set(['cluster-1', 'cluster-2', 'cluster-3']),
      count: 3,
    });

    render(
      <MemoryRouter>
        <RosterPage />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Clusters' }));
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    await userEvent.click(screen.getAllByRole('button', { name: /^Dismiss$/i }).at(-1)!);

    expect(clusterActionState.bulkDismissMutation.mutateAsync).toHaveBeenCalledWith({
      clusterIds: ['cluster-1', 'cluster-2', 'cluster-3'],
    });
  });

  it('allows selecting all visible clusters from the clusters header', async () => {
    render(
      <MemoryRouter>
        <RosterPage />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole('tab', { name: 'Clusters' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all clusters' }));

    expect(selectionState.selectAll).toHaveBeenCalledWith(['cluster-1']);
  });

  it('retains only currently visible clusters while the clusters tab is active', () => {
    render(
      <MemoryRouter initialEntries={['/?tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(selectionState.retainVisible).toHaveBeenCalledWith(['cluster-1']);
  });
});
