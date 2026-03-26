import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig, isDevMode } from '../config';
import { DATA_SOURCE, normalizeDataSource } from './types/dataSource';
import type {
  IdentitySuggestionsResponse,
  MediaIdentitiesResponse,
  PendingMergeSuggestionsResponse,
  PendingNameSuggestionsResponse,
  PendingSuggestionsResponse,
} from './types';
import {
  mapPendingMergeSuggestions,
  mapPendingSuggestions,
} from './identitySuggestionMappers';
import { createRecognitionTimeoutSignal } from './requestTimeout';

export const fetchMediaIdentities = async (mediaIds: number[]): Promise<MediaIdentitiesResponse> => {
  if (mediaIds.length === 0) {
    return { identities_by_media: {}, data_source: DATA_SOURCE.LOCAL_PROJECTION };
  }

  const endpoint = getEndpoint('recognitionMediaIdentities');
  const url = new URL(endpoint, window.location.origin);
  mediaIds.forEach((id) => {
    url.searchParams.append('media_ids[]', String(id));
  });

  if (isDevMode()) {
    url.searchParams.set('include_debug', 'true');
  }

  const response = await fetchRequiredApi<MediaIdentitiesResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });

  return {
    identities_by_media: response.identities_by_media ?? {},
    data_source: normalizeDataSource(response.data_source),
  };
};

export const fetchIdentitySuggestions = async (identityId: string, topK = 5): Promise<IdentitySuggestionsResponse> => {
  const base = getEndpoint('recognitionIdentitySuggestions');
  const normalized = stripTrailingSlash(base);
  const url = new URL(`${normalized}/${identityId}/suggestions`, window.location.origin);
  url.searchParams.set('top_k', String(topK));

  return fetchRequiredApi<IdentitySuggestionsResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });
};

export const fetchPendingSuggestions = async (limit = 10, offset = 0): Promise<PendingSuggestionsResponse> => {
  const base = getEndpoint('recognitionSuggestions');
  const url = new URL(base, window.location.origin);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('offset', String(offset));

  const response = await fetchRequiredApi<PendingSuggestionsResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });

  return mapPendingSuggestions(response, limit, offset);
};

export const fetchPendingMergeSuggestions = async (
  limit = 10,
  offset = 0,
): Promise<PendingMergeSuggestionsResponse> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(base, window.location.origin);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('offset', String(offset));

  const response = await fetchRequiredApi<PendingMergeSuggestionsResponse>(
    url.toString(),
    {
      method: 'GET',
      restNonce: getConfig().nonce,
      signal: createRecognitionTimeoutSignal(2_000),
    },
  );

  return mapPendingMergeSuggestions(response, limit, offset);
};

export const fetchPendingNameSuggestions = async (
  minConfidence = 0,
  limit = 25,
  offset = 0,
): Promise<PendingNameSuggestionsResponse> => {
  const base = getEndpoint('recognitionNameSuggestions');
  const url = new URL(base, window.location.origin);
  url.searchParams.set('min_confidence', String(minConfidence));
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('offset', String(offset));

  return fetchRequiredApi<PendingNameSuggestionsResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  }).then((response) => ({
    suggestions: response.suggestions ?? [],
    total: response.total ?? 0,
    limit: response.limit ?? limit,
    offset: response.offset ?? offset,
    data_source: normalizeDataSource(response.data_source),
  }));
};
