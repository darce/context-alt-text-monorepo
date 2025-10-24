/**
 * FaceChip Component Tests
 *
 * Tests for the interactive face chip component that displays label status
 * and handles user interactions for face labeling.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { FaceChip } from "./FaceChip";

describe("FaceChip", () => {
    const defaultProps = {
        label: "Test Label",
        variant: "confirmed" as const,
        isSelected: false,
        onClick: vi.fn(),
        position: { top: 100, left: 150 },
    };

    describe("Basic Rendering", () => {
        it("renders with label text", () => {
            render(<FaceChip {...defaultProps} />);

            expect(screen.getByText("Test Label")).toBeInTheDocument();
        });

        it("applies correct positioning", () => {
            render(<FaceChip {...defaultProps} position={{ top: 50, left: 75 }} />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveStyle({
                top: "50px",
                left: "75px",
            });
        });

        it("renders as a button element", () => {
            render(<FaceChip {...defaultProps} />);

            expect(screen.getByRole("button")).toBeInTheDocument();
        });
    });

    describe("Variant States", () => {
        it("applies unknown variant class", () => {
            render(<FaceChip {...defaultProps} variant="unknown" label="Who is this?" />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveClass("cat-face-chip--unknown");
        });

        it("applies suggested variant class", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="Ana Rodriguez?" />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveClass("cat-face-chip--suggested");
        });

        it("applies confirmed variant class", () => {
            render(<FaceChip {...defaultProps} variant="confirmed" label="Ana Rodriguez" />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveClass("cat-face-chip--confirmed");
        });
    });

    describe("Selection State", () => {
        it("applies selected class when isSelected is true", () => {
            render(<FaceChip {...defaultProps} isSelected={true} />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveClass("cat-face-chip--selected");
        });

        it("does not apply selected class when isSelected is false", () => {
            render(<FaceChip {...defaultProps} isSelected={false} />);

            const chip = screen.getByRole("button");
            expect(chip).not.toHaveClass("cat-face-chip--selected");
        });
    });

    describe("Confidence Display", () => {
        it("shows confidence percentage for suggested variant", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="Ana Rodriguez?" confidence={0.95} />);

            expect(screen.getByText("95%")).toBeInTheDocument();
        });

        it("does not show confidence for unknown variant", () => {
            render(<FaceChip {...defaultProps} variant="unknown" label="Who is this?" confidence={0.95} />);

            expect(screen.queryByText("95%")).not.toBeInTheDocument();
        });

        it("does not show confidence for confirmed variant", () => {
            render(<FaceChip {...defaultProps} variant="confirmed" label="Ana Rodriguez" confidence={0.95} />);

            expect(screen.queryByText("95%")).not.toBeInTheDocument();
        });

        it("rounds confidence to nearest integer", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="John Smith?" confidence={0.873} />);

            expect(screen.getByText("87%")).toBeInTheDocument();
        });

        it("does not show confidence when undefined", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="Ana Rodriguez?" />);

            expect(screen.queryByText(/%/)).not.toBeInTheDocument();
        });
    });

    describe("User Interactions", () => {
        it("calls onClick when clicked", async () => {
            const onClick = vi.fn();
            const user = userEvent.setup();

            render(<FaceChip {...defaultProps} onClick={onClick} />);

            await user.click(screen.getByRole("button"));

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onClick when Enter key is pressed", async () => {
            const onClick = vi.fn();
            const user = userEvent.setup();

            render(<FaceChip {...defaultProps} onClick={onClick} />);

            const chip = screen.getByRole("button");
            chip.focus();
            await user.keyboard("{Enter}");

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onClick when Space key is pressed", async () => {
            const onClick = vi.fn();
            const user = userEvent.setup();

            render(<FaceChip {...defaultProps} onClick={onClick} />);

            const chip = screen.getByRole("button");
            chip.focus();
            await user.keyboard(" ");

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("does not call onClick for other keys", async () => {
            const onClick = vi.fn();
            const user = userEvent.setup();

            render(<FaceChip {...defaultProps} onClick={onClick} />);

            const chip = screen.getByRole("button");
            chip.focus();
            await user.keyboard("a");
            await user.keyboard("{Escape}");
            await user.keyboard("{ArrowDown}");

            expect(onClick).not.toHaveBeenCalled();
        });
    });

    describe("Accessibility", () => {
        it("has appropriate aria-label for unknown variant", () => {
            render(<FaceChip {...defaultProps} variant="unknown" label="Who is this?" />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveAccessibleName(/unlabeled face/i);
        });

        it("has appropriate aria-label for suggested variant", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="Ana Rodriguez?" confidence={0.95} />);

            const chip = screen.getByRole("button");
            const ariaLabel = chip.getAttribute("aria-label");
            expect(ariaLabel).toMatch(/suggested/i);
            expect(ariaLabel).toMatch(/Ana Rodriguez/i);
            expect(ariaLabel).toMatch(/95%/i);
        });

        it("has appropriate aria-label for confirmed variant", () => {
            render(<FaceChip {...defaultProps} variant="confirmed" label="John Smith" />);

            const chip = screen.getByRole("button");
            const ariaLabel = chip.getAttribute("aria-label");
            expect(ariaLabel).toMatch(/confirmed/i);
            expect(ariaLabel).toMatch(/John Smith/i);
        });

        it("hides confidence percentage from screen readers", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="Ana Rodriguez?" confidence={0.95} />);

            const confidenceElement = screen.getByText("95%");
            expect(confidenceElement).toHaveAttribute("aria-hidden", "true");
        });
    });

    describe("CSS Classes", () => {
        it("applies base class", () => {
            render(<FaceChip {...defaultProps} />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveClass("cat-face-chip");
        });

        it("applies multiple classes correctly", () => {
            render(<FaceChip {...defaultProps} variant="suggested" isSelected={true} />);

            const chip = screen.getByRole("button");
            expect(chip).toHaveClass("cat-face-chip");
            expect(chip).toHaveClass("cat-face-chip--suggested");
            expect(chip).toHaveClass("cat-face-chip--selected");
        });

        it("applies label class to label span", () => {
            render(<FaceChip {...defaultProps} label="Test" />);

            const label = screen.getByText("Test");
            expect(label).toHaveClass("cat-face-chip__label");
        });

        it("applies confidence class to confidence span", () => {
            render(<FaceChip {...defaultProps} variant="suggested" label="Ana?" confidence={0.85} />);

            const confidence = screen.getByText("85%");
            expect(confidence).toHaveClass("cat-face-chip__confidence");
        });
    });
});
