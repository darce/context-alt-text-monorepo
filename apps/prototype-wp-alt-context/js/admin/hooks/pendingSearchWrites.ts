import { APP_LINK_PARAMS } from '../navigation/appLinks';
import { serializeQueueState, type WorkbenchQueueState } from './workbenchQueueUrl';

/**
 * Shared across every `useWorkbenchFilters` instance (ScanTabContent +
 * WorkbenchMediaProvider). Per-hook refs lose same-commit p/rq writes
 * because react-router's updater reads the render snapshot (R1-01).
 */
interface PendingSearchWrites {
  rq?: WorkbenchQueueState;
  /** URL `rq` at the moment the pending write was first queued. */
  rqSnapshot?: string | null;
  p?: number;
  pSnapshot?: string | null;
}

let pendingSearchWrites: PendingSearchWrites = {};
let workbenchFilterInstanceCount = 0;

const clearPendingSearchWrites = (): void => {
  pendingSearchWrites = {};
};

/** Test-only: isolate module-level write-through between cases (TEST-07). */
export const resetPendingSearchWritesForTests = (): void => {
  clearPendingSearchWrites();
  workbenchFilterInstanceCount = 0;
};

/** Test-only: observe the module buffer. Do not use reset to hide a live ghost. */
export const peekPendingSearchWritesForTests = (): PendingSearchWrites => ({
  ...pendingSearchWrites,
});

export const applyPendingSearchWrites = (prev: URLSearchParams): URLSearchParams => {
  const next = new URLSearchParams(prev);
  if (pendingSearchWrites.rq !== undefined) {
    const serialized = serializeQueueState(pendingSearchWrites.rq);
    if (serialized === null) {
      next.delete(APP_LINK_PARAMS.rq);
    } else {
      next.set(APP_LINK_PARAMS.rq, serialized);
    }
  }
  if (pendingSearchWrites.p !== undefined) {
    next.set('p', String(pendingSearchWrites.p));
  }
  return next;
};

const pageMatches = (urlP: string | null, page: number): boolean =>
  urlP === String(page) || (page === 1 && urlP === null);

export const reconcilePendingSearchWrites = (searchParams: URLSearchParams): void => {
  if (pendingSearchWrites.rq !== undefined) {
    const urlRq = searchParams.get(APP_LINK_PARAMS.rq);
    const pendingRq = serializeQueueState(pendingSearchWrites.rq);
    if (urlRq === pendingRq) {
      delete pendingSearchWrites.rq;
      delete pendingSearchWrites.rqSnapshot;
    } else if (
      pendingSearchWrites.rqSnapshot == null ||
      urlRq !== pendingSearchWrites.rqSnapshot
    ) {
      // Null snapshot + empty dest is abandon: a landing would have written the value, and hook reconcile runs after setSearchParams flush so this is external-nav not in-flight.
      delete pendingSearchWrites.rq;
      delete pendingSearchWrites.rqSnapshot;
    }
  }
  if (pendingSearchWrites.p !== undefined) {
    const urlP = searchParams.get('p');
    if (pageMatches(urlP, pendingSearchWrites.p)) {
      delete pendingSearchWrites.p;
      delete pendingSearchWrites.pSnapshot;
    } else if (
      pendingSearchWrites.pSnapshot == null ||
      urlP !== pendingSearchWrites.pSnapshot
    ) {
      // Same contract as the rq null-snapshot arm: empty dest never acquired the pending page.
      delete pendingSearchWrites.p;
      delete pendingSearchWrites.pSnapshot;
    }
  }
};

type SearchParamsWriter = (
  nextInit: URLSearchParams | ((prev: URLSearchParams) => URLSearchParams),
  navigateOpts?: { replace?: boolean },
) => void;

/**
 * Shared write-through so every workbench URL writer merges the pending
 * `rq`/`p` buffer instead of last-write-winning against the render snapshot.
 */
export const commitSearchParams = (
  setSearchParams: SearchParamsWriter,
  mutate: (next: URLSearchParams) => void,
): void => {
  setSearchParams((prev) => {
    const next = applyPendingSearchWrites(prev);
    mutate(next);
    return next;
  }, { replace: true });
};

export const queuePendingQueueState = (nextState: WorkbenchQueueState, snapshotRq: string | null): void => {
  if (pendingSearchWrites.rq === undefined) {
    pendingSearchWrites.rqSnapshot = snapshotRq;
  }
  pendingSearchWrites.rq = nextState;
};

export const queuePendingPage = (page: number, snapshotP: string | null): void => {
  if (pendingSearchWrites.p === undefined) {
    pendingSearchWrites.pSnapshot = snapshotP;
  }
  pendingSearchWrites.p = page;
};

export const getPendingQueueState = (): WorkbenchQueueState | undefined => pendingSearchWrites.rq;

export const retainWorkbenchFilterInstance = (): (() => void) => {
  workbenchFilterInstanceCount += 1;
  return () => {
    workbenchFilterInstanceCount -= 1;
    if (workbenchFilterInstanceCount <= 0) {
      workbenchFilterInstanceCount = 0;
      clearPendingSearchWrites();
    }
  };
};
