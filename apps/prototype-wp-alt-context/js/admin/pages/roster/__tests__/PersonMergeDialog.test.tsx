import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../../api/personMergeApi';
import type { RosterEntry } from '../../../api/rosterApi';
import { RosterEntriesSection } from '../RosterEntriesSection';

vi.mock('../../../api/personMergeApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../../api/personMergeApi')>(),
  previewPersonMerge: vi.fn(), commitPersonMerge: vi.fn(), undoPersonMerge: vi.fn(),
}));
vi.mock('../../../hooks/useRosterHooks', () => ({
  useUpdatePerson: () => ({ mutate: vi.fn() }), useDeletePerson: () => ({ mutate: vi.fn() }), useCreatePerson: () => ({ mutate: vi.fn() }),
}));
vi.mock('../IdentityThumbnail', () => ({ IdentityThumbnail: () => null }));
const entry = (id: number, name: string): RosterEntry => ({
  id, name, person_uuid: `person-${id}`, tags: [], cluster_count: 0, clusters: [], queue_memberships: [],
  updated_at: '', source_version: 1, projection_status: 'current', projection_refreshed_at: null,
});
const preview = { survivor: { id: 1, name: 'Server Alice', cluster_count: 8 }, loser: { id: 2, name: 'Server Ally', cluster_count: 5 }, tags: ['server tag'], conflicts: [] };
const setup = () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><RosterEntriesSection query={{ data: [entry(1, 'Alice'), entry(2, 'Ally')], isLoading: false, isError: false, refetch: vi.fn() }} /></MemoryRouter></QueryClientProvider>);
  return userEvent.setup();
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.previewPersonMerge).mockResolvedValue(preview);
  vi.mocked(api.commitPersonMerge).mockResolvedValue({ survivor_id: 1, merged_cluster_ids: ['c'], undo_token: 'token' });
  vi.mocked(api.undoPersonMerge).mockResolvedValue({ restored_person_id: 2, restored_cluster_ids: ['c'] });
});
describe('person merge flow', () => {
  it('opens from a row, previews server values, commits chosen IDs and undoes', async () => {
    const user = setup();
    await user.click(screen.getByRole('button', { name: 'Merge Ally into another person' }));
    await user.selectOptions(screen.getByLabelText('Person to keep'), '1');
    expect(screen.queryByRole('button', { name: 'Merge' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Preview merge' }));
    expect(await screen.findByText('Server Ally will be removed; its 5 face groups move to Server Alice. You can undo.')).toBeInTheDocument();
    expect(screen.getByText('Tags: server tag')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Merge' }));
    await screen.findByText('Merged Server Ally into Server Alice.');
    expect(vi.mocked(api.commitPersonMerge).mock.calls[0][0]).toEqual({ survivor_id: 1, loser_id: 2 });
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText('Person restored.');
    expect(vi.mocked(api.undoPersonMerge).mock.calls[0][0]).toBe('token');
  });
  it.each([400, 409])('renders the server error for status %s', async status => {
    vi.mocked(api.previewPersonMerge).mockRejectedValue(Object.assign(new Error('Person changed on server'), { status }));
    const user = setup();
    await user.click(screen.getByRole('button', { name: 'Merge Ally into another person' }));
    await user.selectOptions(screen.getByLabelText('Person to keep'), '1');
    await user.click(screen.getByRole('button', { name: 'Preview merge' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Person changed on server');
    if (status === 409) expect(screen.getByRole('alert')).toHaveTextContent('Merge conflict');
  });
  it('closes through controlled cancel and can reopen the same row', async () => {
    const user = setup();
    await user.click(screen.getByRole('button', { name: 'Merge Ally into another person' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Merge Ally into another person' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
