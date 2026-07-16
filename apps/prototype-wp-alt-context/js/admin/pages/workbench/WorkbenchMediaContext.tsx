import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { __, _n, sprintf } from '@wordpress/i18n';
import { useMediaSelectionState } from '../../hooks/useMediaSelectionState';
import { useWorkbenchFilters } from '../../hooks/useWorkbenchFilters';
import { useWorkbenchMedia, type WorkbenchMediaItem } from '../../hooks/useWorkbenchMedia';
import type { WorkbenchMediaStatus } from '../../api/workbenchMediaApi';

export interface WorkbenchMediaSelection {
  selection: Record<string, boolean>;
  selectedMedia: WorkbenchMediaItem[];
  toggleRow: (item: WorkbenchMediaItem, checked: boolean) => void;
  toggleAll: (items: WorkbenchMediaItem[], checked: boolean) => void;
  isPageFullySelected: (items: WorkbenchMediaItem[]) => boolean;
}

export interface WorkbenchMediaFilters {
  searchQuery: string;
  statusFilter: WorkbenchMediaStatus;
  currentPage: number;
  perPage: number;
  handleSearchChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  handleStatusChange: (status: WorkbenchMediaStatus) => void;
  setCurrentPage: (page: number) => void;
  setPerPage: (perPage: number) => void;
}

export interface WorkbenchMediaQueue {
  mediaQuery: ReturnType<typeof useWorkbenchMedia>;
  statusMessage: string;
  detailTruncationNotice: string | null;
  hasIdentities: boolean;
}

export interface WorkbenchMediaContextValue {
  selection: WorkbenchMediaSelection;
  filters: WorkbenchMediaFilters;
  mediaQueue: WorkbenchMediaQueue;
}

const WorkbenchMediaContext = createContext<WorkbenchMediaContextValue | null>(null);

export const WorkbenchMediaProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [knownTotalPages, setKnownTotalPages] = useState<number | null>(null);
  const { selection, selectedMedia, toggleRow, toggleAll, isPageFullySelected } = useMediaSelectionState();
  const {
    searchQuery,
    currentPage,
    perPage,
    setPerPage,
    setCurrentPage,
    handleSearchChange,
    normalizedSearch,
    statusFilter,
    handleStatusChange,
  } = useWorkbenchFilters();

  const clampedPage = Math.min(Math.max(1, currentPage), knownTotalPages ?? currentPage);

  const mediaQuery = useWorkbenchMedia({
    page: clampedPage,
    perPage,
    search: normalizedSearch,
    status: statusFilter,
    enabled: true,
  });

  const mediaData = mediaQuery.data;
  const mediaItems = mediaQuery.itemsWithIdentities ?? mediaData?.items ?? [];
  const totalCount = mediaData?.total ?? 0;

  useEffect(() => {
    if (currentPage === clampedPage) {
      return;
    }
    setCurrentPage(clampedPage);
  }, [clampedPage, currentPage, setCurrentPage]);

  useEffect(() => {
    if (!mediaData) {
      return;
    }
    setKnownTotalPages(mediaData.totalPages);
  }, [mediaData]);

  const statusMessage = useMemo(() => {
    if (mediaQuery.isFetching) {
      return __('Updating media queue…', 'alt-context');
    }

    if (mediaQuery.isError) {
      return __('Unable to load media. Please try again.', 'alt-context');
    }

    if (totalCount === 0) {
      return normalizedSearch
        ? sprintf(__('No media found for “%s”.', 'alt-context'), normalizedSearch)
        : __('No media items match the current filters.', 'alt-context');
    }

    return sprintf(_n('Showing %d media item.', 'Showing %d media items.', totalCount, 'alt-context'), totalCount);
  }, [mediaQuery.isError, mediaQuery.isFetching, normalizedSearch, totalCount]);

  const detailTruncationNotice = useMemo(() => {
    const detailData = mediaQuery.detailQuery.data;
    if (!detailData?.truncated) {
      return null;
    }

    return sprintf(
      __(
        'Showing detail metadata for the first %1$d of %2$d requested media items. Narrow the page size to inspect the rest.',
        'alt-context',
      ),
      detailData.limit,
      detailData.total,
    );
  }, [mediaQuery.detailQuery.data]);

  // Per-group memos keyed on leaf deps so each group's identity only changes
  // when its own data changes (a consumer of one group must not re-render
  // when an unrelated group changes).
  const selectionGroup = useMemo<WorkbenchMediaSelection>(
    () => ({
      selection,
      selectedMedia,
      toggleRow,
      toggleAll,
      isPageFullySelected,
    }),
    [selection, selectedMedia, toggleRow, toggleAll, isPageFullySelected],
  );

  const filtersGroup = useMemo<WorkbenchMediaFilters>(
    () => ({
      searchQuery,
      statusFilter,
      currentPage: clampedPage,
      perPage,
      handleSearchChange,
      handleStatusChange,
      setCurrentPage,
      setPerPage,
    }),
    [
      searchQuery,
      statusFilter,
      clampedPage,
      perPage,
      handleSearchChange,
      handleStatusChange,
      setCurrentPage,
      setPerPage,
    ],
  );

  const mediaQueueGroup = useMemo<WorkbenchMediaQueue>(
    () => ({
      mediaQuery,
      statusMessage,
      detailTruncationNotice,
      hasIdentities: mediaItems.length > 0,
    }),
    [mediaQuery, statusMessage, detailTruncationNotice, mediaItems.length],
  );

  const value = useMemo<WorkbenchMediaContextValue>(
    () => ({
      selection: selectionGroup,
      filters: filtersGroup,
      mediaQueue: mediaQueueGroup,
    }),
    [selectionGroup, filtersGroup, mediaQueueGroup],
  );

  return <WorkbenchMediaContext.Provider value={value}>{children}</WorkbenchMediaContext.Provider>;
};

export const useWorkbenchMediaContext = (): WorkbenchMediaContextValue => {
  const context = useContext(WorkbenchMediaContext);
  if (!context) {
    throw new Error('useWorkbenchMediaContext must be used within a WorkbenchMediaProvider');
  }
  return context;
};
