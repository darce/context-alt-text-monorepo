import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SuggestionChip } from "./SuggestionChip";

describe("SuggestionChip", () => {
    it("renders suggestion details", () => {
        render(<SuggestionChip displayName="Jordan Lee" confidence={0.92} reason="Recent match" />);

        expect(screen.getByText(/Suggested match/i)).toBeInTheDocument();
        expect(screen.getByText("Jordan Lee")).toBeInTheDocument();
        expect(screen.getByText(/92% confidence/i)).toBeInTheDocument();
        expect(screen.getByText("Recent match")).toBeInTheDocument();
    });

    it("supports interactive selection", async () => {
        const handleSelect = vi.fn();
        const user = userEvent.setup();

        render(<SuggestionChip displayName="Harper Lane" onSelect={handleSelect} confidence={0.81} />);

        const button = screen.getByRole("button", { name: /Suggested match/i });
        expect(button).not.toBeDisabled();

        await user.click(button);

        expect(handleSelect).toHaveBeenCalledTimes(1);
    });
});
