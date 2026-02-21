import { ChangeEvent, useCallback, useMemo, useState } from 'react';
import type { WorkbenchMediaStatus } from '../api/workbenchMediaApi';

export const useWorkbenchFilters = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<WorkbenchMediaStatus>('all');

  const handleSearchChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(event.target.value);
    setCurrentPage(1);
  }, []);

  const handleStatusChange = useCallback((status: WorkbenchMediaStatus) => {
    setStatusFilter(status);
    setCurrentPage(1);
  }, []);

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
