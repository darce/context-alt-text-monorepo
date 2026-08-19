import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';

import type { RosterClusterCommitResponse, RosterEntry } from '../../api/rosterApi';
import type { BatchAnalyzeResponse, ClusterSummary } from '../../api/recognition';
import { useRecognitionCluster } from '../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useRosterEntries, useUpdatePerson } from '../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';
import { RosterPage } from '../RosterPage';
import { PersonWorkspacePanel } from '../roster/PersonWorkspacePanel';
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
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-05-07T12:00:00Z',
  source_version: 11,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T12:00:00Z',
  ...overrides,
});

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
  >(
    {
      mutate: vi.fn(),
      isPending: false,
    },
  ),
  rescanGate: {
    disabled: false,
    'aria-disabled': undefined as true | undefined,
    title: undefined as string | undefined,
  },
  errorMessage: null,
  resetAll: vi.fn(),
};

const RouteStateProbe = (): React.JSX.Element => {
  const [searchParams] = useSearchParams();

  return <output aria-label="route-state">{searchParams.toString()}</output>;
};

const PersonRouteController = (): React.JSX.Element => {
  const [, setSearchParams] = useSearchParams();

  return (
    <>
      <button type="button" onClick={() => setSearchParams({ person: 'person-uuid-2' })}>
        Open Tory workspace
      </button>
      <button
        type="button"
        onClick={() => {
          setSearchParams((previous) => {
            const next = new URLSearchParams(previous);
            next.delete('person');
            return next;
          });
        }}
      >
        Clear person route
      </button>
    </>
  );
};

const createTestQueryClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

