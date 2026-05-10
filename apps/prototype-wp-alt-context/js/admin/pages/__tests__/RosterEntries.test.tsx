import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';

import type { RosterEntry } from '../../api/rosterApi';
import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../hooks/useRosterHooks';
import { createMockMutation } from '../../test-utils/mockHooks';
import { RosterEntriesSection } from '../roster/RosterEntriesSection';
import type { RosterEntriesQuery } from '../roster/RosterEntriesSection';
import { RosterEntriesTable } from '../roster/RosterEntriesTable';
import { vi } from 'vitest';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  _n: (single: string) => single,
}));

vi.mock('../../hooks/useRosterHooks', () => ({
  useCreatePerson: vi.fn(),
  useUpdatePerson: vi.fn(),
  useDeletePerson: vi.fn(),
}));

const entries: RosterEntry[] = [
  {
    id: 1,
    person_uuid: 'person-uuid-alice',
    name: 'Alice',
    tags: ['tag-a'],
    cluster_count: 2,
    clusters: [],
    queue_memberships: ['singleton-proposals'],
    updated_at: new Date().toISOString(),
    source_version: 1,
    projection_status: 'current',
    projection_refreshed_at: new Date().toISOString(),
  },
  {
    id: 2,
    person_uuid: 'person-uuid-bob',
    name: 'Bob',
    tags: [],
    cluster_count: 0,
    clusters: [],
    queue_memberships: ['hard-examples'],
    updated_at: new Date().toISOString(),
    source_version: 1,
    projection_status: 'current',
    projection_refreshed_at: new Date().toISOString(),
  },
];

interface CreateRosterMutationContext {
  previousEntries: RosterEntry[] | undefined;
  optimisticId: number;
}

interface RosterMutationContext {
  previousEntries: RosterEntry[] | undefined;
  optimisticId?: number;
}

const createMutation = createMockMutation<
  RosterEntry,
  Error,
  { name: string; tags?: string[] },
  CreateRosterMutationContext
>({
  mutate: vi.fn(),
  isPending: false,
});
const updateMutation = createMockMutation<
  RosterEntry,
  Error,
  { id: number; name?: string; tags?: string[] },
  RosterMutationContext
>({
  mutate: vi.fn(),
  isPending: false,
});
const deleteMutation = createMockMutation<void, Error, number, RosterMutationContext>({
  mutate: vi.fn(),
  isPending: false,
});

const LocationProbe = () => {
  const location = useLocation();
  return <output data-testid="location-search">{location.search}</output>;
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCreatePerson).mockReturnValue(createMutation);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation);
});

describe('RosterEntriesTable', () => {
  it('renders identity rows', () => {
    render(<RosterEntriesTable entries={entries} />);

    expect(screen.getByText(/Alice/)).toBeInTheDocument();
    expect(screen.getByText(/tag-a/)).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('confirms before deleting a person', async () => {
    render(<RosterEntriesTable entries={entries} />);

    await userEvent.click(screen.getAllByRole('button', { name: 'Delete person' })[0]);

    expect(
      screen.getByText('Are you sure you want to delete this person? Assigned clusters will be dissociated.'),
    ).toBeInTheDocument();

    await userEvent.click(screen.getAllByRole('button', { name: 'Delete' }).at(-1)!);

    expect(deleteMutation.mutate).toHaveBeenCalledWith(1, expect.any(Object));
  });
});

describe('RosterEntriesSection', () => {
  const renderSection = (query: RosterEntriesQuery, route = '/?tab=entries') =>
    render(
      <MemoryRouter initialEntries={[route]}>
        <RosterEntriesSection query={query} />
        <LocationProbe />
      </MemoryRouter>,
    );

  it('shows loading state', () => {
    const query: RosterEntriesQuery = { isLoading: true, isError: false, data: undefined, refetch: vi.fn() };
    renderSection(query);
    expect(screen.getByText(/Loading roster entries/)).toBeInTheDocument();
  });

  it('shows error state with retry button', async () => {
    const refetch = vi.fn();
    const query: RosterEntriesQuery = { isLoading: false, isError: true, data: undefined, refetch };

    renderSection(query);

    expect(screen.getByText(/Unable to load roster entries/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it('creates a new person via Add Person form', async () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query);

    await userEvent.click(screen.getByRole('button', { name: /Add Person/ }));
    await userEvent.type(screen.getByPlaceholderText('Full Name'), 'Carol');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    expect(createMutation.mutate).toHaveBeenCalledTimes(1);
    expect(createMutation.mutate).toHaveBeenCalledWith({ name: 'Carol' }, expect.any(Object));

    const calls = vi.mocked(createMutation.mutate).mock.calls;
    const options = calls[0]?.[1];
    expect(options).toBeDefined();
    expect(typeof options?.onSuccess).toBe('function');
  });

  it('renders entries without filter', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query);

    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.queryByText('Filtered: Unassigned')).not.toBeInTheDocument();
    expect(screen.queryByText('Showing unassigned people only.')).not.toBeInTheDocument();
  });

  it('filters to unassigned people when personFilter=unassigned', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };
    renderSection(query, '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('Filtered: Unassigned')).toBeInTheDocument();
    expect(screen.getByText('Showing unassigned people only.')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.queryByText('Alice')).not.toBeInTheDocument();
  });

  it('filters to queue members when queue=singleton-proposals', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=singleton-proposals');

    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.queryByText('Bob')).not.toBeInTheDocument();
    expect(screen.getByText('Showing singleton proposals queue only.')).toBeInTheDocument();
  });

  it('routes singleton-proposals review actions to the workbench scan tab', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=singleton-proposals');

    expect(screen.getByRole('link', { name: 'Review singleton proposals in Workbench' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('routes needs-confirmation-after-merge review actions to the workbench scan tab', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=needs-confirmation-after-merge');

    expect(screen.getByRole('link', { name: 'Review merge confirmations in Workbench' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan',
    );
  });

  it('explains that hard-examples review actions are unavailable until the contract lands', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };

    renderSection(query, '/?tab=entries&queue=hard-examples');

    expect(
      screen.getByText('Hard-examples review actions stay unavailable here until the dedicated review contract lands.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Workbench/i })).not.toBeInTheDocument();
  });

  it('shows filtered empty state and allows clearing the filter', async () => {
    const query: RosterEntriesQuery = {
      isLoading: false,
      isError: false,
      data: [
        {
          id: 3,
          person_uuid: 'person-uuid-chris',
          name: 'Chris',
          tags: [],
          cluster_count: 1,
          clusters: [],
          queue_memberships: [],
          updated_at: new Date().toISOString(),
          source_version: 1,
          projection_status: 'current',
          projection_refreshed_at: new Date().toISOString(),
        },
      ],
      refetch: vi.fn(),
    };

    renderSection(query, '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('No unassigned people found.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Clear filter' }));

    expect(screen.queryByText('No unassigned people found.')).not.toBeInTheDocument();
    expect(screen.getByText('Chris')).toBeInTheDocument();
    expect(screen.getByTestId('location-search')).toHaveTextContent('?tab=entries');
  });
});
