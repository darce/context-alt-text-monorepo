import React from "react";

import type { CoverageTrendPoint } from "@/admin/types";

interface CoverageTrendProps {
    points: CoverageTrendPoint[];
}

const clamp = (value: number) => Math.max(0, Math.min(100, value));

export const CoverageTrend = ({ points }: CoverageTrendProps): React.JSX.Element => {
    if (points.length === 0) {
        return <div className="cat-sparkline" aria-hidden="true" />;
    }

    const normalized = points
        .map((point, index) => {
            const coverage = clamp(point.coverage);
            const x = (index / (points.length - 1 || 1)) * 100;
            const y = 100 - coverage;
            return `${x},${y}`;
        })
        .join(" ");

    return (
        <svg className="cat-sparkline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <polyline points={normalized} />
        </svg>
    );
};
