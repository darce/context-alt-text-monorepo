import { fetchRequiredApi } from '../../utils/http';
import { getEndpoint, getConfig } from '../config';
import type { SyncStatusResponse } from './types';

export const fetchSyncStatus = async (): Promise<SyncStatusResponse> => {
  const endpoint = getEndpoint('recognitionSyncStatus');
  return fetchRequiredApi<SyncStatusResponse>(endpoint, {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
};
