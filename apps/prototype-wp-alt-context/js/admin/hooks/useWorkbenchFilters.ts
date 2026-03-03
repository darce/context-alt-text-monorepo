import { ChangeEvent, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { WorkbenchMediaStatus } from '../api/workbenchMediaApi';

export const useWorkbenchFilters = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  const searchQuery = searchParams.get('s') ?? '';
  const currentPageStr = searchParams.get('p') ?? '1';
  const currentPage = Number.parseInt(currentPageStr, 10) || 1;
  const statusFilter = (searchParams.get('status') as WorkbenchMediaStatus) || 'all';

  const handleSearchChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
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
      { replace: true }
    );
  }, [setSearchParams]);

  const handleStatusChange = useCallback((status: WorkbenchMediaStatus) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('status', status);
        next.set('p', '1');
        return next;
      },
      { replace: true }
    );
  }, [setSearchParams]);

  const setCurrentPage = useCallback((page: number) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('p', page.toString());
        return next;
      },
      { replace: true }
    );
  }, [setSearchParams]);

  const normalizedSearch = useMemo(() => searchQuery.trim(), [searchQuery]);

  return {
    searchQuery,
    currentPage,
    statusFilter,
    setCurrentPage,
    handleSearchChange,
    handleStatusChange,
    normalizedSearch,
  } as const;
};
