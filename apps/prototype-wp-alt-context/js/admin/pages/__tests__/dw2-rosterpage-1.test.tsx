import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { BatchAnalyzeResponse, ClusterSummary } from '../../api/recognition';
import type { RosterClusterCommitResponse, RosterEntry } from '../../api/rosterApi';
import { useRecognitionCluster } from '../../hooks/useRecognitionHooks';
import { useRosterEntries } from '../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';
import { RosterPage } from '../RosterPage';
import { useClusterActions } from '../roster/hooks/useClusterActions';
import { useClusterDragDrop } from '../roster/hooks/useClusterDragDrop';
import { useClusterMediaMap } from '../roster/hooks/useClusterMediaMap';
import { useTopUnlabeledTotal } from '../roster/hooks/useTopUnlabeledTotal';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string, plural: string, count: number) => (count === 1 ? single : plural),
  sprintf: (format: string) => format,
}));

vi.mock('../../hooks/useRecognitionHooks', () => ({ useRecognitionCluster: vi.fn() }));
vi.mock('../../hooks/useRosterHooks', () => ({ useRosterEntries: vi.fn() }));
vi.mock('../roster/hooks/useClusterMediaMap', () => ({ useClusterMediaMap: vi.fn() }));
vi.mock('../roster/hooks/useClusterDragDrop', () => ({ useClusterDragDrop: vi.fn() }));
vi.mock('../roster/hooks/useClusterActions', () => ({ useClusterActions: vi.fn() }));
vi.mock('../roster/hooks/useTopUnlabeledTotal', () => ({ useTopUnlabeledTotal: vi.fn() }));
vi.mock('../roster/ClusterDrawerPanel', () => ({
  ClusterDrawerPanel: () => null,
  ROSTER_ASSIGN_STATUS: { error: 'error', loading: 'loading', ready: 'ready' },
}));
vi.mock('../roster/RosterEntriesSection', () => ({ RosterEntriesSection: () => null }));
vi.mock('../roster/PersonWorkspacePanel', () => ({
  PersonWorkspacePanel: ({ entry }: { entry: RosterEntry }) => <div data-testid="person-workspace">{entry.name}</div>,
}));
vi.mock('../roster/SamePersonPrompt', () => ({ SamePersonPrompt: () => null }));

const entry: RosterEntry = {
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
};

describe('RosterPage default workspace filters', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRecognitionCluster).mockReturnValue(
      createMockQuery<ClusterSummary, Error>({ data: undefined, isLoading: false, isError: false }),
    );
    vi.mocked(useRosterEntries).mockReturnValue(
      createMockQuery<RosterEntry[], Error>({ data: [entry], isLoading: false, isError: false, refetch: vi.fn() }),
    );
    vi.mocked(useTopUnlabeledTotal).mockReturnValue(null);
    vi.mocked(useClusterMediaMap).mockReturnValue({});
    vi.mocked(useClusterDragDrop).mockReturnValue({
      dragPayload: null,
      dropTarget: null,
      isDragging: false,
      handleFaceDragStart: vi.fn(),
      handleFaceDragEnd: vi.fn(),
      handleDropTargetChange: vi.fn(),
      resetDragState: vi.fn(),
    });
    vi.mocked(useClusterActions).mockReturnValue({
      reassignMutation: createMockMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
        mutate: vi.fn(),
      }),
      rescanMutation: createMockMutation<
        BatchAnalyzeResponse,
        Error,
        { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
      >({ mutate: vi.fn(), isPending: false }),
      commitMutation: createMockMutation<
        RosterClusterCommitResponse,
        Error,
        { clusterId: string; rosterEntryId?: number; newEntryName?: string }
      >({ mutate: vi.fn(), isPending: false }),
      rescanGate: { disabled: false, 'aria-disabled': undefined, title: undefined },
      errorMessage: null,
      resetAll: vi.fn(),
    });
  });

  it('does not open an unrelated default person workspace when the catalogue search is active', () => {
    render(
      <MemoryRouter initialEntries={['/?s=unrelated']}>
        <RosterPage />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId('person-workspace')).not.toBeInTheDocument();
  });
});
