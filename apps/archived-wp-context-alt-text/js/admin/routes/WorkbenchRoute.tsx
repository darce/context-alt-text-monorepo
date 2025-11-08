import React from "react";
import { __, _n, sprintf } from "@wordpress/i18n";

import { WorkbenchApp } from "@/components/workbench";
import { PaginationControls } from "@/components/workbench/PaginationControls";
import { SearchBar } from "@/components/workbench/SearchBar";
import type { WorkbenchData } from "@/admin/types";
import { useWorkbenchMedia } from "@/admin/hooks/useWorkbenchMedia";
import { useDebouncedValue } from "@/admin/hooks/useDebouncedValue";
import { useWorkbenchAnalytics } from "@/admin/hooks/useWorkbenchAnalytics";
import { useWorkbenchPagination } from "@/admin/hooks/useWorkbenchPagination";
import { emitDashboardEvent } from "@/admin/analytics";
import { dispatchNotice, notifyError, type NoticeStatus } from "@/admin/notices";
import { normalizeSearchQuery, formatSelectionCount } from "@/admin/utils/searchHelpers";

const runtimeProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
const SEARCH_INPUT_DEBOUNCE_MS = runtimeProcess?.env?.NODE_ENV === "test" ? 0 : 400;

interface WorkbenchRouteProps {
    bootstrap: WorkbenchData;
}

interface BulkNoticeBuilder {
    status: NoticeStatus;
    buildMessage: (count: number, action: string) => string;
}

const BULK_ACTION_NOTICE_MAP: Record<string, BulkNoticeBuilder> = {
    generate: {
        status: "info",
        buildMessage: (count) =>
            sprintf(__("Preparing to generate alt text for %s.", "context-alt-text"), formatSelectionCount(count)),
    },
    regenerate: {
        status: "info",
        buildMessage: (count) =>
            sprintf(__("Regenerating alt text for %s.", "context-alt-text"), formatSelectionCount(count)),
    },
    mark_reviewed: {
        status: "success",
        buildMessage: (count) => sprintf(__("Marked %s as reviewed.", "context-alt-text"), formatSelectionCount(count)),
    },
};

const DEFAULT_BULK_NOTICE: BulkNoticeBuilder = {
    status: "info",
    buildMessage: (count, action) =>
        sprintf(__('Bulk action "%1$s" queued for %2$s.', "context-alt-text"), action, formatSelectionCount(count)),
};

/**
 * Workbench route component
 *
 * Media management interface for reviewing and generating alt text.
 *
 * Features:
 * - Search and filter media items
 * - Bulk actions (generate, regenerate, mark reviewed)
 * - Pagination with configurable page size
 * - Real-time status updates
 * - Recognition job integration
 *
 * State management:
 * - 5 useEffect hooks (handles pagination sync, search debounce, analytics, error notices, page bounds)
 * - Debounced search for better UX
 * - Auto-refetch on perPage change
 *
 * @param {WorkbenchRouteProps} props - Component props
 * @returns {React.JSX.Element} Workbench view
 */
