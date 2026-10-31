import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useSearchParams } from 'react-router-dom';

import type { RosterClusterCommitResponse, RosterEntry } from '../../api/rosterApi';
import type { BatchAnalyzeResponse, ClusterSummary } from '../../api/recognition';
import { useRecognitionCluster } from '../../hooks/useRecognitionHooks';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../hooks/useRosterHooks';
import { createMockMutation, createMockQuery } from '../../test-utils/mockHooks';
import { listRosterEntries } from '../../api/rosterApi';
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

vi.mock('../../api/rosterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/rosterApi')>()),
  listRosterEntries: vi.fn(),
}));

vi.mock('../../hooks/useRecognitionHooks', () => ({
  useRecognitionCluster: vi.fn(),
}));

vi.mock('../roster/hooks/useTopUnlabeledTotal', () => ({
  useTopUnlabeledTotal: vi.fn(() => null),
}));

vi.mock('../../hooks/useRosterHooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks/useRosterHooks')>()),
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
  queue_memberships: ['hard-examples'],
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

const RouteStateProbe = (): React.JSX.Element => {
  const [searchParams] = useSearchParams();

  return <output aria-label="route-state">{searchParams.toString()}</output>;
};

const stale = projectionEntry({ projection_status: 'stale' });
const current = projectionEntry();
const load = vi.mocked(listRosterEntries);
const route = '/?person=person-uuid-1&section=photos&queue=hard-examples&face=face-7&s=Alice';
const renderPage = (data: RosterEntry[] | undefined = [stale], initialRoute = route) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (data !== undefined) {
    client.setQueryData(['roster', 'entries'], data);
  }
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialRoute]}>
        <RouteStateProbe />
        <RosterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, client };
};

beforeEach(() => {
  vi.clearAllMocks();
  load.mockResolvedValue([stale]);
  vi.mocked(useRecognitionCluster).mockReturnValue(createMockQuery<ClusterSummary, Error>({ data: undefined }));
  vi.mocked(useCreatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn() }));
  vi.mocked(useUpdatePerson).mockReturnValue(createMockMutation({ mutate: vi.fn() }));
  vi.mocked(useDeletePerson).mockReturnValue(createMockMutation({ mutate: vi.fn() }));
  vi.mocked(useClusterMediaMap).mockReturnValue({});
  vi.mocked(useClusterDragDrop).mockReturnValue(dragDropState);
  vi.mocked(useClusterActions).mockReturnValue(clusterActionState);
});
afterEach(() => vi.useRealTimers());

it('recovers the actual stale View photos route using one read, retaining selection, route and add draft', async () => {
  const user = userEvent.setup();
  renderPage([stale], '/');
  await user.click(screen.getByRole('button', { name: 'Add Person' }));
  await user.type(screen.getByRole('textbox', { name: 'Full name' }), 'Unfinished name');
  await user.click(screen.getByRole('link', { name: 'View photos for Alice' }));
  const before = screen.getByLabelText('route-state').textContent;
  expect(before).toContain('person=person-uuid-1');
  expect(before).toContain('section=photos');
  const recovery = screen.getByRole('group', { name: 'People refresh' });
  expect(within(recovery).getByRole('heading')).toHaveFocus();
  await user.click(within(recovery).getByRole('button', { name: 'Refresh people' }));
  await waitFor(() => expect(load).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(within(recovery).getByRole('status')).toHaveTextContent('People checked.'));
  expect(within(recovery).getByRole('status')).toHaveTextContent('still out of date');
  expect(screen.queryByRole('region', { name: 'Person workspace: Alice' })).not.toBeInTheDocument();
  expect(screen.getByLabelText('route-state')).toHaveTextContent(before);
  expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('Unfinished name');
  expect(clusterActionState.commitMutation.mutate).not.toHaveBeenCalled();
  expect(clusterActionState.rescanMutation.mutate).not.toHaveBeenCalled();
});

it('does not treat a failed read with cached current data as a fresh workspace', async () => {
  load.mockRejectedValue(new Error('offline'));
  renderPage([current]);
  await userEvent.click(screen.getByRole('button', { name: 'Refresh people' }));
  const recovery = screen.getByRole('group', { name: 'People refresh' });
  await waitFor(() => expect(within(recovery).getByRole('status')).toHaveTextContent('Could not refresh people'));
  expect(screen.queryByRole('region', { name: 'Person workspace: Alice' })).not.toBeInTheDocument();
  expect(screen.queryByText('No people yet')).not.toBeInTheDocument();
  load.mockResolvedValue([current]);
  await userEvent.click(within(recovery).getByRole('button', { name: 'Retry refresh' }));
  await screen.findByRole('region', { name: 'Person workspace: Alice' });
  expect(screen.getByRole('button', { name: 'Refresh people' })).toHaveFocus();
  expect(screen.getByLabelText('route-state')).toHaveTextContent(
    'person=person-uuid-1&section=photos&queue=hard-examples&face=face-7&s=Alice',
  );
});

