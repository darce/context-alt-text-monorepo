import { ChangeEvent, useCallback, useEffect, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { WORKBENCH_MEDIA_STATUSES, type WorkbenchMediaStatus } from '../api/workbenchMediaApi';
import {
  commitSearchParams,
  getPendingQueueState,
  queuePendingPage,
  queuePendingQueueState,
  reconcilePendingSearchWrites,
  retainWorkbenchFilterInstance,
} from './pendingSearchWrites';
import {
  DEFAULT_QUEUE_STATE,
  parseQueueState,
  serializeQueueState,
  type ReviewQueueBandParam,
  type ReviewQueueKindParam,
  type WorkbenchQueueState,
} from './workbenchQueueUrl';

export const MEDIA_PAGE_SIZE_OPTIONS = [10, 50, 100] as const;
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
  STEP_INDEX: 'step_index',
} as const;

export type QueueAction =
  | { type: typeof QUEUE_ACTION.SET_KIND; kind: ReviewQueueKindParam }
  | { type: typeof QUEUE_ACTION.SET_BAND; band: ReviewQueueBandParam }
  | { type: typeof QUEUE_ACTION.SET_INDEX; index: number }
  | { type: typeof QUEUE_ACTION.CLAMP_INDEX; index: number }
  | { type: typeof QUEUE_ACTION.STEP_INDEX; delta: number; length: number }
  | { type: typeof QUEUE_ACTION.CLEAR_FILTERS };

const sanitizeIndex = (index: number): number => {
  if (!Number.isFinite(index)) {
    return 0;
  }
  return Math.max(0, Math.trunc(index));
};

const QUEUE_ACTION_HANDLERS: {
  readonly [T in QueueAction['type']]: (
    state: WorkbenchQueueState,
    action: Extract<QueueAction, { type: T }>,
  ) => WorkbenchQueueState;
} = {
  [QUEUE_ACTION.SET_KIND]: (state, action) => ({ ...state, kind: action.kind, index: 0 }),
  [QUEUE_ACTION.SET_BAND]: (state, action) => ({ ...state, band: action.band, index: 0 }),
  [QUEUE_ACTION.SET_INDEX]: (state, action) => ({ ...state, index: sanitizeIndex(action.index) }),
  [QUEUE_ACTION.CLAMP_INDEX]: (state, action) => ({ ...state, index: sanitizeIndex(action.index) }),
  [QUEUE_ACTION.STEP_INDEX]: (state, action) => {
    const length = Number.isFinite(action.length) ? Math.max(0, Math.trunc(action.length)) : 0;
    if (length <= 0) {
      return { ...state, index: 0 };
    }
    const delta = Number.isFinite(action.delta) ? Math.trunc(action.delta) : 0;
    const clamped = Math.min(sanitizeIndex(state.index), length - 1);
    return { ...state, index: Math.min(Math.max(0, clamped + delta), length - 1) };
  },
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

  useEffect(() => retainWorkbenchFilterInstance(), []);

  useEffect(() => {
    reconcilePendingSearchWrites(searchParams);
  }, [searchParams]);

  const writePage = useCallback(
    (page: number): void => {
      queuePendingPage(page, searchParams.get('p'));
      commitSearchParams(setSearchParams, (next) => {
        next.set('p', page.toString());
      });
    },
    [searchParams, setSearchParams],
  );

  const setSearch = useCallback(
    (s: string): void => {
      queuePendingPage(1, searchParams.get('p'));
      commitSearchParams(setSearchParams, (next) => {
        if (s) {
          next.set('s', s);
        } else {
          next.delete('s');
        }
        next.set('p', '1');
      });
    },
    [searchParams, setSearchParams],
  );

  const handleSearchChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>): void => setSearch(event.target.value),
    [setSearch],
  );

  const clearSearch = useCallback((): void => setSearch(''), [setSearch]);

  const handleStatusChange = useCallback(
    (status: WorkbenchMediaStatus) => {
      queuePendingPage(1, searchParams.get('p'));
      commitSearchParams(setSearchParams, (next) => {
        next.set('status', status);
        next.set('p', '1');
      });
    },
    [searchParams, setSearchParams],
  );

  const setCurrentPage = useCallback(
    (page: number) => {
      writePage(page);
    },
    [writePage],
  );

  const setPerPage = useCallback(
    (nextPerPage: number) => {
      if (!MEDIA_PAGE_SIZE_OPTIONS.includes(nextPerPage as (typeof MEDIA_PAGE_SIZE_OPTIONS)[number])) {
        return;
      }

      queuePendingPage(1, searchParams.get('p'));
      commitSearchParams(setSearchParams, (next) => {
        next.set('perPage', nextPerPage.toString());
        next.set('p', '1');
      });
    },
    [searchParams, setSearchParams],
  );

  const writeQueueState = useCallback(
    (nextState: WorkbenchQueueState): void => {
      queuePendingQueueState(nextState, searchParams.get('rq'));
      commitSearchParams(setSearchParams, (next) => {
        const serialized = serializeQueueState(nextState);
        if (serialized === null) {
          next.delete('rq');
        } else {
          next.set('rq', serialized);
        }
      });
    },
    [searchParams, setSearchParams],
  );

  const dispatchQueue = useCallback(
    (action: QueueAction): void => {
      writeQueueState(reduceQueueAction(getPendingQueueState() ?? queueState, action));
    },
    [queueState, writeQueueState],
  );

  const normalizedSearch = useMemo(() => searchQuery.trim(), [searchQuery]);

  return {
    searchQuery,
    currentPage,
    perPage,
    statusFilter,
    setCurrentPage,
    setPerPage,
    handleSearchChange,
    clearSearch,
    handleStatusChange,
    normalizedSearch,
    queueState,
    dispatchQueue,
  } as const;
};
