export interface SyncStatusResponse {
  last_snapshot_version: number;
  last_synced_at: string | null;
  is_stale: boolean;
}
