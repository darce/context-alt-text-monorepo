import { fetchRequiredApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { SyncHealthResponse, SyncStatusResponse, SyncTriggerResponse } from './types';
import { createRecognitionTimeoutSignal } from './requestTimeout';

export const fetchSyncHealth = async (): Promise<SyncHealthResponse> => {
  const endpoint = getEndpoint('recognitionSyncHealth');
  return fetchRequiredApi<SyncHealthResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(10_000),
  });
};

export const fetchSyncStatus = async (): Promise<SyncStatusResponse> => {
  const endpoint = getEndpoint('recognitionSyncStatus');
  return fetchRequiredApi<SyncStatusResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(10_000),
  });
};

export const triggerSync = async (): Promise<SyncTriggerResponse> => {
  const endpoint = getEndpoint('recognitionSyncTrigger');
  return fetchRequiredApi<SyncTriggerResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(30_000),
  });
};

export const resetMirror = async (): Promise<SyncTriggerResponse> => {
  const endpoint = getEndpoint('recognitionSyncResetMirror');
  return fetchRequiredApi<SyncTriggerResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(30_000),
  });
};
