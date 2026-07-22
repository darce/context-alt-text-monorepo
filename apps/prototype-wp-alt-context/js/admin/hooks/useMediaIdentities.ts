import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../api/queryKeys';
import { fetchMediaIdentities, type MediaIdentitiesResponse } from '../api/recognition';
import {
  cooldownRemainingMs,
  DEFAULT_COOLDOWN_SECONDS,
  gateRefetchInterval,
  runAfterCooldown,
} from '../utils/recognitionCooldown';

/**
 * Floor for the one-shot post-error recovery delay. Dominant failure mode is a
 * 2s TimeoutError which never opens the 429/503 cooldown; without a floor the
 * deferred refetch would fire immediately. Derived from the shared cooldown
 * default so recovery stays on one vocabulary (UXP-2 seam).
 */
export const RECOVERY_DELAY_FLOOR_MS = DEFAULT_COOLDOWN_SECONDS * 1000;

/**
 * Check if any identities are pending clustering assignment.
 * When faces are detected, they may not immediately have a cluster assigned
 * because clustering runs asynchronously. This helper determines if we should
 * poll for updates.
 */
const hasPendingClustering = (data: MediaIdentitiesResponse | undefined): boolean => {
  if (!data?.identities_by_media) {
    return false;
  }
  return Object.values(data.identities_by_media).some((identities) =>
    identities.some((identity) => identity.clustering_pending),
  );
};

const serializeQueryKey = (mediaIds: number[]): string => mediaIds.join(',');

export const useMediaIdentities = (mediaIds: number[], enabled = true) => {
  const queryKey = queryKeys.media.identitiesByIds(mediaIds);
  const keySerialized = serializeQueryKey(mediaIds);
  /**
   * Per-query-key one-shot latch: set when the deferred recovery actually fires.
   * Resets only on success or when the serialized key changes. A second consecutive
   * error (recovery refetch fails) does not re-arm because the latch already matches.
   */
  const recoveryLatchKeyRef = useRef<string | null>(null);
  /** Tracks an in-flight scheduled recovery so strict-mode double-mount does not double-arm. */
  const pendingRecoveryKeyRef = useRef<string | null>(null);

  const query = useQuery<MediaIdentitiesResponse>({
    queryKey,
    queryFn: () => fetchMediaIdentities(mediaIds),
    enabled: enabled && mediaIds.length > 0,
    // Deliberate exception to shared retry: conditional query already stops polling on error;
    // next scheduled poll (recognition cooldown in slice 2) is the retry. [RES-06]
    retry: false,
    staleTime: 15_000,
    placeholderData: (previousData) => previousData,
    // Auto-poll every 3 seconds when there are identities pending cluster assignment.
    // This provides automatic updates when clustering completes without manual refresh.
    refetchInterval: gateRefetchInterval((queryState) => {
      if (queryState.state.status === 'error') {
        return false;
      }
      return hasPendingClustering(queryState.state.data) ? 3000 : false;
    }),
  });

  // Stable refetch handle so the recovery effect does not re-run (and cancel its timer)
  // when React Query returns a new refetch function identity each render.
  const refetchRef = useRef(query.refetch);
  refetchRef.current = query.refetch;

  // Drop episode state when the query key changes so a new key can arm independently.
  const prevKeyRef = useRef(keySerialized);
  if (prevKeyRef.current !== keySerialized) {
    prevKeyRef.current = keySerialized;
    recoveryLatchKeyRef.current = null;
    pendingRecoveryKeyRef.current = null;
  }

  useEffect(() => {
    if (query.isSuccess) {
      recoveryLatchKeyRef.current = null;
      pendingRecoveryKeyRef.current = null;
      return;
    }

    if (!enabled || mediaIds.length === 0 || !query.isError) {
      return;
    }

    // Episode already consumed (recovery fired once for this key) — do not re-arm.
    if (recoveryLatchKeyRef.current === keySerialized) {
      return;
    }

    // Timer already pending for this key (e.g. effect re-entry) — do not double-schedule.
    if (pendingRecoveryKeyRef.current === keySerialized) {
      return;
    }
    pendingRecoveryKeyRef.current = keySerialized;

    const delayMs = Math.max(cooldownRemainingMs(), RECOVERY_DELAY_FLOOR_MS);
    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      if (cancelled) {
        return;
      }
      // Consume the episode at fire time so a failed recovery refetch does not re-arm.
      recoveryLatchKeyRef.current = keySerialized;
      pendingRecoveryKeyRef.current = null;
      // Defer further if a cooldown opened/extended during the floor wait.
      runAfterCooldown(() => {
        if (!cancelled) {
          void refetchRef.current();
        }
      });
    }, delayMs);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
      if (pendingRecoveryKeyRef.current === keySerialized) {
        pendingRecoveryKeyRef.current = null;
      }
    };
  }, [enabled, keySerialized, mediaIds.length, query.isError, query.isSuccess]);

  return query;
};
