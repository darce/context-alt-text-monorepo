import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route, Navigate, Link, useNavigate } from "react-router-dom";
import { __, _n, sprintf } from "@wordpress/i18n";

import { HeroStatusSection } from "@/components/dashboard/HeroStatus";
import { CoverageCard } from "@/components/dashboard/CoverageCard";
import { ActivityCard } from "@/components/dashboard/ActivityCard";
import { RecognitionCard } from "@/components/dashboard/RecognitionCard";
import { AutomationCard } from "@/components/dashboard/AutomationCard";
import { ActionFooter } from "@/components/dashboard/ActionFooter";
import { WorkbenchApp } from "@/components/workbench";
import { PaginationControls } from "@/components/workbench/PaginationControls";
import type { DashboardData, WorkbenchData, AdminRouteKey } from "@/admin/types";
import {
    getDashboardConfig,
    getDashboardData,
    getWorkbenchData,
    getInitialRoute,
} from "./dashboardData";
import { useCoverageMetrics } from "./hooks/useCoverageMetrics";
import { useWorkbenchMedia } from "./hooks/useWorkbenchMedia";
import { emitDashboardEvent } from "./analytics";
import { dispatchNotice, notifyError, type NoticeStatus } from "@/admin/notices";
import { SearchBar } from "@/components/workbench/SearchBar";

import "./styles.scss";

const runtimeProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
const SEARCH_INPUT_DEBOUNCE_MS = runtimeProcess?.env?.NODE_ENV === "test" ? 0 : 400;

const normalizeSearchQuery = (value: string): string | null => {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
};

const useDebouncedValue = <T,>(value: T, delay: number): T => {
    const [debouncedValue, setDebouncedValue] = React.useState(value);

    React.useEffect(() => {
        if (delay <= 0) {
            setDebouncedValue(value);
            return;
        }

        const timer = window.setTimeout(() => {
            setDebouncedValue(value);
        }, delay);

        return () => {
            window.clearTimeout(timer);
        };
    }, [value, delay]);

    return debouncedValue;
};

export const App = (): React.JSX.Element => {
    const bootstrap = React.useMemo(() => getDashboardData(), []);
    const workbenchBootstrap = React.useMemo(() => getWorkbenchData(), []);
    const initialRoute = React.useMemo(() => getInitialRoute(), []);
    const config = React.useMemo(() => getDashboardConfig(), []);
    const [queryClient] = React.useState(
        () =>
            new QueryClient({
                defaultOptions: {
                    queries: {
                        staleTime: 60_000,
                        refetchOnWindowFocus: false,
                    },
                },
            }),
    );

    return (
        <QueryClientProvider client={queryClient}>
            <AdminRouter
                initialRoute={initialRoute}
                dashboard={bootstrap}
                workbench={workbenchBootstrap}
                config={config}
            />
        </QueryClientProvider>
    );
};

interface AdminRouterProps {
    initialRoute: AdminRouteKey;
    dashboard: DashboardData;
    workbench: WorkbenchData;
    config: ReturnType<typeof getDashboardConfig>;
}

const AdminRouter = ({ initialRoute, dashboard, workbench, config }: AdminRouterProps): React.JSX.Element => {
    const workbenchEnabled = Boolean(config.featureFlags?.workbenchEnabled);
    const initialPath = initialRoute === "workbench" && workbenchEnabled ? "/workbench" : "/dashboard";

    return (
        <MemoryRouter initialEntries={[initialPath]}>
            <nav
                className="cat-admin-nav"
                aria-label={__("Context Alt Text navigation", "context-alt-text")}
            >
                <Link to="/dashboard" data-nav-link>
                    {__("Dashboard", "context-alt-text")}
                </Link>
                {workbenchEnabled && (
                    <Link to="/workbench" data-nav-link>
                        {__("Alt-Text Workbench", "context-alt-text")}
                    </Link>
                )}
            </nav>
            <Routes>
                <Route path="/" element={<Navigate to={initialPath} replace />} />
                <Route path="/dashboard" element={<DashboardRoute bootstrap={dashboard} config={config} />} />
                {workbenchEnabled ? (
                    <Route path="/workbench" element={<WorkbenchRoute bootstrap={workbench} config={config} />} />
                ) : (
                    <Route
                        path="/workbench"
                        element={
                            <p className="cat-workbench__disabled" role="status">
                                {__(
                                    "The Workbench is currently unavailable. Enable the feature flag to access this surface.",
                                    "context-alt-text",
                                )}
                            </p>
                        }
                    />
                )}
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
        </MemoryRouter>
    );
};

