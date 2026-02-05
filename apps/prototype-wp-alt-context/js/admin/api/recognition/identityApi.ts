/**
 * Identity Operations API
 *
 * API functions for identity queries and suggestions.
 */

import { fetchApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig, isDevMode } from '../config';
import type {
  MediaIdentitiesResponse,
  IdentitySuggestionsResponse,
  PendingSuggestionsResponse,
  PendingMergeSuggestionsResponse,
  PendingMergeSuggestion,
  SuggestionActionResponse,
  BoundingBox,
} from './types';

interface PendingSuggestionApiResponse {
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

interface PendingMergeSuggestionApiResponse {
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

export const fetchMediaIdentities = async (mediaIds: number[]): Promise<MediaIdentitiesResponse> => {
  if (mediaIds.length === 0) {
    return { identities_by_media: {} };
  }

  const endpoint = getEndpoint('recognitionMediaIdentities');
  const url = new URL(endpoint, window.location.origin);
  mediaIds.forEach((id) => {
    url.searchParams.append('media_ids[]', String(id));
  });

  // Include debug metrics (pose, age, gender, etc.) in development mode
  if (isDevMode()) {
    url.searchParams.set('include_debug', 'true');
  }

  return fetchApi(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

/**
 * Fetch cluster suggestions for an identity.
 *
 * Note: Threshold filtering is handled by the backend - all pending suggestions
 * returned have already passed the backend's similarity threshold.
 */
export const fetchIdentitySuggestions = async (identityId: string, topK = 5): Promise<IdentitySuggestionsResponse> => {
  const base = getEndpoint('recognitionIdentitySuggestions');
  const normalized = stripTrailingSlash(base);
  const url = new URL(`${normalized}/${identityId}/suggestions`, window.location.origin);
  url.searchParams.set('top_k', String(topK));

  return fetchApi<IdentitySuggestionsResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};

/**
 * Fetch pending suggestions for user review.
 * These are borderline matches that need human confirmation.
 */
export const fetchPendingSuggestions = async (limit = 10, offset = 0): Promise<PendingSuggestionsResponse> => {
  const base = getEndpoint('recognitionSuggestions');
  const url = new URL(base, window.location.origin);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('offset', String(offset));

  const response = await fetchApi<PendingSuggestionsResponse | PendingSuggestionApiResponse[]>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });

  if (Array.isArray(response)) {
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
  }

  return response;
};

export const fetchPendingMergeSuggestions = async (
  limit = 10,
  offset = 0,
): Promise<PendingMergeSuggestionsResponse> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(base, window.location.origin);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('offset', String(offset));

  const response = await fetchApi<PendingMergeSuggestionsResponse | PendingMergeSuggestionApiResponse[]>(
    url.toString(),
    {
      method: 'GET',
      restNonce: getConfig().nonce,
    },
  );

  if (Array.isArray(response)) {
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
  }

  return response;
};

/**
 * Accept a suggestion - assign the identity to the suggested cluster.
 */
export const acceptSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('recognitionSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);

  return fetchApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const acceptMergeSuggestion = async (suggestionId: string): Promise<PendingMergeSuggestion> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);

  return fetchApi<PendingMergeSuggestion>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

/**
 * Reject a suggestion - identity stays in its current cluster/singleton.
 */
export const rejectSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('recognitionSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/reject`, window.location.origin);

  return fetchApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const rejectMergeSuggestion = async (suggestionId: string): Promise<PendingMergeSuggestion> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/reject`, window.location.origin);

  return fetchApi<PendingMergeSuggestion>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};
