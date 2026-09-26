// This file is generated from packages/shared-contracts/schemas/roster-entry.schema.json.

export interface RosterEntryBbox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface RosterEntryInstance {
  identity_id: string;
  media_id: number;
  media_url: string | null;
  bbox: RosterEntryBbox | null;
  similarity: number | null;
  similarity_threshold?: number | null;
}

export interface RosterEntryQualityComponents {
  confidence: number | null;
  bbox_area: number | null;
  sharpness: number | null;
  occlusion_severity: number | null;
}

export interface RosterEntryRepresentativeIdentity extends RosterEntryInstance {
  representative_quality?: number | null;
  quality_components?: RosterEntryQualityComponents | null;
}

export interface RosterEntryCluster {
  cluster_id: string;
  identity_count: number;
  representative_identity: RosterEntryRepresentativeIdentity | null;
  instances: RosterEntryInstance[];
  representative_media_id?: number | null;
  undoable_merge_receipt_id?: string | null;
}

export interface RosterEntry {
  id: number;
  person_uuid: string;
  name: string;
  tags: string[];
  cluster_count: number;
  clusters: RosterEntryCluster[];
  queue_memberships: ('singleton-proposals' | 'hard-examples' | 'needs-confirmation-after-merge')[];
  updated_at: string;
  source_version: number;
  projection_status: 'current' | 'refreshing' | 'stale' | 'failed';
  projection_refreshed_at: string | null;
}
