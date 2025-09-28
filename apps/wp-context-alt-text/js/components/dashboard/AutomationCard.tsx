import React from "react";
import type { AutomationPipelineCard as AutomationPipelineCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";

interface AutomationCardProps {
    data: AutomationPipelineCardData;
}

export const AutomationCard = ({ data }: AutomationCardProps): React.JSX.Element => {
    return (
        <Card title="Automation Pipeline" className="cat-card--automation">
            <ul className="cat-automation">
                <li>
                    <span>Queued</span>
                    <strong>{data.queued}</strong>
                </li>
                <li>
                    <span>Running</span>
                    <strong>{data.running}</strong>
                </li>
                <li>
                    <span>Completed (24h)</span>
                    <strong>{data.completed}</strong>
                </li>
            </ul>
            {data.next_run && <p className="cat-automation__next">Next scheduled action in {data.next_run}</p>}
        </Card>
    );
};
