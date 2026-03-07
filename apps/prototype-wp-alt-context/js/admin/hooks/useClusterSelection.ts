import { useState, useCallback } from 'react';

/**
 * Hook to manage multi-selection of clusters.
 */
export const useClusterSelection = () => {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const selectRange = useCallback((ids: string[]) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setSelectedIds((prev) => (prev.size === 0 ? prev : new Set()));
  }, []);

  const selectAll = useCallback((allIds: string[]) => {
    setSelectedIds(new Set(allIds));
  }, []);

  const isSelected = useCallback((id: string) => selectedIds.has(id), [selectedIds]);

  const isAllSelected = useCallback(
    (allIds: string[]) => allIds.length > 0 && allIds.every((id) => selectedIds.has(id)),
    [selectedIds],
  );

  return {
    selectedIds,
    toggle,
    selectRange,
    clear,
    selectAll,
    isSelected,
    isAllSelected,
    count: selectedIds.size,
  };
};
