import { ChangeEvent, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { WorkbenchMediaStatus } from '../api/workbenchMediaApi';

const MEDIA_PAGE_SIZE_OPTIONS = [10, 50, 100] as const;
const DEFAULT_MEDIA_PAGE_SIZE = MEDIA_PAGE_SIZE_OPTIONS[0];

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
  const statusFilter = (searchParams.get('status') as WorkbenchMediaStatus) || 'all';

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
  } as const;
};
