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
  cluster_a_representative_attachment_url?: string | null;
  cluster_a_representative_thumb_url?: string | null;
  cluster_a_representative_bbox?: BoundingBox | null;
  cluster_b_representative_media_id?: number | null;
  cluster_b_representative_media_url?: string | null;
  cluster_b_representative_attachment_url?: string | null;
  cluster_b_representative_thumb_url?: string | null;
  cluster_b_representative_bbox?: BoundingBox | null;
  /** Authoritative post-accept retired id (optional on list/older backends). */
  source_cluster_id?: string | null;
  /** Authoritative post-accept survivor id (optional on list/older backends). */
  target_cluster_id?: string | null;
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
      identity_attachment_url: suggestion.identity_attachment_url ?? null,
      identity_thumb_url: suggestion.identity_thumb_url ?? null,
      identity_bbox: suggestion.identity_bbox ?? null,
      representative_media_id: suggestion.representative_media_id ?? null,
      representative_media_url: suggestion.representative_media_url ?? null,
      representative_attachment_url: suggestion.representative_attachment_url ?? null,
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

  const suggestions: PendingMergeSuggestion[] = rawSuggestions.map((suggestion) =>
    mapPendingMergeSuggestion(suggestion),
  );

  return {
    suggestions,
    ...metadata,
  };
};

const optionalClusterId = (value: unknown): string | null => {
  if (typeof value !== 'string' || value.length === 0) {
    return null;
  }
  return value;
};

const requireStringField = (value: unknown, fieldName: string): string => {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`Merge suggestion response must include ${fieldName}.`);
  }
  return value;
};

/**
 * Narrow a raw merge-suggestion payload (list item or accept/reject response).
 * Validates required fields; authoritative source/target ids are optional.
 * No non-null assertions — every field is type-narrowed explicitly.
 */
export const mapPendingMergeSuggestion = (raw: unknown): PendingMergeSuggestion => {
  if (raw === null || typeof raw !== 'object') {
    throw new Error('Merge suggestion response must be an object.');
  }
  const suggestion = raw as Record<string, unknown>;

  const id = requireStringField(suggestion.id, 'a non-empty id');
  const clusterAId = requireStringField(suggestion.cluster_a_id, 'cluster_a_id');
  const clusterBId = requireStringField(suggestion.cluster_b_id, 'cluster_b_id');
  const status = requireStringField(suggestion.status, 'status');

  const similarity = suggestion.similarity;
  if (typeof similarity !== 'number' || !Number.isFinite(similarity)) {
    throw new Error('Merge suggestion response must include a numeric similarity.');
  }

  const bboxOrNull = (value: unknown): BoundingBox | null => {
    if (value === null || value === undefined) {
      return null;
    }
    if (typeof value !== 'object') {
      return null;
    }
    return value as BoundingBox;
  };

  return {
    id,
    cluster_a_id: clusterAId,
    cluster_b_id: clusterBId,
    similarity,
    status,
    cluster_a_label: typeof suggestion.cluster_a_label === 'string' ? suggestion.cluster_a_label : null,
    cluster_b_label: typeof suggestion.cluster_b_label === 'string' ? suggestion.cluster_b_label : null,
    cluster_a_identity_count:
      typeof suggestion.cluster_a_identity_count === 'number' ? suggestion.cluster_a_identity_count : null,
    cluster_b_identity_count:
      typeof suggestion.cluster_b_identity_count === 'number' ? suggestion.cluster_b_identity_count : null,
    cluster_a_representative_media_id:
      typeof suggestion.cluster_a_representative_media_id === 'number'
        ? suggestion.cluster_a_representative_media_id
        : null,
    cluster_a_representative_media_url:
      typeof suggestion.cluster_a_representative_media_url === 'string'
        ? suggestion.cluster_a_representative_media_url
        : null,
    cluster_a_representative_attachment_url:
      typeof suggestion.cluster_a_representative_attachment_url === 'string'
        ? suggestion.cluster_a_representative_attachment_url
        : null,
    cluster_a_representative_thumb_url:
      typeof suggestion.cluster_a_representative_thumb_url === 'string'
        ? suggestion.cluster_a_representative_thumb_url
        : null,
    cluster_a_representative_bbox: bboxOrNull(suggestion.cluster_a_representative_bbox),
    cluster_b_representative_media_id:
      typeof suggestion.cluster_b_representative_media_id === 'number'
        ? suggestion.cluster_b_representative_media_id
        : null,
    cluster_b_representative_media_url:
      typeof suggestion.cluster_b_representative_media_url === 'string'
        ? suggestion.cluster_b_representative_media_url
        : null,
    cluster_b_representative_attachment_url:
      typeof suggestion.cluster_b_representative_attachment_url === 'string'
        ? suggestion.cluster_b_representative_attachment_url
        : null,
    cluster_b_representative_thumb_url:
      typeof suggestion.cluster_b_representative_thumb_url === 'string'
        ? suggestion.cluster_b_representative_thumb_url
        : null,
    cluster_b_representative_bbox: bboxOrNull(suggestion.cluster_b_representative_bbox),
    source_cluster_id: optionalClusterId(suggestion.source_cluster_id),
    target_cluster_id: optionalClusterId(suggestion.target_cluster_id),
  };
};
