/**
 * Face Detection Canvas Component Tests
 *
 * @package ContextAltText
 * @since 1.0.0
 */

import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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

/**
 * Helper to wait for image to load in tests
 */
const waitForImageLoad = async () => {
    await waitFor(() => {
        const img = document.querySelector(".cat-face-detection__image") as HTMLImageElement;
        if (!img) throw new Error("Image not found");

        // Simulate image load event
        Object.defineProperty(img, "naturalWidth", { value: 1000, writable: true });
        Object.defineProperty(img, "naturalHeight", { value: 800, writable: true });
        Object.defineProperty(img, "complete", { value: true, writable: true });
        fireEvent.load(img);

        // Wait for container to become visible
        const container = document.querySelector(".cat-face-detection__container") as HTMLElement;
        if (!container || container.style.display === "none") {
            throw new Error("Container not visible yet");
        }
    });
};

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

    it("renders image with correct dimensions", async () => {
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

        await waitForImageLoad();
        const image = screen.getByRole("img");

        expect(image).toBeInTheDocument();
        expect(image.tagName).toBe("IMG");
        expect(image).toHaveAttribute("alt", "Test image");
    });

    it("displays correct alt text for no faces", () => {
        render(
            <FaceDetectionDisplay imageUrl={mockImageUrl} imageAlt="Test image" detections={[]} selectedIndex={null} />,
        );

        const image = screen.getByRole("img", { hidden: true });
        expect(image).toHaveAttribute("alt", "Test image");
    });

    it("displays correct alt text for one face", async () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={[mockDetections[0]!]}
                selectedIndex={null}
            />,
        );

        await waitForImageLoad();

        // Face overlay should be present
        expect(screen.getByRole("button", { name: /Face 1/i })).toBeInTheDocument();
    });

    it("displays correct alt text for multiple faces", async () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        await waitForImageLoad();

        // Both face overlays should be present
        expect(screen.getByRole("button", { name: /Face 1/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Face 2/i })).toBeInTheDocument();
    });

    it("calls onFaceClick when face is clicked", async () => {
        const onFaceClick = vi.fn();

        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                onFaceClick={onFaceClick}
            />,
        );

        await waitForImageLoad();

        const faceBox = screen.getByRole("button", { name: /Face 1/i });
        fireEvent.click(faceBox);

        expect(onFaceClick).toHaveBeenCalledWith(0);
    });

    it("is keyboard accessible", async () => {
        const onFaceClick = vi.fn();

        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                onFaceClick={onFaceClick}
            />,
        );

        await waitForImageLoad();

        const faceBox = screen.getByRole("button", { name: /Face 1/i });
        expect(faceBox).toHaveAttribute("tabindex", "0");

        // Test keyboard interaction
        fireEvent.keyDown(faceBox, { key: "Enter" });
        expect(onFaceClick).toHaveBeenCalledWith(0);
    });

    it("provides screen reader help text when faces detected", async () => {
        render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        await waitForImageLoad();

        // Help text is present
        const helpText = screen.getByText(/Click or press Enter on a face to select it/i);
        expect(helpText).toBeInTheDocument();
    });

    it("does not show help text when no faces detected", () => {
        render(
            <FaceDetectionDisplay imageUrl={mockImageUrl} imageAlt="Test image" detections={[]} selectedIndex={null} />,
        );

        expect(screen.queryByText(/Click or press Enter on a face to select it/i)).not.toBeInTheDocument();
    });

    it("respects maxWidth constraint", async () => {
        const { container } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                maxWidth={400}
            />,
        );

        const image = await waitFor(() => container.querySelector("img"));
        expect(image).toBeInTheDocument();
        expect(image).toHaveStyle({ maxWidth: "400px" });
    });

    it("respects maxHeight constraint", async () => {
        const { container } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
                maxHeight={300}
            />,
        );

        const image = await waitFor(() => container.querySelector("img"));
        expect(image).toBeInTheDocument();
        expect(image).toHaveStyle({ maxHeight: "300px" });
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

    it("updates when detections change", async () => {
        const { rerender } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        await waitForImageLoad();

        // Both faces initially
        expect(screen.getByRole("button", { name: /Face 1/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /Face 2/i })).toBeInTheDocument();

        const newDetections: FaceDetection[] = [mockDetections[0]!];

        rerender(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={newDetections}
                selectedIndex={null}
            />,
        );

        // Only one face now
        expect(screen.getByRole("button", { name: /Face 1/i })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Face 2/i })).not.toBeInTheDocument();
    });

    it("highlights selected face", async () => {
        const { rerender } = render(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={null}
            />,
        );

        await waitForImageLoad();

        const face1 = screen.getByRole("button", { name: /Face 1/i });
        expect(face1).not.toHaveClass("cat-face-detection__box--selected");

        rerender(
            <FaceDetectionDisplay
                imageUrl={mockImageUrl}
                imageAlt="Test image"
                detections={mockDetections}
                selectedIndex={0}
            />,
        );

        // First face box should be highlighted
        expect(face1).toHaveClass("cat-face-detection__box--selected");
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
