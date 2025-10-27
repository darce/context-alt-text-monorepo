import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { FaceGrid } from "./FaceGrid";
import type { ClusterFaceDetail } from "@/types/face-clustering";

const createFaces = (count: number): ClusterFaceDetail[] => {
    return Array.from({ length: count }).map((_, index) => ({
        id: `face-${index + 1}`,
        attachmentId: 100 + index,
        databaseId: null,
        clusterId: "cluster-alpha",
        detectedAt: "2025-10-24T12:00:00Z",
        resolvedAt: null,
        rosterId: null,
        embeddingId: null,
        thumbnailUrl: `http://example.test/crops/face-${index + 1}.jpg`,
        bbox: { x: 10, y: 20, width: 80, height: 90 },
    }));
};

describe("FaceGrid", () => {
    it("supports roving tabindex and arrow-key navigation", async () => {
        const faces = createFaces(4);
        const handleToggle = vi.fn();
        const user = userEvent.setup();

        render(
            <FaceGrid
                faces={faces}
                selectedFaceIds={["face-1"]}
                onToggleFace={handleToggle}
                selectionAnchorIndex={0}
            />,
        );

        const faceButtons = screen.getAllByRole("button", { name: /face \d+ preview/i });

        expect(faceButtons).toHaveLength(4);
        expect(faceButtons[0]).toHaveAttribute("tabIndex", "0");
        expect(faceButtons[1]).toHaveAttribute("tabIndex", "-1");

        faceButtons[0].focus();
        expect(document.activeElement).toBe(faceButtons[0]);

        await user.keyboard("[ArrowRight]");
        expect(document.activeElement).toBe(faceButtons[1]);
        expect(faceButtons[1]).toHaveAttribute("tabIndex", "0");
        expect(faceButtons[0]).toHaveAttribute("tabIndex", "-1");

        await user.keyboard("[ArrowLeft]");
        expect(document.activeElement).toBe(faceButtons[0]);
        expect(faceButtons[0]).toHaveAttribute("tabIndex", "0");
        expect(faceButtons[1]).toHaveAttribute("tabIndex", "-1");

        expect(handleToggle).not.toHaveBeenCalled();
    });

    it("toggles face selection with Space and Enter keys", async () => {
        const faces = createFaces(2);
        const handleToggle = vi.fn();
        const user = userEvent.setup();

        render(
            <FaceGrid
                faces={faces}
                selectedFaceIds={["face-1"]}
                onToggleFace={handleToggle}
                selectionAnchorIndex={0}
            />,
        );

        const faceButtons = screen.getAllByRole("button", { name: /face \d+ preview/i });
        faceButtons[1].focus();

        await user.keyboard("[Space]");
        await user.keyboard("[Enter]");

        expect(handleToggle).toHaveBeenCalledTimes(2);
        expect(handleToggle).toHaveBeenNthCalledWith(1, "face-2", { index: 1 });
        expect(handleToggle).toHaveBeenNthCalledWith(2, "face-2", { index: 1 });
    });

    it("selects range when shift-clicking a face", async () => {
        const faces = createFaces(4);
        const handleRange = vi.fn();
        const handleToggle = vi.fn();
        const user = userEvent.setup();

        render(
            <FaceGrid
                faces={faces}
                selectedFaceIds={["face-1"]}
                onToggleFace={handleToggle}
                onRangeSelect={handleRange}
                selectionAnchorIndex={0}
            />,
        );

        const faceButtons = screen.getAllByRole("button", { name: /face \d+ preview/i });
        await user.click(faceButtons[0]);
        fireEvent.click(faceButtons[2], { shiftKey: true });

        expect(handleRange).toHaveBeenCalledWith({
            faceIds: ["face-1", "face-2", "face-3"],
            startIndex: 0,
            endIndex: 2,
        });
        expect(handleToggle).toHaveBeenCalledWith("face-1", { index: 0 });
    });

    it("supports Cmd/Ctrl+A shortcut to select all", async () => {
        const faces = createFaces(3);
        const handleSelectAll = vi.fn();
        const user = userEvent.setup();

        render(
            <FaceGrid
                faces={faces}
                selectedFaceIds={["face-1"]}
                onToggleFace={vi.fn()}
                onSelectAll={handleSelectAll}
                selectionAnchorIndex={0}
            />,
        );

        const [firstButton] = screen.getAllByRole("button", { name: /face \d+ preview/i });
        firstButton.focus();

        await user.keyboard("{Control>}a{/Control}");

        expect(handleSelectAll).toHaveBeenCalledTimes(1);
    });

    it("extends selection with shift + arrow keys", async () => {
        const faces = createFaces(4);
        const handleRange = vi.fn();
        const user = userEvent.setup();

        render(
            <FaceGrid
                faces={faces}
                selectedFaceIds={["face-2"]}
                onToggleFace={vi.fn()}
                onRangeSelect={handleRange}
                selectionAnchorIndex={1}
            />,
        );

        const faceButtons = screen.getAllByRole("button", { name: /face \d+ preview/i });
        faceButtons[1].focus();

        await user.keyboard("{Shift>}[ArrowRight]{/Shift}");

        expect(handleRange).toHaveBeenCalledWith({
            faceIds: ["face-2", "face-3"],
            startIndex: 1,
            endIndex: 2,
        });
    });
});