const renderWithProviders = (
  ui: React.ReactElement,
  initialEntries: string[] = ['/'],
): ReturnType<typeof render> => {
  const queryClient = createTestQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('RosterPage projection-aware workspace shell', () => {
  const mockedUseRecognitionCluster = vi.mocked(useRecognitionCluster);
  const mockedUseRosterEntries = vi.mocked(useRosterEntries);
  const mockedUseCreatePerson = vi.mocked(useCreatePerson);
  const mockedUseUpdatePerson = vi.mocked(useUpdatePerson);
  const mockedUseDeletePerson = vi.mocked(useDeletePerson);
  const mockedUseClusterMediaMap = vi.mocked(useClusterMediaMap);
  const mockedUseClusterDragDrop = vi.mocked(useClusterDragDrop);
  const mockedUseClusterActions = vi.mocked(useClusterActions);

  beforeEach(() => {
    vi.clearAllMocks();

    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({ data: undefined, isLoading: false, isError: false }),
    );
    mockedUseCreatePerson.mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    mockedUseUpdatePerson.mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    mockedUseDeletePerson.mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
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

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

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

    renderWithProviders(<RosterPage />);

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add Person/ })).toBeInTheDocument();
  });

  it('[PAG-M3-S2] restores the default workspace after ?person= is set then cleared', async () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          projectionEntry({
            id: 2,
            person_uuid: 'person-uuid-2',
            name: 'Tory',
            projection_status: 'current',
          }),
          projectionEntry({
            id: 1,
            person_uuid: 'person-uuid-1',
            name: 'Alice',
            projection_status: 'current',
          }),
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(
      <>
        <PersonRouteController />
        <RouteStateProbe />
        <RosterPage />
      </>,
    );

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Open Tory workspace' }));
    expect(screen.getByLabelText('route-state')).toHaveTextContent('person=person-uuid-2');
    expect(screen.getByRole('region', { name: /Person workspace: Tory/i })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace: Alice/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Clear person route' }));
    expect(screen.getByLabelText('route-state')).not.toHaveTextContent('person=');
    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace: Tory/i })).not.toBeInTheDocument();
    expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add Person/ })).toBeInTheDocument();
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

    renderWithProviders(<RosterPage />);

    const workspace = screen.getByRole('region', { name: /Person workspace: Alice/i });
    expect(workspace).toBeInTheDocument();
    expect(within(workspace).getByText('Data status: current')).toBeInTheDocument();
    expect(
      within(workspace).getByText(`Last refreshed: ${new Date(refreshedAt).toLocaleString()}`),
    ).toBeInTheDocument();
    expect(within(workspace).getByText('Record version: 11')).toBeInTheDocument();
    expect(within(workspace).getByText('Face group detail')).toBeInTheDocument();
    expect(
      within(workspace).getByText('2 face groups are currently assigned to this person.'),
    ).toBeInTheDocument();
    expect(within(workspace).getByText('Primary')).toBeInTheDocument();
    expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();
  });

  it('[PAG-M4-S4] renders populated and empty curriculum queue states in the person workspace', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          projectionEntry({
            projection_status: 'current',
            person_uuid: 'person-uuid-1',
            name: 'Alice',
            queue_memberships: ['singleton-proposals', 'needs-confirmation-after-merge'],
          }),
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

    const singletonQueue = screen.getByRole('region', { name: 'Singleton proposals queue' });
    const hardExamplesQueue = screen.getByRole('region', { name: 'Hard examples queue' });
    const confirmationQueue = screen.getByRole('region', { name: 'Needs confirmation after merge queue' });

    expect(within(singletonQueue).getByText('Queued for review in this workspace.')).toBeInTheDocument();
    expect(within(singletonQueue).getByText('Open singleton proposals queue')).toBeInTheDocument();

    expect(within(hardExamplesQueue).getByText('No queued items for this person yet.')).toBeInTheDocument();
    expect(
      within(hardExamplesQueue).getByText('Hard examples will appear after the next refresh.'),
    ).toBeInTheDocument();

    expect(within(confirmationQueue).getByText('Queued for review in this workspace.')).toBeInTheDocument();
    expect(within(confirmationQueue).getByText('Open needs confirmation after merge queue')).toBeInTheDocument();
  });

  it('[PAG-M4-S4] opens the queued singleton proposals route from the person workspace', async () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          projectionEntry({
            projection_status: 'current',
            person_uuid: 'person-uuid-1',
            name: 'Alice',
            queue_memberships: ['singleton-proposals'],
          }),
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderWithProviders(
      <>
        <RouteStateProbe />
        <RosterPage />
      </>,
      ['/?person=person-uuid-1'],
    );

    await userEvent.click(screen.getByRole('button', { name: 'Open singleton proposals queue' }));

    expect(screen.getByLabelText('route-state')).toHaveTextContent(
      'person=person-uuid-1&queue=singleton-proposals',
    );
    expect(screen.getByRole('region', { name: 'Person workspace: Alice' })).toBeInTheDocument();
  });

  it('[PAG-M4-S4] disables queued actions when the person identifier is unavailable', () => {
    const onOpenQueue = vi.fn();

    renderWithProviders(
      <PersonWorkspacePanel
        entry={projectionEntry({
          person_uuid: '',
          name: 'Alice',
          queue_memberships: ['hard-examples'],
        })}
        onOpenQueue={onOpenQueue}
      />,
    );

    expect(screen.getByRole('button', { name: 'Open hard examples queue' })).toBeDisabled();
    expect(screen.getByText('Person identifier unavailable until the next refresh.')).toBeInTheDocument();
    expect(onOpenQueue).not.toHaveBeenCalled();
  });

  it('[PAG-M3-S3] renders face evidence and all faces for the selected person', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          projectionEntry({
            projection_status: 'current',
            person_uuid: 'person-uuid-1',
            name: 'Alice',
            clusters: [
              {
                cluster_id: 'cluster-alpha',
                identity_count: 2,
                representative_identity: {
                  identity_id: 'identity-1',
                  media_id: 101,
                  media_url: 'https://example.com/rep-alpha.jpg',
                  bbox: { x: 10, y: 20, width: 30, height: 40 },
                  similarity: 0.97,
                },
                instances: [
                  {
                    identity_id: 'identity-1',
                    media_id: 101,
                    media_url: 'https://example.com/instance-101.jpg',
                    bbox: { x: 10, y: 20, width: 30, height: 40 },
                    similarity: 0.97,
                  },
                  {
                    identity_id: 'identity-2',
                    media_id: 102,
                    media_url: 'https://example.com/instance-102.jpg',
                    bbox: { x: 20, y: 30, width: 40, height: 50 },
                    similarity: 0.89,
                  },
                ],
              },
            ],
          }),
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

    const evidenceSection = screen.getByRole('region', { name: 'Face evidence' });
    const clusterRegion = within(evidenceSection).getByRole('region', { name: 'Face group 1' });

    expect(within(clusterRegion).getByText('2 faces')).toBeInTheDocument();
    expect(within(evidenceSection).queryByText(/cluster-alpha/)).not.toBeInTheDocument();

    const evidenceImages = [
      { name: 'Representative face for face group 1', src: 'https://example.com/rep-alpha.jpg' },
      { name: 'Face from media 101 in face group 1', src: 'https://example.com/instance-101.jpg' },
      { name: 'Face from media 102 in face group 1', src: 'https://example.com/instance-102.jpg' },
    ];
    for (const { name, src } of evidenceImages) {
      const image = within(clusterRegion).getByRole('img', { name });
      expect(image).toHaveAttribute('src', src);
      expect(image).toHaveAttribute('loading', 'lazy');
      expect(image.closest('.acx-face-thumbnail')).not.toBeNull();
      expect(image.closest('button')).not.toBeNull();
      expect(image).not.toHaveAttribute('width', '96');
    }

    for (const role of ['img', 'button', 'region'] as const) {
      expect(within(clusterRegion).queryByRole(role, { name: /cluster-alpha/i })).toBeNull();
    }

    expect(within(clusterRegion).getByText('Media 101')).toBeInTheDocument();
    expect(within(clusterRegion).getByText('Media 102')).toBeInTheDocument();
  });

  it('[PAG-M5-S5] keeps evidence useful when only fallback similarity fields are available', () => {
    renderWithProviders(
      <PersonWorkspacePanel
        entry={projectionEntry({
          clusters: [
            {
              cluster_id: 'cluster-alpha',
              identity_count: 2,
              representative_identity: {
                identity_id: 'identity-1',
                media_id: 101,
                media_url: 'https://example.com/rep-alpha.jpg',
                bbox: { x: 10, y: 20, width: 30, height: 40 },
                similarity: 0.97,
              },
              instances: [
                {
                  identity_id: 'identity-1',
                  media_id: 101,
                  media_url: 'https://example.com/instance-101.jpg',
                  bbox: { x: 10, y: 20, width: 30, height: 40 },
                  similarity: 0.89,
                },
                {
                  identity_id: 'identity-2',
                  media_id: 102,
                  media_url: null,
                  bbox: { x: 20, y: 30, width: 40, height: 50 },
                  similarity: null,
                },
              ],
            },
          ],
        })}
        onOpenQueue={vi.fn()}
      />,
    );

    expect(screen.getAllByText('strong match').length).toBeGreaterThan(0);
    expect(screen.getAllByText('likely match').length).toBeGreaterThan(0);
    expect(screen.getByText('Similarity pending the next refresh.')).toBeInTheDocument();
  });

  it('[PAG-M5-S5] renders threshold metadata when projected score thresholds are present', () => {
    renderWithProviders(
      <PersonWorkspacePanel
        entry={projectionEntry({
          clusters: [
            {
              cluster_id: 'cluster-beta',
              identity_count: 1,
              representative_identity: {
                identity_id: 'identity-9',
                media_id: 201,
                media_url: 'https://example.com/rep-beta.jpg',
                bbox: { x: 20, y: 20, width: 50, height: 50 },
                similarity: 0.91,
                similarity_threshold: 0.85,
              },
              instances: [],
            },
          ],
        })}
        onOpenQueue={vi.fn()}
      />,
    );

    expect(screen.getAllByText('strong match').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Above this face group’s current threshold').length).toBeGreaterThan(0);
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

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

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

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

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

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

    expect(
      screen.getByText(
        'Roster projection failed to refresh. Person workspace is unavailable until the projection recovers.',
      ),
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

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-1']);

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

    renderWithProviders(<RosterPage />, ['/?person=person-uuid-missing']);

    expect(
      screen.getByText(
        'No roster entry matches this person route yet. The workspace will appear once a matching projection row is available.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Person workspace/i })).not.toBeInTheDocument();
  });
});
