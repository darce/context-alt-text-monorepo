import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
    describe("Status Display", () => {
        it('should render "Synced" for SYNCED status', () => {
            render(<StatusBadge status="SYNCED" />);
            expect(screen.getByText("Synced")).toBeInTheDocument();
        });

        it('should render "Local" for LOCAL status', () => {
            render(<StatusBadge status="LOCAL" />);
            expect(screen.getByText("Local")).toBeInTheDocument();
        });

        it('should render "Conflict" for CONFLICT status', () => {
            render(<StatusBadge status="CONFLICT" />);
            expect(screen.getByText("Conflict")).toBeInTheDocument();
        });
    });

    describe("CSS Classes", () => {
        it("should apply base class to all badges", () => {
            const { container } = render(<StatusBadge status="SYNCED" />);
            const badge = container.querySelector(".cat-roster__badge");
            expect(badge).toBeInTheDocument();
        });

        it("should apply synced modifier class for SYNCED status", () => {
            const { container } = render(<StatusBadge status="SYNCED" />);
            const badge = container.querySelector(".cat-roster__badge--synced");
            expect(badge).toBeInTheDocument();
        });

        it("should apply local modifier class for LOCAL status", () => {
            const { container } = render(<StatusBadge status="LOCAL" />);
            const badge = container.querySelector(".cat-roster__badge--local");
            expect(badge).toBeInTheDocument();
        });

        it("should apply conflict modifier class for CONFLICT status", () => {
            const { container } = render(<StatusBadge status="CONFLICT" />);
            const badge = container.querySelector(".cat-roster__badge--conflict");
            expect(badge).toBeInTheDocument();
        });
    });

    describe("HTML Structure", () => {
        it("should render as a span element", () => {
            const { container } = render(<StatusBadge status="SYNCED" />);
            const badge = container.querySelector("span");
            expect(badge).toBeInTheDocument();
        });

        it("should contain only text content", () => {
            const { container } = render(<StatusBadge status="LOCAL" />);
            const badge = container.querySelector(".cat-roster__badge");
            expect(badge?.textContent).toBe("Local");
            expect(badge?.children.length).toBe(0);
        });
    });
});
