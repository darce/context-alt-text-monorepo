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
  /**
   * True while the queue is fetching — same condition that produces the transient
   * "Updating media queue…" statusMessage. Consumers that suppress that transient
   * from live regions must gate on this flag, not on display-copy equality [sr-007].
   */
  isStatusPending: boolean;
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
  // Stable identity: bare `?? []` would allocate a new array every render and
  // thrash the statusMessage useMemo that depends on mediaItems [WBUX-5-BR-112].
  const mediaItems = useMemo(
    () => mediaQuery.itemsWithIdentities ?? mediaData?.items ?? [],
    [mediaQuery.itemsWithIdentities, mediaData?.items],
  );
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

    // Envelope total stays server truth — never rewritten from listed rows [rg-015].
    const showing = sprintf(
      _n('Showing %d media item.', 'Showing %d media items.', totalCount, 'alt-context'),
      totalCount,
    );

    // Status=missing only: when corrections patch listed rows to complete without
    // invalidating the list, the filter label + envelope count + visible rows
    // would otherwise form an undesigned composite [WBUX-5-BR-112][RLSE-04].
    // Reconcile by labelling what we can observe on this page — never by
    // guessing other pages or decrementing total. Status=all has no filter
    // mismatch (complete rows belong there), so no sentence under that filter.
    if (statusFilter === 'missing') {
      // Split arms: ordinary corrections "have alt text"; decorative marks do
      // not — claiming alt text for them is false [INT-08]. Each arm uses its
      // own _n() on its own count so plural selection is per-outcome, not a
      // summed total [INT-08][D-01]. Mixed arms emit two sentences joined via
      // the same translatable sprintf format as showing + reconciliation.
      // Showing + reconciliation are joined the same way so translators
      // control order and separator [INT-08][WBUX-5-D-04].
      const nowHasAlt = mediaItems.filter(
        (item) => item.status === 'complete' && item.isDecorative !== true,
      ).length;
      const markedDecorative = mediaItems.filter(
        (item) => item.status === 'complete' && item.isDecorative === true,
      ).length;
      if (nowHasAlt > 0 || markedDecorative > 0) {
        const altSentence =
          nowHasAlt > 0
            ? sprintf(
                _n(
                  '%d now has alt text and will leave this view when the list next refreshes.',
                  '%d now have alt text and will leave this view when the list next refreshes.',
                  nowHasAlt,
                  'alt-context',
                ),
                nowHasAlt,
              )
            : null;
        const decorativeSentence =
          markedDecorative > 0
            ? sprintf(
                _n(
                  '%d is marked decorative and will leave this view when the list next refreshes.',
                  '%d are marked decorative and will leave this view when the list next refreshes.',
                  markedDecorative,
                  'alt-context',
                ),
                markedDecorative,
              )
            : null;
        // Mixed: two independent sentences, each with its own _n() count.
        // translators: 1: alt-text reconciliation sentence; 2: decorative reconciliation sentence.
        const reconciliation =
          altSentence && decorativeSentence
            ? sprintf(__('%1$s %2$s', 'alt-context'), altSentence, decorativeSentence)
            : (altSentence ?? decorativeSentence ?? '');
        // translators: 1: "Showing N media items." sentence; 2: reconciliation sentence about corrected rows.
        return sprintf(__('%1$s %2$s', 'alt-context'), showing, reconciliation);
      }
    }

    return showing;
  }, [mediaItems, mediaQuery.isError, mediaQuery.isFetching, normalizedSearch, statusFilter, totalCount]);

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

  // Same condition that yields the transient "Updating media queue…" message —
  // exposed as a boolean so consumers never key control flow on translated copy.
  const isStatusPending = mediaQuery.isFetching;

  const mediaQueueGroup = useMemo<WorkbenchMediaQueue>(
    () => ({
      mediaQuery,
      statusMessage,
      isStatusPending,
      detailTruncationNotice,
      hasIdentities: mediaItems.length > 0,
    }),
    [mediaQuery, statusMessage, isStatusPending, detailTruncationNotice, mediaItems.length],
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
