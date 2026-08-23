import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query';
import type { RetentionStatusResponse, SyncStatusResponse, SyncTriggerResponse } from '../../../api/recognition';
import { createMockQuery } from '../../../test-utils/mockHooks';
import { SYNC_VOCABULARY } from '../syncVocabulary';

const buildSyncStatus = (overrides: Partial<SyncStatusResponse> = {}): SyncStatusResponse => ({
  last_snapshot_version: 0,
  last_synced_at: null,
  is_stale: false,
  sync_health: 'healthy',
  last_sync_result: 'ok',
  ...overrides,
});

const buildSyncTriggerResponse = (overrides: Partial<SyncTriggerResponse> = {}): SyncTriggerResponse => ({
  synced: false,
  reason: 'sync_failed',
  last_snapshot_version: 0,
  last_synced_at: null,
  is_stale: true,
  sync_health: 'offline',
  last_sync_result: 'unreachable',
  ...overrides,
});

const mockReturn = {
  data: null as SyncStatusResponse | null | undefined,
  isLoading: false,
  isError: false,
};

const syncHealthMock = {
  data: undefined as import('../../../api/recognition/types/sync').SyncHealthResponse | undefined,
};

const retentionQueryState = {
  data: {
    available: true,
    policy: {
      retention_mode: 'dispose_after_ack',
      last_export_at: null,
      last_purge_at: null,
      retention_updated_at: null,
    },
    recent_audit_events: [],
  } as RetentionStatusResponse | null | undefined,
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
      result = result.replace(/%(?:[0-9]+\$)?[sd]/, String(value));
    }
    return result;
  },
}));

vi.mock('../../../hooks/useSyncStatus', () => ({
  useSyncStatus: () => mockReturn as unknown as UseQueryResult<SyncStatusResponse>,
}));

vi.mock('../../../hooks/useSyncHealth', () => ({
  useSyncHealth: () =>
    createMockQuery({
      data: syncHealthMock.data,
    }),
}));

vi.mock('../../../hooks/useSyncTrigger', () => ({
  useSyncTrigger: () => mockTrigger,
}));

vi.mock('../../../hooks/useRetentionStatus', () => ({
  useRetentionStatus: () =>
    createMockQuery({
      data: retentionQueryState.data,
    }),
}));

import { SyncStatusIndicator } from '../SyncStatusIndicator';

