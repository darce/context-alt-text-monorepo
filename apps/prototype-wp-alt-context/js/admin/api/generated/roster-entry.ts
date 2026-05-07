// This file is generated from packages/shared-contracts/schemas/roster-entry.schema.json.

export interface RosterEntry {
  id: number;
  person_uuid: string;
  name: string;
  tags: string[];
  cluster_count: number;
  updated_at: string;
  source_version: number;
  projection_status: 'current' | 'refreshing' | 'stale' | 'failed';
  projection_refreshed_at: string | null;
}
