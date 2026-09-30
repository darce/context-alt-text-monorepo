import { act, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PersonMergeFlow } from '../RosterEntriesSection';
import { commitPersonMerge, undoPersonMerge } from '../../../api/personMergeApi';
import { listRosterEntries, type RosterEntry } from '../../../api/rosterApi';

vi.mock('../../../api/personMergeApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/personMergeApi')>()),
  commitPersonMerge: vi.fn(),
  undoPersonMerge: vi.fn(),
}));
vi.mock('../../../api/rosterApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/rosterApi')>()),
  listRosterEntries: vi.fn(),
}));
vi.mock('../PersonMergeDialog', () => ({
  PersonMergeDialog: ({
    open,
    merge,
    onMerged,
    onOpenChange,
  }: {
    open: boolean;
    merge: ReturnType<typeof import('../../../hooks/usePersonMerge').usePersonMerge>;
    onMerged: (preview: unknown) => void;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <button
        onClick={() =>
          merge.commit.mutate(
            { loser_id: 1, survivor_id: 2 },
            {
              onSuccess: () => {
                onMerged({ loser: { id: 1, name: 'Alice' }, survivor: { id: 2, name: 'Bob' } });
                onOpenChange(false);
              },
            },
          )
        }
      >
        Complete merge
      </button>
    ) : null,
}));

const loser = { id: 1, name: 'Alice' } as RosterEntry;

const setup = async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onDismiss = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <PersonMergeFlow loser={loser} entries={[loser]} onDismiss={onDismiss} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByText('Complete merge'));
  await screen.findByRole('button', { name: 'Undo' });
  return { onDismiss };
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(commitPersonMerge).mockResolvedValue({ survivor_id: 2, merged_cluster_ids: [], undo_token: 'token' });
});
afterEach(() => vi.useRealTimers());

describe('roster merge undo dismissal', () => {
  it('keeps dismissal disabled during a retryable undo error and restores it after reconciliation', async () => {
    vi.mocked(undoPersonMerge).mockRejectedValueOnce(new Error('Network error')).mockRejectedValueOnce({ status: 409 });
    vi.mocked(listRosterEntries).mockResolvedValue([loser]);
    const { onDismiss } = await setup();

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText(/Undo failed/);
    expect(screen.getByRole('button', { name: 'Undo' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Dismiss merge notification' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss merge notification' }));
    expect(onDismiss).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    });
    await screen.findByText('Roster refreshed: the person is present.');
    expect(screen.getByRole('button', { name: 'Dismiss merge notification' })).toBeEnabled();
  });

  it('keeps dismissal available after a roster check failure', async () => {
    vi.mocked(undoPersonMerge).mockRejectedValueOnce(new Error('Network error')).mockRejectedValueOnce({ status: 409 });
    vi.mocked(listRosterEntries).mockRejectedValueOnce(new Error('Roster unavailable'));
    const { onDismiss } = await setup();

    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await screen.findByText(/Undo failed/);
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    });
    await screen.findByText('Unable to refresh the roster to confirm the undo outcome. Try checking again.');
    expect(screen.getByRole('button', { name: 'Dismiss merge notification' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss merge notification' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
