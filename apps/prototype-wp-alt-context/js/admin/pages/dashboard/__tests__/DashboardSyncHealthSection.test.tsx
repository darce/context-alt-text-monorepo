import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DashboardSyncHealthSection } from '../DashboardSyncHealthSection';

const baseProps = {
  isLoading: false,
  isError: false,
  syncStatus: { last_snapshot_version: 12 },
  localClusterCount: 0,
  showMirrorDivergenceBanner: false,
  pendingReplayCount: 0,
  conflictCount: 0,
  failedReplayCount: 0,
  topologyPending: 0,
  topologyFailed: 0,
  topologyConflicts: 0,
  lastConflictDate: null,
  lastFailureDate: null,
  resetPending: false,
  onResetMirror: () => undefined,
};

describe('DashboardSyncHealthSection', () => {
  it('shows offline copy when effective health is offline despite legacy healthy status', () => {
    render(
      <DashboardSyncHealthSection
        {...baseProps}
        effectiveSyncHealth="offline"
        syncHealthEnvelope={{
          breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
          outbox: { pending: 0, failed: 0 },
          conflicts: { open: 0 },
          replays: { failed: null, source: 'unavailable_local' },
          last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
          warnings: [],
        }}
      />,
    );

    expect(screen.getByText('The recognition backend is currently unreachable.')).toBeInTheDocument();
    expect(screen.queryByText('Machine sync is healthy and local changes are caught up.')).not.toBeInTheDocument();
  });

  it('shows warning copy when the envelope reports warnings on an otherwise healthy effective state', () => {
    render(
      <DashboardSyncHealthSection
        {...baseProps}
        effectiveSyncHealth="healthy"
        syncHealthEnvelope={{
          breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
          outbox: { pending: 0, failed: 0 },
          conflicts: { open: 0 },
          replays: { failed: null, source: 'unavailable_local' },
          last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
          warnings: [
            {
              code: 'open_conflicts_high',
              message: 'Too many conflicts',
              count: 9,
              threshold: 5,
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/warning threshold/i)).toBeInTheDocument();
    expect(screen.queryByText('Machine sync is healthy and local changes are caught up.')).not.toBeInTheDocument();
  });
});
