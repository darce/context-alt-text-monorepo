export interface SyncStatusResponse {
  last_snapshot_version: number;
  last_synced_at: string | null;
  is_stale: boolean;
  pending_curation_operations?: number;
  conflict_count?: number;
  last_curation_acknowledged_at?: string | null;
  last_curation_conflict_at?: string | null;
}

export interface SyncTriggerResponse {
  synced: boolean;
  reason: 'ok' | 'sync_failed' | 'sync_unavailable' | 'no_remote_data';
  last_snapshot_version: number;
  last_synced_at: string | null;
  is_stale: boolean;
}
