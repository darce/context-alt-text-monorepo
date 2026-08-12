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
  count: number;
  threshold: number;
}

export interface SyncHealthResponse {
  breaker: {
    state: BreakerState;
    base_url: string;
    opened_at: string | null;
  };
  outbox: {
    pending: number;
    failed: number;
  };
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
