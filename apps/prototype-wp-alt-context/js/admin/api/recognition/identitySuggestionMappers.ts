import { parseDataSource } from './types/dataSource';
import type {
  BoundingBox,
  PendingMergeSuggestion,
  PendingMergeSuggestionsResponse,
  PendingSuggestionsResponse,
} from './types';

export interface PendingSuggestionApiResponse {
  id: string;
  identity_id: string;
  cluster_id?: string;
  suggested_cluster_id?: string;
  rep_similarity?: number;
  representative_similarity?: number;
  member_similarity?: number | null;
  avg_member_similarity?: number | null;
  status?: string;
  resolution?: string;
  confidence_score?: number | null;
  cluster_label?: string | null;
  cluster_identity_count?: number | null;
  identity_media_id?: number | null;
  identity_media_url?: string | null;
  identity_thumb_url?: string | null;
  identity_bbox?: BoundingBox | null;
  representative_media_id?: number | null;
  representative_media_url?: string | null;
  representative_thumb_url?: string | null;
  representative_bbox?: BoundingBox | null;
  suggested_label?: string | null;
  suggested_label_source?: 'identity' | 'roster' | 'similar_cluster' | 'none' | null;
  suggested_label_confidence?: number | null;
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
  cluster_a_representative_thumb_url?: string | null;
  cluster_a_representative_bbox?: BoundingBox | null;
  cluster_b_representative_media_id?: number | null;
  cluster_b_representative_media_url?: string | null;
  cluster_b_representative_thumb_url?: string | null;
  cluster_b_representative_bbox?: BoundingBox | null;
}

const requireEnvelopeNumber = (value: unknown, fieldName: string, responseName: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${responseName} must include a numeric ${fieldName}.`);
  }

  return value;
};

const requireSuggestionEnvelopeMetadata = (
  response: PendingSuggestionsResponse | PendingMergeSuggestionsResponse,
  responseName: string,
) => {
  const dataSource = parseDataSource(response.data_source);
  if (!dataSource) {
    throw new Error(`${responseName} must include a valid data_source.`);
  }

  // COR-3 (rg-015): no authoritative `total` is forwarded; consumers count loaded items.
  return {
    limit: requireEnvelopeNumber(response.limit, 'limit', responseName),
    offset: requireEnvelopeNumber(response.offset, 'offset', responseName),
    data_source: dataSource,
  };
};

export const mapPendingSuggestions = (response: PendingSuggestionsResponse): PendingSuggestionsResponse => {
  const metadata = requireSuggestionEnvelopeMetadata(response, 'Pending suggestions response');
  const rawSuggestions = response.suggestions as PendingSuggestionApiResponse[] | undefined;
  if (!Array.isArray(rawSuggestions)) {
    throw new Error('Pending suggestions response must include a suggestions array.');
  }

  const suggestions = rawSuggestions.map((suggestion) => {
    const suggestedClusterId = suggestion.suggested_cluster_id ?? suggestion.cluster_id ?? '';
    const representativeSimilarity = suggestion.representative_similarity ?? suggestion.rep_similarity ?? 0;
    const avgMemberSimilarity =
      suggestion.avg_member_similarity ?? suggestion.member_similarity ?? representativeSimilarity;

    return {
      id: suggestion.id,
      identity_id: suggestion.identity_id,
      suggested_cluster_id: suggestedClusterId,
      representative_similarity: representativeSimilarity,
      avg_member_similarity: avgMemberSimilarity,
      confidence_score: suggestion.confidence_score ?? representativeSimilarity,
      resolution: suggestion.resolution ?? suggestion.status,
      cluster_label: suggestion.cluster_label ?? null,
      cluster_identity_count: suggestion.cluster_identity_count ?? null,
      identity_media_id: suggestion.identity_media_id ?? null,
      identity_media_url: suggestion.identity_media_url ?? null,
      identity_thumb_url: suggestion.identity_thumb_url ?? null,
      identity_bbox: suggestion.identity_bbox ?? null,
      representative_media_id: suggestion.representative_media_id ?? null,
      representative_media_url: suggestion.representative_media_url ?? null,
      representative_thumb_url: suggestion.representative_thumb_url ?? null,
      representative_bbox: suggestion.representative_bbox ?? null,
      suggested_label: suggestion.suggested_label ?? null,
      suggested_label_source: suggestion.suggested_label_source ?? null,
      suggested_label_confidence: suggestion.suggested_label_confidence ?? null,
    };
  });

  return {
    suggestions,
    ...metadata,
  };
};

export const mapPendingMergeSuggestions = (
  response: PendingMergeSuggestionsResponse,
): PendingMergeSuggestionsResponse => {
  const metadata = requireSuggestionEnvelopeMetadata(response, 'Pending merge suggestions response');
  const rawSuggestions = response.suggestions as PendingMergeSuggestionApiResponse[] | undefined;
  if (!Array.isArray(rawSuggestions)) {
    throw new Error('Pending merge suggestions response must include a suggestions array.');
  }

  const suggestions: PendingMergeSuggestion[] = rawSuggestions.map((suggestion) => ({
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
    cluster_a_representative_thumb_url: suggestion.cluster_a_representative_thumb_url ?? null,
    cluster_a_representative_bbox: suggestion.cluster_a_representative_bbox ?? null,
    cluster_b_representative_media_id: suggestion.cluster_b_representative_media_id ?? null,
    cluster_b_representative_media_url: suggestion.cluster_b_representative_media_url ?? null,
    cluster_b_representative_thumb_url: suggestion.cluster_b_representative_thumb_url ?? null,
    cluster_b_representative_bbox: suggestion.cluster_b_representative_bbox ?? null,
  }));

  return {
    suggestions,
    ...metadata,
  };
};