export const WorkbenchRoute = ({ bootstrap }: WorkbenchRouteProps): React.JSX.Element => {
    const [page, setPage] = React.useState(() => Math.max(1, bootstrap.pagination?.page ?? 1));
    const [perPage, setPerPage] = React.useState(() => Math.max(1, bootstrap.pagination?.perPage ?? 20));
    const [statusFilter] = React.useState<"missing" | "all">("missing");
    const [searchInput, setSearchInput] = React.useState<string>("");
    const [searchTerm, setSearchTerm] = React.useState<string | null>(null);

    const debouncedSearchInput = useDebouncedValue(searchInput, SEARCH_INPUT_DEBOUNCE_MS);

    const mediaQuery = useWorkbenchMedia({
        initialItems: bootstrap.items,
        initialMeta: {
            total: bootstrap.pagination?.total ?? bootstrap.items.length,
            totalPages: bootstrap.pagination?.totalPages ?? 0,
        },
        page,
        perPage,
        status: statusFilter,
        search: searchTerm,
    });

    const hasWorkbenchEndpoint = mediaQuery.hasEndpoint;
    const refetchWorkbenchMedia = mediaQuery.refetch;
    const isMediaLoading = mediaQuery.isFetching || mediaQuery.isPending;

    // Update search term and reset to page 1 when debounced input changes
    React.useEffect(() => {
        const normalizedQuery = normalizeSearchQuery(debouncedSearchInput);
        if (normalizedQuery === searchTerm) {
            return;
        }

        setSearchTerm(normalizedQuery);
        setPage(1);
    }, [debouncedSearchInput, searchTerm]);

    const filters = React.useMemo(
        () => ({
            status: statusFilter,
            search: searchTerm,
        }),
        [statusFilter, searchTerm],
    );

    // Track workbench analytics (one-time mount event)
    useWorkbenchAnalytics({ bootstrap, perPage, filters });

    const handleBulkAction = React.useCallback(
        (action: string, ids: string[]) => {
            if (ids.length === 0) {
                return;
            }

            emitDashboardEvent("cat_workbench_bulk_action", {
                action,
                selection: ids,
                count: ids.length,
                filters,
            });

            const config = BULK_ACTION_NOTICE_MAP[action] ?? DEFAULT_BULK_NOTICE;
            const message = config.buildMessage(ids.length, action);

            dispatchNotice(config.status, message, {
                id: `workbench-bulk-${action}`,
                spokenMessage: message,
            });
        },
        [filters],
    );

    // Show error notice when media query fails
    const hasShownErrorNotice = React.useRef(false);
    React.useEffect(() => {
        if (mediaQuery.isError) {
            if (!hasShownErrorNotice.current) {
                notifyError(__("Unable to load media queue. Please try again later.", "context-alt-text"), {
                    id: "workbench-media-error",
                });
                hasShownErrorNotice.current = true;
            }
            return;
        }

        hasShownErrorNotice.current = false;
    }, [mediaQuery.isError]);

    const items = mediaQuery.data ?? bootstrap.items;
    const totalCount = mediaQuery.total ?? items.length;
    const totalPagesCount = mediaQuery.totalPages ?? (totalCount > 0 ? Math.ceil(totalCount / perPage) : 0);

    // Manage pagination: refetch on perPage change, enforce page bounds
    useWorkbenchPagination({
        page,
        perPage,
        totalPagesCount,
        isMediaLoading,
        hasWorkbenchEndpoint,
        setPage,
        refetchWorkbenchMedia,
    });

    const searchErrorMessage = mediaQuery.isError
        ? __("Unable to load results. Please try again.", "context-alt-text")
        : null;

    const activeSearch = React.useMemo(() => {
        if (searchTerm) {
            return searchTerm;
        }

        return normalizeSearchQuery(searchInput);
    }, [searchInput, searchTerm]);

    const searchStatusMessage = React.useMemo(() => {
        if (isMediaLoading && hasWorkbenchEndpoint) {
            return activeSearch
                ? sprintf(__('Searching for "%s"…', "context-alt-text"), activeSearch)
                : __("Updating media results…", "context-alt-text");
        }

        if (mediaQuery.isError) {
            return null;
        }

        if (totalCount === 0) {
            return activeSearch
                ? sprintf(__('No media found for "%s".', "context-alt-text"), activeSearch)
                : __("No media items match the current filters.", "context-alt-text");
        }

        if (activeSearch) {
            return sprintf(
                _n("Showing %d search result.", "Showing %d search results.", totalCount, "context-alt-text"),
                totalCount,
            );
        }

        return sprintf(
            _n("Showing %d media item.", "Showing %d media items.", totalCount, "context-alt-text"),
            totalCount,
        );
    }, [activeSearch, hasWorkbenchEndpoint, isMediaLoading, mediaQuery.isError, totalCount]);

    const handleSearchInputChange = React.useCallback((query: string) => {
        setSearchInput(query);
    }, []);

    const handlePerPageChange = React.useCallback(
        (nextPerPage: number) => {
            if (runtimeProcess?.env?.NODE_ENV === "test") {
                console.info("handlePerPageChange", { current: perPage, next: nextPerPage });
            }

            if (perPage === nextPerPage) {
                return;
            }

            setPerPage(nextPerPage);
            setPage(1);
        },
        [perPage],
    );

    const handleRetrySearch = React.useCallback(() => {
        void mediaQuery.refetch();
    }, [mediaQuery]);

    return (
        <div className="cat-workbench-route">
            <div className="cat-workbench__header">
                <SearchBar
                    value={searchInput}
                    onSearch={handleSearchInputChange}
                    isLoading={isMediaLoading}
                    error={searchErrorMessage}
                    onRetry={searchErrorMessage ? handleRetrySearch : undefined}
                    statusMessage={searchStatusMessage ?? undefined}
                />
            </div>
            <WorkbenchApp
                items={items}
                viewMode={bootstrap.viewMode}
                onGenerateAltText={(ids) => handleBulkAction("generate", ids)}
                onRegenerateAltText={(ids) => handleBulkAction("regenerate", ids)}
                onMarkReviewed={(ids) => handleBulkAction("mark_reviewed", ids)}
            />
            <PaginationControls
                page={page}
                perPage={perPage}
                total={totalCount}
                totalPages={totalPagesCount}
                onPageChange={setPage}
                isLoading={isMediaLoading}
                onPerPageChange={handlePerPageChange}
            />
            {isMediaLoading && (
                <p className="cat-workbench__refresh" role="status" aria-live="polite">
                    {__("Refreshing media queue…", "context-alt-text")}
                </p>
            )}
            {mediaQuery.isError && (
                <p className="cat-workbench__error" role="alert">
                    {__("Unable to load media queue. Try again later.", "context-alt-text")}
                </p>
            )}
        </div>
    );
};
