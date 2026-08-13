import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig, isDevMode } from '../config';
import { parseDataSource } from './types/dataSource';
import type {
  IdentityBatchSuggestionsResponse,
  MediaIdentitiesResponse,
  PendingMergeSuggestionsResponse,
  PendingNameSuggestion,
  PendingNameSuggestionsResponse,
  PendingSuggestionsResponse,
} from './types';
import {
  normalizeTopUnlabeledRepresentative,
  type TopUnlabeledRepresentativePayload,
} from './normalizeTopUnlabeledRepresentative';
import { mapPendingMergeSuggestions, mapPendingSuggestions } from './identitySuggestionMappers';
import { createRecognitionTimeoutSignal } from './requestTimeout';

type PendingNameSuggestionPayload = Omit<PendingNameSuggestion, 'representatives'> & {
  representatives?: TopUnlabeledRepresentativePayload[] | null;
};

interface PendingNameSuggestionsResponsePayload {
  suggestions?: PendingNameSuggestionPayload[] | null;
  limit?: number | null;
  offset?: number | null;
  data_source?: string | null;
}

const requireEnvelopeNumber = (value: unknown, fieldName: string, responseName: string): number => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${responseName} must include a numeric ${fieldName}.`);
  }

  return value;
};

const requireCanonicalDataSource = (value: unknown, responseName: string) => {
  const dataSource = parseDataSource(value);
  if (!dataSource) {
    throw new Error(`${responseName} must include a valid data_source.`);
  }

  return dataSource;
};

export const fetchMediaIdentities = async (mediaIds: number[]): Promise<MediaIdentitiesResponse> => {
  if (mediaIds.length === 0) {
    throw new Error(
      "fetchMediaIdentities requires at least one media ID. Use the hook's enabled guard to prevent empty calls.",
    );
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

  if (
    typeof response.identities_by_media !== 'object' ||
    response.identities_by_media === null ||
    Array.isArray(response.identities_by_media)
  ) {
    throw new Error('Media identities response must include an identities_by_media object.');
  }

  return {
    identities_by_media: response.identities_by_media,
    data_source: requireCanonicalDataSource(response.data_source, 'Media identities response'),
  };
};

export const fetchIdentitiesSuggestions = async (
  identityIds: string[],
  topK = 1,
): Promise<IdentityBatchSuggestionsResponse> => {
  if (identityIds.length === 0) {
    throw new Error(
      "fetchIdentitiesSuggestions requires at least one identity ID. Use the hook's enabled guard to prevent empty calls.",
    );
  }

  const base = getEndpoint('recognitionIdentitySuggestions');
  const normalized = stripTrailingSlash(base);
  const url = new URL(`${normalized}/suggestions`, window.location.origin);
  // Comma-joined scalar: the PHP proxy forwards `identity_ids` unchanged so the
  // FastAPI batch route binds every id (array syntax would split into indexed
  // params that bind nothing). The endpoint is bounded per identity by `top_k`.
  url.searchParams.set('identity_ids', identityIds.join(','));
  url.searchParams.set('top_k', String(topK));

  return fetchRequiredApi<IdentityBatchSuggestionsResponse>(url.toString(), {
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

  return mapPendingSuggestions(response);
};

export const fetchPendingMergeSuggestions = async (
  limit = 10,
  offset = 0,
): Promise<PendingMergeSuggestionsResponse> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(base, window.location.origin);
  url.searchParams.set('limit', String(limit));
  url.searchParams.set('offset', String(offset));

  const response = await fetchRequiredApi<PendingMergeSuggestionsResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });

  return mapPendingMergeSuggestions(response);
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

  return fetchRequiredApi<PendingNameSuggestionsResponsePayload>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  }).then((response) => {
    if (!Array.isArray(response.suggestions)) {
      throw new Error('Pending name suggestions response must include a suggestions array.');
    }

    return {
      suggestions: response.suggestions.map((suggestion) => ({
        ...suggestion,
        representatives: Array.isArray(suggestion.representatives)
          ? suggestion.representatives.map(normalizeTopUnlabeledRepresentative)
          : [],
      })),
      // COR-3 (rg-015): no authoritative total forwarded; consumers count loaded items.
      limit: requireEnvelopeNumber(response.limit, 'limit', 'Pending name suggestions response'),
      offset: requireEnvelopeNumber(response.offset, 'offset', 'Pending name suggestions response'),
      data_source: requireCanonicalDataSource(response.data_source, 'Pending name suggestions response'),
    };
  });
};
