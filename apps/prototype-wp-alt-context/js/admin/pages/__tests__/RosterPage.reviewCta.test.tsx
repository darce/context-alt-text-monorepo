import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import type { RosterClusterCommitResponse, RosterEntry } from '../../api/rosterApi';
import type { BatchAnalyzeResponse, ClusterSummary } from '../../api/recognition';
import { useRecognitionCluster } from '../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useRosterEntries, useUpdatePerson } from '../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';
import { RosterPage } from '../RosterPage';
import { useClusterActions } from '../roster/hooks/useClusterActions';
import { useClusterDragDrop } from '../roster/hooks/useClusterDragDrop';
import { useClusterMediaMap } from '../roster/hooks/useClusterMediaMap';
import { useTopUnlabeledTotal } from '../roster/hooks/useTopUnlabeledTotal';

/**
 * UXW2-4 Commit 1 — the needs-assignment rail is retired (NAV-05: no dual home
 * with the workbench queue). Roster keeps a compact CTA card that deep-links to
 * the workbench review queue; the cluster drawer survives only as a `?cluster=`
 * deep-link shim (E21-10).
 */

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

describe('RosterPage workbench review CTA (UXW2-4 rail retirement)', () => {
  const mockedUseRecognitionCluster = vi.mocked(useRecognitionCluster);
  const mockedUseRosterEntries = vi.mocked(useRosterEntries);
  const mockedUseTopUnlabeledTotal = vi.mocked(useTopUnlabeledTotal);

  beforeEach(() => {
    vi.clearAllMocks();

    mockedUseRecognitionCluster.mockReturnValue(
      createMockQuery<ClusterSummary, Error>({ data: undefined, isLoading: false, isError: false }),
    );
    mockedUseRosterEntries.mockReturnValue(
      createMockQuery<RosterEntry[], Error>({ data: [], isLoading: false, isError: false, refetch: vi.fn() }),
    );
    vi.mocked(useCreatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useUpdatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useDeletePerson).mockReturnValue(createMockMutation({ mutate: vi.fn(), isPending: false }));
    vi.mocked(useClusterMediaMap).mockReturnValue({});
    vi.mocked(useClusterDragDrop).mockReturnValue(dragDropState);
    vi.mocked(useClusterActions).mockReturnValue(clusterActionState);
    mockedUseTopUnlabeledTotal.mockReturnValue(null);
  });

  it('links the CTA card to the workbench review queue and renders no rail', () => {
    renderRosterPage('/');

    const cta = screen.getByTestId('roster-review-cta');
    expect(cta).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Open Review Queue/i });
    expect(link).toHaveAttribute('href', '#/workbench?tab=scan&rq=all.all.0');

    // Rail retired: no section, no bulk rail controls, no per-cluster rail rows.
    expect(screen.queryByTestId('needs-assignment-section')).not.toBeInTheDocument();
    expect(screen.queryByText('Needs assignment')).not.toBeInTheDocument();
  });

  it('shows the server-reported waiting count when the top-unlabeled total is known (rg-015)', () => {
    mockedUseTopUnlabeledTotal.mockReturnValue(7);

    renderRosterPage('/');

    expect(screen.getByTestId('roster-review-cta')).toHaveTextContent('7 face groups waiting');
    expect(within(screen.getByTestId('roster-review-cta')).getByRole('status')).toHaveTextContent(
      '7 face groups waiting',
    );
  });

  it('uses a singular waiting count for total === 1', () => {
    mockedUseTopUnlabeledTotal.mockReturnValue(1);

    renderRosterPage('/');

    const status = within(screen.getByTestId('roster-review-cta')).getByRole('status');
    expect(status).toHaveTextContent('1 face group waiting');
    expect(status).not.toHaveTextContent(/face groups waiting/);
  });

  it('mounts an empty status live region before the count resolves (A11Y-21)', () => {
    mockedUseTopUnlabeledTotal.mockReturnValue(null);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const Harness = () => (
      <MemoryRouter initialEntries={['/']}>
        <QueryClientProvider client={queryClient}>
          <RosterPage />
        </QueryClientProvider>
      </MemoryRouter>
    );
    const { rerender } = render(<Harness />);

    const cta = screen.getByTestId('roster-review-cta');
    const status = within(cta).getByRole('status');
    expect(status).toBeInTheDocument();
    expect(status).toHaveTextContent('');

    mockedUseTopUnlabeledTotal.mockReturnValue(7);
    rerender(<Harness />);

    const next = within(screen.getByTestId('roster-review-cta')).getByRole('status');
    expect(next).toBe(status);
    expect(status).toHaveTextContent('7 face groups waiting');
  });

  it('never invents a total when the count is unknown (rg-015)', () => {
    mockedUseTopUnlabeledTotal.mockReturnValue(null);

    renderRosterPage('/');

    const cta = screen.getByTestId('roster-review-cta');
    expect(cta).toHaveTextContent('Unnamed faces are reviewed in the Review Queue.');
    expect(cta).not.toHaveTextContent(/face groups waiting/);
    expect(cta).not.toHaveTextContent('Unnamed faces waiting');
  });

  it('uses empty copy when the envelope total is a known zero', () => {
    mockedUseTopUnlabeledTotal.mockReturnValue(0);

    renderRosterPage('/');

    const cta = screen.getByTestId('roster-review-cta');
    expect(cta).toHaveTextContent('No unnamed face groups right now');
    expect(cta).not.toHaveTextContent('0 face groups waiting');
    expect(cta).not.toHaveTextContent('Unnamed faces waiting');
  });
});
