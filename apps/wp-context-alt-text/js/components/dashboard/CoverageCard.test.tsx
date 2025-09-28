import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { CoverageCard } from "./CoverageCard";
import { renderDashboard } from "@/admin/testing/renderDashboard";
import { FALLBACK_COVERAGE } from "@/admin/dashboardData";

describe("CoverageCard", () => {
    it("clamps displayed coverage percentage between 0 and 100", () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 120,
            with_alt: 90,
            missing: 30,
            coverage_percent: 150,
        };

        const { getByText, getByLabelText } = renderDashboard(<CoverageCard data={data} />);

        expect(getByText("100%")).toBeInTheDocument();
        expect(getByLabelText(/Coverage 100%/i)).toBeInTheDocument();
    });

    it("shows a neutral zero-state message when the media library is empty", () => {
        const data = {
            ...FALLBACK_COVERAGE,
        };

        const { getByText, container } = renderDashboard(<CoverageCard data={data} />);

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

        const { container } = renderDashboard(<CoverageCard data={data} />);

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

        const { container } = renderDashboard(<CoverageCard data={data} />);

        expect(container.querySelector(".cat-sparkline")).toBeNull();
    });

    // NOTE: When the coverage trend feature flag graduates to GA, update the expectations
    // in this suite to reflect the new default behaviour. See CAT-FEATURE-COVERAGE-TREND.

    it("passes axe accessibility checks", async () => {
        const data = {
            ...FALLBACK_COVERAGE,
            total: 80,
            with_alt: 60,
            missing: 20,
            coverage_percent: 75,
        };

        const { container } = renderDashboard(<CoverageCard data={data} />);

        const results = await axe(container);
        expect(results).toHaveNoViolations();
    });
});
