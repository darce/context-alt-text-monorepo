export type SyncHealth = 'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline';

/**
 * Wire vocabulary for last_sync_result [sr-007].
 * Mirrored by PHP SyncStateRepository::SYNC_RESULT_* and
 * TenantLocalRekeyService::RESYNC_REQUIRED_RESULT.
 */
export const LAST_SYNC_RESULT = {
  OK: 'ok',
  FAILED: 'failed',
  UNREACHABLE: 'unreachable',
  RESYNC_REQUIRED: 'resync_required',
} as const;

export type LastSyncResult = (typeof LAST_SYNC_RESULT)[keyof typeof LAST_SYNC_RESULT];

/** Frozen wire vocabulary for the per-tenant reclaimer sync status. */
export const RECLAIMER_VOCABULARY = {
  state: {
    NEVER_RUN: 'never_run',
    HEALTHY: 'healthy',
    OVERDUE: 'overdue',
    BREACH: 'breach',
  },
  scheduler_mode: {
    ACTION_SCHEDULER: 'action_scheduler',
    WP_CRON: 'wp_cron',
  },
  last_outcome: {
    SUCCESS: 'success',
    FAILED: 'failed',
    LOCK_CONTENDED: 'lock_contended',
  },
} as const;

export type ReclaimerState = (typeof RECLAIMER_VOCABULARY.state)[keyof typeof RECLAIMER_VOCABULARY.state];
export type ReclaimerSchedulerMode =
  (typeof RECLAIMER_VOCABULARY.scheduler_mode)[keyof typeof RECLAIMER_VOCABULARY.scheduler_mode];
export type ReclaimerLastOutcome =
  (typeof RECLAIMER_VOCABULARY.last_outcome)[keyof typeof RECLAIMER_VOCABULARY.last_outcome];

export interface ReclaimerStatus {
  state: ReclaimerState;
  scheduler_mode: ReclaimerSchedulerMode;
  effective_period_seconds: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_outcome: ReclaimerLastOutcome | null;
  last_purged_count: number | null;
  backlog_remaining: number | null;
  backlog_oldest_age_seconds: number | null;
  batch_cap_reached: boolean;
}

export interface TopologyCommandStatus {
  pending: number;
  applied: number;
  failed: number;
  conflict: number;
  last_reconciled_at: string | null;
}

export interface SyncStatusResponse {
  last_snapshot_version: number;
  last_synced_at: string | null;
  is_stale: boolean;
  sync_health: SyncHealth;
  last_sync_result: LastSyncResult;
  sync_mode?: 'delta' | 'full';
  pending_curation_operations?: number;
  failed_curation_operations?: number;
  conflict_count?: number;
  last_curation_acknowledged_at?: string | null;
  last_curation_conflict_at?: string | null;
  last_curation_failed_at?: string | null;
  topology_commands?: TopologyCommandStatus;
  reclaimer?: ReclaimerStatus | null;
}

export interface SyncTriggerResponse extends SyncStatusResponse {
  synced: boolean;
  reason: 'ok' | 'sync_failed' | 'sync_unavailable' | 'no_remote_data';
  error?: string | null;
}

export type BreakerState = 'open' | 'closed';

export interface SyncHealthWarning {
  code: string;
  message: string;
  count: number | null;
  threshold: number | null;
}

export type SyncHealthOutbox =
  | {
      state: 'ok';
      pending: number;
      failed: number;
      dead_lettered: number;
      oldest_age_seconds: number;
    }
  | {
      state: 'degraded';
      pending: null;
      failed: null;
      dead_lettered: null;
      oldest_age_seconds: null;
      warnings: SyncHealthWarning[];
    };

export interface SyncHealthResponse {
  breaker: {
    state: BreakerState;
    base_url: string;
    opened_at: string | null;
  };
  outbox: SyncHealthOutbox;
  conflicts: {
    open: number;
  };
  replays: {
    failed: number | null;
    source: string;
  };
  last_pull: {
    at: string | null;
    ok: boolean;
  };
  warnings: SyncHealthWarning[];
}
