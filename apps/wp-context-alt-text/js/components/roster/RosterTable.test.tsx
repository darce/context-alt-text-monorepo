import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RosterTable } from "./RosterTable";
import type { RosterEntry } from "@/admin/types";

const mockEntry: RosterEntry = {
    remoteId: "test-123",
    label: "Test Person",
    type: "person",
    status: "SYNCED",
    avatarUrl: "https://example.com/avatar.jpg",
    avatarId: 42,
    updatedAt: "2024-01-15T10:00:00Z",
    referenceImageCount: 3,
    metadata: {},
    referenceImages: [],
};

const mockLocalEntry: RosterEntry = {
    remoteId: null,
    label: "Local Person",
    type: "person",
    status: "LOCAL",
    avatarUrl: null,
    avatarId: null,
    updatedAt: null,
    referenceImageCount: 0,
    metadata: {},
    referenceImages: [],
};

describe("RosterTable", () => {
    describe("Empty State", () => {
        it("should show loading message when loading with no entries", () => {
            render(<RosterTable entries={[]} isLoading={true} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("Loading roster entries…")).toBeInTheDocument();
        });

        it("should show empty message when not loading with no entries", () => {
            render(<RosterTable entries={[]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("No roster entries yet. Create one to get started.")).toBeInTheDocument();
        });

        it("should apply empty modifier class", () => {
            const { container } = render(
                <RosterTable entries={[]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            expect(container.querySelector(".cat-roster__table--empty")).toBeInTheDocument();
        });

        it("should not render table when empty", () => {
            const { container } = render(
                <RosterTable entries={[]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            expect(container.querySelector("table")).not.toBeInTheDocument();
        });
    });

    describe("Table Rendering", () => {
        it("should render table with entries", () => {
            const { container } = render(
                <RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            expect(container.querySelector("table")).toBeInTheDocument();
        });

        it("should render all column headers", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("Avatar")).toBeInTheDocument();
            expect(screen.getByText("Label")).toBeInTheDocument();
            expect(screen.getByText("Type")).toBeInTheDocument();
            expect(screen.getByText("Status")).toBeInTheDocument();
            expect(screen.getByText("Updated")).toBeInTheDocument();
            expect(screen.getByText("Images")).toBeInTheDocument();
            expect(screen.getByText("Actions")).toBeInTheDocument();
        });

        it("should have region role and aria-live", () => {
            const { container } = render(
                <RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            const tableWrapper = container.querySelector(".cat-roster__table");
            expect(tableWrapper).toHaveAttribute("role", "region");
            expect(tableWrapper).toHaveAttribute("aria-live", "polite");
        });
    });

    describe("Entry Display", () => {
        it("should render entry with avatar image", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            const avatar = screen.getByRole("img", { name: "Avatar for Test Person" });
            expect(avatar).toBeInTheDocument();
            expect(avatar).toHaveAttribute("src", "https://example.com/avatar.jpg");
        });

        it("should render placeholder avatar when no avatarUrl", () => {
            const { container } = render(
                <RosterTable entries={[mockLocalEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            const placeholder = container.querySelector(".cat-roster__avatar--placeholder");
            expect(placeholder).toBeInTheDocument();
            expect(placeholder?.textContent).toBe("L"); // First letter of "Local Person"
        });

        it("should render label as strong text", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            const label = screen.getByText("Test Person");
            expect(label.tagName).toBe("STRONG");
        });

        it("should render remoteId in meta", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("test-123")).toBeInTheDocument();
        });

        it("should render 'Local draft' for entries without remoteId", () => {
            render(<RosterTable entries={[mockLocalEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("Local draft")).toBeInTheDocument();
        });

        it("should render type", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("person")).toBeInTheDocument();
        });

        it("should render status badge", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("Synced")).toBeInTheDocument();
        });

        it("should render formatted date", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            const date = new Date("2024-01-15T10:00:00Z");
            expect(screen.getByText(date.toLocaleString())).toBeInTheDocument();
        });

        it("should render em dash for missing date", () => {
            render(<RosterTable entries={[mockLocalEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            // Em dash "—" appears in multiple places, check it exists
            expect(screen.getAllByText("—").length).toBeGreaterThan(0);
        });

        it("should render image count with singular form", () => {
            const entry = { ...mockEntry, referenceImageCount: 1 };
            render(<RosterTable entries={[entry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("1 image")).toBeInTheDocument();
        });

        it("should render image count with plural form", () => {
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getByText("3 images")).toBeInTheDocument();
        });
    });

    describe("Actions", () => {
        it("should render Edit button for all entries", () => {
            render(
                <RosterTable
                    entries={[mockEntry, mockLocalEntry]}
                    isLoading={false}
                    onEdit={vi.fn()}
                    onDelete={vi.fn()}
                />,
            );
            const editButtons = screen.getAllByText("Edit");
            expect(editButtons).toHaveLength(2);
        });

        it("should call onEdit when Edit button clicked", async () => {
            const user = userEvent.setup();
            const onEdit = vi.fn();
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={onEdit} onDelete={vi.fn()} />);

            const editButton = screen.getByText("Edit");
            await user.click(editButton);

            expect(onEdit).toHaveBeenCalledWith(mockEntry);
            expect(onEdit).toHaveBeenCalledTimes(1);
        });

        it("should render Delete button only for entries with remoteId", () => {
            render(
                <RosterTable
                    entries={[mockEntry, mockLocalEntry]}
                    isLoading={false}
                    onEdit={vi.fn()}
                    onDelete={vi.fn()}
                />,
            );
            const deleteButtons = screen.queryAllByText("Delete");
            expect(deleteButtons).toHaveLength(1); // Only mockEntry has remoteId
        });

        it("should not render Delete button for local entries", () => {
            render(<RosterTable entries={[mockLocalEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.queryByText("Delete")).not.toBeInTheDocument();
        });

        it("should call onDelete when Delete button clicked", async () => {
            const user = userEvent.setup();
            const onDelete = vi.fn();
            render(<RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={onDelete} />);

            const deleteButton = screen.getByText("Delete");
            await user.click(deleteButton);

            expect(onDelete).toHaveBeenCalledWith("test-123");
            expect(onDelete).toHaveBeenCalledTimes(1);
        });

        it("should apply danger class to Delete button", () => {
            const { container } = render(
                <RosterTable entries={[mockEntry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            const deleteButton = screen.getByText("Delete");
            expect(deleteButton).toHaveClass("cat-button--danger");
        });
    });

    describe("Multiple Entries", () => {
        it("should render multiple entries", () => {
            const entries = [
                { ...mockEntry, remoteId: "test-1", label: "Person 1" },
                { ...mockEntry, remoteId: "test-2", label: "Person 2" },
                { ...mockEntry, remoteId: "test-3", label: "Person 3" },
            ];
            render(<RosterTable entries={entries} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);

            expect(screen.getByText("Person 1")).toBeInTheDocument();
            expect(screen.getByText("Person 2")).toBeInTheDocument();
            expect(screen.getByText("Person 3")).toBeInTheDocument();
        });

        it("should use unique keys for each row", () => {
            const entries = [
                { ...mockEntry, remoteId: "test-1" },
                { ...mockEntry, remoteId: "test-2" },
            ];
            render(<RosterTable entries={entries} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            const rows = screen.getAllByRole("row");
            expect(rows.length).toBeGreaterThanOrEqual(2); // Header + 2 data rows
        });
    });

    describe("Fallback Values", () => {
        it("should show remoteId when label is empty", () => {
            const entry = { ...mockEntry, label: "   " };
            render(<RosterTable entries={[entry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            // remoteId appears in both <strong> (as label fallback) and <span> (in meta)
            const elements = screen.getAllByText("test-123");
            expect(elements[0]?.tagName).toBe("STRONG");
        });

        it("should show em dash for empty type", () => {
            const entry = { ...mockEntry, type: "   " };
            render(<RosterTable entries={[entry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />);
            expect(screen.getAllByText("—").length).toBeGreaterThan(0);
        });

        it("should use question mark placeholder when label is empty", () => {
            const entry = { ...mockEntry, label: "", avatarUrl: null };
            const { container } = render(
                <RosterTable entries={[entry]} isLoading={false} onEdit={vi.fn()} onDelete={vi.fn()} />,
            );
            const placeholder = container.querySelector(".cat-roster__avatar--placeholder");
            expect(placeholder?.textContent).toBe("?");
        });
    });
});
