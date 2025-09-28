import React from "react";

import { HeroStatusSection } from "@/components/dashboard/HeroStatus";
import { CoverageCard } from "@/components/dashboard/CoverageCard";
import { ActivityCard } from "@/components/dashboard/ActivityCard";
import { RecognitionCard } from "@/components/dashboard/RecognitionCard";
import { AutomationCard } from "@/components/dashboard/AutomationCard";
import { ActionFooter } from "@/components/dashboard/ActionFooter";
import { getDashboardData } from "./dashboardData";

import "./styles.scss";

export const App = (): React.JSX.Element => {
    const data = getDashboardData();

    return (
        <div className="cat-dashboard">
            <HeroStatusSection data={data.hero} />

            <section className="cat-dashboard__grid">
                <CoverageCard data={data.coverage} />
                <ActivityCard data={data.latestActivity} />
                <RecognitionCard data={data.recognition} />
                <AutomationCard data={data.automation} />
            </section>

            <ActionFooter data={data.footer} />
        </div>
    );
};