it.each(['refreshing', 'failed', 'stale'] as const)(
  'keeps the %s server hold after a successful read',
  async (status) => {
    load.mockResolvedValue([projectionEntry({ projection_status: status })]);
    renderPage([projectionEntry({ projection_status: status })]);
    await userEvent.click(screen.getByRole('button', { name: 'Refresh people' }));
    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('People checked.'),
    );
    expect(screen.queryByRole('region', { name: 'Person workspace: Alice' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Refresh people' })).toBeEnabled();
  },
);

it.each([
  ['empty', []],
  ['unknown', [{ ...current, projection_status: 'future-status' } as unknown as RosterEntry]],
  ['unmatched', [{ ...current, person_uuid: 'other-person' }]],
] as const)('offers recovery for %s data without inventing an identity or failure', async (_state, entries) => {
  load.mockResolvedValue([...entries]);
  renderPage([...entries]);
  const recovery = screen.getByRole('group', { name: 'People refresh' });
  await userEvent.click(within(recovery).getByRole('button', { name: 'Refresh people' }));
  await waitFor(() => expect(within(recovery).getByRole('status')).toHaveTextContent('People checked.'));
  expect(recovery).not.toHaveTextContent('Could not refresh');
  expect(screen.queryByRole('region', { name: /Person workspace: / })).not.toBeInTheDocument();
});

it('bounds an unresolved read, joins retries, and handles late stale results truthfully', async () => {
  let finish!: (data: RosterEntry[]) => void;
  load.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  renderPage([stale]);
  vi.useFakeTimers();
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const refresh = screen.getByRole('button', { name: 'Refresh people' });
  await user.click(refresh);
  expect(refresh).toHaveAttribute('aria-disabled', 'true');
  await user.click(refresh);
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
  });
  expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('Still waiting');
  await user.click(screen.getByRole('button', { name: 'Refresh people' }));
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => {
    finish([stale]);
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
  expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('People checked.');
  expect(screen.queryByRole('region', { name: 'Person workspace: Alice' })).not.toBeInTheDocument();
});

it('allows stop waiting without cancelling the query or clearing a draft', async () => {
  load.mockImplementation(() => new Promise(() => undefined));
  renderPage([stale]);
  await userEvent.click(screen.getByRole('button', { name: 'Refresh people' }));
  await userEvent.click(screen.getByRole('button', { name: 'Stop waiting' }));
  expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('Stopped waiting');
  expect(screen.getByRole('button', { name: 'Refresh people' })).toHaveFocus();
  expect(load).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('route-state')).toHaveTextContent('person=person-uuid-1');
});

it('keeps rename input and search draft mounted through a failed refresh', async () => {
  const user = userEvent.setup();
  load.mockRejectedValue(new Error('offline'));
  renderPage([stale]);
  await user.click(screen.getByRole('button', { name: 'Edit person' }));
  const name = screen.getByRole('textbox', { name: 'Person name' });
  await user.clear(name);
  await user.type(name, 'Alice draft');
  await user.click(screen.getByRole('button', { name: 'Refresh people' }));
  await waitFor(() =>
    expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('Could not refresh people'),
  );
  expect(screen.getByRole('textbox', { name: 'Person name' })).toBe(name);
  expect(name).toHaveValue('Alice draft');
  expect(screen.getByRole('searchbox', { name: 'Search people' })).toHaveValue('Alice');
});

it('bounds initial loading and offers a retry without an empty or failure claim', async () => {
  load.mockImplementation(() => new Promise(() => undefined));
  // Explicitly do not seed the real query cache.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.useFakeTimers();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <RosterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('Checking people');
  expect(screen.queryByText('No people yet')).not.toBeInTheDocument();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15_000);
  });
  expect(screen.getByRole('group', { name: 'People refresh' })).toHaveTextContent('Still waiting');
  expect(screen.getByRole('button', { name: 'Refresh people' })).toBeEnabled();
});
