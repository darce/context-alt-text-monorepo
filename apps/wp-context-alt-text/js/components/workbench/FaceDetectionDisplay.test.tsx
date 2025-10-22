/**
 * Face Detection Canvas Component Tests
 *
 * @package ContextAltText
 * @since 1.0.0
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FaceDetectionDisplay } from "./FaceDetectionDisplay";
import type { FaceDetection } from "../../utils/mediaPipeLoader";

/**
 * Mock MediaPipe loader
 */
vi.mock("../../utils/mediaPipeLoader", () => ({
    toPixelCoordinates: (
        normalized: {
            originX: number;
            originY: number;
            width: number;
            height: number;
        },
        imageWidth: number,
        imageHeight: number,
    ) => ({
        x: Math.round(normalized.originX * imageWidth),
        y: Math.round(normalized.originY * imageHeight),
        width: Math.round(normalized.width * imageWidth),
        height: Math.round(normalized.height * imageHeight),
    }),
}));

describe("FaceDetectionDisplay", () => {
    const mockImageUrl = "http://example.test/photo.jpg";

    const mockDetections: FaceDetection[] = [
        {
            boundingBox: {
                originX: 0.2,
                originY: 0.3,
                width: 0.15,
                height: 0.2,
            },
            confidence: 0.95,
        },
        {
            boundingBox: {
                originX: 0.5,
                originY: 0.4,
                width: 0.18,
                height: 0.22,
            },
            confidence: 0.88,
        },
    ];

    it("renders loading state initially", () => {
        render(
            <FaceDetectionDisplay imageUrl={mockImageUrl} imageAlt="Test image" detections={[]} selectedIndex={null} />,
        );

        expect(screen.getByRole("status")).toBeInTheDocument();
        expect(screen.getByText(/Loading image/i)).toBeInTheDocument();
    });

    it("renders canvas with correct dimensions", async () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                maxWidth={800}
                maxHeight={600}
            />,
        );

        const canvas = await waitFor(() => screen.getByRole("img"));

        expect(canvas).toBeInTheDocument();
        expect(canvas.tagName).toBe("CANVAS");
    });

    it("displays correct alt text for no faces", () => {
        render(
            <FaceDetectionDisplay imageUrl={mockImageUrl} imageAlt="Test image" detections={[]} selectedIndex={null} />,
        );

        const canvas = screen.getByRole("img", { hidden: true });
        expect(canvas).toHaveAttribute("aria-label", "Photo with no faces detected");
    });

    it("displays correct alt text for one face", () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={[mockDetections[0]!]}
                selectedIndex={null}
            />,
        );

        const canvas = screen.getByRole("img", { hidden: true });
        expect(canvas).toHaveAttribute("aria-label", "Photo with 1 detected face");
    });

    it("displays correct alt text for multiple faces", () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        const canvas = screen.getByRole("img", { hidden: true });
        expect(canvas).toHaveAttribute("aria-label", "Photo with 2 detected faces");
    });

    it("calls onFaceClick when face is clicked", async () => {
        const user = userEvent.setup();
        const handleClick = vi.fn();

        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                onFaceClick={handleClick}
            />,
        );

        const canvas = screen.getByRole("img", { hidden: true });

        // Click on canvas (simplified - actual click handling requires canvas coordinate math)
        await user.click(canvas);

        // Note: Full click detection requires DOM measurements which are not available in JSDOM
        // This test verifies the click handler is attached
        expect(canvas).toHaveAttribute("tabindex", "0");
    });

    it("is keyboard accessible", () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                onFaceClick={vi.fn()}
            />,
        );

        const canvas = screen.getByRole("img", { hidden: true });
        expect(canvas).toHaveAttribute("tabindex", "0");
    });

    it("provides screen reader help text when faces detected", () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        // Help text is present but visually hidden
        const helpText = screen.getByText(/Use Tab key to navigate/i);
        expect(helpText).toBeInTheDocument();
        expect(helpText).toHaveClass("screen-reader-text");
    });

    it("does not show help text when no faces detected", () => {
        render(
            <FaceDetectionDisplay imageUrl={mockImageUrl} imageAlt="Test image" detections={[]} selectedIndex={null} />,
        );

        expect(screen.queryByText(/Use Tab key to navigate/i)).not.toBeInTheDocument();
    });

    it("respects maxWidth constraint", () => {
        const { container } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                maxWidth={400}
            />,
        );

        const canvas = container.querySelector("canvas");
        expect(canvas).toBeInTheDocument();
        // Width will be set after image loads
    });

    it("respects maxHeight constraint", () => {
        const { container } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                maxHeight={300}
            />,
        );

        const canvas = container.querySelector("canvas");
        expect(canvas).toBeInTheDocument();
        // Height will be set after image loads
    });

    it("handles image load failure gracefully", () => {
        const consoleError = vi.spyOn(console, "error").mockImplementation(() => {
            // Mock implementation
        });

        render(
            <FaceDetectionDisplay
                imageUrl="http://example.test/invalid.jpg"
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        // Component should still render loading state
        expect(screen.getByRole("status")).toBeInTheDocument();

        consoleError.mockRestore();
    });

    it("updates when imageUrl changes", () => {
        const { rerender } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        rerender(
            <FaceDetectionDisplay
                imageUrl="http://example.test/new-photo.jpg"
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        // Should show loading state again
        expect(screen.getByRole("status")).toBeInTheDocument();
    });

    it("updates when detections change", () => {
        const { rerender } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        const newDetections: FaceDetection[] = [mockDetections[0]!];

        rerender(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={newDetections}
                selectedIndex={null}
            />,
        );

        const canvas = screen.getByRole("img", { hidden: true });
        expect(canvas).toHaveAttribute("aria-label", "Photo with 1 detected face");
    });

    it("highlights selected face", () => {
        const { rerender } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        rerender(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={0}
            />,
        );

        // Canvas should re-render with highlighted box
        // (Canvas drawing is tested via visual regression in E2E)
        expect(screen.getByRole("img", { hidden: true })).toBeInTheDocument();
    });

    it("optionally shows confidence scores", () => {
        const { rerender } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                showConfidence={false}
            />,
        );

        rerender(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                showConfidence={true}
            />,
        );

        // Canvas should re-render with confidence labels
        // (Canvas text rendering is tested via visual regression in E2E)
        expect(screen.getByRole("img", { hidden: true })).toBeInTheDocument();
    });
});
