import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { HeroStatusSection } from "@/components/dashboard/HeroStatus";
import { CoverageCard } from "@/components/dashboard/CoverageCard";
import { ActivityCard } from "@/components/dashboard/ActivityCard";
import { RecognitionCard } from "@/components/dashboard/RecognitionCard";
import { AutomationCard } from "@/components/dashboard/AutomationCard";
import { ActionFooter } from "@/components/dashboard/ActionFooter";
import type { DashboardData } from "@/admin/types";
import { getDashboardData } from "./dashboardData";
import { useCoverageMetrics } from "./hooks/useCoverageMetrics";

import "./styles.scss";

export const App = (): React.JSX.Element => {
    const bootstrap = React.useMemo(() => getDashboardData(), []);
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
            <Dashboard bootstrap={bootstrap} />
        </QueryClientProvider>
    );
};

interface DashboardProps {
    bootstrap: DashboardData;
}

const Dashboard = ({ bootstrap }: DashboardProps): React.JSX.Element => {
    const coverageQuery = useCoverageMetrics({ initialData: bootstrap.coverage });
    const coverage = coverageQuery.data ?? bootstrap.coverage;

    return (
        <div className="cat-dashboard">
            <HeroStatusSection data={bootstrap.hero} />

            <section className="cat-dashboard__grid">
                <CoverageCard data={coverage} />
                <ActivityCard data={bootstrap.latestActivity} />
                <RecognitionCard data={bootstrap.recognition} />
                <AutomationCard data={bootstrap.automation} />
            </section>

            <ActionFooter data={bootstrap.footer} />
        </div>
    );
};
