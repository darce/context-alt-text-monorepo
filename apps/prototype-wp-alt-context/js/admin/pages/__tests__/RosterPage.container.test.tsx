import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';

import type { BatchAnalyzeResponse, ClusterSummary } from '../../api/recognition';
import type { RosterClusterCommitResponse } from '../../api/rosterApi';
import { useRecognitionCluster } from '../../hooks/useRecognitionHooks';
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
  useRecognitionCluster: vi.fn(),
}));

vi.mock('../roster/hooks/useTopUnlabeledTotal', () => ({
  useTopUnlabeledTotal: vi.fn(() => null),
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
  label: '',
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

const ClusterRouteReset = (): React.JSX.Element => {
  const [, setSearchParams] = useSearchParams();

  return (
    <button
      type="button"
      onClick={() => {
        setSearchParams(new URLSearchParams('tab=clusters'), { replace: true });
      }}
    >
      Reset cluster route
    </button>
  );
};

describe('RosterPage route container (E21-9 single surface)', () => {
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
      BatchAnalyzeResponse,
      Error,
      { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
    >({
      mutate: vi.fn(),
      isPending: false,
    }),
    commitMutation: createMockMutation<
      RosterClusterCommitResponse,
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
    bulkMergeFailure: null,
    clearBulkMergeFailure: vi.fn(),
    rescanGate: {
      disabled: false,
      'aria-disabled': undefined as true | undefined,
      title: undefined as string | undefined,
    },
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

  it('renders the single person-first surface (no tablist)', () => {
    render(
      <MemoryRouter initialEntries={['/?tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /Face groups/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'People' }).length).toBeGreaterThanOrEqual(1);
    // UXW2-4: rail retired; the workbench queue CTA is the single path to unnamed faces.
    expect(screen.queryByTestId('needs-assignment-section')).not.toBeInTheDocument();
    expect(screen.getByTestId('roster-review-cta')).toBeInTheDocument();
  });

  it('preserves personFilter=unassigned on the single surface', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 7,
            person_uuid: 'person-uuid-unassigned',
            name: 'Unassigned Person',
            tags: [],
            cluster_count: 0,
            clusters: [],
            queue_memberships: [],
            updated_at: new Date().toISOString(),
            source_version: 1,
            projection_status: 'current',
            projection_refreshed_at: new Date().toISOString(),
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

    expect(screen.getByText('Filtered: Unassigned')).toBeInTheDocument();
    expect(screen.getByText('Showing unassigned people only.')).toBeInTheDocument();
    expect(screen.getByText('Unassigned Person')).toBeInTheDocument();
  });

  it('keeps person and face routes on the person surface with gate notice', () => {
    render(
      <MemoryRouter initialEntries={['/?person=person-123&face=identity-9&tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText(
        'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
      ),
    ).toBeInTheDocument();
  });

  it('keeps face-only routes with the gate notice', () => {
    render(
      <MemoryRouter initialEntries={['/?face=identity-9&tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText(
        'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
      ),
    ).toBeInTheDocument();
  });

  it('keeps queue routes reachable without implying the person workspace exists', () => {
    render(
      <MemoryRouter initialEntries={['/?queue=needs-review&tab=clusters']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText(
        'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
      ),
    ).toBeInTheDocument();
  });

  it('opens the cluster drawer from cluster= deep link on the single surface', async () => {
    render(
      <MemoryRouter initialEntries={['/?tab=entries&cluster=cluster-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: /^Close$/i })).toBeInTheDocument();
  });

  it('clears cluster drawer state when the cluster route is removed', async () => {
    render(
      <MemoryRouter initialEntries={['/?tab=clusters&cluster=cluster-1']}>
        <ClusterRouteReset />
        <RosterPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: /^Close$/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Reset cluster route' }));

    expect(screen.queryByRole('button', { name: /^Close$/i })).not.toBeInTheDocument();
  });

  it('opens and closes the cluster drawer from the cluster= deep link (E21-10 shim)', async () => {
    render(
      <MemoryRouter initialEntries={['/?cluster=cluster-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole('button', { name: /^Close$/i })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /Commit to roster entry/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^Close$/i }));

    expect(screen.queryByRole('combobox', { name: /Commit to roster entry/i })).not.toBeInTheDocument();
    expect(clusterActionState.resetAll).toHaveBeenCalledTimes(1);
    expect(dragDropState.resetDragState).toHaveBeenCalledTimes(1);
  });

  it('navigates from the cluster drawer into the assigned person workspace', async () => {
    const assignedCluster = makeCluster({ person_uuid: 'person-uuid-alex' });
    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({
        data: assignedCluster,
        isLoading: false,
        isError: false,
      }),
    );
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 42,
            person_uuid: 'person-uuid-alex',
            name: 'Alex Carter',
            tags: ['event'],
            cluster_count: 3,
            clusters: [],
            queue_memberships: [],
            updated_at: '2026-01-01T00:00:00Z',
            source_version: 1,
            projection_status: 'current',
            projection_refreshed_at: '2026-01-01T00:00:00Z',
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/?tab=clusters&cluster=cluster-1']}>
          <RosterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('button', { name: /^Close$/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('link', { name: /Open person review/i }));

    expect(screen.getByRole('region', { name: /Person workspace: Alex Carter/i })).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /Commit to roster entry/i })).not.toBeInTheDocument();
  });

  it('uses the cluster detail person_uuid for the person review link', async () => {
    const detailCluster = makeCluster({ person_uuid: 'person-uuid-detail', label: 'Detail Label' });
    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({
        data: detailCluster,
        isLoading: false,
        isError: false,
      }),
    );
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 8,
            person_uuid: 'person-uuid-detail',
            name: 'Detail Person',
            tags: [],
            cluster_count: 1,
            clusters: [],
            queue_memberships: [],
            updated_at: '2026-01-01T00:00:00Z',
            source_version: 1,
            projection_status: 'current',
            projection_refreshed_at: '2026-01-01T00:00:00Z',
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/?tab=clusters&cluster=cluster-1']}>
          <RosterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText('Assigned face group')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open person review/i })).toHaveAttribute(
      'href',
      '#/roster?person=person-uuid-detail',
    );

    await userEvent.click(screen.getByRole('link', { name: /Open person review/i }));

    expect(screen.getByRole('region', { name: /Person workspace: Detail Person/i })).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: /Commit to roster entry/i })).not.toBeInTheDocument();
  });

  it('prefers cluster detail person_uuid over a competing list person of the same name shape', async () => {
    const detailCluster = makeCluster({ person_uuid: 'person-uuid-detail', label: 'Detail Label' });
    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({
        data: detailCluster,
        isLoading: false,
        isError: false,
      }),
    );
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 7,
            person_uuid: 'person-uuid-list',
            name: 'List Person',
            tags: [],
            cluster_count: 1,
            clusters: [],
            queue_memberships: [],
            updated_at: '2026-01-01T00:00:00Z',
            source_version: 1,
            projection_status: 'current',
            projection_refreshed_at: '2026-01-01T00:00:00Z',
          },
          {
            id: 8,
            person_uuid: 'person-uuid-detail',
            name: 'Detail Person',
            tags: [],
            cluster_count: 1,
            clusters: [],
            queue_memberships: [],
            updated_at: '2026-01-01T00:00:00Z',
            source_version: 1,
            projection_status: 'current',
            projection_refreshed_at: '2026-01-01T00:00:00Z',
          },
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/?cluster=cluster-1']}>
          <RosterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByRole('link', { name: /Open person review/i }));

    expect(screen.getByRole('region', { name: /Person workspace: Detail Person/i })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace: List Person/i })).not.toBeInTheDocument();
  });

  it('mounts the drawer shell with Close while the cluster= deep link is loading', () => {
    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({
        data: undefined,
        isLoading: true,
        isError: false,
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?cluster=cluster-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('button', { name: /^Close$/i })).toBeInTheDocument();
    expect(screen.getByText('Loading faces…')).toBeInTheDocument();
  });

  it('mounts the drawer shell with Close and error copy when the cluster= fetch fails', async () => {
    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({
        data: undefined,
        isLoading: false,
        isError: true,
        error: new Error('Unable to load face group details.'),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?cluster=cluster-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('button', { name: /^Close$/i })).toBeInTheDocument();
    expect(screen.getByText('Unable to load face group details.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /^Close$/i }));

    expect(screen.queryByRole('button', { name: /^Close$/i })).not.toBeInTheDocument();
  });

  it('does not claim the tenant has no other face groups on the cluster= shim', () => {
    render(
      <MemoryRouter initialEntries={['/?cluster=cluster-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.queryByText(/No other face groups available/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Move to/i })).not.toBeInTheDocument();
    expect(screen.getByText('Face moves happen in the Workbench review queue.')).toBeInTheDocument();
    expect(screen.queryAllByRole('button', { name: /Move to/i })).toHaveLength(0);
  });

  // UXW2-4: rail-era tests (bulk merge/dismiss, select-all, truncation notice,
  // retainVisible) deleted with the rail — bulk merge/dismiss reachability moves
  // to the workbench queue in a later task (E21-9 Q1).
});
