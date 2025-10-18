import React from "react";
import { __, _n, sprintf } from "@wordpress/i18n";

import type { LatestActivityCard as LatestActivityCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";
import { TooltipProvider, TooltipRoot, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

interface LatestActivityCardProps {
    data: LatestActivityCardData;
}

interface ActivityRowProps {
    label: string;
    value: LatestActivityCardData[keyof LatestActivityCardData];
}

const formatActivity = (value: LatestActivityCardData[keyof LatestActivityCardData]): string => {
    if (value === null || value === undefined || value === "") {
        return __("No recent activity", "context-alt-text");
    }

    if (typeof value === "number") {
        if (value <= 0) {
            return __("No recent activity", "context-alt-text");
        }
        const minutes = Math.round((Date.now() / 1000 - value) / 60);
        if (minutes < 1) {
            return __("Just now", "context-alt-text");
        }
        if (minutes < 60) {
            return sprintf(
                /* translators: %d: number of minutes since the last activity */
                _n("%d minute ago", "%d minutes ago", minutes, "context-alt-text"),
                minutes,
            );
        }
        const hours = Math.round(minutes / 60);
        return sprintf(
            /* translators: %d: number of hours since the last activity */
            _n("%d hour ago", "%d hours ago", hours, "context-alt-text"),
            hours,
        );
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
                <TooltipContent side="bottom">
                    {String(value ?? __("No recent activity recorded", "context-alt-text"))}
                </TooltipContent>
            </TooltipRoot>
        </li>
    );
};

export const ActivityCard = ({ data }: LatestActivityCardProps): React.JSX.Element => {
    return (
        <Card title={__("Latest Activity", "context-alt-text")} className="cat-card--activity">
            <TooltipProvider delayDuration={150}>
                <ul className="cat-activity">
                    <ActivityRow label={__("Recognition", "context-alt-text")} value={data.last_recognition} />
                    <ActivityRow
                        label={__("Alt-text generation", "context-alt-text")}
                        value={data.last_alt_text_generation}
                    />
                    <ActivityRow label={__("Roster sync", "context-alt-text")} value={data.last_roster_sync} />
                </ul>
            </TooltipProvider>
        </Card>
    );
};
