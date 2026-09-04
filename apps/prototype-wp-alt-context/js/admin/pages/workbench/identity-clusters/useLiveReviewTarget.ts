/**
 * Live-derived open review target (E21-5 §11 / FBT-1 ⑤ / B1).
 *
 * Existence probe: members fetch with limit:1. A 404 is the retirement signal
 * (`cluster_not_found`). Transient/5xx/network errors are NOT retirement —
 * the probe fails open to status `'unverified'`, which keeps the pane mounted
 * without claiming the target was seen (FEBT1-LD-03).
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
import { classifyError, isHttpStatus } from '../../../utils/appError';
import { shouldRetryRequest } from '../../../utils/retryPolicy';
import { isAbortError } from './clusterMutationUtils';

/**
 * Canonical status set for the open-review-target probe (sr-007).
 *
 * `UNVERIFIED` is the designed third state (RLSE-04 / REF-33): the probe has not
 * answered — still in flight, or it failed with something that is not a
 * retirement or an auth expiry. It is NOT retirement.
 *
 * Fail-open is deliberate and asymmetric: this probe guards a *read* surface, and
 * closing an operator's open review pane on a 503 blip is destructive, so an
 * unanswered probe keeps the pane mounted. The duplicate-lookup guard on the
 * *write* path must fail closed for the same null. Same absence of an answer,
 * opposite correct default — which is why they cannot share one channel.
 */
export const LIVE_REVIEW_TARGET_STATUS = {
  /** Probe answered 200: the target provably exists. */
  LIVE: 'live',
  /** Probe has not answered (in flight, or a non-terminal failure). Keep the pane open. */
  UNVERIFIED: 'unverified',
  REBOUND: 'rebound',
  RETIRED: 'retired',
  AUTH_EXPIRED: 'auth_expired',
} as const;

export type LiveReviewTargetStatus =
  (typeof LIVE_REVIEW_TARGET_STATUS)[keyof typeof LIVE_REVIEW_TARGET_STATUS];

/** True when the target must stay mounted: everything except a definitive retirement. */
export const isOpenTargetRetained = (status: LiveReviewTargetStatus): boolean =>
  status !== LIVE_REVIEW_TARGET_STATUS.RETIRED && status !== LIVE_REVIEW_TARGET_STATUS.REBOUND;

export interface LiveReviewTargetResult {
  status: LiveReviewTargetStatus;
  resolvedClusterId: string | null;
  /**
   * Existence-probe error, null while the probe has not failed.
   *
   * FEBT1-W2A-06 / FEBT1-LD-03: `status` now carries the unverified state itself
   * (`'unverified'`), so a consumer no longer has to read `error` to tell
   * "checked and present" from "never got an answer". `error` remains the
   * *reason* channel: non-null on every probe failure, including the 5xx blips
   * that keep the pane open.
   */
  error: unknown;
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

const isClusterNotFound = (err: unknown): boolean => isHttpStatus(err, 404);
const isAuthExpired = (err: unknown): boolean => classifyError(err)._tag === 'auth_expired';

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
    // Never retry a definitive retirement 404, an auth expiry, or an abort/
    // timeout; anything else follows the shared policy, capped at one retry so
    // the probe cannot outlive the pane it guards. FEBT1-GATE-06: the comment
    // and the predicate must not drift — the classification lives in
    // shouldRetryRequest, not in a hand-rolled copy of it.
    retry: (failureCount, error) => {
      if (isClusterNotFound(error) || isAuthExpired(error) || isAbortError(error)) {
        return false;
      }
      return failureCount < 1 && shouldRetryRequest(failureCount, error);
    },
  });

  const retired = openClusterId != null && existenceQuery.isError && isClusterNotFound(existenceQuery.error);
  const authExpired = openClusterId != null && existenceQuery.isError && isAuthExpired(existenceQuery.error);

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

  // FEBT1-LD-03: `'live'` is a claim of existence, so only a settled 200 may make
  // it. Reading a success-side query field subscribes this consumer to the success
  // transition and costs one extra render — that is exactly the render the shared
  // announcement channel used to lose a message to (FEBT1-LD-02), which is why the
  // channel had to be split before this state could exist.
  const verified = existenceQuery.isSuccess;

  // Auth expiry must not be absorbed into the fail-open default (UXP-NET-2 / FORM-05).
  // Keep resolvedClusterId so in-progress UI is not wiped ([INT-11]).
  const status: LiveReviewTargetStatus = authExpired
    ? LIVE_REVIEW_TARGET_STATUS.AUTH_EXPIRED
    : retired
      ? survivorId
        ? LIVE_REVIEW_TARGET_STATUS.REBOUND
        : LIVE_REVIEW_TARGET_STATUS.RETIRED
      : verified
        ? LIVE_REVIEW_TARGET_STATUS.LIVE
        : LIVE_REVIEW_TARGET_STATUS.UNVERIFIED;

  const resolvedClusterId: string | null =
    status === LIVE_REVIEW_TARGET_STATUS.REBOUND
      ? survivorId
      : status === LIVE_REVIEW_TARGET_STATUS.RETIRED
        ? null
        : openClusterId;

  // Surface every probe failure, not only auth expiry: a consumer that reads a
  // null error as "verified live" would be consuming "I don't know" as "I
  // checked and it is there". Only `isError`/`error` are read here — reading
  // further query fields would subscribe consumers to extra re-renders.
  const error: unknown = existenceQuery.isError ? existenceQuery.error : null;

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
