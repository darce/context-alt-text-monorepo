import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import type { RosterEntry } from '../../../api/rosterApi';
import { RosterEntriesTable } from '../RosterEntriesTable';
import { RosterEntriesSection } from '../RosterEntriesSection';

vi.mock('../../../hooks/useRosterHooks', () => ({
  useUpdatePerson: () => ({ mutate: vi.fn(), isPending: false }),
  useDeletePerson: () => ({ mutate: vi.fn(), isPending: false }),
  useCreatePerson: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('../IdentityThumbnail', () => ({
  IdentityThumbnail: () => <span data-testid="directory-face" />,
}));

const entry: RosterEntry = {
  id: 42,
  person_uuid: 'person-alice',
  name: 'Alice Anderson',
  tags: [],
  cluster_count: 3,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-01-01T00:00:00Z',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: '2026-01-01T00:00:00Z',
};

const Location = () => <output data-testid="location">{useLocation().search}</output>;

describe('roster workspace navigation', () => {
  it('opens from the name, avatar and count while only the pencil edits', async () => {
    const user = userEvent.setup();
    const open = vi.fn();
    render(<RosterEntriesTable entries={[entry]} onOpenPerson={open} />);
    const person = screen.getByRole('button', { name: entry.name });
    expect(person).toHaveAttribute('type', 'button');
    await user.click(within(person).getByText(entry.name));
    await user.click(within(person).getByTestId('directory-face'));
    await user.click(screen.getByRole('button', { name: 'Open 3 face groups for Alice Anderson' }));
    expect(open).toHaveBeenCalledTimes(3);
    expect(open).toHaveBeenLastCalledWith(entry);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Edit person' }));
    expect(screen.getByRole('textbox', { name: 'Person name' })).toHaveValue(entry.name);
    expect(open).toHaveBeenCalledTimes(3);
  });

  it.each(['{Enter}', ' '])('supports keyboard activation with %s', async (key) => {
    const user = userEvent.setup();
    const open = vi.fn();
    render(<RosterEntriesTable entries={[entry]} onOpenPerson={open} />);
    await user.tab();
    expect(screen.getByRole('button', { name: entry.name })).toHaveFocus();
    await user.keyboard(key);
    await user.tab();
    await user.keyboard(key);
    expect(open).toHaveBeenCalledTimes(2);
  });

  it('provides a name for unnamed people', () => {
    render(<RosterEntriesTable entries={[{ ...entry, name: ' ' }]} onOpenPerson={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Unnamed person' })).toBeInTheDocument();
  });

  it('writes the person UUID and clears stale workspace context', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/?s=Alice&tab=entries&face=old&cluster=old']}>
        <RosterEntriesSection query={{ data: [entry], isLoading: false, isError: false, refetch: vi.fn() }} />
        <Location />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: entry.name }));
    const params = new URLSearchParams(screen.getByTestId('location').textContent ?? '');
    expect(params.get('person')).toBe(entry.person_uuid);
    expect(params.get('s')).toBe('Alice');
    for (const key of ['tab', 'face', 'cluster']) expect(params.has(key)).toBe(false);
  });

  it('preserves the queue filter when opening a person', async () => {
    const user = userEvent.setup();
    const queuedEntry: RosterEntry = { ...entry, queue_memberships: ['hard-examples'] };
    render(
      <MemoryRouter initialEntries={['/?queue=hard-examples&face=old']}>
        <RosterEntriesSection query={{ data: [queuedEntry], isLoading: false, isError: false, refetch: vi.fn() }} />
        <Location />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole('button', { name: entry.name }));
    const params = new URLSearchParams(screen.getByTestId('location').textContent ?? '');
    expect(params.get('person')).toBe(entry.person_uuid);
    expect(params.get('queue')).toBe('hard-examples');
    expect(params.has('face')).toBe(false);
  });

  it('renders a non-actionable label and count when the entry has no resolvable person uuid', async () => {
    const user = userEvent.setup();
    const open = vi.fn();
    const unresolved: RosterEntry = { ...entry, person_uuid: null as unknown as string };
    render(<RosterEntriesTable entries={[unresolved]} onOpenPerson={open} />);
    expect(screen.queryByRole('button', { name: entry.name })).not.toBeInTheDocument();
    expect(screen.getByText(entry.name)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open 3 face groups for Alice Anderson' })).not.toBeInTheDocument();
    const count = screen.getByText('3');
    expect(count.closest('button, [role="button"]')).toBeNull();
    await user.click(screen.getByText(entry.name));
    await user.click(count);
    expect(open).not.toHaveBeenCalled();
  });
});
