import React from "react";
import type { ReactNode } from "react";
import { __, sprintf } from "@wordpress/i18n";
import { Link } from "react-router-dom";

import type { RecognitionInsightsCard as RecognitionInsightsCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";

interface RecognitionCardProps {
    data: RecognitionInsightsCardData;
    rosterEnabled?: boolean;
}
const formatRosterSyncMessage = (value: string | null, total: number): string => {
    if (value) {
        return sprintf(
            /* translators: %s is a human readable time difference. */
            __("Last roster sync %s ago.", "context-alt-text"),
            value,
        );
    }

    if (total > 0) {
        return __("Roster sync has not run recently.", "context-alt-text");
    }

    return __("Roster sync has not run yet.", "context-alt-text");
};

const renderMetricValue = (
    label: string,
    value: number,
    warnThreshold: number,
    link?: string | null,
): ReactNode => {
    const content = (
        <strong className={value > warnThreshold ? "cat-text-warning" : undefined}>{value}</strong>
    );

    if (!link) {
        return content;
    }

    return (
        <Link
            to={link}
            className="cat-recognition__metric-link"
            aria-label={`${label}: ${value}`}
        >
            {content}
        </Link>
    );
};

export const RecognitionCard = ({ data, rosterEnabled = false }: RecognitionCardProps): React.JSX.Element => {
    const rosterPendingLink = rosterEnabled ? "/roster?filter=pending" : null;
    const rosterConflictLink = rosterEnabled ? "/roster?filter=conflict" : null;
    const rosterManageLink = rosterEnabled ? "/roster" : null;
    const rosterSyncMessage = formatRosterSyncMessage(data.last_roster_sync_human, data.roster_total);

    return (
        <Card title="Recognition Insights" className="cat-card--recognition">
            <ul className="cat-recognition">
                <li>
                    <span>{__("Faces awaiting review", "context-alt-text")}</span>
                    {renderMetricValue(__("Faces awaiting review", "context-alt-text"), data.pending_faces, 0)}
                </li>
                <li>
                    <span>{__("Brands awaiting review", "context-alt-text")}</span>
                    {renderMetricValue(__("Brands awaiting review", "context-alt-text"), data.pending_brands, 0)}
                </li>
                <li>
                    <span>{__("Unresolved matches", "context-alt-text")}</span>
                    {renderMetricValue(__("Unresolved matches", "context-alt-text"), data.unresolved_matches, 0)}
                </li>
                <li>
                    <span>{__("Roster entries pending sync", "context-alt-text")}</span>
                    {renderMetricValue(
                        __("Roster entries pending sync", "context-alt-text"),
                        data.roster_pending,
                        0,
                        rosterPendingLink,
                    )}
                </li>
                <li>
                    <span>{__("Roster conflicts", "context-alt-text")}</span>
                    {renderMetricValue(
                        __("Roster conflicts", "context-alt-text"),
                        data.roster_conflicts,
                        0,
                        rosterConflictLink,
                    )}
                </li>
            </ul>
            {rosterManageLink && (
                <div className="cat-recognition__actions">
                    <Link to={rosterManageLink} className="cat-button cat-button--link">
                        {__("Review roster", "context-alt-text")}
                    </Link>
                </div>
            )}
            <p className="cat-recognition__meta" role="status" aria-live="polite">
                {rosterSyncMessage}
            </p>
        </Card>
    );
};
