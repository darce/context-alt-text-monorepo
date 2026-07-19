import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getConfig, getEndpoint } from '../config';
import type {
  BulkRetryResponse,
  ConflictDetailResponse,
  ConflictListResponse,
  OutboxListResponse,
  OutboxMutationResponse,
  ResolveConflictRequest,
  ResolveConflictResponse,
} from './types';
import { createRecognitionTimeoutSignal } from './requestTimeout';

export interface ConflictListParams {
  resolution_status?: 'open' | 'accepted' | 'dismissed';
  limit?: number;
  offset?: number;
}

export interface FailedOutboxListParams {
  limit?: number;
  offset?: number;
}

export interface OutboxListParams {
  status?: string;
  limit?: number;
  offset?: number;
}

const getOutboxOperationEndpoint = (id: number, action: 'retry' | 'discard'): string =>
  buildResourceEndpoint(getEndpoint('recognitionOutbox', 'recognitionFailedOutbox'), id, action);

const withQuery = (baseEndpoint: string, params: Record<string, string | number | undefined>): string => {
  const hasAbsoluteOrigin = /^[a-z][a-z\d+\-.]*:\/\//i.test(baseEndpoint);
  const url = new URL(baseEndpoint, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '') {
      return;
    }
    url.searchParams.set(key, String(value));
  });
  return hasAbsoluteOrigin ? url.toString() : `${url.pathname}${url.search}`;
};

const buildResourceEndpoint = (baseEndpoint: string, id: number, action?: string): string => {
  const endpoint = `${stripTrailingSlash(baseEndpoint)}/${id}`;
  return action ? `${endpoint}/${action}` : endpoint;
};

export const fetchConflicts = async (params: ConflictListParams = {}): Promise<ConflictListResponse> => {
  const endpoint = withQuery(getEndpoint('recognitionConflicts'), {
    resolution_status: params.resolution_status ?? 'open',
    limit: params.limit,
    offset: params.offset,
  });

  return fetchRequiredApi<ConflictListResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });
};

export const fetchConflictDetail = async (id: number): Promise<ConflictDetailResponse> => {
  const endpoint = buildResourceEndpoint(getEndpoint('recognitionConflicts'), id);
  return fetchRequiredApi<ConflictDetailResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });
};

export const resolveConflict = async (
  id: number,
  request: ResolveConflictRequest,
): Promise<ResolveConflictResponse> => {
  const endpoint = buildResourceEndpoint(getEndpoint('recognitionConflicts'), id, 'resolve');
  return fetchRequiredApi<ResolveConflictResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    body: request,
    signal: createRecognitionTimeoutSignal(5_000),
  });
};

export const fetchFailedOutboxOperations = async (params: FailedOutboxListParams = {}): Promise<OutboxListResponse> => {
  const endpoint = withQuery(getEndpoint('recognitionFailedOutbox'), {
    limit: params.limit,
    offset: params.offset,
  });

  return fetchRequiredApi<OutboxListResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });
};

export const fetchOutboxOperations = async (params: OutboxListParams = {}): Promise<OutboxListResponse> => {
  const endpoint = withQuery(getEndpoint('recognitionOutbox', 'recognitionFailedOutbox'), {
    status: params.status,
    limit: params.limit,
    offset: params.offset,
  });

  return fetchRequiredApi<OutboxListResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });
};

export const retryFailedOperation = async (id: number): Promise<OutboxMutationResponse> => {
  const endpoint = getOutboxOperationEndpoint(id, 'retry');
  return fetchRequiredApi<OutboxMutationResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(5_000),
  });
};

export const bulkRetryFailedOperations = async (): Promise<BulkRetryResponse> => {
  // E15-35 Slice 2: requeues every failed push for the tenant in one guarded call;
  // the backend paces the requeued rows across drain cycles.
  const endpoint = getEndpoint('recognitionSyncRetryFailed');
  return fetchRequiredApi<BulkRetryResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(30_000),
  });
};

export const discardFailedOperation = async (id: number): Promise<OutboxMutationResponse> => {
  const endpoint = getOutboxOperationEndpoint(id, 'discard');
  return fetchRequiredApi<OutboxMutationResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(5_000),
  });
};
