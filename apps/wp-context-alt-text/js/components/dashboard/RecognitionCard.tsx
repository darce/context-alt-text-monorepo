import React from "react";
import type { RecognitionInsightsCard as RecognitionInsightsCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";

interface RecognitionCardProps {
    data: RecognitionInsightsCardData;
}

export const RecognitionCard = ({ data }: RecognitionCardProps): React.JSX.Element => {
    return (
        <Card title="Recognition Insights" className="cat-card--recognition">
            <ul className="cat-recognition">
                <li>
                    <span>Faces awaiting review</span>
                    <strong className={data.pending_faces > 0 ? "cat-text-warning" : ""}>{data.pending_faces}</strong>
                </li>
                <li>
                    <span>Brands awaiting review</span>
                    <strong className={data.pending_brands > 0 ? "cat-text-warning" : ""}>{data.pending_brands}</strong>
                </li>
                <li>
                    <span>Unresolved matches</span>
                    <strong className={data.unresolved_matches > 0 ? "cat-text-warning" : ""}>{data.unresolved_matches}</strong>
                </li>
            </ul>
        </Card>
    );
};
