import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { CoverageCard } from "./CoverageCard";
import { renderDashboard } from "@/admin/testing/renderDashboard";
import { FALLBACK_COVERAGE } from "@/admin/dashboardData";
import * as analytics from "@/admin/analytics";

const baseFlags = {
    coverageTrend: true,
} as const;

const successQueryState = {
    status: "success" as const,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    hasEndpoint: true,
};

afterEach(() => {
    vi.restoreAllMocks();
});

describe("CoverageCard", () => {
    it("clamps displayed coverage percentage between 0 and 100", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 120,
            with_alt: 90,
            missing: 30,
            coverage_percent: 150,
        };

        const { getByText, getByLabelText } = renderDashboard(
            <CoverageCard data={data} featureFlags={baseFlags} queryState={successQueryState} />,
        );

        expect(getByText("100%")).toBeInTheDocument();
        expect(getByLabelText(/Coverage 100%/i)).toBeInTheDocument();
    });

    it("shows a neutral zero-state message when the media library is empty", () => {
        const data = {
            ...FALLBACK_COVERAGE,
        };

        const { getByText, container } = renderDashboard(
            <CoverageCard data={data} featureFlags={baseFlags} queryState={successQueryState} />,
        );

        expect(getByText(/No Media Library items yet/i)).toBeInTheDocument();
        expect(container.querySelector(".cat-coverage__donut")).toBeNull();
    });

    it("renders a trend sparkline when multiple points are available", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 150,
            with_alt: 120,
            missing: 30,
            coverage_percent: 80,
            trend_series: [
                { timestamp: 1, coverage: 60, total: 150, with_alt: 90, missing: 60 },
                { timestamp: 2, coverage: 70, total: 150, with_alt: 105, missing: 45 },
                { timestamp: 3, coverage: 80, total: 150, with_alt: 120, missing: 30 },
            ],
        };

        const { container } = renderDashboard(
            <CoverageCard data={data} featureFlags={baseFlags} queryState={successQueryState} />,
        );

        expect(container.querySelector(".cat-sparkline")).not.toBeNull();
    });

    it("hides the trend sparkline until there is enough history", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 150,
            with_alt: 100,
            missing: 50,
            coverage_percent: 66.7,
            trend_series: [{ timestamp: 1, coverage: 60, total: 150, with_alt: 90, missing: 60 }],
        };

        const { container } = renderDashboard(
            <CoverageCard data={data} featureFlags={baseFlags} queryState={successQueryState} />,
        );

        expect(container.querySelector(".cat-sparkline")).toBeNull();
    });

    it("gates the coverage trend behind the feature flag", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 150,
            with_alt: 120,
            missing: 30,
            coverage_percent: 80,
            trend_series: [
                { timestamp: 1, coverage: 60, total: 150, with_alt: 90, missing: 60 },
                { timestamp: 2, coverage: 70, total: 150, with_alt: 105, missing: 45 },
            ],
        };

        const { container } = renderDashboard(
            <CoverageCard
                data={data}
                featureFlags={{ coverageTrend: false }}
                queryState={successQueryState}
            />,
        );

        expect(container.querySelector(".cat-sparkline")).toBeNull();
    });

    it("renders a skeleton while the query is pending", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 200,
            with_alt: 180,
            missing: 20,
            coverage_percent: 90,
        };

        const { container, getByRole } = renderDashboard(
            <CoverageCard
                data={data}
                featureFlags={baseFlags}
                queryState={{
                    ...successQueryState,
                    status: "pending",
                    isLoading: true,
                }}
            />,
        );

        expect(getByRole("status")).toHaveClass("cat-coverage__skeleton");
        expect(container.querySelector(".cat-coverage__metric")).toBeNull();
    });

    it("surfaces error feedback with retry affordance", async () => {
        const refetch = vi.fn().mockResolvedValue(undefined);
        const data = {
            ...FALLBACK_COVERAGE,
            total: 200,
            with_alt: 150,
            missing: 50,
            coverage_percent: 75,
        };

        const { getByRole, getByText, user } = renderDashboard(
            <CoverageCard
                data={data}
                featureFlags={baseFlags}
                queryState={{
                    ...successQueryState,
                    status: "error",
                    isError: true,
                    error: new Error("Server timed out"),
                    refetch,
                }}
            />,
        );

        const alert = getByRole("alert");
        expect(alert.textContent).toContain("Unable to refresh coverage metrics");
        expect(alert.textContent).toContain("Server timed out");

        await user.click(getByText(/Try again/i));
        expect(refetch).toHaveBeenCalled();
    });

    it("announces when a refetch is in progress", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 200,
            with_alt: 150,
            missing: 50,
            coverage_percent: 75,
        };

        const { getByText } = renderDashboard(
            <CoverageCard
                data={data}
                featureFlags={baseFlags}
                queryState={{
                    ...successQueryState,
                    isFetching: true,
                }}
            />,
        );

        expect(getByText(/Refreshing latest coverage/i)).toBeInTheDocument();
    });

    it("passes axe accessibility checks", async () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 80,
            with_alt: 60,
            missing: 20,
            coverage_percent: 75,
        };

        const { container } = renderDashboard(
            <CoverageCard data={data} featureFlags={baseFlags} queryState={successQueryState} />,
        );

        const results = await axe(container);
        expect(results).toHaveNoViolations();
    });

    it("invokes the drill-down handler and emits analytics when the action is clicked", async () => {
        const analyticsSpy = vi.spyOn(analytics, "emitDashboardEvent");
        const onDrilldown = vi.fn();
        const data = {
            ...FALLBACK_COVERAGE,
            total: 50,
            with_alt: 35,
            missing: 15,
            coverage_percent: 70,
        };

        const { getByRole, user } = renderDashboard(
            <CoverageCard
                data={data}
                featureFlags={{ ...baseFlags, workbenchEnabled: true }}
                queryState={successQueryState}
                onDrilldown={onDrilldown}
            />,
        );

        const drilldownButton = getByRole("button", { name: /Workbench/i });
        await user.click(drilldownButton);

        expect(onDrilldown).toHaveBeenCalledTimes(1);
        expect(analyticsSpy).toHaveBeenCalledWith(
            "cat_coverage_drilldown",
            expect.objectContaining({
                coverage_percent: 70,
                missing: 15,
                total: 50,
            }),
        );
    });

    it("invokes the export handler and emits analytics when the action is clicked", async () => {
        const analyticsSpy = vi.spyOn(analytics, "emitDashboardEvent");
        const onExport = vi.fn();
        const data = {
            ...FALLBACK_COVERAGE,
            total: 80,
            with_alt: 60,
            missing: 20,
            coverage_percent: 75,
        };

        const { getByRole, user } = renderDashboard(
            <CoverageCard
                data={data}
                featureFlags={baseFlags}
                queryState={successQueryState}
                onExport={onExport}
            />,
        );

        const exportButton = getByRole("button", { name: /Export coverage/i });
        await user.click(exportButton);

        expect(onExport).toHaveBeenCalledTimes(1);
        expect(analyticsSpy).toHaveBeenCalledWith(
            "cat_coverage_export",
            expect.objectContaining({
                coverage_percent: 75,
                missing: 20,
                total: 80,
            }),
        );
    });

    it("hides the action buttons while the skeleton is visible", () => {
        const { queryByRole } = renderDashboard(
            <CoverageCard
                data={{
                    ...FALLBACK_COVERAGE,
                    total: 120,
                    with_alt: 90,
                    missing: 30,
                    coverage_percent: 75,
                }}
                featureFlags={{ ...baseFlags, workbenchEnabled: true }}
                queryState={{
                    ...successQueryState,
                    status: "pending",
                    isLoading: true,
                }}
                onDrilldown={vi.fn()}
                onExport={vi.fn()}
            />,
        );

        expect(queryByRole("button", { name: /Workbench/i })).toBeNull();
        expect(queryByRole("button", { name: /Export coverage/i })).toBeNull();
    });
});
