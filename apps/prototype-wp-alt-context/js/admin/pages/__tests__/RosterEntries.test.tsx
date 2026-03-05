import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { useCreatePerson, useDeletePerson, useUpdatePerson } from '../../hooks/useRosterHooks';
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

const entries = [
  {
    id: 1,
    name: 'Alice',
    tags: ['tag-a'],
    cluster_count: 2,
    updated_at: new Date().toISOString(),
  },
  {
    id: 2,
    name: 'Bob',
    tags: [],
    cluster_count: 0,
    updated_at: new Date().toISOString(),
  },
];

const createMutation: {
  mutate: (variables: { name: string; tags?: string[] }, options?: { onSuccess?: () => void }) => void;
  isPending: boolean;
} = { mutate: vi.fn(), isPending: false };
const updateMutation: {
  mutate: (variables: { id: number; name?: string; tags?: string[] }, options?: { onSuccess?: () => void }) => void;
  isPending: boolean;
} = { mutate: vi.fn(), isPending: false };
const deleteMutation: {
  mutate: (id: number) => void;
  isPending: boolean;
} = { mutate: vi.fn(), isPending: false };

beforeEach(() => {
  vi.mocked(useCreatePerson).mockReturnValue(createMutation as unknown as ReturnType<typeof useCreatePerson>);
  vi.mocked(useUpdatePerson).mockReturnValue(updateMutation as unknown as ReturnType<typeof useUpdatePerson>);
  vi.mocked(useDeletePerson).mockReturnValue(deleteMutation as unknown as ReturnType<typeof useDeletePerson>);
});

describe('RosterEntriesTable', () => {
  it('renders identity rows', () => {
    render(<RosterEntriesTable entries={entries} />);

    expect(screen.getByText(/Alice/)).toBeInTheDocument();
    expect(screen.getByText(/tag-a/)).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });
});

describe('RosterEntriesSection', () => {
  const renderSection = (query: RosterEntriesQuery, route = '/?tab=entries') =>
    render(
      <MemoryRouter initialEntries={[route]}>
        <RosterEntriesSection query={query} />
      </MemoryRouter>
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
    expect(screen.queryByText('Showing unassigned people only.')).not.toBeInTheDocument();
  });

  it('filters to unassigned people when personFilter=unassigned', () => {
    const query: RosterEntriesQuery = { isLoading: false, isError: false, data: entries, refetch: vi.fn() };
    renderSection(query, '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('Showing unassigned people only.')).toBeInTheDocument();
    expect(screen.getByText('Bob')).toBeInTheDocument();
    expect(screen.queryByText('Alice')).not.toBeInTheDocument();
  });

  it('shows filtered empty state and allows clearing the filter', async () => {
    const query: RosterEntriesQuery = {
      isLoading: false,
      isError: false,
      data: [
        {
          id: 3,
          name: 'Chris',
          tags: [],
          cluster_count: 1,
          updated_at: new Date().toISOString(),
        },
      ],
      refetch: vi.fn(),
    };

    renderSection(query, '/?tab=entries&personFilter=unassigned');

    expect(screen.getByText('No unassigned people found.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Clear filter' }));

    expect(screen.queryByText('No unassigned people found.')).not.toBeInTheDocument();
    expect(screen.getByText('Chris')).toBeInTheDocument();
  });
});
