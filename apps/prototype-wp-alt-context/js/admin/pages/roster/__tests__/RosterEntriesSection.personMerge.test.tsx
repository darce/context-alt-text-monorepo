import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PersonMergeFlow, UNDO_BANNER_TTL_MS } from '../RosterEntriesSection';
import { commitPersonMerge, undoPersonMerge } from '../../../api/personMergeApi';
import { listRosterEntries, type RosterEntry } from '../../../api/rosterApi';
import { queryKeys } from '../../../api/queryKeys';

vi.mock('../../../api/personMergeApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../../api/personMergeApi')>(),
  commitPersonMerge: vi.fn(),
  undoPersonMerge: vi.fn(),
}));
vi.mock('../../../api/rosterApi', async importOriginal => ({
  ...await importOriginal<typeof import('../../../api/rosterApi')>(),
  listRosterEntries: vi.fn(),
}));
vi.mock('../PersonMergeDialog', () => ({
  PersonMergeDialog: ({ open, merge, onMerged, onOpenChange }: {
    open: boolean;
    merge: ReturnType<typeof import('../../../hooks/usePersonMerge').usePersonMerge>;
    onMerged: (preview: unknown) => void;
    onOpenChange: (open: boolean) => void;
  }) => open ? <button onClick={() => merge.commit.mutate(
    { loser_id: 1, survivor_id: 2 },
    { onSuccess: () => {
      onMerged({ loser: { id: 1, name: 'Alice' }, survivor: { id: 2, name: 'Bob' } });
      onOpenChange(false);
    } },
  )}>Complete merge</button> : null,
}));

const loser = { id: 1, name: 'Alice' } as RosterEntry;

const setup = async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const onDismiss = vi.fn();
  render(<QueryClientProvider client={client}>
    <PersonMergeFlow loser={loser} entries={[loser]} onDismiss={onDismiss} />
  </QueryClientProvider>);
  fireEvent.click(screen.getByText('Complete merge'));
  await screen.findByRole('button', { name: 'Undo' });
  invalidate.mockClear();
  return { invalidate, onDismiss };
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(commitPersonMerge).mockResolvedValue({ survivor_id: 2, merged_cluster_ids: [], undo_token: 'token' });
});
afterEach(() => vi.useRealTimers());

describe('person merge undo recovery', () => {
  it('re-reads stored state after a lost response and a consumed-token retry', async () => {
    vi.mocked(undoPersonMerge).mockRejectedValueOnce(new Error('Network error')).mockRejectedValueOnce({ status: 409 });
    vi.mocked(listRosterEntries).mockResolvedValue([loser]);
    const { invalidate } = await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText(/Undo failed/);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText('Roster refreshed: the person is present.');
    expect(screen.queryByText(/can no longer be undone/)).not.toBeInTheDocument();
    for (const queryKey of [queryKeys.roster.all, queryKeys.clusters.all, queryKeys.media.identities()]) {
      expect(invalidate).toHaveBeenCalledWith(expect.objectContaining({ queryKey }));
    }
    expect(listRosterEntries).toHaveBeenCalledTimes(1);
    expect(undoPersonMerge).toHaveBeenCalledTimes(2);
  });

  it('keeps the existing error for a first-attempt conflict', async () => {
    vi.mocked(undoPersonMerge).mockRejectedValue({ status: 409 });
    await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText(/This merge can no longer be undone/);
    expect(listRosterEntries).not.toHaveBeenCalled();
  });

  it('keeps the banner while pending and restarts dismissal after success', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let resolveUndo: ((value: { restored_person_id: number; restored_cluster_ids: string[] }) => void) | undefined;
    vi.mocked(undoPersonMerge).mockImplementation(() => new Promise(resolve => { resolveUndo = resolve; }));
    const { onDismiss } = await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByRole('button', { name: 'Undoing…' });
    act(() => { vi.advanceTimersByTime(UNDO_BANNER_TTL_MS * 2); });
    expect(onDismiss).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Undoing…' })).toBeDisabled();
    await act(async () => { resolveUndo?.({ restored_person_id: 1, restored_cluster_ids: [] }); });
    await waitFor(() => expect(screen.getByText('Person restored.')).toBeVisible());
    act(() => { vi.advanceTimersByTime(UNDO_BANNER_TTL_MS); });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('does not dismiss a retryable undo failure', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(undoPersonMerge).mockRejectedValue(new Error('Network error'));
    const { onDismiss } = await setup();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText(/Undo failed/);
    act(() => { vi.advanceTimersByTime(UNDO_BANNER_TTL_MS * 2); });
    expect(onDismiss).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled();
  });
});
