/**
 * SuggestionStack Component Tests
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { SuggestionStack, type SuggestionStackProps } from "./SuggestionStack";

describe("SuggestionStack", () => {
    const defaultProps: SuggestionStackProps = {
        rosterId: "person-123",
        displayName: "Ana Rodriguez",
        count: 5,
        confidence: 0.95,
        isSelected: false,
        onClick: vi.fn(),
        onConfirmAll: vi.fn(),
    };

    describe("Basic Rendering", () => {
        it("renders suggestion with person name", () => {
            render(<SuggestionStack {...defaultProps} />);

            expect(screen.getByText("Ana Rodriguez?")).toBeInTheDocument();
        });

        it("displays confidence percentage", () => {
            render(<SuggestionStack {...defaultProps} confidence={0.87} />);

            expect(screen.getByText("87% confidence")).toBeInTheDocument();
        });

        it("displays face count with proper pluralization for multiple faces", () => {
            render(<SuggestionStack {...defaultProps} count={5} />);

            expect(screen.getByText("5 faces")).toBeInTheDocument();
        });

        it("displays face count with proper pluralization for single face", () => {
            render(<SuggestionStack {...defaultProps} count={1} />);

            expect(screen.getByText("1 face")).toBeInTheDocument();
        });

        it("renders Confirm All button", () => {
            render(<SuggestionStack {...defaultProps} />);

            const button = screen.getByRole("button", { name: /Confirm all as Ana Rodriguez/i });
            expect(button).toBeInTheDocument();
            expect(button).toHaveTextContent("Confirm All");
        });

        it("renders person avatar placeholder with first initial", () => {
            render(<SuggestionStack {...defaultProps} />);

            const placeholder = document.querySelector(".cat-suggestion-stack__placeholder");
            expect(placeholder).toBeInTheDocument();
            expect(placeholder).toHaveTextContent("A");
        });

        it("renders avatar image when avatarUrl provided", () => {
            render(<SuggestionStack {...defaultProps} avatarUrl="https://example.com/avatar.jpg" />);

            const image = document.querySelector(".cat-suggestion-stack__image");
            expect(image).toBeInTheDocument();
            expect(image).toHaveAttribute("src", "https://example.com/avatar.jpg");
            expect(image).toHaveAttribute("alt", "");
            expect(image).toHaveAttribute("aria-hidden", "true");
        });

        it("displays count badge on avatar", () => {
            render(<SuggestionStack {...defaultProps} count={12} />);

            const badge = document.querySelector(".cat-suggestion-stack__badge");
            expect(badge).toBeInTheDocument();
            expect(badge).toHaveTextContent("12");
        });
    });

    describe("Selected State", () => {
        it("applies selected class when isSelected is true", () => {
            render(<SuggestionStack {...defaultProps} isSelected={true} />);

            const stack = document.querySelector(".cat-suggestion-stack");
            expect(stack).toHaveClass("cat-suggestion-stack--selected");
        });

        it("does not apply selected class when isSelected is false", () => {
            render(<SuggestionStack {...defaultProps} isSelected={false} />);

            const stack = document.querySelector(".cat-suggestion-stack");
            expect(stack).not.toHaveClass("cat-suggestion-stack--selected");
        });
    });

    describe("User Interactions", () => {
        it("calls onClick when clicking the stack", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();

            render(<SuggestionStack {...defaultProps} onClick={onClick} />);

            const stack = screen.getByRole("button", { name: /Ana Rodriguez.*confidence.*faces/i });
            await user.click(stack);

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onClick when pressing Enter on the stack", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();

            render(<SuggestionStack {...defaultProps} onClick={onClick} />);

            const stack = screen.getByRole("button", { name: /Ana Rodriguez.*confidence.*faces/i });
            stack.focus();
            await user.keyboard("{Enter}");

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onClick when pressing Space on the stack", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();

            render(<SuggestionStack {...defaultProps} onClick={onClick} />);

            const stack = screen.getByRole("button", { name: /Ana Rodriguez.*confidence.*faces/i });
            stack.focus();
            await user.keyboard(" ");

            expect(onClick).toHaveBeenCalledTimes(1);
        });

        it("calls onConfirmAll when clicking Confirm All button", async () => {
            const user = userEvent.setup();
            const onConfirmAll = vi.fn();

            render(<SuggestionStack {...defaultProps} onConfirmAll={onConfirmAll} />);

            const button = screen.getByRole("button", { name: /Confirm all as Ana Rodriguez/i });
            await user.click(button);

            expect(onConfirmAll).toHaveBeenCalledTimes(1);
        });

        it("calls onConfirmAll when pressing Enter on Confirm All button", async () => {
            const user = userEvent.setup();
            const onConfirmAll = vi.fn();

            render(<SuggestionStack {...defaultProps} onConfirmAll={onConfirmAll} />);

            const button = screen.getByRole("button", { name: /Confirm all as Ana Rodriguez/i });
            button.focus();
            await user.keyboard("{Enter}");

            expect(onConfirmAll).toHaveBeenCalledTimes(1);
        });

        it("calls onConfirmAll when pressing Space on Confirm All button", async () => {
            const user = userEvent.setup();
            const onConfirmAll = vi.fn();

            render(<SuggestionStack {...defaultProps} onConfirmAll={onConfirmAll} />);

            const button = screen.getByRole("button", { name: /Confirm all as Ana Rodriguez/i });
            button.focus();
            await user.keyboard(" ");

            expect(onConfirmAll).toHaveBeenCalledTimes(1);
        });

        it("does not call onClick when clicking Confirm All button", async () => {
            const user = userEvent.setup();
            const onClick = vi.fn();
            const onConfirmAll = vi.fn();

            render(<SuggestionStack {...defaultProps} onClick={onClick} onConfirmAll={onConfirmAll} />);

            const button = screen.getByRole("button", { name: /Confirm all as Ana Rodriguez/i });
            await user.click(button);

            expect(onConfirmAll).toHaveBeenCalledTimes(1);
            expect(onClick).not.toHaveBeenCalled();
        });
    });

    describe("Accessibility", () => {
        it("has proper ARIA label for the stack", () => {
            render(<SuggestionStack {...defaultProps} confidence={0.87} count={3} />);

            const stack = screen.getByRole("button", { name: "Ana Rodriguez, 87% confidence, 3 faces" });
            expect(stack).toBeInTheDocument();
        });

        it("has proper ARIA label for Confirm All button", () => {
            render(<SuggestionStack {...defaultProps} />);

            const button = screen.getByRole("button", { name: "Confirm all as Ana Rodriguez" });
            expect(button).toBeInTheDocument();
        });

        it("has aria-hidden on decorative avatar image", () => {
            render(<SuggestionStack {...defaultProps} avatarUrl="https://example.com/avatar.jpg" />);

            const image = document.querySelector(".cat-suggestion-stack__image");
            expect(image).toHaveAttribute("aria-hidden", "true");
        });

        it("has aria-hidden on avatar placeholder", () => {
            render(<SuggestionStack {...defaultProps} />);

            const placeholder = document.querySelector(".cat-suggestion-stack__placeholder");
            expect(placeholder).toHaveAttribute("aria-hidden", "true");
        });

        it("has aria-hidden on count badge", () => {
            render(<SuggestionStack {...defaultProps} />);

            const badge = document.querySelector(".cat-suggestion-stack__badge");
            expect(badge).toHaveAttribute("aria-hidden", "true");
        });

        it("has aria-hidden on separator", () => {
            render(<SuggestionStack {...defaultProps} />);

            const separator = document.querySelector(".cat-suggestion-stack__separator");
            expect(separator).toHaveAttribute("aria-hidden", "true");
            expect(separator).toHaveTextContent("•");
        });
    });

    describe("Confidence Formatting", () => {
        it("rounds confidence to nearest percentage", () => {
            render(<SuggestionStack {...defaultProps} confidence={0.8765} />);

            expect(screen.getByText("88% confidence")).toBeInTheDocument();
        });

        it("handles 100% confidence", () => {
            render(<SuggestionStack {...defaultProps} confidence={1.0} />);

            expect(screen.getByText("100% confidence")).toBeInTheDocument();
        });

        it("handles low confidence", () => {
            render(<SuggestionStack {...defaultProps} confidence={0.12} />);

            expect(screen.getByText("12% confidence")).toBeInTheDocument();
        });

        it("rounds 0.5 up", () => {
            render(<SuggestionStack {...defaultProps} confidence={0.875} />);

            expect(screen.getByText("88% confidence")).toBeInTheDocument();
        });
    });

    describe("Edge Cases", () => {
        it("handles very long display names gracefully", () => {
            const longName = "Dr. Ana María Rodríguez-Gutiérrez de la Vega y Fernández";
            render(<SuggestionStack {...defaultProps} displayName={longName} />);

            expect(screen.getByText(`${longName}?`)).toBeInTheDocument();
        });

        it("handles single character names", () => {
            render(<SuggestionStack {...defaultProps} displayName="X" />);

            expect(screen.getByText("X?")).toBeInTheDocument();
            const placeholder = document.querySelector(".cat-suggestion-stack__placeholder");
            expect(placeholder).toHaveTextContent("X");
        });

        it("handles names with special characters", () => {
            render(<SuggestionStack {...defaultProps} displayName="Zoë O'Brien-Smith" />);

            expect(screen.getByText("Zoë O'Brien-Smith?")).toBeInTheDocument();
            const placeholder = document.querySelector(".cat-suggestion-stack__placeholder");
            expect(placeholder).toHaveTextContent("Z");
        });

        it("renders with empty avatar URL gracefully", () => {
            render(<SuggestionStack {...defaultProps} avatarUrl="" />);

            const image = document.querySelector(".cat-suggestion-stack__image");
            expect(image).not.toBeInTheDocument();

            const placeholder = document.querySelector(".cat-suggestion-stack__placeholder");
            expect(placeholder).toBeInTheDocument();
        });

        it("handles large face counts", () => {
            render(<SuggestionStack {...defaultProps} count={999} />);

            expect(screen.getByText("999 faces")).toBeInTheDocument();
            const badge = document.querySelector(".cat-suggestion-stack__badge");
            expect(badge).toHaveTextContent("999");
        });
    });
});
