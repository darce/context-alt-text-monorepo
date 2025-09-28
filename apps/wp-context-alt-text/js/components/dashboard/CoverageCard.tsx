import React from "react";
import type { CoverageCard as CoverageCardData } from "@/admin/types";
import { Card } from "@/components/dashboard/Card";
import { CoverageDonut } from "@/components/dashboard/CoverageDonut";

interface CoverageCardProps {
    data: CoverageCardData;
}

const formatPercent = (value: number): string => {
    if (Number.isNaN(value)) {
        return "0";
    }

    if (value % 1 === 0) {
        return value.toFixed(0);
    }

    return value.toFixed(1);
};

export const CoverageCard = ({ data }: CoverageCardProps): React.JSX.Element => {
    const percent = Math.min(100, Math.max(0, data.coverage_percent ?? 0));

    return (
        <Card title="Coverage Progress" className="cat-card--coverage">
            <div className="cat-coverage">
                <div className="cat-coverage__metric">
                    <span className="cat-coverage__metric-value">{formatPercent(percent)}%</span>
                    <CoverageDonut value={percent} />
                </div>
                <dl className="cat-coverage__stats">
                    <div>
                        <dt>Total images</dt>
                        <dd>{data.total}</dd>
                    </div>
                    <div>
                        <dt>With alt text</dt>
                        <dd>{data.with_alt}</dd>
                    </div>
                    <div>
                        <dt>Missing alt text</dt>
                        <dd className={data.missing > 0 ? "cat-text-warning" : ""}>{data.missing}</dd>
                    </div>
                </dl>
            </div>
            {data.trend_series && data.trend_series.length > 1 && (
                <div className="cat-coverage__trend">
                    <small>Trend (beta)</small>
                    <Sparkline points={data.trend_series.map((point) => point.coverage)} />
                </div>
            )}
        </Card>
    );
};

interface SparklineProps {
    points: number[];
}

const Sparkline = ({ points }: SparklineProps): React.JSX.Element => {
    if (!points.length) {
        return <div className="cat-sparkline" />;
    }

    const normalized = points
        .map((value) => Math.max(0, Math.min(100, value)))
        .map((value, index) => {
            const x = (index / (points.length - 1 || 1)) * 100;
            const y = 100 - value;
            return `${x},${y}`;
        })
        .join(" ");

    return (
        <svg className="cat-sparkline" viewBox="0 0 100 100" preserveAspectRatio="none">
            <polyline points={normalized} />
        </svg>
    );
};
