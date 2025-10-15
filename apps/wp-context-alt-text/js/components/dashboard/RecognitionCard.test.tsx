import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { RecognitionCard } from "./RecognitionCard";
import { renderDashboard } from "@/admin/testing/renderDashboard";

describe("RecognitionCard", () => {
    it("highlights non-zero counts with the warning class", () => {
        const data = {
            pending_faces: 3,
            pending_brands: 2,
            unresolved_matches: 5,
            roster_pending: 4,
            roster_conflicts: 1,
            roster_total: 12,
            last_roster_sync_human: "5 minutes",
            last_roster_sync_at: "2024-03-17T00:00:00.000Z",
        };

        const { container } = renderDashboard(
            <RecognitionCard data={data} rosterEnabled />,
            { withRouter: true },
        );

        const warnings = container.querySelectorAll(".cat-text-warning");
        expect(warnings).toHaveLength(5);
        expect([...warnings].map((node) => node.textContent?.trim())).toEqual(["3", "2", "5", "4", "1"]);
    });

    it("renders plain counts when everything is cleared", () => {
        const data = {
            pending_faces: 0,
            pending_brands: 0,
            unresolved_matches: 0,
            roster_pending: 0,
            roster_conflicts: 0,
            roster_total: 0,
            last_roster_sync_human: null,
            last_roster_sync_at: null,
        };

        const { container, getAllByText } = renderDashboard(
            <RecognitionCard data={data} rosterEnabled />,
            { withRouter: true },
        );

        expect(getAllByText("0")).toHaveLength(5);
        expect(container.querySelectorAll(".cat-text-warning")).toHaveLength(0);
        expect(container.querySelector(".cat-recognition__meta")?.textContent).toMatch(/not run yet/i);
    });

    it("passes axe accessibility checks", async () => {
        const data = {
            pending_faces: 1,
            pending_brands: 0,
            unresolved_matches: 2,
            roster_pending: 1,
            roster_conflicts: 0,
            roster_total: 6,
            last_roster_sync_human: "10 minutes",
            last_roster_sync_at: "2024-03-17T00:05:00.000Z",
        };

        const { container, getByRole } = renderDashboard(
            <RecognitionCard data={data} rosterEnabled />,
            { withRouter: true },
        );

        expect(getByRole("link", { name: /review roster/i })).toBeInTheDocument();

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });
});
