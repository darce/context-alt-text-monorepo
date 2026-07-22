import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import { mapPendingMergeSuggestion } from './identitySuggestionMappers';
import type { BulkAcceptRequest, BulkAcceptResponse, PendingMergeSuggestion, SuggestionActionResponse } from './types';

export const acceptSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('recognitionSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);

  return fetchRequiredApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const acceptMergeSuggestion = async (suggestionId: string): Promise<PendingMergeSuggestion> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);

  // Narrow/validate — including optional authoritative source/target ids.
  const raw = await fetchRequiredApi<Record<string, unknown>>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
  return mapPendingMergeSuggestion(raw);
};

export const rejectSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('recognitionSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/reject`, window.location.origin);

  return fetchRequiredApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const rejectMergeSuggestion = async (suggestionId: string): Promise<PendingMergeSuggestion> => {
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/reject`, window.location.origin);

  const raw = await fetchRequiredApi<Record<string, unknown>>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
  return mapPendingMergeSuggestion(raw);
};

export const acceptNameSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('recognitionNameSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);

  return fetchRequiredApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const rejectNameSuggestion = async (suggestionId: string): Promise<SuggestionActionResponse> => {
  const base = getEndpoint('recognitionNameSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/reject`, window.location.origin);

  return fetchRequiredApi<SuggestionActionResponse>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};

export const bulkAcceptSuggestions = async (request: BulkAcceptRequest): Promise<BulkAcceptResponse> => {
  const base = getEndpoint('recognitionBulkAcceptSuggestions');

  return fetchRequiredApi<BulkAcceptResponse>(base, {
    method: 'POST',
    body: request,
    restNonce: getConfig().nonce,
  });
};
