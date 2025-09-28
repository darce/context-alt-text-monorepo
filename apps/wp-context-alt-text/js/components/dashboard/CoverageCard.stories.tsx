import type { Meta, StoryObj } from "@storybook/react";

import { CoverageCard } from "./CoverageCard";
import type { CoverageCard as CoverageCardData, CoverageTrendPoint } from "@/admin/types";

const meta: Meta<typeof CoverageCard> = {
    title: "Dashboard/CoverageCard",
    component: CoverageCard,
    parameters: {
        layout: "centered",
    },
    decorators: [
        (Story) => (
            <div style={{ width: 360 }}>
                <Story />
            </div>
        ),
    ],
};

export default meta;

type Story = StoryObj<typeof CoverageCard>;

const sampleTrend = (values: number[]): CoverageTrendPoint[] =>
    values.map((coverage, index) => ({
        timestamp: Date.now() - index * 3600 * 1000,
        coverage,
        total: 120,
        with_alt: Math.round((coverage / 100) * 120),
        missing: Math.max(0, 120 - Math.round((coverage / 100) * 120)),
    }));

const baseData: CoverageCardData = {
    total: 120,
    with_alt: 90,
    missing: 30,
    coverage_percent: 75,
    trend_series: sampleTrend([40, 55, 65, 75]).reverse(),
};

export const Default: Story = {
    args: {
        data: baseData,
    },
};

export const ImprovingCoverage: Story = {
    args: {
        data: {
            total: 200,
            with_alt: 150,
            missing: 50,
            coverage_percent: 75,
            trend_series: sampleTrend([35, 42, 55, 67, 75]).reverse(),
        },
    },
};

export const FullCoverage: Story = {
    args: {
        data: {
            total: 80,
            with_alt: 80,
            missing: 0,
            coverage_percent: 100,
            trend_series: sampleTrend([70, 82, 90, 100]).reverse(),
        },
    },
};

export const EmptyLibrary: Story = {
    args: {
        data: {
            total: 0,
            with_alt: 0,
            missing: 0,
            coverage_percent: 0,
            trend_series: [],
        },
    },
};
