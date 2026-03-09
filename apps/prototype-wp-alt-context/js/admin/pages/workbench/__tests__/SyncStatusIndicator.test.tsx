import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import type { UseQueryResult } from '@tanstack/react-query';
import type { UseMutationResult } from '@tanstack/react-query';
import type { SyncStatusResponse, SyncTriggerResponse } from '../../../api/recognition';

const mockReturn = {
  data: null as SyncStatusResponse | null | undefined,
  isLoading: false,
  isError: false,
};

const mutateSpy = vi.fn();

const mockTrigger = {
  isPending: false,
  isSuccess: false,
  isError: false,
  data: null as SyncTriggerResponse | null | undefined,
  mutate: mutateSpy,
} as unknown as UseMutationResult<SyncTriggerResponse, Error, void, unknown>;

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]): string => {
    let result = text;
    for (const value of values) {
      result = result.replace(/%[sd]/, String(value));
    }
    return result;
  },
}));

vi.mock('../../../hooks/useSyncStatus', () => ({
  useSyncStatus: () => mockReturn as unknown as UseQueryResult<SyncStatusResponse>,
}));

vi.mock('../../../hooks/useSyncTrigger', () => ({
  useSyncTrigger: () => mockTrigger,
}));

// Static import AFTER vi.mock hoisting
import { SyncStatusIndicator } from '../SyncStatusIndicator';

describe('SyncStatusIndicator', () => {
  beforeEach(() => {
    mockReturn.data = null;
    mockReturn.isLoading = false;
    mockReturn.isError = false;
    mutateSpy.mockClear();
    (mockTrigger as Record<string, unknown>).isPending = false;
    (mockTrigger as Record<string, unknown>).isSuccess = false;
    (mockTrigger as Record<string, unknown>).isError = false;
    (mockTrigger as Record<string, unknown>).data = null;
  });

  it('renders stale status badge when is_stale is true', () => {
    mockReturn.data = { last_snapshot_version: 2, last_synced_at: '2026-02-14 00:00:00', is_stale: true };

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument();
  });

  it('renders fresh badge when is_stale is false', () => {
    mockReturn.data = { last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00', is_stale: false };

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Fresh')).toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
  });

  it('returns null when loading', () => {
    mockReturn.isLoading = true;

    const { container } = render(<SyncStatusIndicator />);
    expect(container.firstChild).toBeNull();
  });

  it('renders unavailable message when error occurs', () => {
    mockReturn.isError = true;

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Sync status unavailable')).toBeInTheDocument();
  });

  it('renders unavailable message when data is null', () => {
    render(<SyncStatusIndicator />);

    expect(screen.getByText('Sync status unavailable')).toBeInTheDocument();
  });

  it('renders syncing state when trigger is pending', () => {
    mockReturn.data = { last_snapshot_version: 0, last_synced_at: null, is_stale: true };
    (mockTrigger as Record<string, unknown>).isPending = true;

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Syncing…')).toBeInTheDocument();
    expect(screen.getByText('In Progress')).toBeInTheDocument();
  });

  it('renders success state after sync completes', () => {
    mockReturn.data = { last_snapshot_version: 1, last_synced_at: '2026-02-18 10:00:00', is_stale: false };
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = {
      synced: true,
      reason: 'ok',
      last_snapshot_version: 1,
      last_synced_at: '2026-02-18 10:00:00',
      is_stale: false,
    };

    render(<SyncStatusIndicator />);

    expect(screen.getByText(/Sync completed/)).toBeInTheDocument();
    expect(screen.getByText('Fresh')).toBeInTheDocument();
  });

  it('renders waiting-for-service state when sync was attempted but failed', () => {
    mockReturn.data = { last_snapshot_version: 0, last_synced_at: null, is_stale: true };
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = {
      synced: false,
      reason: 'sync_failed',
      last_snapshot_version: 0,
      last_synced_at: null,
      is_stale: true,
    };

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Waiting for service…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('renders waiting-for-service state on trigger error', () => {
    mockReturn.data = { last_snapshot_version: 0, last_synced_at: null, is_stale: true };
    (mockTrigger as Record<string, unknown>).isError = true;

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Waiting for service…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('calls mutate when retry is clicked', () => {
    mockReturn.data = { last_snapshot_version: 0, last_synced_at: null, is_stale: true };
    (mockTrigger as Record<string, unknown>).isError = true;

    render(<SyncStatusIndicator />);

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(mutateSpy).toHaveBeenCalledTimes(1);
  });

  it('calls mutate when sync now is clicked in stale idle state', () => {
    mockReturn.data = { last_snapshot_version: 2, last_synced_at: '2026-02-14 00:00:00', is_stale: true };

    render(<SyncStatusIndicator />);

    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(mutateSpy).toHaveBeenCalledTimes(1);
  });

  it('does not stay in waiting-for-service when stale flag clears', () => {
    mockReturn.data = { last_snapshot_version: 2, last_synced_at: '2026-02-19 13:00:00', is_stale: false };
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = {
      synced: false,
      reason: 'sync_failed',
      last_snapshot_version: 2,
      last_synced_at: '2026-02-19 13:00:00',
      is_stale: false,
    };

    render(<SyncStatusIndicator />);

    expect(screen.queryByText('Waiting for service…')).not.toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
  });

  it('renders connected-no-clusters state on no_remote_data reason', () => {
    mockReturn.data = { last_snapshot_version: 0, last_synced_at: null, is_stale: true };
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = {
      synced: true,
      reason: 'no_remote_data',
      last_snapshot_version: 0,
      last_synced_at: null,
      is_stale: true,
    };

    render(<SyncStatusIndicator />);

    expect(screen.getByText(/Service connected/)).toBeInTheDocument();
    expect(screen.getByText(/no clusters yet/)).toBeInTheDocument();
    expect(screen.queryByText('Waiting for service…')).not.toBeInTheDocument();
  });

  it('renders curation replay counters and timestamps when available', () => {
    mockReturn.data = {
      last_snapshot_version: 8,
      last_synced_at: '2026-03-07 02:00:00',
      is_stale: false,
      pending_curation_operations: 3,
      conflict_count: 1,
      last_curation_acknowledged_at: '2026-03-07T02:05:00Z',
      last_curation_conflict_at: '2026-03-07T02:15:00Z',
    };

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Pending curation: 3')).toBeInTheDocument();
    expect(screen.getByText('Conflicts: 1')).toBeInTheDocument();
    expect(screen.getByText(/Last curation acknowledgement:/)).toBeInTheDocument();
    expect(screen.getByText(/Last curation conflict:/)).toBeInTheDocument();
  });

  it('renders projecting sync progress ahead of the generic stale indicator', () => {
    mockReturn.data = { last_snapshot_version: 4, last_synced_at: '2026-03-08 10:00:00', is_stale: true };

    render(<SyncStatusIndicator pipelinePhase="projecting" projectionState="syncing" />);

    expect(screen.getByText('Syncing results…')).toBeInTheDocument();
    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
  });

  it('renders projection retry state with the provided error message', () => {
    const retryProjection = vi.fn();
    mockReturn.data = { last_snapshot_version: 4, last_synced_at: '2026-03-08 10:00:00', is_stale: true };

    render(
      <SyncStatusIndicator
        pipelinePhase="projecting"
        projectionState="error"
        projectionError="Waiting for service…"
        onRetryProjection={retryProjection}
      />,
    );

    expect(screen.getByText('Waiting for service…')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry sync' }));
    expect(retryProjection).toHaveBeenCalledTimes(1);
  });
});
