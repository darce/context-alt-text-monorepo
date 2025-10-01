import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route, Navigate, Link } from "react-router-dom";

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

import "./styles.scss";

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
            <nav className="cat-admin-nav" aria-label="Context Alt Text navigation">
                <Link to="/dashboard" data-nav-link>
                    Dashboard
                </Link>
                {workbenchEnabled && (
                    <Link to="/workbench" data-nav-link>
                        Alt-Text Workbench
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
                                The Workbench is currently unavailable. Enable the feature flag to access this surface.
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

const formatSelectionCount = (count: number): string => `${count} item${count === 1 ? "" : "s"}`;

type BulkNoticeBuilder = {
    status: NoticeStatus;
    buildMessage: (count: number, action: string) => string;
};

const BULK_ACTION_NOTICE_MAP: Record<string, BulkNoticeBuilder> = {
    generate: {
        status: "info",
        buildMessage: (count) => `Preparing to generate alt text for ${formatSelectionCount(count)}.`,
    },
    regenerate: {
        status: "info",
        buildMessage: (count) => `Regenerating alt text for ${formatSelectionCount(count)}.`,
    },
    mark_reviewed: {
        status: "success",
        buildMessage: (count) => `Marked ${formatSelectionCount(count)} as reviewed.`,
    },
    generate_drafts: {
        status: "info",
        buildMessage: (count) => `Draft generation requested for ${formatSelectionCount(count)}.`,
    },
    publish_drafts: {
        status: "success",
        buildMessage: (count) => `Publishing drafts for ${formatSelectionCount(count)}.`,
    },
};

const DEFAULT_BULK_NOTICE: BulkNoticeBuilder = {
    status: "info",
    buildMessage: (count, action) => `Bulk action "${action}" queued for ${formatSelectionCount(count)}.`,
};

const WorkbenchRoute = ({ bootstrap, config }: WorkbenchRouteProps): React.JSX.Element => {
    const [page, setPage] = React.useState(() => Math.max(1, bootstrap.pagination?.page ?? 1));
    const perPage = React.useMemo(() => bootstrap.pagination?.perPage ?? 20, [bootstrap.pagination?.perPage]);
    const [filters] = React.useState(() => ({
        status: "missing" as const,
        search: null as string | null,
    }));

    const mediaQuery = useWorkbenchMedia({
        initialItems: bootstrap.items,
        initialMeta: {
            total: bootstrap.pagination?.total ?? bootstrap.items.length,
            totalPages: bootstrap.pagination?.totalPages ?? 0,
        },
        page,
        perPage,
        status: filters.status,
        search: filters.search,
    });

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

    const handleRecognition = React.useCallback((ids: string[]) => {
        if (ids.length === 0) {
            return;
        }

        emitDashboardEvent("cat_workbench_recognition_triggered", {
            selection: ids,
            count: ids.length,
            filters,
        });

        const message = `Recognition triggered for ${formatSelectionCount(ids.length)}.`;

        dispatchNotice("info", message, {
            id: "workbench-recognition",
            spokenMessage: message,
        });
    }, [filters]);

    const hasShownErrorNotice = React.useRef(false);
    React.useEffect(() => {
        if (mediaQuery.isError) {
            if (!hasShownErrorNotice.current) {
                notifyError("Unable to load media queue. Please try again later.", {
                    id: "workbench-media-error",
                });
                hasShownErrorNotice.current = true;
            }
            return;
        }

        hasShownErrorNotice.current = false;
    }, [mediaQuery.isError]);

    React.useEffect(() => {
        if (mediaQuery.totalPages > 0 && page > mediaQuery.totalPages) {
            setPage(mediaQuery.totalPages);
        }
    }, [mediaQuery.totalPages, page]);

    const items = mediaQuery.data ?? bootstrap.items;

    return (
        <div className="cat-workbench-route">
            <WorkbenchApp
                items={items}
                viewMode={bootstrap.viewMode}
                recognitionEnabled={config.featureFlags?.workbenchRecognition}
                bulkAIEnabled={config.featureFlags?.workbenchBulkAI}
                onGenerateAltText={(ids) => handleBulkAction("generate", ids)}
                onRegenerateAltText={(ids) => handleBulkAction("regenerate", ids)}
                onMarkReviewed={(ids) => handleBulkAction("mark_reviewed", ids)}
                onTriggerRecognition={handleRecognition}
                onGenerateDrafts={(ids) => handleBulkAction("generate_drafts", ids)}
                onPublishDrafts={(ids) => handleBulkAction("publish_drafts", ids)}
            />
            <PaginationControls
                page={page}
                perPage={perPage}
                total={mediaQuery.total}
                totalPages={mediaQuery.totalPages}
                onPageChange={setPage}
                isLoading={mediaQuery.isFetching}
            />
            {mediaQuery.isFetching && (
                <p className="cat-workbench__refresh" role="status" aria-live="polite">
                    Refreshing media queue…
                </p>
            )}
            {mediaQuery.isError && (
                <p className="cat-workbench__error" role="alert">
                    Unable to load media queue. Try again later.
                </p>
            )}
        </div>
    );
};
