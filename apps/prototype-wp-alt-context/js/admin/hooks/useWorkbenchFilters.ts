import { ChangeEvent, useCallback, useEffect, useMemo, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { WORKBENCH_MEDIA_STATUSES, type WorkbenchMediaStatus } from '../api/workbenchMediaApi';
import {
  DEFAULT_QUEUE_STATE,
  parseQueueState,
  serializeQueueState,
  type ReviewQueueBandParam,
  type ReviewQueueKindParam,
  type WorkbenchQueueState,
} from './workbenchQueueUrl';

const MEDIA_PAGE_SIZE_OPTIONS = [10, 50, 100] as const;
const DEFAULT_MEDIA_PAGE_SIZE = MEDIA_PAGE_SIZE_OPTIONS[0];
const WORKBENCH_MEDIA_STATUS_SET: ReadonlySet<string> = new Set(WORKBENCH_MEDIA_STATUSES);

const parseWorkbenchMediaStatus = (value: string | null): WorkbenchMediaStatus =>
  value && WORKBENCH_MEDIA_STATUS_SET.has(value) ? (value as WorkbenchMediaStatus) : 'all';

export type { WorkbenchQueueState };
export {
  bandParamToBand,
  bandToBandParam,
  DEFAULT_QUEUE_STATE,
  filterToKindParam,
  kindParamToFilter,
  parseQueueState,
  REVIEW_QUEUE_BAND_PARAM,
  REVIEW_QUEUE_KIND_PARAM,
  serializeQueueState,
  type ReviewQueueBandParam,
  type ReviewQueueKindParam,
} from './workbenchQueueUrl';

/**
 * UXW2-1: one user action → exactly one `rq=` write (DATA-14). Reducer-style
 * actions; kind/band/clear reset index INSIDE the reducer so callers never
 * issue a second same-tick write. Enum-keyed handler map (REF-02, sr-007).
 */
export const QUEUE_ACTION = {
  SET_KIND: 'set_kind',
  SET_BAND: 'set_band',
  SET_INDEX: 'set_index',
  CLEAR_FILTERS: 'clear_filters',
  CLAMP_INDEX: 'clamp_index',
} as const;

export type QueueAction =
  | { type: typeof QUEUE_ACTION.SET_KIND; kind: ReviewQueueKindParam }
  | { type: typeof QUEUE_ACTION.SET_BAND; band: ReviewQueueBandParam }
  | { type: typeof QUEUE_ACTION.SET_INDEX; index: number }
  | { type: typeof QUEUE_ACTION.CLAMP_INDEX; index: number }
  | { type: typeof QUEUE_ACTION.CLEAR_FILTERS };

const QUEUE_ACTION_HANDLERS: {
  readonly [T in QueueAction['type']]: (
    state: WorkbenchQueueState,
    action: Extract<QueueAction, { type: T }>,
  ) => WorkbenchQueueState;
} = {
  [QUEUE_ACTION.SET_KIND]: (state, action) => ({ ...state, kind: action.kind, index: 0 }),
  [QUEUE_ACTION.SET_BAND]: (state, action) => ({ ...state, band: action.band, index: 0 }),
  [QUEUE_ACTION.SET_INDEX]: (state, action) => ({ ...state, index: action.index }),
  [QUEUE_ACTION.CLAMP_INDEX]: (state, action) => ({ ...state, index: Math.max(0, action.index) }),
  [QUEUE_ACTION.CLEAR_FILTERS]: () => ({ ...DEFAULT_QUEUE_STATE }),
};

export const reduceQueueAction = (state: WorkbenchQueueState, action: QueueAction): WorkbenchQueueState => {
  const handler = QUEUE_ACTION_HANDLERS[action.type] as (
    s: WorkbenchQueueState,
    a: QueueAction,
  ) => WorkbenchQueueState;
  return handler(state, action);
};

export const useWorkbenchFilters = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const searchQuery = searchParams.get('s') ?? '';
  const currentPageStr = searchParams.get('p') ?? '1';
  const currentPage = Number.parseInt(currentPageStr, 10) || 1;
  const perPageStr = searchParams.get('perPage');
  const perPageParsed = perPageStr ? Number.parseInt(perPageStr, 10) : DEFAULT_MEDIA_PAGE_SIZE;
  const perPage = MEDIA_PAGE_SIZE_OPTIONS.includes(perPageParsed as (typeof MEDIA_PAGE_SIZE_OPTIONS)[number])
    ? perPageParsed
    : DEFAULT_MEDIA_PAGE_SIZE;
  const statusFilter = parseWorkbenchMediaStatus(searchParams.get('status'));

  // E21-5: review-queue position/filter/band (rq=<kind>.<band>.<index>).
  const queueState = useMemo(() => parseQueueState(searchParams.get('rq')), [searchParams]);

  const handleSearchChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const s = event.target.value;
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (s) {
            next.set('s', s);
          } else {
            next.delete('s');
          }
          next.set('p', '1');
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const handleStatusChange = useCallback(
    (status: WorkbenchMediaStatus) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('status', status);
          next.set('p', '1');
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const setCurrentPage = useCallback(
    (page: number) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('p', page.toString());
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const setPerPage = useCallback(
    (nextPerPage: number) => {
      if (!MEDIA_PAGE_SIZE_OPTIONS.includes(nextPerPage as (typeof MEDIA_PAGE_SIZE_OPTIONS)[number])) {
        return;
      }

      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set('perPage', nextPerPage.toString());
          next.set('p', '1');
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // RLSE-06 defence: react-router's functional setSearchParams updater reads the
  // RENDER snapshot, so two writes in one tick both see the pre-click URL and the
  // last wins. Write-through the last dispatched queue state so any stray
  // same-tick second dispatch merges against it, never against a stale snapshot.
  const pendingQueueRef = useRef<WorkbenchQueueState | null>(null);
  useEffect(() => {
    pendingQueueRef.current = null;
  }, [searchParams]);

  const writeQueueState = useCallback(
    (nextState: WorkbenchQueueState): void => {
      pendingQueueRef.current = nextState;
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          const serialized = serializeQueueState(nextState);
          if (serialized === null) {
            next.delete('rq');
          } else {
            next.set('rq', serialized);
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /**
   * Merge partial queue state into `rq=` without clobbering unrelated params
   * (coexists with tab/panel/s/p/status writers).
   */
  const setQueueState = useCallback(
    (partial: Partial<WorkbenchQueueState>) => {
      const base = pendingQueueRef.current ?? queueState;
      writeQueueState({
        kind: partial.kind ?? base.kind,
        band: partial.band ?? base.band,
        index: partial.index ?? base.index,
      });
    },
    [queueState, writeQueueState],
  );

  const dispatchQueue = useCallback(
    (action: QueueAction): void => {
      writeQueueState(reduceQueueAction(pendingQueueRef.current ?? queueState, action));
    },
    [queueState, writeQueueState],
  );

  const getQueueState = useCallback((): WorkbenchQueueState => queueState, [queueState]);

  const normalizedSearch = useMemo(() => searchQuery.trim(), [searchQuery]);

  return {
    searchQuery,
    currentPage,
    perPage,
    statusFilter,
    setCurrentPage,
    setPerPage,
    handleSearchChange,
    handleStatusChange,
    normalizedSearch,
    queueState,
    getQueueState,
    setQueueState,
    dispatchQueue,
  } as const;
};
