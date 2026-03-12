export type SyncHealth = 'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline';

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
  last_sync_result: 'ok' | 'failed' | 'unreachable';
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
