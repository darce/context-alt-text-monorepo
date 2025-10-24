/**
 * ClusterStack Component Tests
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ClusterStack } from "./ClusterStack";

describe("ClusterStack", () => {
    const defaultProps = {
        clusterId: "cluster-123",
        count: 5,
        thumbnailUrl: "https://example.com/face.jpg",
        isSelected: false,
        onClick: vi.fn(),
        onReview: vi.fn(),
    };

    describe("Basic Rendering", () => {
        it("renders cluster with thumbnail image", () => {
            render(<ClusterStack {...defaultProps} />);

            // Find the image by its class or by querying img tags
            const image = document.querySelector(".cat-cluster-stack__image") as HTMLImageElement;
            expect(image).toBeInTheDocument();
            expect(image).toHaveAttribute("src", "https://example.com/face.jpg");
            expect(image).toHaveAttribute("alt", "");
        });

        it("displays count badge on thumbnail", () => {
            render(<ClusterStack {...defaultProps} count={12} />);

            // Badge should show count
            expect(screen.getByText("12")).toBeInTheDocument();
        });

        it("renders 'Likely same person' title", () => {
            render(<ClusterStack {...defaultProps} />);

            expect(screen.getByText(/Likely same person/i)).toBeInTheDocument();
        });

        it("displays face count with proper pluralization", () => {
            const { rerender } = render(<ClusterStack {...defaultProps} count={1} />);
            expect(screen.getByText("1 face")).toBeInTheDocument();

            rerender(<ClusterStack {...defaultProps} count={5} />);
            expect(screen.getByText("5 faces")).toBeInTheDocument();
        });

        it("renders Review button", () => {
            render(<ClusterStack {...defaultProps} />);

            const reviewButton = screen.getByRole("button", { name: /Review 5 faces/i });
            expect(reviewButton).toBeInTheDocument();
        });
    });

    describe("Selected State", () => {
        it("applies selected class when isSelected is true", () => {
            const { container } = render(<ClusterStack {...defaultProps} isSelected={true} />);

            const stack = container.querySelector(".cat-cluster-stack");
            expect(stack).toHaveClass("cat-cluster-stack--selected");
        });

        it("does not apply selected class when isSelected is false", () => {
            const { container } = render(<ClusterStack {...defaultProps} isSelected={false} />);

            const stack = container.querySelector(".cat-cluster-stack");
            expect(stack).not.toHaveClass("cat-cluster-stack--selected");
        });
    });

    describe("User Interactions", () => {
        it("calls onClick when clicking the stack", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();

            render(<ClusterStack {...defaultProps} onClick={onClick} />);

            const stack = screen.getByRole("button", { name: /Likely same person, 5 faces/i });
            await user.click(stack);

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onClick when pressing Enter on the stack", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();

            render(<ClusterStack {...defaultProps} onClick={onClick} />);

            const stack = screen.getByRole("button", { name: /Likely same person, 5 faces/i });
            stack.focus();
            await user.keyboard("{Enter}");

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onClick when pressing Space on the stack", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();

            render(<ClusterStack {...defaultProps} onClick={onClick} />);

            const stack = screen.getByRole("button", { name: /Likely same person, 5 faces/i });
            stack.focus();
            await user.keyboard(" ");

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onReview when clicking Review button", async () => {
            const user = userEvent.setup();
            const onReview = vi.fn();
            const onClick = vi.fn();

            render(<ClusterStack {...defaultProps} onClick={onClick} onReview={onReview} />);

            const reviewButton = screen.getByRole("button", { name: /Review 5 faces/i });
            await user.click(reviewButton);

            expect(onReview).toHaveBeenCalledTimes(1);
            // Should not call onClick when clicking Review button
            expect(onClick).not.toHaveBeenCalled();
        });

        it("calls onReview when pressing Enter on Review button", async () => {
            const user = userEvent.setup();
            const onReview = vi.fn();
            const onClick = vi.fn();

            render(<ClusterStack {...defaultProps} onClick={onClick} onReview={onReview} />);

            const reviewButton = screen.getByRole("button", { name: /Review 5 faces/i });
            reviewButton.focus();
            await user.keyboard("{Enter}");

            expect(onReview).toHaveBeenCalledTimes(1);
            expect(onClick).not.toHaveBeenCalled();
        });

        it("calls onReview when pressing Space on Review button", async () => {
            const user = userEvent.setup();
            const onReview = vi.fn();
            const onClick = vi.fn();

            render(<ClusterStack {...defaultProps} onClick={onClick} onReview={onReview} />);

            const reviewButton = screen.getByRole("button", { name: /Review 5 faces/i });
            reviewButton.focus();
            await user.keyboard(" ");

            expect(onReview).toHaveBeenCalledTimes(1);
            expect(onClick).not.toHaveBeenCalled();
        });
    });

    describe("Accessibility", () => {
        it("has proper ARIA label for the stack", () => {
            render(<ClusterStack {...defaultProps} count={3} />);

            const stack = screen.getByRole("button", { name: /Likely same person, 3 faces/i });
            expect(stack).toBeInTheDocument();
        });

        it("has proper ARIA label for Review button", () => {
            render(<ClusterStack {...defaultProps} count={7} />);

            const reviewButton = screen.getByRole("button", { name: /Review 7 faces/i });
            expect(reviewButton).toBeInTheDocument();
        });

        it("is keyboard accessible (focusable)", () => {
            render(<ClusterStack {...defaultProps} />);

            const stack = screen.getByRole("button", { name: /Likely same person, 5 faces/i });
            expect(stack).toHaveAttribute("tabIndex", "0");
        });

        it("has aria-hidden on decorative image", () => {
            render(<ClusterStack {...defaultProps} />);

            const image = document.querySelector(".cat-cluster-stack__image") as HTMLImageElement;
            expect(image).toHaveAttribute("aria-hidden", "true");
        });
    });

    describe("Edge Cases", () => {
        it("handles count of 1 correctly", () => {
            render(<ClusterStack {...defaultProps} count={1} />);

            expect(screen.getByText("1 face")).toBeInTheDocument();
            expect(screen.getByRole("button", { name: /Review 1 face/i })).toBeInTheDocument();
        });

        it("handles large counts", () => {
            render(<ClusterStack {...defaultProps} count={999} />);

            expect(screen.getByText("999")).toBeInTheDocument(); // Badge
            expect(screen.getByText("999 faces")).toBeInTheDocument(); // Count text
        });

        it("renders with empty thumbnail URL gracefully", () => {
            render(<ClusterStack {...defaultProps} thumbnailUrl="" />);

            const image = document.querySelector(".cat-cluster-stack__thumbnail");
            expect(image).toBeInTheDocument();
            // When thumbnailUrl is empty, the src attribute should not be set
            expect(image).not.toHaveAttribute("src");
        });
    });
});
