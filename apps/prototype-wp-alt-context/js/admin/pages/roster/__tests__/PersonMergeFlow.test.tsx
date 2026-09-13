import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../../api/personMergeApi';
import type { RosterEntry } from '../../../api/rosterApi';
import { PersonMergeFlow, UNDO_BANNER_TTL_MS } from '../RosterEntriesSection';

vi.mock('../../../api/personMergeApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../../api/personMergeApi')>(),
  previewPersonMerge: vi.fn(), commitPersonMerge: vi.fn(), undoPersonMerge: vi.fn(),
}));

const entry = (id: number, name: string): RosterEntry => ({
  id, name, person_uuid: `person-${id}`, tags: [], cluster_count: 0, clusters: [], queue_memberships: [],
  updated_at: '', source_version: 1, projection_status: 'current', projection_refreshed_at: null,
});

const preview = { survivor: { id: 1, name: 'Alice', cluster_count: 8 }, loser: { id: 2, name: 'Ally', cluster_count: 5 }, tags: [], conflicts: [] };

const setup = (onDismiss: () => void) => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PersonMergeFlow loser={entry(2, 'Ally')} entries={[entry(1, 'Alice'), entry(2, 'Ally')]} onDismiss={onDismiss} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.previewPersonMerge).mockResolvedValue(preview);
  vi.mocked(api.commitPersonMerge).mockResolvedValue({ survivor_id: 1, merged_cluster_ids: ['c'], undo_token: 'token' });
  vi.mocked(api.undoPersonMerge).mockResolvedValue({ restored_person_id: 2, restored_cluster_ids: ['c'] });
});

describe('PersonMergeFlow session cleanup (IDCHIP-1-MUI-R-05)', () => {
  it('removes the session when closed without a completed merge', async () => {
    const onDismiss = vi.fn();
    const user = setup(onDismiss);
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(onDismiss).toHaveBeenCalledTimes(1));
  });

  it('does not remove the session when the dialog auto-closes after a successful merge', async () => {
    const onDismiss = vi.fn();
    const user = setup(onDismiss);
    await user.selectOptions(screen.getByLabelText('Person to keep'), '1');
    await user.click(screen.getByRole('button', { name: 'Preview merge' }));
    await screen.findByText('Ally will be removed; its 5 face groups move to Alice. You can undo.');
    await user.click(screen.getByRole('button', { name: 'Merge' }));
    await screen.findByText('Merged Ally into Alice.');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(onDismiss).not.toHaveBeenCalled();
  });
});

describe('PersonMergeFlow undo banner expiry (IDCHIP-1-MUI-R-04)', () => {
  afterEach(() => vi.useRealTimers());

  it.each([false, true])('keeps the original expiry across callback changes (unmount: %s)', async unmountBeforeExpiry => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onDismiss = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const view = (dismiss: () => void) => (
      <QueryClientProvider client={client}>
        <PersonMergeFlow loser={entry(2, 'Ally')} entries={[entry(1, 'Alice'), entry(2, 'Ally')]} onDismiss={dismiss} />
      </QueryClientProvider>
    );
    const { rerender, unmount } = render(view(onDismiss));
    await user.selectOptions(screen.getByLabelText('Person to keep'), '1');
    await user.click(screen.getByRole('button', { name: 'Preview merge' }));
    await screen.findByText('Ally will be removed; its 5 face groups move to Alice. You can undo.');
    await user.click(screen.getByRole('button', { name: 'Merge' }));
    await screen.findByText('Merged Ally into Alice.');
    expect(onDismiss).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    const latestDismiss = vi.fn();
    rerender(view(latestDismiss));
    if (unmountBeforeExpiry) unmount();
    await act(() => vi.advanceTimersByTimeAsync(UNDO_BANNER_TTL_MS - 20_000 + 1_000));
    expect(onDismiss).not.toHaveBeenCalled();
    expect(latestDismiss).toHaveBeenCalledTimes(unmountBeforeExpiry ? 0 : 1);
    await act(() => vi.advanceTimersByTimeAsync(UNDO_BANNER_TTL_MS));
    expect(latestDismiss).toHaveBeenCalledTimes(unmountBeforeExpiry ? 0 : 1);
  });
});
