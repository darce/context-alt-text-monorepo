import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import * as axeMatchers from "vitest-axe/matchers";
import type { AxeMatchers } from "vitest-axe/matchers";

import { SelectionToolbar } from "./SelectionToolbar";

expect.extend(axeMatchers);

declare module "vitest" {
    interface Assertion<T = any> extends AxeMatchers { }
    interface AsymmetricMatchersContaining extends AxeMatchers { }
}

describe("SelectionToolbar", () => {
    it("renders with no selection", () => {
        render(
            <SelectionToolbar
                selectionCount={0}
                onClearSelection={vi.fn()}
            />,
        );

        // Text is split across elements: "0" + " items" + " selected"
        expect(screen.getByText('0')).toBeInTheDocument();
        expect(screen.getByText(/selected/i)).toBeInTheDocument();
    });

    it("renders with selection count", () => {
        render(
            <SelectionToolbar
                selectionCount={5}
                onClearSelection={vi.fn()}
            />,
        );

        // Text is split across elements: "5" + " items" + " selected"
        expect(screen.getByText('5')).toBeInTheDocument();
        expect(screen.getByText(/selected/i)).toBeInTheDocument();
    });

    it("disables action buttons when no items selected", () => {
        render(
            <SelectionToolbar
                selectionCount={0}
                onClearSelection={vi.fn()}
            />,
        );

        const generateBtn = screen.getByRole("button", { name: "Generate Alt Text" });
        const regenerateBtn = screen.getByRole("button", { name: "Regenerate" });
        const reviewedBtn = screen.getByRole("button", { name: "Mark Reviewed" });

        expect(generateBtn).toBeDisabled();
        expect(regenerateBtn).toBeDisabled();
        expect(reviewedBtn).toBeDisabled();
    });

    it("enables action buttons when items selected", () => {
        render(
            <SelectionToolbar
                selectionCount={3}
                onClearSelection={vi.fn()}
            />,
        );

        const generateBtn = screen.getByRole("button", { name: "Generate Alt Text" });
        const regenerateBtn = screen.getByRole("button", { name: "Regenerate" });
        const reviewedBtn = screen.getByRole("button", { name: "Mark Reviewed" });

        expect(generateBtn).not.toBeDisabled();
        expect(regenerateBtn).not.toBeDisabled();
        expect(reviewedBtn).not.toBeDisabled();
    });

    // Note: Action button callbacks are not exposed as props yet
    // These will be wired through WorkbenchApp's bulk action handlers

    it("calls onClearSelection when clear button clicked", async () => {
        const user = userEvent.setup();
        const onClearSelection = vi.fn();

        render(
            <SelectionToolbar
                selectionCount={5}
                onClearSelection={onClearSelection}
            />,
        );

        const clearBtn = screen.getByRole("button", { name: "Clear Selection" });
        await user.click(clearBtn);

        expect(onClearSelection).toHaveBeenCalledTimes(1);
    });

    it("shows clear button when items selected", () => {
        render(
            <SelectionToolbar
                selectionCount={3}
                onClearSelection={vi.fn()}
            />,
        );

        expect(screen.getByRole("button", { name: "Clear Selection" })).toBeInTheDocument();
    });

    it("has no accessibility violations", async () => {
        const { container } = render(
            <SelectionToolbar
                selectionCount={3}
                onClearSelection={vi.fn()}
            />,
        );

        const results = await axe(container);
        expect(results).toHaveNoViolations();
    });

    it("supports keyboard navigation", async () => {
        const user = userEvent.setup();

        render(
            <SelectionToolbar
                selectionCount={2}
                onClearSelection={vi.fn()}
            />,
        );

        const generateBtn = screen.getByRole("button", { name: "Generate Alt Text" });

        // Tab to focus the button
        await user.tab();
        expect(generateBtn).toHaveFocus();

        // Buttons should be keyboard accessible
        expect(generateBtn).not.toBeDisabled();
    });
});
