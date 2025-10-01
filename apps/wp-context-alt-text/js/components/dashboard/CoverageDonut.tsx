import React from "react";

interface CoverageDonutProps {
    value: number;
    size?: number;
    strokeWidth?: number;
    describedBy?: string;
    label?: string;
}

const clampValue = (value: number): number => {
    if (Number.isNaN(value)) {
        return 0;
    }

    return Math.min(100, Math.max(0, value));
};

export const CoverageDonut = ({
    value,
    size = 140,
    strokeWidth = 16,
    describedBy,
    label,
}: CoverageDonutProps): React.JSX.Element => {
    const clamped = clampValue(value);
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const dashOffset = circumference - (clamped / 100) * circumference;

    return (
        <svg
            className="cat-coverage__donut"
            width={size}
            height={size}
            role="img"
            aria-label={label ?? `Coverage ${clamped}%`}
            aria-describedby={describedBy}
        >
            <circle
                className="cat-coverage__donut-track"
                cx={size / 2}
                cy={size / 2}
                r={radius}
                strokeWidth={strokeWidth}
            />
            <circle
                className="cat-coverage__donut-indicator"
                cx={size / 2}
                cy={size / 2}
                r={radius}
                strokeWidth={strokeWidth}
                strokeDasharray={`${circumference} ${circumference}`}
                strokeDashoffset={dashOffset}
                strokeLinecap="round"
            />
        </svg>
    );
};
