import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import type { BatchAnalyzeResponse, ClusterSummary } from '../../api/recognition';
import type { RosterClusterCommitResponse, RosterEntry } from '../../api/rosterApi';
import { useRecognitionCluster } from '../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useRosterEntries, useUpdatePerson } from '../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';
import { RosterPage } from '../RosterPage';
import { ClusterDrawerPanel } from '../roster/ClusterDrawerPanel';
import { useClusterActions } from '../roster/hooks/useClusterActions';
import { useClusterDragDrop } from '../roster/hooks/useClusterDragDrop';
import { useClusterMediaMap } from '../roster/hooks/useClusterMediaMap';
import { useTopUnlabeledTotal } from '../roster/hooks/useTopUnlabeledTotal';

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
    onCreate,
    ariaLabel,
    id,
  }: {
    options: { value: string; label: string }[];
    value?: string;
    onSelect?: (nextValue: string) => void;
    onCreate?: (value: string) => void;
    ariaLabel?: string;
    id?: string;
  }) => (
    <div>
      <select id={id} aria-label={ariaLabel} value={value ?? ''} onChange={(event) => onSelect?.(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button type="button" onClick={() => onCreate?.('Taylor')}>
        Create "Taylor"
      </button>
    </div>
  ),
}));

vi.mock('../../hooks/useRecognitionHooks', () => ({
  useRecognitionCluster: vi.fn(),
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

vi.mock('../roster/hooks/useTopUnlabeledTotal', () => ({
  useTopUnlabeledTotal: vi.fn(),
}));

vi.mock('../roster/PersonWorkspacePanel', () => ({
  PersonWorkspacePanel: () => null,
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
        onOpenPersonWorkspace={vi.fn()}
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
        onOpenPersonWorkspace={vi.fn()}
        isCommitting={false}
        rosterEntries={[
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

    const commitButton = screen.getByRole('button', { name: /^Confirm Assignment$/i });
    expect(commitButton).toBeEnabled();

    await userEvent.click(commitButton);
    expect(onCommitCluster).toHaveBeenCalledWith(cluster, { rosterEntryId: 42 });
  });

  it('supports inline create from combobox and commits with newEntryName', async () => {
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
        onOpenPersonWorkspace={vi.fn()}
        isCommitting={false}
        rosterEntries={[
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

    await userEvent.click(screen.getByRole('button', { name: 'Create "Taylor"' }));
    await userEvent.click(screen.getByRole('button', { name: /^Confirm Assignment$/i }));

    expect(onCommitCluster).toHaveBeenCalledWith(cluster, { newEntryName: 'Taylor' });
  });

  it('clears create state when selecting an existing person after create', async () => {
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
        onOpenPersonWorkspace={vi.fn()}
        isCommitting={false}
        rosterEntries={[
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

    await userEvent.click(screen.getByRole('button', { name: 'Create "Taylor"' }));
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Commit to roster entry/i }), '42');
    await userEvent.click(screen.getByRole('button', { name: /^Confirm Assignment$/i }));

    expect(onCommitCluster).toHaveBeenCalledWith(cluster, { rosterEntryId: 42 });
  });

  it('traps focus inside drawer and autofocuses close control', async () => {
    render(
      <ClusterDrawerPanel
        cluster={makeCluster()}
        identities={[]}
        mediaMap={{}}
        onClose={vi.fn()}
        onRescanCluster={vi.fn()}
        isRescanning={false}
        onCommitCluster={vi.fn()}
        onOpenPersonWorkspace={vi.fn()}
        isCommitting={false}
        rosterEntries={[
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

    const closeButton = screen.getByRole('button', { name: 'Close' });
    expect(closeButton).toHaveFocus();

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Commit to roster entry/i }), '42');

    // Tab from the LAST focusable element in the drawer wraps back to the first
    // focusable (the close button). This pins the trap-wrap semantics rather
    // than the identity of any specific button, so adding/removing buttons
    // (e.g. "Open person workspace") does not silently invalidate the assertion.
    const drawer = closeButton.closest('aside');
    if (!drawer) {
      throw new Error('expected drawer aside to be present in DOM');
    }
    const focusables = drawer.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    const last = focusables[focusables.length - 1];
    last.focus();
    expect(last).toHaveFocus();

    await userEvent.keyboard('{Tab}');
    expect(closeButton).toHaveFocus();
  });

  it('opens person review from the cluster person_uuid without inventing a picker link', async () => {
    const onOpenPersonWorkspace = vi.fn();

    render(
      <ClusterDrawerPanel
        cluster={makeCluster({ person_uuid: 'person-uuid-alex' })}
        identities={[]}
        mediaMap={{}}
        onClose={vi.fn()}
        onRescanCluster={vi.fn()}
        isRescanning={false}
        onCommitCluster={vi.fn()}
        onOpenPersonWorkspace={onOpenPersonWorkspace}
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

    const reviewLink = screen.getByRole('link', { name: /Open person review/i });
    await userEvent.click(reviewLink);

    expect(onOpenPersonWorkspace).toHaveBeenCalledWith('person-uuid-alex');
  });

  it('unresolved cluster with a selected roster entry does not invent a person review link', async () => {
    render(
      <ClusterDrawerPanel
        cluster={makeCluster({ person_uuid: null, identity_count: 3, label: null })}
        identities={[]}
        mediaMap={{}}
        onClose={vi.fn()}
        onRescanCluster={vi.fn()}
        isRescanning={false}
        onCommitCluster={vi.fn()}
        onOpenPersonWorkspace={vi.fn()}
        isCommitting={false}
        rosterEntries={[
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

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Commit to roster entry/i }), '42');

    expect(screen.getByText('Unresolved face group')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Open person review/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Open person/i })).not.toBeInTheDocument();
  });
});

const namedEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 7,
  person_uuid: 'person-uuid-alice',
  name: 'Alice Anderson',
  tags: ['family'],
  cluster_count: 1,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-01-01T00:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: '2026-01-01T00:00:00Z',
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
  >({
    mutate: vi.fn(),
    isPending: false,
  }),
  rescanGate: {
    disabled: false,
    'aria-disabled': undefined as true | undefined,
    title: undefined as string | undefined,
  },
  errorMessage: null,
  resetAll: vi.fn(),
};

const renderRosterPage = (): ReturnType<typeof render> => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={['/']}>
      <QueryClientProvider client={queryClient}>
        <RosterPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
};

describe('RosterPage headings [GPUFLOW-2 B1]', () => {
  const mockedUseRecognitionCluster = vi.mocked(useRecognitionCluster);
  const mockedUseRosterEntries = vi.mocked(useRosterEntries);
  const mockedUseTopUnlabeledTotal = vi.mocked(useTopUnlabeledTotal);

  beforeEach(() => {
    vi.clearAllMocks();

    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({ data: undefined, isLoading: false, isError: false }),
    );
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery<RosterEntry[], Error>({
        data: [namedEntry(), namedEntry({ id: 8, person_uuid: 'person-uuid-bob', name: 'Bob' })],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
      }),
    );
    mockedUseTopUnlabeledTotal.mockReturnValue(null);
    vi.mocked(useCreatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useUpdatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useDeletePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useClusterMediaMap).mockReturnValue({});
    vi.mocked(useClusterDragDrop).mockReturnValue(dragDropState);
    vi.mocked(useClusterActions).mockReturnValue(clusterActionState);
  });

  it('exposes exactly one accessible heading named People', () => {
    renderRosterPage();

    const peopleHeadings = screen.getAllByRole('heading', { name: /^People$/ });
    expect(peopleHeadings).toHaveLength(1);
    expect(peopleHeadings[0].tagName).toBe('H1');
    expect(peopleHeadings[0]).toHaveAttribute('id', 'acx-roster-title');
    expect(screen.getByRole('heading', { name: 'Named people (2)' })).toBeVisible();
    expect(
      screen.queryByText('People are the faces you have named. Unnamed face groups are reviewed in the Review Queue.'),
    ).not.toBeInTheDocument();
  });
});
