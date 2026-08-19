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
 *
 * S5-02: survivor lookup is lazy on each render (not memoized against only
 * retired/openClusterId). record-after-404 must rebind once the map is
 * populated, including upgrading a prior close for the same open id.
 */

import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { __ } from '@wordpress/i18n';

import { fetchClusterMembers } from '../../../api/recognition';
import { queryKeys } from '../../../api/queryKeys';
import { AuthExpiredError, HTTPError } from '../../../utils/http';

export type LiveReviewTargetStatus = 'live' | 'rebound' | 'retired' | 'auth_expired';

export interface LiveReviewTargetResult {
  status: LiveReviewTargetStatus;
  resolvedClusterId: string | null;
  /** Existence-probe error when status is auth_expired; null otherwise. */
  error: unknown | null;
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

  // Exactly-once / upgrade-aware retirement handling per open-target id.
  // E215-BR-06: single ref — action alone is enough (reset on openClusterId change).
  const handledActionRef = useRef<'rebind' | 'close' | null>(null);

  useEffect(() => {
    handledActionRef.current = null;
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
    // BR-70: this limit:1 probe IS the criterion-4 retirement-detection
    // mechanism — a 404 is the retirement signal. Modest staleTime/gcTime keep
    // incidental re-renders (and brief remounts) from re-issuing it; an explicit
    // invalidation still refetches, so a real retirement 404 still lands.
    staleTime: 5_000,
    gcTime: 30_000,
    // Never retry a definitive retirement 404 or auth expiry; other errors may retry once.
    retry: (failureCount, error) => {
      if (isClusterNotFound(error)) {
        return false;
      }
      if (error instanceof AuthExpiredError) {
        return false;
      }
      return failureCount < 1;
    },
  });

  const retired = openClusterId != null && existenceQuery.isError && isClusterNotFound(existenceQuery.error);
  const authExpired =
    openClusterId != null && existenceQuery.isError && existenceQuery.error instanceof AuthExpiredError;

  // S5-02: resolve survivor lazily at read time — do not memoize against
  // [retired, openClusterId] alone. recordMergeSurvivor mutates a ref-backed
  // map without changing those deps; a memoized null after 404 stayed stale
  // forever (close instead of rebind) once the map was populated on a later
  // render. optsRef always holds the latest resolveSurvivor.
  let survivorId: string | null = null;
  if (retired && openClusterId != null) {
    const survivor = optsRef.current.resolveSurvivor?.(openClusterId) ?? null;
    if (survivor && survivor !== openClusterId) {
      survivorId = survivor;
    }
  }

  // Auth expiry must not be absorbed into fail-safe 'live' (UXP-NET-2 / FORM-05).
  // Keep resolvedClusterId so in-progress UI is not wiped ([INT-11]).
  const status: LiveReviewTargetStatus = authExpired
    ? 'auth_expired'
    : !retired
      ? 'live'
      : survivorId
        ? 'rebound'
        : 'retired';

  const resolvedClusterId: string | null =
    status === 'live' || status === 'auth_expired'
      ? openClusterId
      : status === 'rebound'
        ? survivorId
        : null;

  const error: unknown | null = authExpired ? existenceQuery.error : null;

  // Side effects: announce + rebind/close. Prefer rebind; allow late upgrade
  // when survivor lands after a prior close for the same open id.
  useEffect(() => {
    if (!retired || openClusterId == null) {
      return;
    }

    const { onAnnounce: announce, onRebind: rebind, onClose: close } = optsRef.current;
    // BR-64: only claim a rebind when this consumer can actually rebind. A queue
    // head (onRebind undefined) owns no bound pane to advance, so the survivor is
    // effectively gone for it — announcing the rebind copy there is a false AT
    // claim. Fall to the honest close copy unless a real rebind sink is wired.
    if (survivorId && rebind) {
      if (handledActionRef.current === 'rebind') {
        return;
      }
      handledActionRef.current = 'rebind';
      announce?.(__('This group was merged — switched to the surviving group.', 'alt-context'));
      rebind(survivorId);
      return;
    }

    if (handledActionRef.current !== null) {
      return;
    }
    handledActionRef.current = 'close';
    announce?.(__('This review target is no longer available.', 'alt-context'));
    close?.();
  }, [retired, openClusterId, survivorId]);

  return { status, resolvedClusterId, error };
};
