import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { BulkAltTextPanel } from "./BulkAltTextPanel";

describe("BulkAltTextPanel", () => {
    it("disables actions when no items are selected", () => {
        render(<BulkAltTextPanel selectionCount={0} />);

        expect(screen.getByRole("button", { name: /generate drafts/i })).toBeDisabled();
        expect(screen.getByRole("button", { name: /publish drafts/i })).toBeDisabled();
        expect(
            screen.getByPlaceholderText(/Enable the Workbench AI feature flag to unlock draft generation/i),
        ).toBeDisabled();
    });

    it("enables publishing but keeps generation disabled when the flag is off", () => {
        render(<BulkAltTextPanel selectionCount={3} />);

        expect(screen.getByRole("button", { name: /generate drafts/i })).toBeDisabled();
        expect(screen.getByRole("button", { name: /publish drafts/i })).toBeEnabled();
        expect(
            screen.getByPlaceholderText(/Enable the Workbench AI feature flag to unlock draft generation/i),
        ).toBeInTheDocument();
    });

    it("invokes callbacks when generation is available", () => {
        const onGenerate = vi.fn();
        const onPublish = vi.fn();

        render(
            <BulkAltTextPanel
                selectionCount={2}
                enableGeneration
                onGenerateDrafts={onGenerate}
                onPublishDrafts={onPublish}
            />,
        );

        const generate = screen.getByRole("button", { name: /generate drafts/i });
        const publish = screen.getByRole("button", { name: /publish drafts/i });

        expect(generate).toBeEnabled();
        expect(publish).toBeEnabled();

        generate.click();
        publish.click();

        expect(onGenerate).toHaveBeenCalledTimes(1);
        expect(onPublish).toHaveBeenCalledTimes(1);
        expect(
            screen.getByPlaceholderText(/Draft alt text will appear here once hooked up to the API./i),
        ).toBeInTheDocument();
    });
});
