import type {
  BoundingBox,
  PendingMergeSuggestion,
  PendingMergeSuggestionsResponse,
  PendingSuggestionsResponse,
} from './types';

export interface PendingSuggestionApiResponse {
  id: string;
  identity_id: string;
  cluster_id: string;
  rep_similarity: number;
  member_similarity: number | null;
  status: string;
  cluster_label?: string | null;
  cluster_identity_count?: number | null;
  identity_media_id?: number | null;
  identity_media_url?: string | null;
  identity_thumbnail_url?: string | null;
  identity_bbox?: BoundingBox | null;
  representative_media_id?: number | null;
  representative_media_url?: string | null;
  representative_thumbnail_url?: string | null;
  representative_bbox?: BoundingBox | null;
  suggested_label?: string | null;
  suggested_label_source?: 'identity' | 'roster' | 'similar_cluster' | 'none' | null;
  suggested_label_confidence?: number | null;
  cluster_thumbnails?: string[] | null;
}

export interface PendingMergeSuggestionApiResponse {
  id: string;
  cluster_a_id: string;
  cluster_b_id: string;
  similarity: number;
  status: string;
  cluster_a_label?: string | null;
  cluster_b_label?: string | null;
  cluster_a_identity_count?: number | null;
  cluster_b_identity_count?: number | null;
  cluster_a_representative_media_id?: number | null;
  cluster_a_representative_media_url?: string | null;
  cluster_a_representative_thumbnail_url?: string | null;
  cluster_a_representative_bbox?: BoundingBox | null;
  cluster_b_representative_media_id?: number | null;
  cluster_b_representative_media_url?: string | null;
  cluster_b_representative_thumbnail_url?: string | null;
  cluster_b_representative_bbox?: BoundingBox | null;
}

export const mapPendingSuggestions = (
  response: PendingSuggestionsResponse | PendingSuggestionApiResponse[],
  limit: number,
  offset: number,
): PendingSuggestionsResponse => {
  if (!Array.isArray(response)) {
    return response;
  }

  const suggestions = response.map((suggestion) => ({
    id: suggestion.id,
    identity_id: suggestion.identity_id,
    suggested_cluster_id: suggestion.cluster_id,
    representative_similarity: suggestion.rep_similarity,
    avg_member_similarity: suggestion.member_similarity ?? suggestion.rep_similarity,
    confidence_score: suggestion.rep_similarity,
    resolution: suggestion.status,
    cluster_label: suggestion.cluster_label ?? null,
    cluster_identity_count: suggestion.cluster_identity_count ?? null,
    identity_media_id: suggestion.identity_media_id ?? null,
    identity_media_url: suggestion.identity_media_url ?? null,
    identity_thumbnail_url: suggestion.identity_thumbnail_url ?? null,
    identity_bbox: suggestion.identity_bbox ?? null,
    representative_media_id: suggestion.representative_media_id ?? null,
    representative_media_url: suggestion.representative_media_url ?? null,
    representative_thumbnail_url: suggestion.representative_thumbnail_url ?? null,
    representative_bbox: suggestion.representative_bbox ?? null,
    suggested_label: suggestion.suggested_label ?? null,
    suggested_label_source: suggestion.suggested_label_source ?? null,
    suggested_label_confidence: suggestion.suggested_label_confidence ?? null,
    cluster_thumbnails: suggestion.cluster_thumbnails ?? [],
  }));

  return {
    suggestions,
    total: suggestions.length,
    limit,
    offset,
  };
};

export const mapPendingMergeSuggestions = (
  response: PendingMergeSuggestionsResponse | PendingMergeSuggestionApiResponse[],
  limit: number,
  offset: number,
): PendingMergeSuggestionsResponse => {
  if (!Array.isArray(response)) {
    return response;
  }

  const suggestions: PendingMergeSuggestion[] = response.map((suggestion) => ({
    id: suggestion.id,
    cluster_a_id: suggestion.cluster_a_id,
    cluster_b_id: suggestion.cluster_b_id,
    similarity: suggestion.similarity,
    status: suggestion.status,
    cluster_a_label: suggestion.cluster_a_label ?? null,
    cluster_b_label: suggestion.cluster_b_label ?? null,
    cluster_a_identity_count: suggestion.cluster_a_identity_count ?? null,
    cluster_b_identity_count: suggestion.cluster_b_identity_count ?? null,
    cluster_a_representative_media_id: suggestion.cluster_a_representative_media_id ?? null,
    cluster_a_representative_media_url: suggestion.cluster_a_representative_media_url ?? null,
    cluster_a_representative_thumbnail_url: suggestion.cluster_a_representative_thumbnail_url ?? null,
    cluster_a_representative_bbox: suggestion.cluster_a_representative_bbox ?? null,
    cluster_b_representative_media_id: suggestion.cluster_b_representative_media_id ?? null,
    cluster_b_representative_media_url: suggestion.cluster_b_representative_media_url ?? null,
    cluster_b_representative_thumbnail_url: suggestion.cluster_b_representative_thumbnail_url ?? null,
    cluster_b_representative_bbox: suggestion.cluster_b_representative_bbox ?? null,
  }));

  return {
    suggestions,
    total: suggestions.length,
    limit,
    offset,
  };
};
