/**
 * PeopleOverlay Component Tests
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { PeopleOverlay, type PeopleOverlayProps } from "./PeopleOverlay";
import type { DetectedFaceFE } from "@/types/people-labeling";

// Mock FaceChip component
vi.mock("./FaceChip", () => ({
    FaceChip: ({ label, variant, isSelected, onClick, confidence }: any) => (
        <button
            onClick={onClick}
            data-testid="face-chip"
            data-label={label}
            data-variant={variant}
            data-selected={isSelected}
            data-confidence={confidence}
        >
            {label}
        </button>
    ),
}));

describe("PeopleOverlay", () => {
    const mockFaces: DetectedFaceFE[] = [
        {
            faceId: "face-1",
            attachmentId: 123,
            bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
            confidence: 0.95,
            suggestions: [{ rosterId: "person-1", display: "Ana Rodriguez", score: 0.95 }],
            clusterId: null,
            confirmedRosterId: null,
            labelDraft: null,
        },
        {
            faceId: "face-2",
            attachmentId: 123,
            bbox: { x: 0.5, y: 0.6, width: 0.2, height: 0.25 },
            confidence: 0.85,
            suggestions: [],
            clusterId: "cluster-1",
            confirmedRosterId: null,
            labelDraft: null,
        },
    ];

    const defaultProps: PeopleOverlayProps = {
        imageUrl: "https://example.com/photo.jpg",
        imageAlt: "Test photo",
        faces: mockFaces,
        selectedFaceIndex: null,
        onFaceClick: vi.fn(),
    };

    /**
     * Helper to locate overlay image element.
     */
    const getOverlayImage = (): HTMLImageElement => {
        const element = document.querySelector(".cat-people-overlay__image");
        if (!(element instanceof HTMLImageElement)) {
            throw new Error("Image element not found");
        }

        return element;
    };

    /**
     * Helper to trigger image load event in tests
     */
    const triggerImageLoad = () => {
        const img = getOverlayImage();

        // Mock natural dimensions
        Object.defineProperty(img, "naturalWidth", { value: 800, writable: true });
        Object.defineProperty(img, "naturalHeight", { value: 600, writable: true });
        Object.defineProperty(img, "complete", { value: true, writable: true });
        // Fire load event
        img.dispatchEvent(new Event("load"));
    };

    describe("Basic Rendering", () => {
        it("renders the image with correct src and alt", () => {
            render(<PeopleOverlay {...defaultProps} />);

            // Image is initially hidden, query directly
            const image = document.querySelector(".cat-people-overlay__image");
            expect(image).toBeInTheDocument();
            expect(image).toHaveAttribute("src", "https://example.com/photo.jpg");
            expect(image).toHaveAttribute("alt", "Test photo");
        });

        it("shows loading state initially", () => {
            render(<PeopleOverlay {...defaultProps} />);

            expect(screen.getByText(/Loading image/i)).toBeInTheDocument();
            expect(screen.getByRole("status")).toBeInTheDocument();
        });

        it("renders face chips for each detected face", async () => {
            render(<PeopleOverlay {...defaultProps} />);
            triggerImageLoad();

            await waitFor(() => {
                const chips = screen.getAllByTestId("face-chip");
                expect(chips).toHaveLength(2);
            });
        });

        it("hides loading state after image loads", async () => {
            render(<PeopleOverlay {...defaultProps} />);

            expect(screen.getByText(/Loading image/i)).toBeInTheDocument();

            triggerImageLoad();

            await waitFor(() => {
                expect(screen.queryByText(/Loading image/i)).not.toBeInTheDocument();
            });
        });
    });

    describe("Face Chip Variants", () => {
        it("renders suggested chip for face with FAISS match", async () => {
            render(<PeopleOverlay {...defaultProps} />);
            triggerImageLoad();

            await waitFor(() => {
                const chips = screen.getAllByTestId("face-chip");
                const suggestedChip = chips[0];
                expect(suggestedChip).toHaveAttribute("data-label", "Ana Rodriguez?");
                expect(suggestedChip).toHaveAttribute("data-variant", "suggested");
                expect(suggestedChip).toHaveAttribute("data-confidence", "0.95");
            });
        });

        it("renders unknown chip for face without suggestions", async () => {
            render(<PeopleOverlay {...defaultProps} />);
            triggerImageLoad();

            await waitFor(() => {
                const chips = screen.getAllByTestId("face-chip");
                const unknownChip = chips[1];
                expect(unknownChip).toHaveAttribute("data-label", "Who is this?");
                expect(unknownChip).toHaveAttribute("data-variant", "unknown");
            });
        });

        it("renders confirmed chip for face with draft label (new person)", async () => {
            const facesWithDraft: DetectedFaceFE[] = [
                {
                    ...mockFaces[1]!,
                    labelDraft: { newName: "Maria Silva" },
                },
            ];

            render(<PeopleOverlay {...defaultProps} faces={facesWithDraft} />);
            triggerImageLoad();

            await waitFor(() => {
                const chip = screen.getByTestId("face-chip");
                expect(chip).toHaveAttribute("data-label", "Maria Silva");
                expect(chip).toHaveAttribute("data-variant", "confirmed");
            });
        });
    });

    describe("Selection State", () => {
        it("updates selection when selectedFaceIndex changes", async () => {
            const { rerender } = render(<PeopleOverlay {...defaultProps} selectedFaceIndex={0} />);
            triggerImageLoad();

            await waitFor(() => {
                const chips = screen.getAllByTestId("face-chip");
                expect(chips[0]).toHaveAttribute("data-selected", "true");
            });

            rerender(<PeopleOverlay {...defaultProps} selectedFaceIndex={1} />);

            await waitFor(() => {
                const chips = screen.getAllByTestId("face-chip");
                expect(chips[0]).toHaveAttribute("data-selected", "false");
                expect(chips[1]).toHaveAttribute("data-selected", "true");
            });
        });
    });

    describe("User Interactions", () => {
        it("calls onFaceClick when clicking a face chip", async () => {
            const user = userEvent.setup();
            const onFaceClick = vi.fn();

            render(<PeopleOverlay {...defaultProps} onFaceClick={onFaceClick} />);
            triggerImageLoad();

            await waitFor(() => {
                expect(screen.getAllByTestId("face-chip")).toHaveLength(2);
            });

            const chips = screen.getAllByTestId("face-chip");
            await user.click(chips[0]!);

            expect(onFaceClick).toHaveBeenCalledWith(0);
        });
    });

    // Image loading callback tests removed; overlay no longer exposes onImageLoad hook.

    describe("Edge Cases", () => {
        it("handles faces with no suggestions", async () => {
            const facesNoSuggestions: DetectedFaceFE[] = [
                {
                    faceId: "face-1",
                    attachmentId: 123,
                    bbox: { x: 0.1, y: 0.1, width: 0.2, height: 0.2 },
                    confidence: 0.99,
                    suggestions: [],
                    clusterId: null,
                    confirmedRosterId: null,
                    labelDraft: null,
                },
            ];

            render(<PeopleOverlay {...defaultProps} faces={facesNoSuggestions} />);
            triggerImageLoad();

            await waitFor(() => {
                const chip = screen.getByTestId("face-chip");
                expect(chip).toHaveAttribute("data-label", "Who is this?");
                expect(chip).toHaveAttribute("data-variant", "unknown");
            });
        });

        it("handles selectedFaceIndex = null", async () => {
            render(<PeopleOverlay {...defaultProps} selectedFaceIndex={null} />);
            triggerImageLoad();

            await waitFor(() => {
                const chips = screen.getAllByTestId("face-chip");
                chips.forEach((chip) => {
                    expect(chip).toHaveAttribute("data-selected", "false");
                });
            });
        });
    });

    describe("Accessibility", () => {
        it("has crossOrigin attribute on image for CORS", () => {
            render(<PeopleOverlay {...defaultProps} />);
            triggerImageLoad();

            const image = getOverlayImage();
            expect(image).toHaveAttribute("crossOrigin", "anonymous");
        });

        it("has aria-live region for help text", async () => {
            render(<PeopleOverlay {...defaultProps} />);
            triggerImageLoad();

            await waitFor(() => {
                const helpRegion = screen.getByRole("region");
                expect(helpRegion).toHaveAttribute("aria-live", "polite");
            });
        });

        it("has role=status on loading indicator", () => {
            render(<PeopleOverlay {...defaultProps} />);

            expect(screen.getByRole("status")).toBeInTheDocument();
        });

        it("has screen reader text for loading", () => {
            render(<PeopleOverlay {...defaultProps} />);

            expect(screen.getByText(/Loading image/i)).toHaveClass("screen-reader-text");
        });
    });
});
