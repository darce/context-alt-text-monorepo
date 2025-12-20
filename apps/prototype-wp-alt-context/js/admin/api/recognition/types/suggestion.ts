/**
 * Suggestion Types
 *
 * Types for the suggestion review system (borderline matches needing confirmation).
 */

/**
 * A pending suggestion for user review.
 * Created when a face matches a cluster but is below the auto-assign threshold.
 */
export interface PendingSuggestion {
  id: string;
  identity_id: string;
  suggested_cluster_id: string;
  representative_similarity: number;
  avg_member_similarity: number;
  confidence_score: number;
  resolution: string;
  created_at: string;
  resolved_at: string | null;
  // Enriched fields (from include_details=true)
  cluster_label: string | null;
  cluster_identity_count: number | null;
  identity_media_id: number | null;
}

export interface PendingSuggestionsResponse {
  suggestions: PendingSuggestion[];
  total: number;
  limit: number;
  offset: number;
}

export interface SuggestionActionResponse {
  suggestion_id: string;
  resolution: 'accepted' | 'rejected';
  identity_id: string;
  cluster_id: string | null;
  message: string;
}

/**
 * Training stage info based on curriculum learning principles.
 * Thresholds start strict (early stage) and relax as more identities are labeled.
 */
export interface TrainingStageResponse {
  tenant_id: string;
  stage: 'early' | 'developing' | 'mature';
  stage_label: string;
  cluster_count: number;
  identity_count: number;
  current_threshold: number;
  base_threshold: number;
  strict_threshold: number;
  maturity_point: number;
  progress_percent: number;
}
