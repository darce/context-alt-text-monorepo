import { ChangeEvent, useCallback, useMemo, useState } from 'react';

export const useWorkbenchFilters = () => {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const handleSearchChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(event.target.value);
    setCurrentPage(1);
  }, []);

  const normalizedSearch = useMemo(() => searchQuery.trim(), [searchQuery]);

  return {
    searchQuery,
    currentPage,
    setCurrentPage,
    handleSearchChange,
    normalizedSearch,
  } as const;
};
