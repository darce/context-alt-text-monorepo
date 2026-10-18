import { isSyncOffline } from '../pages/workbench/degradedModeBannerLogic';
import type { SyncHealthResponse } from '../api/recognition';

import { useSyncHealth } from './useSyncHealth';

export const SYNC_HEALTH_AVAILABILITY = {
  ONLINE: 'online',
  OFFLINE: 'offline',
  UNKNOWN: 'unknown',
} as const;

export type SyncHealthAvailability =
  (typeof SYNC_HEALTH_AVAILABILITY)[keyof typeof SYNC_HEALTH_AVAILABILITY];

export const getSyncHealthAvailability = (
  health: SyncHealthResponse | undefined,
): SyncHealthAvailability => {
  if (!health) {
    return SYNC_HEALTH_AVAILABILITY.UNKNOWN;
  }

  return isSyncOffline(health)
    ? SYNC_HEALTH_AVAILABILITY.OFFLINE
    : SYNC_HEALTH_AVAILABILITY.ONLINE;
};

/**
 * Shared offline signal for remote-compute fail-fast gating (RES-15, RES-03).
 * Unknown health is a distinct state and is gated until an authoritative
 * online result arrives (CAL-02).
 */
export const useSyncOffline = (): boolean => {
  const { data, isLoading } = useSyncHealth();
  return isLoading || getSyncHealthAvailability(data) !== SYNC_HEALTH_AVAILABILITY.ONLINE;
};
