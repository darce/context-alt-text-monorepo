import { describe, expect, it, vi, afterEach } from "vitest";
import { axe } from "vitest-axe";

import { ActivityCard } from "./ActivityCard";
import { renderDashboard } from "@/admin/testing/renderDashboard";

describe("ActivityCard", () => {
    afterEach(() => {
        vi.useRealTimers();
    });

    it("shows fallback copy when no recent activity is available", () => {
        const data = {
            last_recognition: null,
            last_alt_text_generation: null,
            last_roster_sync: null,
        };

        const { getAllByText } = renderDashboard(<ActivityCard data={data} />);

        const placeholders = getAllByText(/No recent activity/i);
        expect(placeholders).toHaveLength(3);
    });

    it("formats relative timestamps and preserves string values", () => {
        const baseDate = new Date("2024-01-01T12:00:00.000Z");
        vi.useFakeTimers();
        vi.setSystemTime(baseDate);

        const fiveMinutesAgo = baseDate.getTime() / 1000 - 5 * 60;
        const data = {
            last_recognition: fiveMinutesAgo,
            last_alt_text_generation: "Manual batch",
            last_roster_sync: baseDate.getTime() / 1000 - 10,
        };

        const { getByText } = renderDashboard(<ActivityCard data={data} />);

        expect(getByText(/5 minutes ago/i)).toBeInTheDocument();
        expect(getByText("Manual batch")).toBeInTheDocument();
        expect(getByText(/Just now/i)).toBeInTheDocument();
    });

    it("passes axe accessibility checks", async () => {
        const data = {
            last_recognition: 0,
            last_alt_text_generation: "Manual batch",
            last_roster_sync: 0,
        };

        const { container } = renderDashboard(<ActivityCard data={data} />);

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });
});
