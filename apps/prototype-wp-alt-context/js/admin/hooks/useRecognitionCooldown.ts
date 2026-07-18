import { useEffect, useReducer, useSyncExternalStore } from 'react';

import {
  cooldownRemainingSeconds,
  getCooldownExpiresAt,
  isCoolingDown,
  subscribeToCooldown,
} from '../utils/recognitionCooldown';

export interface RecognitionCooldownState {
  isCoolingDown: boolean;
  remainingSeconds: number;
}

/**
 * Observable recognition-cooldown state for UI surfaces (RES-15/OBS-05):
 * exposes the live window plus remaining seconds so frozen surfaces can
 * announce it (RLSE-04/A11Y-21). Re-renders on window changes (subscribe) and
 * once per second while a window is open; values are always computed from the
 * expiry timestamp at render time (REF-09).
 */
export const useRecognitionCooldown = (): RecognitionCooldownState => {
  const expiresAt = useSyncExternalStore(subscribeToCooldown, getCooldownExpiresAt, getCooldownExpiresAt);
  const [, tick] = useReducer((count: number) => count + 1, 0);

  useEffect(() => {
    if (Date.now() >= expiresAt) {
      return undefined;
    }
    const intervalId = window.setInterval(() => {
      tick();
      if (Date.now() >= expiresAt) {
        window.clearInterval(intervalId);
      }
    }, 1_000);
    return () => window.clearInterval(intervalId);
  }, [expiresAt]);

  return { isCoolingDown: isCoolingDown(), remainingSeconds: cooldownRemainingSeconds() };
};
