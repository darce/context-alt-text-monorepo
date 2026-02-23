export interface SyncStatusResponse {
  last_snapshot_version: number;
  last_synced_at: string | null;
  is_stale: boolean;
}

export interface SyncTriggerResponse {
  synced: boolean;
  reason: 'ok' | 'sync_failed' | 'sync_unavailable' | 'no_remote_data';
  last_snapshot_version: number;
  last_synced_at: string | null;
  is_stale: boolean;
}
