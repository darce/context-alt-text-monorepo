import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RosterPagination } from "./RosterPagination";

describe("RosterPagination", () => {
    describe("Empty State", () => {
        it("should render empty container when only one page", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={1}
                    total={5}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            // Should show total count even on single page
            expect(screen.getByText("5 entries")).toBeInTheDocument();
            // Should not show pagination controls
            expect(screen.queryByText("Previous")).not.toBeInTheDocument();
            expect(screen.queryByText("Next")).not.toBeInTheDocument();
        });

        it("should render empty container when total is less than perPage", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={0}
                    total={8}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            // Should show total count
            expect(screen.getByText("8 entries")).toBeInTheDocument();
            // Should not show pagination controls
            expect(screen.queryByText("Previous")).not.toBeInTheDocument();
            expect(screen.queryByText("Next")).not.toBeInTheDocument();
        });
    });

    describe("Navigation Controls", () => {
        it("should render Previous and Next buttons", () => {
            render(
                <RosterPagination
                    page={2}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("Previous")).toBeInTheDocument();
            expect(screen.getByText("Next")).toBeInTheDocument();
        });

        it("should display current page info", () => {
            render(
                <RosterPagination
                    page={3}
                    totalPages={7}
                    total={70}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("Page 3 of 7")).toBeInTheDocument();
        });

        it("should call onPageChange with page - 1 when Previous clicked", async () => {
            const user = userEvent.setup();
            const onPageChange = vi.fn();
            render(
                <RosterPagination
                    page={3}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={onPageChange}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );

            await user.click(screen.getByText("Previous"));
            expect(onPageChange).toHaveBeenCalledWith(2);
        });

        it("should call onPageChange with page + 1 when Next clicked", async () => {
            const user = userEvent.setup();
            const onPageChange = vi.fn();
            render(
                <RosterPagination
                    page={2}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={onPageChange}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );

            await user.click(screen.getByText("Next"));
            expect(onPageChange).toHaveBeenCalledWith(3);
        });

        it("should disable Previous button on first page", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            const prevButton = screen.getByText("Previous");
            expect(prevButton).toBeDisabled();
        });

        it("should disable Next button on last page", () => {
            render(
                <RosterPagination
                    page={5}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            const nextButton = screen.getByText("Next");
            expect(nextButton).toBeDisabled();
        });

        it("should enable both buttons on middle page", () => {
            render(
                <RosterPagination
                    page={3}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("Previous")).not.toBeDisabled();
            expect(screen.getByText("Next")).not.toBeDisabled();
        });

        it("should handle totalPages being 0", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={0}
                    total={100}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
            expect(screen.getByText("Next")).not.toBeDisabled();
        });
    });

    describe("Per Page Selector", () => {
        it("should render per page select with label", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByLabelText("Rows per page")).toBeInTheDocument();
        });

        it("should have options for 10, 20, and 50", async () => {
            const user = userEvent.setup();
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            // Click trigger to open dropdown
            const trigger = screen.getByRole("combobox", { name: "Rows per page" });
            await user.click(trigger);

            // Find options within Portal content
            const option10 = await screen.findByRole("option", { name: "10" });
            const option20 = await screen.findByRole("option", { name: "20" });
            const option50 = await screen.findByRole("option", { name: "50" });
            expect(option10).toBeInTheDocument();
            expect(option20).toBeInTheDocument();
            expect(option50).toBeInTheDocument();
        });

        it("should display current perPage value", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={3}
                    total={47}
                    perPage={20}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            // Verify trigger shows current value
            const trigger = screen.getByRole("combobox", { name: "Rows per page" });
            expect(trigger).toHaveTextContent("20");
        });

        it("should call onPerPageChange when selection changes", async () => {
            const user = userEvent.setup();
            const onPerPageChange = vi.fn();
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={onPerPageChange}
                    disabled={false}
                />,
            );

            // Open dropdown and select option
            const trigger = screen.getByRole("combobox", { name: "Rows per page" });
            await user.click(trigger);
            const option50 = await screen.findByRole("option", { name: "50" });
            await user.click(option50);
            expect(onPerPageChange).toHaveBeenCalledWith(50);
        });
    });

    describe("Total Count Display", () => {
        it("should display singular 'entry' for count of 1", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={1}
                    total={1}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("1 entry")).toBeInTheDocument();
        });

        it("should display plural 'entries' for count > 1", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("47 entries")).toBeInTheDocument();
        });

        it("should display plural 'entries' for count of 0", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={0}
                    total={0}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            expect(screen.getByText("0 entries")).toBeInTheDocument();
        });
    });

    describe("Disabled State", () => {
        it("should disable all buttons when disabled prop is true", () => {
            render(
                <RosterPagination
                    page={2}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={true}
                />,
            );
            expect(screen.getByText("Previous")).toBeDisabled();
            expect(screen.getByText("Next")).toBeDisabled();
        });

        it("should disable select when disabled prop is true", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={true}
                />,
            );
            const select = screen.getByLabelText("Rows per page");
            expect(select).toBeDisabled();
        });
    });

    describe("Accessibility", () => {
        it("should have aria-live attribute", () => {
            const { container } = render(
                <RosterPagination
                    page={2}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            const pagination = container.querySelector(".cat-roster__pagination");
            expect(pagination).toHaveAttribute("aria-live", "polite");
        });

        it("should associate label with select", () => {
            render(
                <RosterPagination
                    page={1}
                    totalPages={5}
                    total={47}
                    perPage={10}
                    onPageChange={vi.fn()}
                    onPerPageChange={vi.fn()}
                    disabled={false}
                />,
            );
            const label = screen.getByText("Rows per page");
            const select = screen.getByLabelText("Rows per page");
            expect(label).toHaveAttribute("for", "cat-roster-per-page");
            expect(select).toHaveAttribute("id", "cat-roster-per-page");
        });
    });
});
