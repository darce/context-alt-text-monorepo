/**
 * Suggestion Types
 *
 * Types for the suggestion review system (borderline matches needing confirmation).
 */

/**
 * A pending suggestion for user review.
 * Created when a face matches a cluster but is below the auto-assign threshold.
 */
import type { DataSource } from './dataSource';
import type { TopUnlabeledRepresentative } from './cluster';
import type { BoundingBox } from './identity';

export interface PendingSuggestion {
  id: string;
  identity_id: string;
  suggested_cluster_id: string;
  representative_similarity: number;
  avg_member_similarity?: number;
  confidence_score?: number;
  expires_at?: string | null;
  source_job_id?: string | null;
  resolution?: string;
  created_at?: string;
  resolved_at?: string | null;
  // Enriched fields (always returned)
  cluster_label?: string | null;
  cluster_identity_count?: number | null;
  identity_media_id?: number | null;
  identity_media_url?: string | null;
  identity_attachment_url?: string | null;
  identity_thumb_url?: string | null;
  identity_bbox?: BoundingBox | null;
  representative_media_id?: number | null;
  representative_media_url?: string | null;
  representative_attachment_url?: string | null;
  representative_thumb_url?: string | null;
  representative_bbox?: BoundingBox | null;
  suggested_label?: string | null;
  suggested_label_source?: 'identity' | 'roster' | 'similar_cluster' | 'none' | null;
  suggested_label_confidence?: number | null;
}

export interface PendingSuggestionsResponse {
  suggestions: PendingSuggestion[];
  // COR-3 (rg-015): the boundary forwards a single bare page with no authoritative
  // grand total. Display counts derive from `suggestions.length` instead.
  limit: number;
  offset: number;
  data_source?: DataSource;
}

/**
 * Phase 0 scaffold for backend-generated naming suggestions.
 */
export interface PendingNameSuggestion {
  id: string;
  cluster_id: string;
  suggested_name: string;
  confidence_score: number | null;
  source: string;
  created_at: string;
  expires_at: string | null;
  representatives?: TopUnlabeledRepresentative[];
}

export interface PendingNameSuggestionsResponse {
  suggestions: PendingNameSuggestion[];
  // COR-3 (rg-015): no authoritative total; count derives from `suggestions.length`.
  limit: number;
  offset: number;
  data_source?: DataSource;
}

export interface BulkAcceptRequest {
  suggestion_type: 'assignment' | 'merge' | 'name';
  min_confidence: number;
}

export interface BulkAcceptResponse {
  accepted_count: number;
  skipped_count: number;
}

export interface SuggestionActionResponse {
  suggestion_id: string;
  resolution: 'accepted' | 'rejected';
  identity_id: string;
  cluster_id: string | null;
  message: string;
}

export interface PendingMergeSuggestion {
  id: string;
  cluster_a_id: string;
  cluster_b_id: string;
  similarity: number;
  status: string;
  confidence_score?: number | null;
  expires_at?: string | null;
  source_job_id?: string | null;
  cluster_a_label?: string | null;
  cluster_b_label?: string | null;
  cluster_a_identity_count?: number | null;
  cluster_b_identity_count?: number | null;
  cluster_a_representative_media_id?: number | null;
  cluster_a_representative_media_url?: string | null;
  cluster_a_representative_attachment_url?: string | null;
  cluster_a_representative_thumb_url?: string | null;
  cluster_a_representative_bbox?: BoundingBox | null;
  cluster_b_representative_media_id?: number | null;
  cluster_b_representative_media_url?: string | null;
  cluster_b_representative_attachment_url?: string | null;
  cluster_b_representative_thumb_url?: string | null;
  cluster_b_representative_bbox?: BoundingBox | null;
  /**
   * Authoritative post-accept topology from `_select_merge_target`
   * (source = retired, target = survivor). Present on accept responses only;
   * absent/null on list/pending and older backends.
   */
  source_cluster_id?: string | null;
  target_cluster_id?: string | null;
  /**
   * Authoritative labeled-for-merge side from `_to_merge_response`
   * (`user_confirmed ∧ label ∧ ¬reserved`). Optional on older backends.
   */
  survivor_cluster_id?: string | null;
  /** Display label for the stamped survivor; null when omitted. */
  survivor_label?: string | null;
}

export interface PendingMergeSuggestionsResponse {
  suggestions: PendingMergeSuggestion[];
  // COR-3 (rg-015): no authoritative total; count derives from `suggestions.length`.
  limit: number;
  offset: number;
  data_source?: DataSource;
}
