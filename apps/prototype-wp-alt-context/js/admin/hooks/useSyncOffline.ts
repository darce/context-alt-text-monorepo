import { isSyncOffline } from '../pages/workbench/degradedModeBannerLogic';

import { useSyncHealth } from './useSyncHealth';

export const SYNC_AVAILABILITY = {
  ONLINE: 'online',
  OFFLINE: 'offline',
  UNAVAILABLE: 'unavailable',
} as const;

export type SyncAvailability = (typeof SYNC_AVAILABILITY)[keyof typeof SYNC_AVAILABILITY];

const assertNever = (value: never): never => {
  throw new Error(`Unhandled sync availability: ${String(value)}`);
};

export const resolveSyncAvailability = (
  health: Parameters<typeof isSyncOffline>[0] | null | undefined,
): SyncAvailability => {
  if (!health) {
    return SYNC_AVAILABILITY.UNAVAILABLE;
  }

  return isSyncOffline(health) ? SYNC_AVAILABILITY.OFFLINE : SYNC_AVAILABILITY.ONLINE;
};

/**
 * Shared offline signal for remote-compute fail-fast gating (RES-15, RES-03).
 * Unknown or unavailable health is intentionally gated: absence of an
 * authoritative healthy result must not be presented as an online backend.
 */
export const useSyncOffline = (): boolean => {
  const { data } = useSyncHealth();
  const availability = resolveSyncAvailability(data);

  switch (availability) {
    case SYNC_AVAILABILITY.ONLINE:
      return false;
    case SYNC_AVAILABILITY.OFFLINE:
    case SYNC_AVAILABILITY.UNAVAILABLE:
      return true;
    default:
      return assertNever(availability);
  }
};
