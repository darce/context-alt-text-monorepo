import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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
  it('offers settings when sync health is unavailable', () => {
    render(
      <DashboardSyncHealthSection
        {...baseProps}
        isError
        syncStatus={null}
        effectiveSyncHealth="offline"
        syncHealthEnvelope={null}
      />,
    );

    expect(screen.getByRole('link', { name: 'Open settings' })).toHaveAttribute('href', '#/settings');
  });

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
    expect(screen.queryByText('Everything is saved and up to date.')).not.toBeInTheDocument();
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
    expect(screen.queryByText('Everything is saved and up to date.')).not.toBeInTheDocument();
  });

  it('pairs the mirror-divergence banner with a warning icon second channel', () => {
    render(
      <DashboardSyncHealthSection
        {...baseProps}
        showMirrorDivergenceBanner
        localClusterCount={3}
        failedReplayCount={2}
        effectiveSyncHealth="stale"
        syncHealthEnvelope={{
          breaker: { state: 'closed', base_url: 'http://localhost:8000', opened_at: null },
          outbox: { pending: 0, failed: 0 },
          conflicts: { open: 0 },
          replays: { failed: 2, source: 'local' },
          last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
          warnings: [],
        }}
      />,
    );

    expect(screen.getByTestId('acx-dashboard-mirror-warning-icon')).toBeInTheDocument();
    expect(screen.getByText(/Mirror is out of sync with the backend/i)).toBeInTheDocument();
    expect(screen.getByText('Mirror is out of sync with the backend — 3 stale face groups, 2 failed sync events.')).toBeInTheDocument();
  });

  it('points the dashboard action card at Review Queue, not the retired Workbench name', () => {
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
          warnings: [],
        }}
      />,
    );

    expect(screen.getByRole('link', { name: /Open Review Queue/ })).toHaveAttribute('href', '#/workbench?tab=scan');
    expect(screen.queryByRole('heading', { name: 'Open Workbench' })).not.toBeInTheDocument();
  });

  it('keeps Reset mirror enabled and firing while the breaker is open (recovery affordance)', () => {
    // resetMirror heals the breaker; gating it would trap the operator offline (plan §3, RES-15).
    const onResetMirror = vi.fn();
    render(
      <DashboardSyncHealthSection
        {...baseProps}
        showMirrorDivergenceBanner
        localClusterCount={3}
        failedReplayCount={2}
        onResetMirror={onResetMirror}
        effectiveSyncHealth="offline"
        syncHealthEnvelope={{
          breaker: { state: 'open', base_url: 'http://localhost:8000', opened_at: null },
          outbox: { pending: 0, failed: 0 },
          conflicts: { open: 0 },
          replays: { failed: 2, source: 'local' },
          last_pull: { at: '2026-06-11T12:00:00Z', ok: true },
          warnings: [],
        }}
      />,
    );

    const resetButton = screen.getByRole('button', { name: 'Reset mirror' });
    expect(resetButton).toBeEnabled();
    fireEvent.click(resetButton);
    expect(onResetMirror).toHaveBeenCalled();
  });
});
