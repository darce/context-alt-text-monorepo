/**
 * Live-derived open review target (E21-5 §11 / FBT-1 ⑤ / B1).
 *
 * Existence probe: members fetch with limit:1. A 404 is the retirement signal
 * (`cluster_not_found`). Transient/5xx/network errors are NOT retirement —
 * fail-safe keeps status `'live'`.
 *
 * On retirement:
 *   (B) recorded local-merge survivor → onRebind + announce (once)
 *   (A) no survivor / remote dismiss → onClose + announce (once)
 *
 * Self-heal: after (B) rebind, the remounted panel re-runs this hook on the
 * guessed survivor; a second 404 with no further survivor falls to (A).
 */

import { useEffect, useMemo, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { fetchClusterMembers } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';
import { HTTPError } from '../../../utils/http';

export type LiveReviewTargetStatus = 'live' | 'rebound' | 'retired';

export interface LiveReviewTargetResult {
  status: LiveReviewTargetStatus;
  resolvedClusterId: string | null;
}

export interface UseLiveReviewTargetOptions {
  resolveSurvivor?: (retiredClusterId: string) => string | null;
  onAnnounce?: (message: string) => void;
  onRebind?: (survivorClusterId: string) => void;
  onClose?: () => void;
}

/** A11Y-21 copy — branch (A) close path. */
export const LIVE_TARGET_CLOSE_ANNOUNCE = 'This review target is no longer available.';

/** A11Y-21 copy — branch (B) rebind path. */
export const LIVE_TARGET_REBIND_ANNOUNCE = 'This group was merged — switched to the surviving group.';

const isClusterNotFound = (err: unknown): boolean => err instanceof HTTPError && err.status === 404;

export const useLiveReviewTarget = (
  openClusterId: string | null,
  opts: UseLiveReviewTargetOptions = {},
): LiveReviewTargetResult => {
  // Keep latest callbacks without re-firing side effects on identity churn.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  // Exactly-once retirement handling per open-target id.
  const handledForRef = useRef<string | null>(null);

  useEffect(() => {
    handledForRef.current = null;
  }, [openClusterId]);

  const existenceQuery = useQuery({
    // Distinct subkey so limit:1 does not poison the full members cache.
    queryKey: openClusterId
      ? ([...queryKeys.clusters.memberList(openClusterId), 'live-target'] as const)
      : (['clusters', 'members', null, 'live-target'] as const),
    queryFn: () => {
      if (!openClusterId) {
        throw new Error('useLiveReviewTarget queryFn called without openClusterId');
      }
      return fetchClusterMembers(openClusterId, { limit: 1 });
    },
    enabled: openClusterId != null,
    // Never retry a definitive retirement 404; other errors may retry once.
    retry: (failureCount, error) => {
      if (isClusterNotFound(error)) {
        return false;
      }
      return failureCount < 1;
    },
  });

  const retired = openClusterId != null && existenceQuery.isError && isClusterNotFound(existenceQuery.error);

  const survivorId = useMemo(() => {
    if (!retired || openClusterId == null) {
      return null;
    }
    const survivor = optsRef.current.resolveSurvivor?.(openClusterId) ?? null;
    if (survivor && survivor !== openClusterId) {
      return survivor;
    }
    return null;
  }, [retired, openClusterId, existenceQuery.errorUpdatedAt]);

  const status: LiveReviewTargetStatus = !retired ? 'live' : survivorId ? 'rebound' : 'retired';

  const resolvedClusterId: string | null =
    status === 'live' ? openClusterId : status === 'rebound' ? survivorId : null;

  // Side effects: announce + rebind/close exactly once per open target.
  useEffect(() => {
    if (!retired || openClusterId == null) {
      return;
    }
    if (handledForRef.current === openClusterId) {
      return;
    }
    handledForRef.current = openClusterId;

    const { onAnnounce: announce, onRebind: rebind, onClose: close } = optsRef.current;
    if (survivorId) {
      announce?.(__(LIVE_TARGET_REBIND_ANNOUNCE, 'alt-context'));
      rebind?.(survivorId);
      return;
    }
    announce?.(__(LIVE_TARGET_CLOSE_ANNOUNCE, 'alt-context'));
    close?.();
  }, [retired, openClusterId, survivorId]);

  return { status, resolvedClusterId };
};
