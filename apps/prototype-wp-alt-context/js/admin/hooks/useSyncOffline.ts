import { isSyncOffline } from '../pages/workbench/degradedModeBannerLogic';

import { useSyncHealth } from './useSyncHealth';

/**
 * Shared offline signal for remote-compute fail-fast gating (RES-15, RES-03).
 * Returns false while health is loading so actions are never gated before an
 * authoritative breaker result (mirrors the !health banner guard).
 */
export const useSyncOffline = (): boolean => {
  const { data } = useSyncHealth();
  return data ? isSyncOffline(data) : false;
};
