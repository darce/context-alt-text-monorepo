import React from "react";

/**
 * Props for useWorkbenchPagination hook
 */
interface UseWorkbenchPaginationProps {
    /** Current page number */
    page: number;
    /** Current items per page */
    perPage: number;
    /** Total number of pages available */
    totalPagesCount: number;
    /** Whether media data is currently loading */
    isMediaLoading: boolean;
    /** Whether workbench endpoint is available */
    hasWorkbenchEndpoint: boolean;
    /** Function to update the current page */
    setPage: (page: number) => void;
    /** Function to refetch media data */
    refetchWorkbenchMedia: (options?: { cancelRefetch?: boolean }) => Promise<unknown>;
}

/**
 * Custom hook for managing workbench pagination logic
 *
 * Handles two pagination responsibilities:
 * 1. Forces a refetch when page size (perPage) changes to resync pagination
 * 2. Enforces page bounds, automatically adjusting to valid page range
 *
 * @param props - Pagination state and control functions
 *
 * @example
 * ```tsx
 * useWorkbenchPagination({
 *   page,
 *   perPage,
 *   totalPagesCount,
 *   isMediaLoading,
 *   hasWorkbenchEndpoint,
 *   setPage,
 *   refetchWorkbenchMedia,
 * });
 * ```
 */
export function useWorkbenchPagination({
    page,
    perPage,
    totalPagesCount,
    isMediaLoading,
    hasWorkbenchEndpoint,
    setPage,
    refetchWorkbenchMedia,
}: UseWorkbenchPaginationProps): void {
    const previousPerPageRef = React.useRef(perPage);

    // Effect 1: Force refetch when page size changes
    React.useEffect(() => {
        if (previousPerPageRef.current === perPage) {
            return;
        }

        previousPerPageRef.current = perPage;

        if (!hasWorkbenchEndpoint) {
            return;
        }

        // Force a remote refresh whenever the page size changes so pagination resyncs immediately.
        void refetchWorkbenchMedia({ cancelRefetch: true });
    }, [hasWorkbenchEndpoint, perPage, refetchWorkbenchMedia]);

    // Effect 2: Enforce page bounds
    React.useEffect(() => {
        if (isMediaLoading) {
            return;
        }

        if (totalPagesCount === 0) {
            if (page !== 1) {
                setPage(1);
            }
            return;
        }

        if (page > totalPagesCount) {
            setPage(totalPagesCount);
        }
    }, [isMediaLoading, page, totalPagesCount, setPage]);
}
