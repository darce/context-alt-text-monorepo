import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RosterToolbar } from "./RosterToolbar";
import type { RosterStats } from "@/admin/types";

describe("RosterToolbar", () => {
    const defaultStats: RosterStats = {
        total: 10,
        synced: 7,
        local: 2,
        conflicts: 1,
        lastSyncAt: null,
        lastSyncHuman: null,
        metrics: {
            created: 0,
            updated: 0,
            deleted: 0,
            errors: 0,
            conflicts: 1,
        },
    };

    const defaultProps = {
        searchInput: "",
        onSearchChange: vi.fn(),
        statusFilter: null,
        onClearStatusFilter: vi.fn(),
        isLoading: false,
        isSubmitting: false,
        isSyncing: false,
        hasEndpoint: true,
        onCreateNew: vi.fn(),
        onSync: vi.fn(),
        stats: defaultStats,
    };

    it("renders header with title and description", () => {
        render(<RosterToolbar {...defaultProps} />);

        expect(screen.getByRole("heading", { name: /roster manager/i })).toBeInTheDocument();
        expect(
            screen.getByText(/manage labeled faces and entities synchronized with the recognition service/i),
        ).toBeInTheDocument();
    });

    it("renders action buttons", () => {
        render(<RosterToolbar {...defaultProps} />);

        expect(screen.getByRole("button", { name: /add entry/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /sync from remote/i })).toBeInTheDocument();
    });

    it("disables Add Entry button when isSubmitting is true", () => {
        render(<RosterToolbar {...defaultProps} isSubmitting={true} />);

        expect(screen.getByRole("button", { name: /add entry/i })).toBeDisabled();
    });

    it("disables Sync button when hasEndpoint is false", () => {
        render(<RosterToolbar {...defaultProps} hasEndpoint={false} />);

        expect(screen.getByRole("button", { name: /sync from remote/i })).toBeDisabled();
    });

    it("shows 'Syncing…' when isSyncing is true", () => {
        render(<RosterToolbar {...defaultProps} isSyncing={true} />);

        expect(screen.getByRole("button", { name: /syncing/i })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /syncing/i })).toBeDisabled();
    });

    it("calls onCreateNew when Add Entry button is clicked", async () => {
        const user = userEvent.setup();
        const onCreateNew = vi.fn();

        render(<RosterToolbar {...defaultProps} onCreateNew={onCreateNew} />);

        await user.click(screen.getByRole("button", { name: /add entry/i }));

        expect(onCreateNew).toHaveBeenCalledOnce();
    });

    it("calls onSync when Sync button is clicked", async () => {
        const user = userEvent.setup();
        const onSync = vi.fn();

        render(<RosterToolbar {...defaultProps} onSync={onSync} />);

        await user.click(screen.getByRole("button", { name: /sync from remote/i }));

        expect(onSync).toHaveBeenCalledOnce();
    });

    it("renders search input with correct value", () => {
        render(<RosterToolbar {...defaultProps} searchInput="John Doe" />);

        const searchInput = screen.getByRole("searchbox", { name: /search roster/i });
        expect(searchInput).toHaveValue("John Doe");
    });

    it("calls onSearchChange when search input changes", async () => {
        const user = userEvent.setup();
        const onSearchChange = vi.fn();

        render(<RosterToolbar {...defaultProps} onSearchChange={onSearchChange} />);

        const searchInput = screen.getByRole("searchbox", { name: /search roster/i });
        await user.type(searchInput, "test");

        expect(onSearchChange).toHaveBeenCalledTimes(4); // once per character
        // Each character typed triggers onChange with just that character
        expect(onSearchChange).toHaveBeenNthCalledWith(1, "t");
        expect(onSearchChange).toHaveBeenNthCalledWith(2, "e");
        expect(onSearchChange).toHaveBeenNthCalledWith(3, "s");
        expect(onSearchChange).toHaveBeenNthCalledWith(4, "t");
    });

    it("shows loading indicator when isLoading is true", () => {
        render(<RosterToolbar {...defaultProps} isLoading={true} />);

        expect(screen.getByText(/searching/i)).toBeInTheDocument();
    });

    it("does not show loading indicator when isLoading is false", () => {
        render(<RosterToolbar {...defaultProps} isLoading={false} />);

        expect(screen.queryByText(/searching/i)).not.toBeInTheDocument();
    });

    it("displays status filter badge for LOCAL status", () => {
        render(<RosterToolbar {...defaultProps} statusFilter="LOCAL" />);

        expect(screen.getByText(/filtered by status: local/i)).toBeInTheDocument();
    });

    it("displays status filter badge for SYNCED status", () => {
        render(<RosterToolbar {...defaultProps} statusFilter="SYNCED" />);

        expect(screen.getByText(/filtered by status: synced/i)).toBeInTheDocument();
    });

    it("displays status filter badge for CONFLICT status", () => {
        render(<RosterToolbar {...defaultProps} statusFilter="CONFLICT" />);

        expect(screen.getByText(/filtered by status: conflict/i)).toBeInTheDocument();
    });

    it("does not display status filter badge when statusFilter is null", () => {
        render(<RosterToolbar {...defaultProps} statusFilter={null} />);

        expect(screen.queryByText(/filtered by status/i)).not.toBeInTheDocument();
    });

    it("calls onClearStatusFilter when Clear button is clicked", async () => {
        const user = userEvent.setup();
        const onClearStatusFilter = vi.fn();

        render(<RosterToolbar {...defaultProps} statusFilter="LOCAL" onClearStatusFilter={onClearStatusFilter} />);

        await user.click(screen.getByRole("button", { name: /clear/i }));

        expect(onClearStatusFilter).toHaveBeenCalledOnce();
    });

    it("disables Clear filter button when isLoading is true", () => {
        render(<RosterToolbar {...defaultProps} statusFilter="LOCAL" isLoading={true} />);

        expect(screen.getByRole("button", { name: /clear/i })).toBeDisabled();
    });

    describe("RosterStats", () => {
        it("displays total entries count", () => {
            render(<RosterToolbar {...defaultProps} />);

            const stats = screen.getByRole("status");
            expect(stats).toBeInTheDocument();
            expect(screen.getByText(/total/i)).toBeInTheDocument();
            expect(screen.getByText("10")).toBeInTheDocument();
        });

        it("displays synced entries count", () => {
            render(<RosterToolbar {...defaultProps} />);

            const stats = screen.getByRole("status");
            expect(stats).toBeInTheDocument();
            // Use getAllByText since "Synced" appears in both stats and button
            const syncedElements = screen.getAllByText(/synced/i);
            expect(syncedElements.length).toBeGreaterThan(0);
            expect(screen.getByText("7")).toBeInTheDocument();
        });

        it("displays local entries count", () => {
            render(<RosterToolbar {...defaultProps} />);

            expect(screen.getByText(/local/i)).toBeInTheDocument();
            expect(screen.getByText("2")).toBeInTheDocument();
        });

        it("displays conflicts count when conflicts > 0", () => {
            render(<RosterToolbar {...defaultProps} />);

            expect(screen.getByText(/conflicts/i)).toBeInTheDocument();
            expect(screen.getByText("1")).toBeInTheDocument();
        });

        it("does not display conflicts when conflicts = 0", () => {
            const statsWithoutConflicts = { ...defaultStats, conflicts: 0 };
            render(<RosterToolbar {...defaultProps} stats={statsWithoutConflicts} />);

            expect(screen.queryByText(/conflicts/i)).not.toBeInTheDocument();
        });

        it("displays last sync message", () => {
            render(<RosterToolbar {...defaultProps} />);

            expect(screen.getByText(/roster has not been synced yet/i)).toBeInTheDocument();
        });

        it("displays last sync time when available", () => {
            const statsWithSync = { ...defaultStats, lastSyncHuman: "5 minutes" };
            render(<RosterToolbar {...defaultProps} stats={statsWithSync} />);

            expect(screen.getByText(/last synced 5 minutes ago/i)).toBeInTheDocument();
        });
    });
});
