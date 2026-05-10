import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import type { RosterEntry } from '../../api/rosterApi';
import type { BatchAnalyzeResponse, ClusterListResponse, ClusterSummary } from '../../api/recognition';
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

const projectionEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-1',
  name: 'Alice',
  tags: [],
  cluster_count: 2,
  updated_at: '2026-05-07T12:00:00Z',
  source_version: 11,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T12:00:00Z',
  ...overrides,
});

const baseClusters: ClusterListResponse = {
  clusters: [],
  limit: 20,
  total: 0,
  truncated: false,
};

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

describe('RosterPage projection-aware workspace shell', () => {
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

  beforeEach(() => {
    vi.clearAllMocks();

    mockedUseRecognitionClusters.mockReturnValue(
      createMockQuery({ data: baseClusters, isLoading: false, isError: false, refetch: vi.fn() }),
    );
    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({ data: undefined, isLoading: false, isError: false }),
    );
    mockedUseCreatePerson.mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    mockedUseUpdatePerson.mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    mockedUseDeletePerson.mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    mockedUseClusterSelection.mockReturnValue(selectionState);
    mockedUseClusterMediaMap.mockReturnValue({});
    mockedUseClusterDragDrop.mockReturnValue(dragDropState);
    mockedUseClusterActions.mockReturnValue(clusterActionState);
  });

  it('[PAG-M3-S2] renders the person workspace shell when projection_status is current and ?person= matches', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'current', person_uuid: 'person-uuid-1', name: 'Alice' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(
      screen.queryByText(
        'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
      ),
    ).not.toBeInTheDocument();
  });

  it('[PAG-M3-S2] renders a deterministic default workspace when no route params are present', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'current', person_uuid: 'person-uuid-1', name: 'Alice' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(screen.queryByTestId('roster-entries-section')).not.toBeInTheDocument();
  });

  it('[PAG-M3-S2] keeps the default workspace visible after switching to clusters and back to entries', async () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'current', person_uuid: 'person-uuid-1', name: 'Alice' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/']}>
        <RosterPage />
      </MemoryRouter>,
    );

    const user = userEvent.setup();

    await user.click(screen.getByRole('tab', { name: 'Clusters' }));
    await user.click(screen.getByRole('tab', { name: 'Entries' }));

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(screen.queryByTestId('roster-entries-section')).not.toBeInTheDocument();
  });

  it('[PAG-M3-S3] chooses a deterministic default workspace entry and shows baseline projection metadata', () => {
    const refreshedAt = '2026-05-07T12:00:00Z';

    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          projectionEntry({
            id: 2,
            person_uuid: 'person-uuid-2',
            name: 'Tory',
            tags: ['Needs review'],
            cluster_count: 4,
            source_version: 22,
            projection_refreshed_at: '2026-05-08T18:30:00Z',
          }),
          projectionEntry({
            id: 1,
            person_uuid: 'person-uuid-1',
            name: 'Alice',
            tags: ['Primary'],
            cluster_count: 2,
            source_version: 11,
            projection_refreshed_at: refreshedAt,
          }),
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(screen.getByText('Projection status: current')).toBeInTheDocument();
    expect(screen.getByText(`Projection refreshed: ${new Date(refreshedAt).toLocaleString()}`)).toBeInTheDocument();
    expect(screen.getByText('Source version: 11')).toBeInTheDocument();
    expect(screen.getByText('Grouped cluster detail')).toBeInTheDocument();
    expect(screen.getByText('2 curated clusters are currently grouped under this person.')).toBeInTheDocument();
    expect(screen.getByText('Primary')).toBeInTheDocument();
  });

  it('[PAG-M3-S2] keeps the gate notice when projection_status is refreshing', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'refreshing' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.getByText('Roster projection is refreshing. Retry once the refresh completes.')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace/i })).not.toBeInTheDocument();
  });

  it('[PAG-M3-S2] surfaces a stale notice when projection_status is stale', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'stale' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText('Roster projection is stale. Person workspace will resume after the next refresh.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace/i })).not.toBeInTheDocument();
  });

  it('[PAG-M3-S2] surfaces a failed notice when projection_status is failed', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'failed' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText('Roster projection failed to refresh. Person workspace is unavailable until the projection recovers.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace/i })).not.toBeInTheDocument();
  });

  it('[PAG-M3-S2] keeps the legacy gate notice when projection fields are absent', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          {
            id: 7,
            name: 'Legacy Person',
            tags: [],
            cluster_count: 0,
            updated_at: new Date().toISOString(),
          } as unknown as RosterEntry,
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?person=person-uuid-1']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText(
        'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace/i })).not.toBeInTheDocument();
  });

  it('[PAG-M3-S2] does not render the person workspace when ?person= does not match any entry', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'current', person_uuid: 'person-uuid-other' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    render(
      <MemoryRouter initialEntries={['/?person=person-uuid-missing']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByText(
        'No roster entry matches this person route yet. The workspace will appear once a matching projection row is available.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace/i })).not.toBeInTheDocument();
  });
});
