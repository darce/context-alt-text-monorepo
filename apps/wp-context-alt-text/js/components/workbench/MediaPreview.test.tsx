import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/components/workbench/utils", () => ({
    formatWorkbenchDate: vi.fn(() => "April 1, 2024, 10:00 AM"),
}));

import { MediaPreview } from "./MediaPreview";
import type { WorkbenchMediaItem } from "./WorkbenchApp";
import { formatWorkbenchDate } from "@/components/workbench/utils";

describe("MediaPreview", () => {
    const baseItem: WorkbenchMediaItem = {
        id: "1",
        title: "Sample asset",
        status: "missing",
        updatedAt: "2024-04-01T10:00:00.000Z",
        altText: "",
        mimeType: "image/jpeg",
        dimensions: { width: 800, height: 600 },
        editUrl: "https://example.test/edit/1",
    };

    it("prompts the user to make a selection when nothing is chosen", () => {
        render(<MediaPreview selectedIds={new Set()} items={[baseItem]} />);

        expect(
            screen.getByText(/Select an item to preview metadata, recognition insights, and draft alt text./i),
        ).toBeInTheDocument();
    });

    it("surfaces metadata for the first selected item", () => {
        render(<MediaPreview selectedIds={new Set(["1"])} items={[{ ...baseItem, altText: "A scenic landscape" }]} />);

        expect(screen.getByRole("heading", { name: /Sample asset/i })).toBeInTheDocument();
        expect(screen.getByText(/Needs alt text/i)).toBeInTheDocument();
        expect(screen.getByText(/April 1, 2024, 10:00 AM/i)).toBeInTheDocument();
        expect(screen.getByText(/800×600px/i)).toBeInTheDocument();
        expect(screen.getByText(/A scenic landscape/i)).toBeInTheDocument();
        expect(formatWorkbenchDate).toHaveBeenCalledWith("2024-04-01T10:00:00.000Z");
    });

    it("falls back gracefully when metadata is missing", () => {
        render(
            <MediaPreview
                selectedIds={new Set(["2"])}
                items={[
                    baseItem,
                    {
                        ...baseItem,
                        id: "2",
                        title: "Thumbnail absent",
                        thumbnailUrl: undefined,
                        dimensions: undefined,
                        mimeType: undefined,
                    },
                ]}
            />,
        );

        expect(screen.getByRole("heading", { name: /Thumbnail absent/i })).toBeInTheDocument();
        const fallbacks = screen.getAllByText(/Unknown/i);
        expect(fallbacks).toHaveLength(2);
        expect(screen.getByText(/Not provided yet\./i)).toBeInTheDocument();
    });
});
