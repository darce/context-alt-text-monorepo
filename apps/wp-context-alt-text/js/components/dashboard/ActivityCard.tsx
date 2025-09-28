import React from "react";
import type { LatestActivityCard as LatestActivityCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";
import {
    TooltipProvider,
    TooltipRoot,
    TooltipTrigger,
    TooltipContent,
} from "@/components/ui/tooltip";

interface LatestActivityCardProps {
    data: LatestActivityCardData;
}

interface ActivityRowProps {
    label: string;
    value: LatestActivityCardData[keyof LatestActivityCardData];
}

const formatActivity = (
    value: LatestActivityCardData[keyof LatestActivityCardData],
): string => {
    if (value === null || value === undefined || value === "") {
        return "No recent activity";
    }

    if (typeof value === "number") {
        if (value <= 0) {
            return "No recent activity";
        }
        const minutes = Math.round((Date.now() / 1000 - value) / 60);
        if (minutes < 1) {
            return "Just now";
        }
        if (minutes < 60) {
            return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
        }
        const hours = Math.round(minutes / 60);
        return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    }

    return String(value);
};

const ActivityRow = ({ label, value }: ActivityRowProps): React.JSX.Element => {
    const formatted = formatActivity(value);

    return (
        <li>
            <span>{label}</span>
            <TooltipRoot>
                <TooltipTrigger asChild>
                    <strong className="cat-activity__value">{formatted}</strong>
                </TooltipTrigger>
                <TooltipContent side="bottom">{String(value ?? "No recent activity recorded")}</TooltipContent>
            </TooltipRoot>
        </li>
    );
};

export const ActivityCard = ({ data }: LatestActivityCardProps): React.JSX.Element => {
    return (
        <Card title="Latest Activity" className="cat-card--activity">
            <TooltipProvider delayDuration={150}>
                <ul className="cat-activity">
                    <ActivityRow label="Recognition" value={data.last_recognition} />
                    <ActivityRow label="Alt-text generation" value={data.last_alt_text_generation} />
                    <ActivityRow label="Roster sync" value={data.last_roster_sync} />
                </ul>
            </TooltipProvider>
        </Card>
    );
};
