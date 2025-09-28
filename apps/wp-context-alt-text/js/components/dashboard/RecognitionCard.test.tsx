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
        };

        const { container } = renderDashboard(<RecognitionCard data={data} />);

        const warnings = container.querySelectorAll(".cat-text-warning");
        expect(warnings).toHaveLength(3);
        expect([...warnings].map((node) => node.textContent?.trim())).toEqual(["3", "2", "5"]);
    });

    it("renders plain counts when everything is cleared", () => {
        const data = {
            pending_faces: 0,
            pending_brands: 0,
            unresolved_matches: 0,
        };

        const { container, getAllByText } = renderDashboard(<RecognitionCard data={data} />);

        expect(getAllByText("0")).toHaveLength(3);
        expect(container.querySelectorAll(".cat-text-warning")).toHaveLength(0);
    });

    it("passes axe accessibility checks", async () => {
        const data = {
            pending_faces: 1,
            pending_brands: 0,
            unresolved_matches: 2,
        };

        const { container } = renderDashboard(<RecognitionCard data={data} />);

        const results = await axe(container);
        expect(results).toHaveNoViolations();
    });
});
