import React from "react";
import { useNavigate } from "react-router-dom";
import { HeroStatusSection } from "@/components/dashboard/HeroStatus";
import { CoverageCard } from "@/components/dashboard/CoverageCard";
import { ActivityCard } from "@/components/dashboard/ActivityCard";
import { RecognitionCard } from "@/components/dashboard/RecognitionCard";
import { AutomationCard } from "@/components/dashboard/AutomationCard";
import { ActionFooter } from "@/components/dashboard/ActionFooter";
import type { DashboardData } from "@/admin/types";
import { getDashboardConfig } from "@/admin/dashboardData";
import { useCoverageMetrics } from "@/admin/hooks/useCoverageMetrics";

interface DashboardRouteProps {
    bootstrap: DashboardData;
    config: ReturnType<typeof getDashboardConfig>;
}

/**
 * Dashboard route component
 *
 * Main dashboard view showing coverage metrics, activity, recognition status,
 * and automation statistics.
 *
 * Features:
 * - Real-time coverage metrics with trend chart
 * - Drilldown to workbench for missing alt text
 * - Recent activity timeline
 * - Recognition service status
 * - Automation rules overview
 *
 * @param {DashboardRouteProps} props - Component props
 * @returns {React.JSX.Element} Dashboard view
 */
export const DashboardRoute = ({ bootstrap, config }: DashboardRouteProps): React.JSX.Element => {
    const coverageQuery = useCoverageMetrics({ initialData: bootstrap.coverage });
    const coverage = coverageQuery.data ?? bootstrap.coverage;
    const navigate = useNavigate();

    const handleCoverageDrilldown = React.useCallback(() => {
        if (config.featureFlags?.workbenchEnabled) {
            void navigate("/workbench?status=missing");
            return;
        }

        if (typeof window !== "undefined" && typeof config.missingAltMediaUrl === "string") {
            window.open(config.missingAltMediaUrl, "_blank", "noopener");
        }
    }, [config.featureFlags?.workbenchEnabled, config.missingAltMediaUrl, navigate]);

    const enableWorkbench = config.featureFlags?.workbenchEnabled ?? false;
    const enableDrilldown = enableWorkbench || Boolean(config.missingAltMediaUrl);

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
                />
                <ActivityCard data={bootstrap.latestActivity} />
                <RecognitionCard
                    data={bootstrap.recognition}
                    rosterEnabled={Boolean(config.featureFlags?.rosterEnabled)}
                />
                <AutomationCard data={bootstrap.automation} />
            </section>

            <ActionFooter data={bootstrap.footer} />
        </div>
    );
};
