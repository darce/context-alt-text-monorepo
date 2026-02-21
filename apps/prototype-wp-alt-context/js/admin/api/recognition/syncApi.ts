import { fetchRequiredApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { SyncStatusResponse, SyncTriggerResponse } from './types';
import { createRecognitionTimeoutSignal } from './requestTimeout';

export const fetchSyncStatus = async (): Promise<SyncStatusResponse> => {
  const endpoint = getEndpoint('recognitionSyncStatus');
  return fetchRequiredApi<SyncStatusResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(2_000),
  });
};

export const triggerSync = async (): Promise<SyncTriggerResponse> => {
  const endpoint = getEndpoint('recognitionSyncTrigger');
  return fetchRequiredApi<SyncTriggerResponse>(endpoint, {
    method: 'POST',
    restNonce: getConfig().nonce,
    signal: createRecognitionTimeoutSignal(5_000),
  });
};