interface DashboardRouteProps {
    bootstrap: DashboardData;
    config: ReturnType<typeof getDashboardConfig>;
}

const DashboardRoute = ({ bootstrap, config }: DashboardRouteProps): React.JSX.Element => {
    const coverageQuery = useCoverageMetrics({ initialData: bootstrap.coverage });
    const coverage = coverageQuery.data ?? bootstrap.coverage;
    const navigate = useNavigate();

    const handleCoverageDrilldown = React.useCallback(() => {
        if (config.featureFlags?.workbenchEnabled) {
            navigate("/workbench?status=missing");
            return;
        }

        if (typeof window !== "undefined" && typeof config.missingAltMediaUrl === "string") {
            window.open(config.missingAltMediaUrl, "_blank", "noopener");
        }
    }, [config.featureFlags?.workbenchEnabled, config.missingAltMediaUrl, navigate]);

    const handleCoverageExport = React.useCallback(() => {
        if (typeof window === "undefined" || typeof document === "undefined") {
            return;
        }

        const rows: Array<string[]> = [
            [__("Metric", "context-alt-text"), __("Value", "context-alt-text")],
            [__("Total items", "context-alt-text"), String(coverage.total)],
            [__("With alt text", "context-alt-text"), String(coverage.with_alt)],
            [__("Missing alt text", "context-alt-text"), String(coverage.missing)],
            [__("Coverage percent", "context-alt-text"), `${coverage.coverage_percent}`],
        ];

        if (Array.isArray(coverage.trend_series) && coverage.trend_series.length > 0) {
            rows.push([]);
            rows.push(
                [
                    __("Timestamp", "context-alt-text"),
                    __("Coverage percent", "context-alt-text"),
                    __("Total items", "context-alt-text"),
                    __("With alt text", "context-alt-text"),
                    __("Missing alt text", "context-alt-text"),
                ],
            );

            for (const point of coverage.trend_series) {
                rows.push([
                    new Date(point.timestamp).toISOString(),
                    `${point.coverage}`,
                    String(point.total),
                    String(point.with_alt),
                    String(point.missing),
                ]);
            }
        }

        const escapeCell = (cell: string): string => {
            if (cell.includes('"')) {
                return `"${cell.replace(/"/g, '""')}"`;
            }

            if (cell.includes(",") || cell.includes("\n")) {
                return `"${cell}"`;
            }

            return cell;
        };

        const csvContent = rows
            .map((row) => row.map((cell) => escapeCell(cell)).join(","))
            .join("\r\n");

        if (typeof window.URL?.createObjectURL !== "function" || !document.body) {
            return;
        }

        const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8" });
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `coverage-report-${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
    }, [coverage]);

    const enableDrilldown = Boolean(config.featureFlags?.workbenchEnabled || config.missingAltMediaUrl);

    return (
        <div className="cat-dashboard">
            <HeroStatusSection data={bootstrap.hero} />

            <section className="cat-dashboard__grid">
                <CoverageCard
                    data={coverage}
                    featureFlags={config.featureFlags}
                    queryState={{
                        status: coverageQuery.status,
                        isLoading: coverageQuery.isLoading,
                        isFetching: coverageQuery.isFetching,
                        isError: coverageQuery.isError,
                        error: coverageQuery.error,
                        refetch: coverageQuery.refetch,
                        hasEndpoint: coverageQuery.hasEndpoint,
                    }}
                    onDrilldown={enableDrilldown ? handleCoverageDrilldown : undefined}
                    onExport={handleCoverageExport}
                />
                <ActivityCard data={bootstrap.latestActivity} />
                <RecognitionCard data={bootstrap.recognition} />
                <AutomationCard data={bootstrap.automation} />
            </section>

            <ActionFooter data={bootstrap.footer} />
        </div>
    );
};

interface WorkbenchRouteProps {
    bootstrap: WorkbenchData;
    config: ReturnType<typeof getDashboardConfig>;
}

const formatSelectionCount = (count: number): string =>
    sprintf(_n("%d item", "%d items", count, "context-alt-text"), count);

type BulkNoticeBuilder = {
    status: NoticeStatus;
    buildMessage: (count: number, action: string) => string;
};

const BULK_ACTION_NOTICE_MAP: Record<string, BulkNoticeBuilder> = {
    generate: {
        status: "info",
        buildMessage: (count) =>
            sprintf(
                __("Preparing to generate alt text for %s.", "context-alt-text"),
                formatSelectionCount(count),
            ),
    },
    regenerate: {
        status: "info",
        buildMessage: (count) =>
            sprintf(
                __("Regenerating alt text for %s.", "context-alt-text"),
                formatSelectionCount(count),
            ),
    },
    mark_reviewed: {
        status: "success",
        buildMessage: (count) =>
            sprintf(
                __("Marked %s as reviewed.", "context-alt-text"),
                formatSelectionCount(count),
            ),
    },
};

const DEFAULT_BULK_NOTICE: BulkNoticeBuilder = {
    status: "info",
    buildMessage: (count, action) =>
        sprintf(
            __("Bulk action \"%1$s\" queued for %2$s.", "context-alt-text"),
            action,
            formatSelectionCount(count),
        ),
};

const WorkbenchRoute = ({ bootstrap, config }: WorkbenchRouteProps): React.JSX.Element => {
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

    const isMediaLoading = mediaQuery.isFetching || mediaQuery.isPending;

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

    const workbenchSeenEventSent = React.useRef(false);
    React.useEffect(() => {
        if (workbenchSeenEventSent.current) {
            return;
        }

        workbenchSeenEventSent.current = true;

        emitDashboardEvent("cat_workbench_seen", {
            pagination: {
                page: bootstrap.pagination?.page ?? 1,
                perPage,
            },
            viewMode: bootstrap.viewMode,
            filters,
        });
    }, [bootstrap.pagination?.page, bootstrap.viewMode, perPage, filters]);

    const handleBulkAction = React.useCallback((action: string, ids: string[]) => {
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
    }, [filters]);

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

    const hasWorkbenchEndpoint = mediaQuery.hasEndpoint;
    const items = mediaQuery.data ?? bootstrap.items;
    const totalCount = mediaQuery.total ?? items.length;
    const totalPagesCount = mediaQuery.totalPages ?? (totalCount > 0 ? Math.ceil(totalCount / perPage) : 0);

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
    }, [isMediaLoading, page, totalPagesCount]);

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
                ? sprintf(
                    __("Searching for \"%s\"…", "context-alt-text"),
                    activeSearch,
                )
                : __("Updating media results…", "context-alt-text");
        }

        if (mediaQuery.isError) {
            return null;
        }

        if (totalCount === 0) {
            return activeSearch
                ? sprintf(
                    __("No media found for \"%s\".", "context-alt-text"),
                    activeSearch,
                )
                : __("No media items match the current filters.", "context-alt-text");
        }

        if (activeSearch) {
            return sprintf(
                _n(
                    "Showing %d search result.",
                    "Showing %d search results.",
                    totalCount,
                    "context-alt-text",
                ),
                totalCount,
            );
        }

        return sprintf(
            _n(
                "Showing %d media item.",
                "Showing %d media items.",
                totalCount,
                "context-alt-text",
            ),
            totalCount,
        );
    }, [activeSearch, hasWorkbenchEndpoint, isMediaLoading, mediaQuery.isError, totalCount]);

    const handleSearchInputChange = React.useCallback((query: string) => {
        setSearchInput(query);
    }, []);

    const handlePerPageChange = React.useCallback((nextPerPage: number) => {
        setPerPage((current) => {
            if (current === nextPerPage) {
                return current;
            }

            setPage(1);
            return nextPerPage;
        });
    }, []);

    const handleRetrySearch = React.useCallback(() => {
        mediaQuery.refetch();
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
