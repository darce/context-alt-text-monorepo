import React from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as api from '../../../api/personMergeApi';
import type { RosterEntry } from '../../../api/rosterApi';
import { PersonMergeFlow, UNDO_BANNER_TTL_MS } from '../RosterEntriesSection';

vi.mock('../../../api/personMergeApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/personMergeApi')>()),
  previewPersonMerge: vi.fn(),
  commitPersonMerge: vi.fn(),
  undoPersonMerge: vi.fn(),
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
        type="button"
        onClick={() =>
          merge.commit.mutate(
            { survivor_id: 1, loser_id: 2 },
            {
              onSuccess: () => {
                onMerged({ loser: { id: 2, name: 'Ally' }, survivor: { id: 1, name: 'Alice' } });
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

const entry = (id: number, name: string): RosterEntry => ({
  id,
  name,
  person_uuid: `person-${id}`,
  tags: [],
  cluster_count: 0,
  clusters: [],
  queue_memberships: [],
  updated_at: '',
  source_version: 1,
  projection_status: 'current',
  projection_refreshed_at: null,
});

const docs = (path: string): string => readFileSync(resolve(process.cwd(), path), 'utf8');

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(api.previewPersonMerge).mockResolvedValue({
    survivor: { id: 1, name: 'Alice', cluster_count: 8 },
    loser: { id: 2, name: 'Ally', cluster_count: 5 },
    tags: [],
    conflicts: [],
  });
  vi.mocked(api.commitPersonMerge).mockResolvedValue({
    survivor_id: 1,
    merged_cluster_ids: ['c'],
    undo_token: 'server-token',
  });
  vi.mocked(api.undoPersonMerge).mockResolvedValue({ restored_person_id: 2, restored_cluster_ids: ['c'] });
});

afterEach(() => vi.useRealTimers());

describe('GPUFLOW-1 deferred review regressions', () => {
  it('keeps stale-image closure open until image digests and the disk precondition are evidenced', () => {
    const report = docs('docs/assessments/GPUFLOW-1-rebaseline-20260914.md');

    expect(report).toMatch(/\| 0 — pre-promotion stale API image[^\n]*\*\*unverified[^\n]*do not close/i);
    expect(report).toContain('dev and staging image digests');
    expect(report).toContain('VM disk usage below the 70% promotion precondition');
  });

  it('documents authenticated GPU and exact naming-agreement parity probes', () => {
    const plan = docs('docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md');

    expect(plan).toContain('X-Api-Key');
    expect(plan).toContain('X-Tenant-ID');
    expect(plan).toContain('/scene/gpu/status');
    expect(plan).toContain('/recognition/tenant/naming-agreement');
    expect(plan).toMatch(/WordPress application password[^\n]*not a credential for the service/i);
  });

  it('retains the undo token after the banner closes and keeps a recovery action available', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const onDismiss = vi.fn();
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <QueryClientProvider client={client}>
        <PersonMergeFlow
          loser={entry(2, 'Ally')}
          entries={[entry(1, 'Alice'), entry(2, 'Ally')]}
          onDismiss={onDismiss}
        />
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole('button', { name: 'Complete merge' }));
    await screen.findByText('Merged Ally into Alice.');
    await act(() => vi.advanceTimersByTimeAsync(UNDO_BANNER_TTL_MS));

    expect(screen.queryByText('Merged Ally into Alice.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Undo recent merge' })).toBeInTheDocument();
    const storedUndoToken = localStorage.getItem('acx:person-merge-undo:2');
    expect(storedUndoToken).toContain('server-token');
    const storedExpiry = storedUndoToken === null ? 0 : JSON.parse(storedUndoToken).expiresAt;
    const remainingValidityMs = storedExpiry - Date.now();
    expect(remainingValidityMs).toBeGreaterThan(23 * 60 * 60 * 1000);
    expect(remainingValidityMs).toBeLessThanOrEqual(24 * 60 * 60 * 1000);

    await user.click(screen.getByRole('button', { name: 'Undo recent merge' }));
    await user.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(api.undoPersonMerge).toHaveBeenCalledWith('server-token'));
  });

  it('assigns the D1 timer and token store to the roster flow and its regression proof', () => {
    const plan = docs('docs/tasks/v0.5.0/GPUFLOW-1-description-service-flow-and-identity-fixes-task-plan.md');
    const d1 = plan.slice(plan.indexOf('### Deferred slice D1:'), plan.indexOf('### Deferred slice D2:'));

    expect(d1).toContain('RosterEntriesSection.tsx');
    expect(d1).toContain('usePersonMerge.ts');
    expect(d1).toContain('dw2-gpuflow1re-1.test.tsx');
    expect(d1).toContain('24-hour');
    expect(plan).toContain('`spa-roster-undo` (deferred; not dispatched)');
  });
});
