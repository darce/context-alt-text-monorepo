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

/**
 * Result of the atomic merge+accept endpoint.
 *
 * The service performs the cluster merge and the ACCEPTED stamp under one
 * transaction, so this single response carries everything the caller needs to
 * apply the merge locally and to offer an undo — no second hop, and therefore
 * no half-applied state to compensate for (rg-002 / ARCH-03).
 */
export interface AcceptedMergeSuggestion extends PendingMergeSuggestion {
  /** Retired cluster (authoritative, server-ordered). */
  source_cluster_id: string;
  /** Surviving cluster (authoritative, server-ordered). */
  target_cluster_id: string;
  /**
   * Identities the merge transaction actually moved — the revert set for
   * `revertMergeCluster`. Empty when the merge moved nothing, or on an
   * already-accepted replay whose moving transaction was an earlier request.
   */
  moved_identity_ids: string[];
}

const requireAcceptedClusterId = (value: unknown, fieldName: string): string => {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`Merge accept response must include a non-empty ${fieldName}.`);
  }
  return value;
};

/**
 * Boundary validation for the accept-only fields (sr-005): the merge topology and
 * the revert set are load-bearing for undo, so a malformed envelope must fail
 * loudly here rather than surface later as a silently un-revertable merge.
 */
const requireMovedIdentityIds = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    throw new Error('Merge accept response must include a moved_identity_ids array.');
  }
  return value.map((entry, index) => {
    if (typeof entry !== 'string' || entry.length === 0) {
      throw new Error(`Merge accept response moved_identity_ids[${index}] must be a non-empty string.`);
    }
    return entry;
  });
};

/**
 * Accept a merge suggestion, optionally pinning the operator's chosen survivor.
 *
 * `targetClusterId` must be one of the suggestion's two clusters; the service
 * rejects anything else with 422 rather than silently re-ranking. Omit it to
 * keep the server-selected survivor.
 */
export interface AcceptMergeSuggestionRequest {
  suggestionId: string;
  targetClusterId?: string;
}

/**
 * Accept a merge suggestion atomically.
 *
 * Single-argument by design: react-query passes a mutation context as the second
 * positional argument, so an extra positional parameter here would silently bind
 * to it. Pass a plain id, or the request object when pinning a survivor.
 *
 * The bare-id overload is declared last so that `mutationFn: acceptMergeSuggestion`
 * keeps inferring `string` mutation variables; callers that pin a survivor pass
 * the request object explicitly.
 */
export async function acceptMergeSuggestion(request: AcceptMergeSuggestionRequest): Promise<AcceptedMergeSuggestion>;
export async function acceptMergeSuggestion(suggestionId: string): Promise<AcceptedMergeSuggestion>;
export async function acceptMergeSuggestion(
  request: string | AcceptMergeSuggestionRequest,
): Promise<AcceptedMergeSuggestion> {
  const { suggestionId, targetClusterId }: AcceptMergeSuggestionRequest =
    typeof request === 'string' ? { suggestionId: request } : request;
  const base = getEndpoint('recognitionMergeSuggestions');
  const url = new URL(`${stripTrailingSlash(base)}/${suggestionId}/accept`, window.location.origin);

  // Narrow/validate — including optional authoritative source/target ids.
  const raw = await fetchRequiredApi<Record<string, unknown>>(url.toString(), {
    method: 'POST',
    body: targetClusterId ? { target_cluster_id: targetClusterId } : undefined,
    restNonce: getConfig().nonce,
  });
  const suggestion = mapPendingMergeSuggestion(raw);

  return {
    ...suggestion,
    source_cluster_id: requireAcceptedClusterId(suggestion.source_cluster_id, 'source_cluster_id'),
    target_cluster_id: requireAcceptedClusterId(suggestion.target_cluster_id, 'target_cluster_id'),
    moved_identity_ids: requireMovedIdentityIds(raw.moved_identity_ids),
  };
}

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
