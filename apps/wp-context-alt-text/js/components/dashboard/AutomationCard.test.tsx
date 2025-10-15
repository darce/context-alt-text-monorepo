import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { AutomationCard } from "./AutomationCard";
import { renderDashboard } from "@/admin/testing/renderDashboard";

describe("AutomationCard", () => {
    it("shows queued, running, and completed counts", () => {
        const data = {
            queued: 4,
            running: 1,
            completed: 12,
            next_run: null,
        };

        const { getByText } = renderDashboard(<AutomationCard data={data} />);

        expect(getByText("4")).toBeInTheDocument();
        expect(getByText("1")).toBeInTheDocument();
        expect(getByText("12")).toBeInTheDocument();
    });

    it("describes the next scheduled run when provided", () => {
        const data = {
            queued: 0,
            running: 0,
            completed: 0,
            next_run: "15 minutes",
        };

        const { container } = renderDashboard(<AutomationCard data={data} />);

        const nextRun = container.querySelector(".cat-automation__next");
        expect(nextRun).not.toBeNull();
        expect(nextRun?.textContent).toContain("Next scheduled action in 15 minutes");
    });

    it("hides the next run copy when not set", () => {
        const data = {
            queued: 0,
            running: 0,
            completed: 0,
            next_run: null,
        };

        const { queryByText } = renderDashboard(<AutomationCard data={data} />);

        expect(queryByText(/Next scheduled action/i)).toBeNull();
    });

    it("passes axe accessibility checks", async () => {
        const data = {
            queued: 2,
            running: 1,
            completed: 5,
            next_run: "30 minutes",
        };

        const { container } = renderDashboard(<AutomationCard data={data} />);

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });
});
