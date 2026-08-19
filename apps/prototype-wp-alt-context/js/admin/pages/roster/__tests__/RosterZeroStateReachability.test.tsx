import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { RosterClusterCommitResponse, RosterEntry } from '../../../api/rosterApi';
import type { BatchAnalyzeResponse, ClusterSummary } from '../../../api/recognition';
import { useRecognitionCluster } from '../../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useRosterEntries, useUpdatePerson } from '../../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../../test-utils/mockHooks';
import { RosterPage } from '../../RosterPage';
import { RosterEntriesSection } from '../RosterEntriesSection';
import { useClusterActions } from '../hooks/useClusterActions';
import { useClusterDragDrop } from '../hooks/useClusterDragDrop';
import { useClusterMediaMap } from '../hooks/useClusterMediaMap';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string, ...args: (string | number)[]) => {
    let index = 0;
    return format.replace(/%(s|d)/g, () => String(args[index++]));
  },
}));

vi.mock('../../../hooks/useRecognitionHooks', () => ({
  useRecognitionCluster: vi.fn(),
}));

vi.mock('../hooks/useTopUnlabeledTotal', () => ({
  useTopUnlabeledTotal: vi.fn(() => null),
}));

vi.mock('../../../hooks/useRosterHooks', () => ({
  useRosterEntries: vi.fn(),
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

vi.mock('../hooks/useClusterMediaMap', () => ({
  useClusterMediaMap: vi.fn(),
}));

vi.mock('../hooks/useClusterDragDrop', () => ({
  useClusterDragDrop: vi.fn(),
}));

vi.mock('../hooks/useClusterActions', () => ({
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

const renderRosterPage = (route = '/'): ReturnType<typeof render> => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={queryClient}>
        <RosterPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

const expectListAndAddPerson = (): void => {
  expect(screen.getByTestId('roster-entries-section')).toBeInTheDocument();
  // Tab panel + section both use the People label after UXP-4 slice 5.
  expect(
    within(screen.getByTestId('roster-entries-section')).getByRole('heading', { name: 'People' }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: /Add Person/ }).length).toBeGreaterThanOrEqual(1);
};

describe('Roster zero-state reachability (rg-003)', () => {
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

  it('shows People list and Add Person in the true zero-person state', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
    );

    renderRosterPage('/');

    expectListAndAddPerson();
    const zeroState = screen.getByTestId('roster-zero-state');
    expect(zeroState).toBeInTheDocument();
    expect(zeroState).toHaveTextContent(/No people yet/i);
    expect(zeroState.querySelector('.acx-roster-section__empty-icon')).toBeTruthy();
    expect(screen.getByRole('link', { name: /run a scan/i })).toBeInTheDocument();
    // rg-003 + NAV-05: the rail is retired; the workbench review queue stays
    // reachable from the true zero state via the CTA card.
    expect(screen.getByTestId('roster-review-cta')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Review in Workbench/i })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&rq=all.all.0',
    );
    expect(screen.queryByTestId('needs-assignment-section')).not.toBeInTheDocument();
  });

  it('pairs the active filter badge with an icon second channel', () => {
    const query = createMockQuery({
      data: [projectionEntry({ queue_memberships: ['singleton-proposals'] })],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    });

    render(
      <MemoryRouter initialEntries={['/?queue=singleton-proposals']}>
        <RosterEntriesSection query={query} />
      </MemoryRouter>,
    );

    const badge = screen.getByTestId('roster-filter-badge');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent(/Filtered: Singleton proposals/i);
    expect(screen.getByTestId('roster-filter-badge-icon')).toBeInTheDocument();
  });

  it('keeps list and Add Person mounted when default workspace auto-opens (fails on old unmount)', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [projectionEntry({ projection_status: 'current', person_uuid: 'person-uuid-1', name: 'Alice' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderRosterPage('/');

    expect(screen.getByRole('region', { name: /Person workspace: Alice/i })).toBeInTheDocument();
    expectListAndAddPerson();
  });

  it('shows list and Add Person when a person filter is active', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery({
        data: [
          projectionEntry({
            id: 2,
            person_uuid: 'person-uuid-bob',
            name: 'Bob',
            cluster_count: 0,
          }),
        ],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );

    renderRosterPage('/?tab=entries&personFilter=unassigned');

    expectListAndAddPerson();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.getByText('Filtered: Unassigned')).toBeInTheDocument();
  });

  it('shows list shell and Add Person when roster query is offline/error', () => {
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery<RosterEntry[], Error>({
        data: undefined,
        isLoading: false,
        isError: true,
        refetch: vi.fn(),
      }),
    );

    renderRosterPage('/');

    expectListAndAddPerson();
    expect(screen.getByText(/Unable to load roster entries/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('renders a designed empty state composition inside RosterEntriesSection', () => {
    render(
      <MemoryRouter initialEntries={['/?tab=entries']}>
        <RosterEntriesSection
          query={{ isLoading: false, isError: false, data: [], refetch: vi.fn() }}
        />
      </MemoryRouter>,
    );

    const zeroState = screen.getByTestId('roster-zero-state');
    expect(zeroState).toHaveAttribute('role', 'status');
    expect(zeroState).toHaveTextContent(/No people yet/i);
    expect(zeroState).toHaveTextContent(/Add someone manually or run a scan/i);
    expect(screen.getAllByRole('button', { name: /Add Person/ }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('link', { name: /run a scan/i })).toHaveAttribute('href', '#/workbench?tab=scan');
  });
});
