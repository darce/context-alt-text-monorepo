import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { PendingMergeSuggestion, SuggestionActionResponse } from './types';

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

  return fetchRequiredApi<PendingMergeSuggestion>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
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

  return fetchRequiredApi<PendingMergeSuggestion>(url.toString(), {
    method: 'POST',
    restNonce: getConfig().nonce,
  });
};
