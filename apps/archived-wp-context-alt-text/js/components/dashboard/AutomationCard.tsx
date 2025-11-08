import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import type { AutomationPipelineCard as AutomationPipelineCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";

interface AutomationCardProps {
    data: AutomationPipelineCardData;
}

export const AutomationCard = ({ data }: AutomationCardProps): React.JSX.Element => {
    return (
        <Card title={__("Automation Pipeline", "context-alt-text")} className="cat-card--automation">
            <ul className="cat-automation">
                <li>
                    <span>{__("Queued", "context-alt-text")}</span>
                    <strong>{data.queued}</strong>
                </li>
                <li>
                    <span>{__("Running", "context-alt-text")}</span>
                    <strong>{data.running}</strong>
                </li>
                <li>
                    <span>{__("Completed (24h)", "context-alt-text")}</span>
                    <strong>{data.completed}</strong>
                </li>
            </ul>
            {data.next_run && (
                <p className="cat-automation__next">
                    {sprintf(
                        /* translators: %s: relative time until the next scheduled automation */
                        __("Next scheduled action in %s", "context-alt-text"),
                        data.next_run,
                    )}
                </p>
            )}
        </Card>
    );
};
