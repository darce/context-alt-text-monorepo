import { ChangeEvent, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { WORKBENCH_MEDIA_STATUSES, type WorkbenchMediaStatus } from '../api/workbenchMediaApi';
import {
  parseQueueState,
  serializeQueueState,
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

  /**
   * Merge partial queue state into `rq=` without clobbering unrelated params
   * (coexists with tab/panel/s/p/status writers).
   */
  const setQueueState = useCallback(
    (partial: Partial<WorkbenchQueueState>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          const current = parseQueueState(prev.get('rq'));
          const merged: WorkbenchQueueState = {
            kind: partial.kind ?? current.kind,
            band: partial.band ?? current.band,
            index: partial.index ?? current.index,
          };
          const serialized = serializeQueueState(merged);
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
  } as const;
};
