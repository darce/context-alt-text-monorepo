import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route, Navigate, Link } from "react-router-dom";
import { __ } from "@wordpress/i18n";

import type { DashboardData, WorkbenchData, AdminRouteKey, RosterData } from "@/admin/types";
import {
    getDashboardConfig,
    getDashboardData,
    getWorkbenchData,
    getInitialRoute,
    getRosterData,
} from "./dashboardData";
import { DashboardRoute } from "./routes/DashboardRoute";
import { WorkbenchRoute } from "./routes/WorkbenchRoute";
import { RosterRoute } from "@/components/roster/RosterRoute";

import "./styles.scss";

export const App = (): React.JSX.Element => {
    const bootstrap = React.useMemo(() => getDashboardData(), []);
    const workbenchBootstrap = React.useMemo(() => getWorkbenchData(), []);
    const rosterBootstrap = React.useMemo(() => getRosterData(), []);
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
                roster={rosterBootstrap}
                config={config}
            />
        </QueryClientProvider>
    );
};

interface AdminRouterProps {
    initialRoute: AdminRouteKey;
    dashboard: DashboardData;
    workbench: WorkbenchData;
    roster: RosterData;
    config: ReturnType<typeof getDashboardConfig>;
}

const AdminRouter = ({ initialRoute, dashboard, workbench, roster, config }: AdminRouterProps): React.JSX.Element => {
    const workbenchEnabled = Boolean(config.featureFlags?.workbenchEnabled);
    const rosterEnabled = Boolean(config.featureFlags?.rosterEnabled);
    const initialPath =
        initialRoute === "workbench" && workbenchEnabled
            ? "/workbench"
            : initialRoute === "roster" && rosterEnabled
              ? "/roster"
              : "/dashboard";

    return (
        <MemoryRouter initialEntries={[initialPath]}>
            <nav className="cat-admin-nav" aria-label={__("Context Alt Text navigation", "context-alt-text")}>
                <Link to="/dashboard" data-nav-link>
                    {__("Dashboard", "context-alt-text")}
                </Link>
                {workbenchEnabled && (
                    <Link to="/workbench" data-nav-link>
                        {__("Alt-Text Workbench", "context-alt-text")}
                    </Link>
                )}
                {rosterEnabled && (
                    <Link to="/roster" data-nav-link>
                        {__("Roster", "context-alt-text")}
                    </Link>
                )}
            </nav>
            <Routes>
                <Route path="/" element={<Navigate to={initialPath} replace />} />
                <Route path="/dashboard" element={<DashboardRoute bootstrap={dashboard} config={config} />} />
                {workbenchEnabled ? (
                    <Route path="/workbench" element={<WorkbenchRoute bootstrap={workbench} />} />
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
                {rosterEnabled ? (
                    <Route path="/roster" element={<RosterRoute bootstrap={roster} config={config} />} />
                ) : (
                    <Route
                        path="/roster"
                        element={
                            <p className="cat-roster__disabled" role="status">
                                {__(
                                    "Roster management is not enabled. Toggle the feature flag to access this area.",
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