describe('SyncStatusIndicator', () => {
  beforeEach(() => {
    mockReturn.data = null;
    mockReturn.isLoading = false;
    mockReturn.isError = false;
    syncHealthMock.data = undefined;
    retentionQueryState.data = {
      available: true,
      policy: {
        retention_mode: 'dispose_after_ack',
        last_export_at: null,
        last_purge_at: null,
        retention_updated_at: null,
      },
      recent_audit_events: [],
    };
    mutateSpy.mockClear();
    (mockTrigger as Record<string, unknown>).isPending = false;
    (mockTrigger as Record<string, unknown>).isSuccess = false;
    (mockTrigger as Record<string, unknown>).isError = false;
    (mockTrigger as Record<string, unknown>).data = null;
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

  it('renders stale status badge when sync health is stale', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 2,
      last_synced_at: '2026-02-14 00:00:00',
      is_stale: true,
      sync_health: 'stale',
    });

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument();
  });

  it('renders fresh badge when sync health is healthy', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00' });

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Fresh')).toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
  });

  it('pairs badge ok/attention color with a glyph second channel', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00' });
    const { container, rerender } = render(<SyncStatusIndicator />);

    const okBadge = container.querySelector('.acx-sync-status__badge--ok');
    expect(okBadge).toBeTruthy();
    expect(okBadge).toHaveAttribute('data-badge-state', 'ok');
    expect(okBadge?.querySelector('.acx-sync-status__badge-mark')?.textContent).toBe('✓');
    expect(screen.getByText('Fresh')).toBeInTheDocument();

    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 2,
      last_synced_at: '2026-02-14 00:00:00',
      is_stale: true,
      sync_health: 'stale',
    });
    rerender(<SyncStatusIndicator />);

    const attentionBadge = container.querySelector('.acx-sync-status__badge:not(.acx-sync-status__badge--ok)');
    expect(attentionBadge).toBeTruthy();
    expect(attentionBadge).toHaveAttribute('data-badge-state', 'attention');
    expect(attentionBadge?.querySelector('.acx-sync-status__badge-mark')?.textContent).toBe('!');
    expect(screen.getByText('Stale')).toBeInTheDocument();
  });

  it('shows a retention badge link when the mode is not retain_all', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00' });

    render(<SyncStatusIndicator />);

    expect(screen.getByRole('link', { name: 'Data Retention: Dispose after confirm' })).toHaveAttribute(
      'href',
      '#/retention',
    );
  });

  it('does not render the internal sync-mode badge (delta/full are payload-only)', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 5,
      last_synced_at: '2026-02-14 12:00:00',
      sync_mode: 'delta',
    });

    render(<SyncStatusIndicator />);

    expect(screen.queryByText('Delta sync')).not.toBeInTheDocument();
    expect(screen.queryByText('Full sync')).not.toBeInTheDocument();
  });

  it('renders pending-work counts without banned ops dialect when topology and delta mode are present', () => {
    mockReturn.data = buildSyncStatus({
      sync_health: 'queued',
      sync_mode: 'delta',
      topology_commands: {
        pending: 2,
        applied: 1,
        failed: 1,
        conflict: 1,
        last_reconciled_at: null,
      },
    });

    const { container } = render(<SyncStatusIndicator />);
    const text = container.textContent ?? '';

    expect(text).not.toMatch(/Delta sync|Machine sync|Machine state|Sync backlog/i);
    expect(screen.getByText('2 waiting, 1 synced, 1 failed, 1 need review')).toBeInTheDocument();
    expect(screen.getByText('Waiting to sync')).toBeInTheDocument();
  });

  it('shows the purge-on-demand retention badge label when configured', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00' });
    retentionQueryState.data = {
      available: true,
      policy: {
        retention_mode: 'purge_on_demand',
        last_export_at: null,
        last_purge_at: null,
        retention_updated_at: null,
      },
      recent_audit_events: [],
    };

    render(<SyncStatusIndicator />);

    expect(screen.getByRole('link', { name: 'Data Retention: Purge on demand' })).toHaveAttribute('href', '#/retention');
  });

  it('does not show a retention badge when the policy is retain_all', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00' });
    retentionQueryState.data = {
      available: true,
      policy: {
        retention_mode: 'retain_all',
        last_export_at: null,
        last_purge_at: null,
        retention_updated_at: null,
      },
      recent_audit_events: [],
    };

    render(<SyncStatusIndicator />);

    expect(screen.queryByRole('link', { name: /Retention:/ })).not.toBeInTheDocument();
  });

  it('does not show a retention badge when retention status is unavailable', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 5, last_synced_at: '2026-02-14 12:00:00' });
    retentionQueryState.data = {
      available: false,
      policy: null,
      recent_audit_events: [],
    };

    render(<SyncStatusIndicator />);

    expect(screen.queryByRole('link', { name: /Retention:/ })).not.toBeInTheDocument();
  });

  it('renders queued state when pending replay exists without failures or conflicts', () => {
    mockReturn.data = buildSyncStatus({
      sync_health: 'queued',
      pending_curation_operations: 4,
      is_stale: false,
    });

    render(<SyncStatusIndicator />);

    expect(
      screen.getByText('Your changes are saved here and will sync when the service is available.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Waiting to sync')).toBeInTheDocument();
  });

  it('renders failures state with failed-ops affordance', () => {
    mockReturn.data = buildSyncStatus({
      sync_health: 'failures',
      failed_curation_operations: 2,
    });

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Some sync operations need attention.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Failures' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=dead-letter',
    );
    expect(screen.getByRole('link', { name: 'Failed operations: 2' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=dead-letter',
    );
  });

  /**
   * HARM-BR-04: resync escalation uses last_sync_result only — never a top-level
   * failed string[] (that key is a settings-save graft and is not produced by sync).
   */
  it('renders re-sync required from last_sync_result even when sync_health is healthy', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 3,
      last_synced_at: '2026-02-14 12:00:00',
      sync_health: 'healthy',
      last_sync_result: 'resync_required',
    });

    const { container } = render(<SyncStatusIndicator />);

    expect(
      screen.getByText('Local identity changed — a full re-sync is required before this view is current.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Re-sync required')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Local rows were re-keyed or marked for resync; run a full sync before trusting this view.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument();
    expect(container.querySelector('[data-sync-status="resync_required"]')).toBeTruthy();
  });

  it('renders offline idle state when no transient sync operation is active', () => {
    mockReturn.data = buildSyncStatus({
      sync_health: 'offline',
      is_stale: false,
      last_sync_result: 'unreachable',
    });

    const { container } = render(<SyncStatusIndicator />);

    expect(
      screen.getByText('Recognition service unreachable — showing your local copy.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(container.firstChild).toHaveClass('acx-sync-status--warning');
  });

  it('announces the offline transition through the role=status sync-status strip (§7 announce channel, Slice-8 / BR-77)', () => {
    // The §7 offline matrix routes the offline announcement through the EXISTING
    // sync-status live region — the CTAs only carry a static aria-describedby reason
    // and must not add a duplicate live region. This asserts that channel is present.
    mockReturn.data = buildSyncStatus({
      sync_health: 'offline',
      is_stale: false,
      last_sync_result: 'unreachable',
    });

    render(<SyncStatusIndicator />);

    const strip = screen.getByTestId('acx-sync-status-strip');
    expect(strip).toHaveAttribute('role', 'status');
    expect(strip).toHaveAttribute('aria-live', 'polite');
    // The offline reason is surfaced inside that one live region.
    expect(strip).toHaveTextContent('Recognition service unreachable — showing your local copy.');
    expect(strip).toHaveTextContent('Offline');
    // Exactly one status live region — no duplicate channel introduced by Slice-8.
    expect(document.querySelectorAll('[data-testid="acx-sync-status-strip"]')).toHaveLength(1);
  });

  it('overrides healthy sync-status when sync-health envelope reports offline', () => {
    mockReturn.data = buildSyncStatus({
      sync_health: 'healthy',
      is_stale: false,
      last_sync_result: 'ok',
    });
    syncHealthMock.data = {
      breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
      outbox: { pending: 0, failed: 0 },
      conflicts: { open: 0 },
      replays: { failed: null, source: 'unavailable_local' },
      last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
      warnings: [],
    };

    const { container } = render(<SyncStatusIndicator />);

    expect(
      screen.getByText('Recognition service unreachable — showing your local copy.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(container.firstChild).toHaveClass('acx-sync-status--warning');
    expect(container.querySelector('.acx-sync-status__badge--ok')).not.toBeInTheDocument();
  });

  it('keeps the Retry sync affordance enabled and firing while the breaker is open (recovery affordance)', () => {
    // triggerSync heals the breaker; gating it would trap the operator offline (plan §3, RES-15).
    mockReturn.data = buildSyncStatus({
      sync_health: 'offline',
      is_stale: false,
      last_sync_result: 'unreachable',
    });
    syncHealthMock.data = {
      breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
      outbox: { pending: 0, failed: 0 },
      conflicts: { open: 0 },
      replays: { failed: null, source: 'unavailable_local' },
      last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
      warnings: [],
    };

    render(<SyncStatusIndicator />);

    const retryButton = screen.getByRole('button', { name: 'Retry' });
    expect(retryButton).toBeEnabled();
    fireEvent.click(retryButton);
    expect(mutateSpy).toHaveBeenCalled();
  });

  it('renders syncing state when trigger is pending', () => {
    mockReturn.data = buildSyncStatus({ is_stale: true, sync_health: 'stale' });
    (mockTrigger as Record<string, unknown>).isPending = true;

    render(<SyncStatusIndicator />);

    expect(screen.getByText('Syncing…')).toBeInTheDocument();
    expect(screen.getByText('In Progress')).toBeInTheDocument();
  });

  it('renders success state after sync completes', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 1, last_synced_at: '2026-02-18 10:00:00' });
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = buildSyncTriggerResponse({
      synced: true,
      reason: 'ok',
      last_snapshot_version: 1,
      last_synced_at: '2026-02-18 10:00:00',
      is_stale: false,
      sync_health: 'healthy',
      last_sync_result: 'ok',
    });

    render(<SyncStatusIndicator />);

    expect(screen.getByText(/Sync completed/)).toBeInTheDocument();
    expect(screen.getByText('Fresh')).toBeInTheDocument();
  });

  it('renders offline recovery state when sync was attempted but failed', () => {
    mockReturn.data = buildSyncStatus({ is_stale: true, sync_health: 'offline', last_sync_result: 'unreachable' });
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = buildSyncTriggerResponse();

    render(<SyncStatusIndicator />);

    expect(
      screen.getByText('Recognition service unreachable — showing your local copy.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('renders offline recovery state on trigger error', () => {
    mockReturn.data = buildSyncStatus({ is_stale: true, sync_health: 'offline', last_sync_result: 'unreachable' });
    (mockTrigger as Record<string, unknown>).isError = true;

    render(<SyncStatusIndicator />);

    expect(
      screen.getByText('Recognition service unreachable — showing your local copy.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('calls mutate when retry is clicked', () => {
    mockReturn.data = buildSyncStatus({ is_stale: true, sync_health: 'offline', last_sync_result: 'unreachable' });
    (mockTrigger as Record<string, unknown>).isError = true;

    render(<SyncStatusIndicator />);

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(mutateSpy).toHaveBeenCalledTimes(1);
  });

  it('calls mutate when sync now is clicked in stale idle state', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 2,
      last_synced_at: '2026-02-14 00:00:00',
      is_stale: true,
      sync_health: 'stale',
    });

    render(<SyncStatusIndicator />);

    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(mutateSpy).toHaveBeenCalledTimes(1);
  });

  it('does not stay in waiting-for-service when stale flag clears', () => {
    mockReturn.data = buildSyncStatus({ last_snapshot_version: 2, last_synced_at: '2026-02-19 13:00:00' });
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = buildSyncTriggerResponse({
      synced: false,
      reason: 'sync_failed',
      last_snapshot_version: 2,
      last_synced_at: '2026-02-19 13:00:00',
      is_stale: false,
      sync_health: 'healthy',
      last_sync_result: 'ok',
    });

    render(<SyncStatusIndicator />);

    expect(screen.queryByText('Waiting for service…')).not.toBeInTheDocument();
    expect(screen.getByText(/Last sync/)).toBeInTheDocument();
  });

  it('renders connected-no-clusters state on no_remote_data reason', () => {
    mockReturn.data = buildSyncStatus({ is_stale: true, sync_health: 'stale' });
    (mockTrigger as Record<string, unknown>).isSuccess = true;
    (mockTrigger as Record<string, unknown>).data = buildSyncTriggerResponse({
      synced: true,
      reason: 'no_remote_data',
      last_snapshot_version: 0,
      last_synced_at: null,
      is_stale: true,
      sync_health: 'stale',
      last_sync_result: 'ok',
    });

    render(<SyncStatusIndicator />);

    expect(screen.getByText(/Service connected/)).toBeInTheDocument();
    expect(screen.getByText(/no clusters yet/)).toBeInTheDocument();
    expect(screen.queryByText('Waiting for service…')).not.toBeInTheDocument();
  });

  it('renders sync change counters and timestamps when available', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 8,
      last_synced_at: '2026-03-07 02:00:00',
      pending_curation_operations: 3,
      failed_curation_operations: 2,
      conflict_count: 1,
      last_curation_acknowledged_at: '2026-03-07T02:05:00Z',
      last_curation_conflict_at: '2026-03-07T02:15:00Z',
      last_curation_failed_at: '2026-03-07T02:25:00Z',
      sync_health: 'conflicts',
    });

    render(<SyncStatusIndicator activeSection="scan" />);

    expect(screen.getByText('Pending changes: 3')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Conflicts' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=conflicts',
    );
    expect(screen.getByRole('link', { name: 'Conflicts: 1' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=conflicts',
    );
    expect(screen.getByRole('link', { name: 'Failed operations: 2' })).toHaveAttribute(
      'href',
      '#/workbench?tab=scan&panel=dead-letter',
    );
    expect(screen.getByText(/Last change confirmed:/)).toBeInTheDocument();
    expect(screen.getByText(/Last conflict:/)).toBeInTheDocument();
    expect(screen.getByText(/Last failure:/)).toBeInTheDocument();
  });

  it('renders pending-work details when topology counts are present', () => {
    mockReturn.data = buildSyncStatus({
      sync_health: 'queued',
      topology_commands: {
        pending: 2,
        applied: 5,
        failed: 1,
        conflict: 3,
        last_reconciled_at: null,
      },
    });

    render(<SyncStatusIndicator />);

    expect(screen.getByText('2 waiting, 5 synced, 1 failed, 3 need review')).toBeInTheDocument();
    expect(screen.queryByText(/Sync backlog/i)).not.toBeInTheDocument();
  });

  it('renders projecting sync progress ahead of the generic stale indicator', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 4,
      last_synced_at: '2026-03-08 10:00:00',
      is_stale: true,
      sync_health: 'stale',
    });

    render(<SyncStatusIndicator pipelinePhase="projecting" projectionState="syncing" />);

    expect(screen.getByText('Syncing results…')).toBeInTheDocument();
    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument();
  });

  it('renders ready-for-review projection state before the final acknowledgement', () => {
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 4,
      last_synced_at: '2026-03-08 10:00:00',
      is_stale: true,
      sync_health: 'stale',
    });

    render(<SyncStatusIndicator pipelinePhase="projecting" projectionState="ready" />);

    expect(screen.getByText('Results ready for review.')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('renders projection retry state with the provided error message', () => {
    const retryProjection = vi.fn();
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 4,
      last_synced_at: '2026-03-08 10:00:00',
      is_stale: true,
      sync_health: 'stale',
    });

    render(
      <SyncStatusIndicator
        pipelinePhase="projecting"
        projectionState="error"
        projectionError={SYNC_VOCABULARY.resultsErrorHeadline}
        onRetryProjection={retryProjection}
      />,
    );

    expect(screen.getByText(SYNC_VOCABULARY.resultsErrorHeadline)).toBeInTheDocument();
    expect(screen.queryByText('Waiting for service…')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry sync' }));
    expect(retryProjection).toHaveBeenCalledTimes(1);
  });

  it('keeps projection retry state visible after the pipeline leaves projecting', () => {
    const retryProjection = vi.fn();
    mockReturn.data = buildSyncStatus({
      last_snapshot_version: 4,
      last_synced_at: '2026-03-08 10:00:00',
      is_stale: true,
      sync_health: 'stale',
    });

    render(
      <SyncStatusIndicator
        pipelinePhase="idle"
        projectionState="error"
        projectionError={SYNC_VOCABULARY.resultsErrorHeadline}
        onRetryProjection={retryProjection}
      />,
    );

    expect(screen.getByText(SYNC_VOCABULARY.resultsErrorHeadline)).toBeInTheDocument();
    expect(screen.queryByText('Waiting for service…')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry sync' }));
    expect(retryProjection).toHaveBeenCalledTimes(1);
  });
});
