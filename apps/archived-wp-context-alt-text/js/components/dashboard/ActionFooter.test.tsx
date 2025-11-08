import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { ActionFooter } from "./ActionFooter";
import { renderDashboard } from "@/admin/testing/renderDashboard";

const buildFooterData = () => ({
    actions: [
        { label: "Run scan again", url: "/wp-admin/admin.php?page=context-alt-text-scan" },
        { label: "Open Alt-Text Workbench", url: "/wp-admin/admin.php?page=context-alt-text-workbench" },
    ],
    statusText: "Last scan completed 10 minutes ago.",
});

describe("ActionFooter", () => {
    it("renders dashboard actions and status text", () => {
        const data = buildFooterData();

        const { getByRole, getByText } = renderDashboard(<ActionFooter data={data} />);

        const [firstAction, secondAction] = data.actions;

        expect(firstAction).toBeDefined();
        expect(secondAction).toBeDefined();

        expect(getByRole("link", { name: /Run scan again/i })).toHaveAttribute("href", firstAction!.url);
        expect(getByRole("link", { name: /Open Alt-Text Workbench/i })).toHaveAttribute("href", secondAction!.url);
        expect(getByText(data.statusText)).toBeInTheDocument();
    });

    it("passes axe accessibility checks", async () => {
        const data = buildFooterData();

        const { container } = renderDashboard(<ActionFooter data={data} />);

        const results = await axe(container);
        expect(results.violations).toHaveLength(0);
    });
});
