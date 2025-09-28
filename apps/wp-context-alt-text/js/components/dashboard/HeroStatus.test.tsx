import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { HeroStatusSection } from "./HeroStatus";
import { renderDashboard } from "@/admin/testing/renderDashboard";
import { getDashboardData } from "@/admin/dashboardData";

describe("HeroStatusSection", () => {
    it("renders the scanning fallback message and styling", () => {
        const { hero } = getDashboardData();

        const { getByText, container } = renderDashboard(<HeroStatusSection data={hero} />);

        expect(getByText(/Scanning media library/i)).toBeInTheDocument();
        const section = container.querySelector(".cat-hero");
        expect(section).not.toBeNull();
        expect(section).toHaveClass("cat-hero--scanning");
    });

    it("shows ready-state CTA label and timestamp when provided", () => {
        const data = {
            state: "ready" as const,
            message: "Scan complete — fix them now.",
            cta_label: "Open Alt-Text Workbench",
            cta_url: "/wp-admin/admin.php?page=context-alt-text",
            last_updated_human: "5 minutes",
        };

        const { getByRole, getByText, container } = renderDashboard(<HeroStatusSection data={data} />);

        expect(getByText(/Scan complete/i)).toBeInTheDocument();
        const section = container.querySelector(".cat-hero");
        expect(section).not.toBeNull();
        expect(section).toHaveClass("cat-hero--ready");

        const cta = getByRole("link", { name: /Open Alt-Text Workbench/i });
        expect(cta).toHaveAttribute("href", data.cta_url);

        expect(getByText(/Last updated 5 minutes ago/i)).toBeInTheDocument();
    });

    it("updates the timestamp copy when hero data changes", () => {
        const base = {
            state: "ready" as const,
            message: "Scan complete — fix them now.",
            cta_label: "Open Alt-Text Workbench",
            cta_url: "/wp-admin/admin.php?page=context-alt-text",
            last_updated_human: "3 minutes",
        };

        const { rerender, queryByText, getByText } = renderDashboard(<HeroStatusSection data={base} />);

        expect(getByText(/Last updated 3 minutes ago/i)).toBeInTheDocument();

        const updated = { ...base, last_updated_human: "4 minutes" };
        rerender(<HeroStatusSection data={updated} />);

        expect(queryByText(/Last updated 3 minutes ago/i)).not.toBeInTheDocument();
        expect(getByText(/Last updated 4 minutes ago/i)).toBeInTheDocument();
    });

    it("passes axe accessibility checks", async () => {
        const data = {
            state: "ready" as const,
            message: "Scan complete — fix them now.",
            cta_label: "Open Alt-Text Workbench",
            cta_url: "/wp-admin/admin.php?page=context-alt-text",
            last_updated_human: "5 minutes",
        };

        const { container } = renderDashboard(<HeroStatusSection data={data} />);

        const results = await axe(container);
        expect(results).toHaveNoViolations();
    });
});
