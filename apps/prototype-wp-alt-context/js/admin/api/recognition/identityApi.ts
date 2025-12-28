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
  SuggestionActionResponse,
} from './types';

type PendingSuggestionApiResponse = {
  id: string;
  identity_id: string;
  cluster_id: string;
  rep_similarity: number;
  member_similarity: number | null;
  status: string;
};

export const fetchMediaIdentities = async (mediaIds: number[]): Promise<MediaIdentitiesResponse> => {
  if (mediaIds.length === 0) {
    return { identities_by_media: {} };
  }

  const endpoint = getEndpoint('workbenchRecognitionMediaIdentities');
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
  const base = getEndpoint('workbenchRecognitionIdentitySuggestions', 'recognitionIdentitySuggestions');
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
  const base = getEndpoint('workbenchRecognitionSuggestions', 'recognitionSuggestions');
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
      cluster_label: null,
      cluster_identity_count: null,
      identity_media_id: null,
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
  const base = getEndpoint('workbenchRecognitionSuggestions', 'recognitionSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);
  const tenantId = getConfig().tenant_id;
  if (tenantId) {
    url.searchParams.set('tenant_id', tenantId);
  }

  return fetchApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

/**
 * Reject a suggestion - identity stays in its current cluster/singleton.
 */
export const rejectSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('workbenchRecognitionSuggestions', 'recognitionSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/reject`, window.location.origin);
  const tenantId = getConfig().tenant_id;
  if (tenantId) {
    url.searchParams.set('tenant_id', tenantId);
  }

  return fetchApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};
