/**
 * Owner-side open-target lifecycle wiring (E21-5 §11 / FBT-1 ⑤ / PR-34).
 *
 * The always-mounted review owner (ScanTabContent) calls this with the review
 * cluster id the panel reducer currently requests. It returns `reviewClusterId`
 * — the cluster whose review panel should actually be mounted — after resolving
 * the open-target retirement invariant:
 *   (B) survivor recorded → rebind: advance to the survivor and announce.
 *   (A) no survivor       → close: clear the target, announce, focus queue root.
 * Self-heal falls out for free: after a rebind the advanced target is re-probed,
 * so a survivor that also 404s walks to (A).
 *
 * Why the advance is render-phase (not the hook's effect callbacks): advancing
 * the open target remounts the react-query-observing review panel. In the
 * act-wrapped test harness (`notifyManager` scheduler = `act`), a state update
 * scheduled from a passive-effect flush that triggers such a remount is dropped
 * — both the announce and the advance are lost. Deriving the transition from the
 * hook's synchronous `status`/`resolvedClusterId` during render, and updating
 * only the owner's own state, sidesteps the scheduler entirely and is reliable
 * in both the test and production. Imperative close work (focus, reducer reset)
 * runs in a post-commit effect, where a plain call — not a dropped update — is
 * all that's needed.
 */

import { useEffect, useRef, useState } from 'react';
import { __ } from '@wordpress/i18n';

import { useMergeSurvivors } from './MergeSurvivorContext';
import {
  LIVE_TARGET_CLOSE_ANNOUNCE,
  LIVE_TARGET_REBIND_ANNOUNCE,
  useLiveReviewTarget,
} from './useLiveReviewTarget';

export interface UseOpenReviewTargetLifecycleParams {
  /** Review cluster id the panel reducer currently requests (user open), or null. */
  requestedClusterId: string | null;
  /** Persistent (owner-owned) A11Y-21 announce sink. Called render-phase. */
  onAnnounce: (message: string) => void;
  /** Focus the queue root anchor after a retirement close. */
  onFocusQueueRoot?: () => void;
  /** Reset the panel reducer to closed after a retirement close (canonical sync). */
  onRetireClose?: () => void;
  /**
   * BR-66: sync the panel reducer to the survivor after a rebind (canonical
   * sync, mirroring onRetireClose). Fired post-commit — never render-phase — so
   * it does not clobber the advanced open target.
   */
  onRebindSync?: (survivorClusterId: string) => void;
}

export interface UseOpenReviewTargetLifecycleResult {
  /** Cluster id whose review panel should currently be mounted, or null. */
  reviewClusterId: string | null;
}

export const useOpenReviewTargetLifecycle = ({
  requestedClusterId,
  onAnnounce,
  onFocusQueueRoot,
  onRetireClose,
  onRebindSync,
}: UseOpenReviewTargetLifecycleParams): UseOpenReviewTargetLifecycleResult => {
  const { resolveSurvivor } = useMergeSurvivors();
  const [openTarget, setOpenTarget] = useState<string | null>(requestedClusterId);
  const requestedRef = useRef<string | null>(requestedClusterId);
  const handledRef = useRef<string | null>(null);
  /** E215-BR-01: closed cluster id after retire-with-no-survivor, for late rebind. */
  const pendingRetireIdRef = useRef<string | null>(null);
  const retireCloseRef = useRef(false);
  const rebindSyncRef = useRef<string | null>(null);

  // Sync user-driven open/close (reducer) into the local effective target. A
  // retirement advance below keeps `requestedRef` unchanged, so it is never
  // clobbered by this sync.
  if (requestedClusterId !== requestedRef.current) {
    requestedRef.current = requestedClusterId;
    setOpenTarget(requestedClusterId);
    handledRef.current = null;
    // Abandon pending late-rebind only on a user-driven non-null open. Canonical
    // onRetireClose sets requested → null and must NOT clear pendingRetireId
    // (E215-BR-01: record-after-404 rebind still needs the closed id).
    if (requestedClusterId !== null) {
      pendingRetireIdRef.current = null;
    }
  }

  const { status, resolvedClusterId } = useLiveReviewTarget(openTarget, {
    resolveSurvivor: (retiredId) => resolveSurvivor(retiredId),
  });

  // Render-phase retirement reconcile: announce + advance the open target
  // (rebind → survivor, retire → null) as owner-state updates, once per target.
  // auth_expired is not retirement — leave the open target mounted ([INT-11]).
  if (
    openTarget !== null &&
    (status === 'rebound' || status === 'retired') &&
    handledRef.current !== openTarget
  ) {
    handledRef.current = openTarget;
    onAnnounce(
      __(status === 'rebound' ? LIVE_TARGET_REBIND_ANNOUNCE : LIVE_TARGET_CLOSE_ANNOUNCE, 'alt-context'),
    );
    setOpenTarget(resolvedClusterId);
    if (resolvedClusterId === null) {
      // Remember the closed id so a survivor recorded after this latch (record-
      // after-404) can still rebind on a later render. The S5-02 upgrade in
      // useLiveReviewTarget alone is unreachable here: openTarget is nulled and
      // handled once, and ReviewQueue leaves onRebind/onClose undefined.
      pendingRetireIdRef.current = openTarget;
      retireCloseRef.current = true;
    } else {
      pendingRetireIdRef.current = null;
      // BR-66: defer the reducer→survivor sync to the post-commit effect. On the
      // next render requestedClusterId becomes the survivor (= openTarget), so
      // the requestedRef sync above is a no-op — no clobber, no requestedRef loop.
      rebindSyncRef.current = resolvedClusterId;
    }
  }

  // E215-BR-01: late rebind — survivor recorded after the retire-close latch.
  // re-check resolveSurvivor on subsequent renders (context revision or any
  // owner re-render after accept). Prefer rebind over staying closed.
  if (openTarget === null && pendingRetireIdRef.current !== null) {
    const retiredId = pendingRetireIdRef.current;
    const survivor = resolveSurvivor(retiredId);
    if (survivor && survivor !== retiredId) {
      pendingRetireIdRef.current = null;
      handledRef.current = survivor;
      onAnnounce(__('This group was merged — switched to the surviving group.', 'alt-context'));
      setOpenTarget(survivor);
      rebindSyncRef.current = survivor;
    }
  }

  // Retirement close / rebind sync are imperative (focus + reducer): run after
  // commit, where a plain call is reliable even in the act-wrapped harness.
  useEffect(() => {
    if (retireCloseRef.current) {
      retireCloseRef.current = false;
      onFocusQueueRoot?.();
      onRetireClose?.();
    }
    if (rebindSyncRef.current !== null) {
      const survivor = rebindSyncRef.current;
      rebindSyncRef.current = null;
      onRebindSync?.(survivor);
    }
  });

  return { reviewClusterId: openTarget };
};
