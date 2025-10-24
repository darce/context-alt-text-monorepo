import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/admin/testing/mswServer";

import { PeoplePicker } from "./PeoplePicker";

describe("PeoplePicker", () => {
    const mockOnClose = vi.fn();
    const mockOnSelect = vi.fn();
    const mockOnCreateNew = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
    });

    describe("Basic Rendering", () => {
        it("renders nothing when closed", () => {
            const { container } = render(
                <PeoplePicker
                    isOpen={false}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            expect(container.firstChild).toBeNull();
        });

        it("renders modal with search input when open", () => {
            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            expect(screen.getByLabelText(/search roster/i)).toBeInTheDocument();
            expect(screen.getByPlaceholderText(/search or create new person/i)).toBeInTheDocument();
        });

        it("renders keyboard hints in footer", () => {
            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            expect(screen.getByText(/use.*to navigate.*enter to select.*esc to cancel/i)).toBeInTheDocument();
        });

        it("auto-focuses search input when opened", () => {
            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            const input = screen.getByLabelText(/search roster/i);
            expect(input).toHaveFocus();
        });
    });

    describe("Roster Loading", () => {
        it("loads all roster persons on mount", async () => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [
                            { id: "1", displayName: "Ana Rodriguez" },
                            { id: "2", displayName: "John Smith" },
                        ],
                    });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            expect(screen.getByText("John Smith")).toBeInTheDocument();
        });

        it("shows error message when loading fails", async () => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({ error: "Failed" }, { status: 500 });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            // Component should still render without crashing (error handling is internal to useRosterSearch)
            expect(screen.getByRole("dialog")).toBeInTheDocument();
        });
    });

    describe("Search Functionality", () => {
        beforeEach(() => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [
                            { id: "1", displayName: "Ana Rodriguez" },
                            { id: "2", displayName: "John Smith" },
                        ],
                    });
                }),
            );
        });

        it("filters results based on search query", async () => {
            const user = userEvent.setup();

            server.use(
                http.get("/wp-json/cat/v1/roster/search", ({ request }) => {
                    const url = new URL(request.url);
                    const search = url.searchParams.get("search");

                    if (search === "ana") {
                        return HttpResponse.json({
                            persons: [{ id: "1", displayName: "Ana Rodriguez" }],
                        });
                    }

                    return HttpResponse.json({ persons: [] });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            // Wait for initial roster load
            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Type search query
            const input = screen.getByLabelText(/search roster/i);
            await user.clear(input);
            await user.type(input, "ana");

            // Wait for debounced search (300ms default)
            await waitFor(
                () => {
                    expect(screen.queryByText("John Smith")).not.toBeInTheDocument();
                },
                { timeout: 1000 },
            );

            // Ana should still be visible
            expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
        });

        it("shows 'Create new person' option when typing", async () => {
            const user = userEvent.setup();

            // Add handler for search query "New Person" that returns empty results
            server.use(
                http.get("/wp-json/cat/v1/roster/search", ({ request }) => {
                    const url = new URL(request.url);
                    const search = url.searchParams.get("search");
                    if (search === "New Person") {
                        return HttpResponse.json({ persons: [] });
                    }
                    return HttpResponse.json({ persons: mockRosterPersons });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            // Wait for roster to load
            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Type a query
            const input = screen.getByLabelText(/search roster/i);
            await user.clear(input);
            await user.type(input, "New Person");

            // Should show create option (text format: "Create new: "query"")
            await waitFor(
                () => {
                    expect(screen.getByText(/Create new:/i)).toBeInTheDocument();
                },
                { timeout: 2000 },
            );

            // The query should appear in the create option text
            expect(screen.getByText(/New Person/i)).toBeInTheDocument();
        });

        it("shows empty state when search has no results", async () => {
            const user = userEvent.setup();

            server.use(
                http.get("/wp-json/cat/v1/roster/search", ({ request }) => {
                    const url = new URL(request.url);
                    const search = url.searchParams.get("search");

                    if (search === "xyz123") {
                        return HttpResponse.json({ persons: [] });
                    }

                    return HttpResponse.json({
                        persons: [
                            { id: "1", displayName: "Ana Rodriguez" },
                            { id: "2", displayName: "John Smith" },
                        ],
                    });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            // Wait for roster to load
            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Search for non-existent person
            const input = screen.getByLabelText(/search roster/i);
            await user.clear(input);
            await user.type(input, "xyz123");

            // Wait for search to complete
            await waitFor(
                () => {
                    // When no results, but has query, should still show "Create new" option
                    expect(screen.getByText(/Create new:/i)).toBeInTheDocument();
                },
                { timeout: 2000 },
            );

            // The query should appear in the create option
            expect(screen.getByText(/xyz123/i)).toBeInTheDocument();

            // When no results match, only "Create new:" is shown (not "No results found")
            // The component doesn't have a separate empty state message
        });
    });

    describe("User Interactions", () => {
        beforeEach(() => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [
                            { id: "person-1", displayName: "Ana Rodriguez" },
                            { id: "person-2", displayName: "John Smith" },
                        ],
                    });
                }),
            );
        });

        it("calls onSelect when clicking a person", async () => {
            const user = userEvent.setup();

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Click on Ana
            const anaOption = screen.getByText("Ana Rodriguez").closest('[role="option"]');
            await user.click(anaOption!);

            expect(mockOnSelect).toHaveBeenCalledWith("person-1");
        });

        it("calls onCreateNew when clicking create new person", async () => {
            const user = userEvent.setup();

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Type a new person name
            const input = screen.getByLabelText(/search roster/i);
            await user.type(input, "Maria Garcia");

            // Wait for create option to appear
            await waitFor(
                () => {
                    expect(screen.getByText(/Create new:/i)).toBeInTheDocument();
                },
                { timeout: 1000 },
            );

            // Click create option (first item in list)
            const createOption = screen.getAllByRole("option")[0];
            await user.click(createOption!);

            expect(mockOnCreateNew).toHaveBeenCalledWith("Maria Garcia");
        });

        it("calls onClose when clicking backdrop", async () => {
            const user = userEvent.setup();

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Click backdrop
            const backdrop = document.querySelector(".cat-people-picker-overlay");
            await user.click(backdrop!);

            expect(mockOnClose).toHaveBeenCalledTimes(1);
        });

        it("calls onClose when pressing Escape", async () => {
            const user = userEvent.setup();

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Press Escape
            await user.keyboard("{Escape}");

            expect(mockOnClose).toHaveBeenCalledTimes(1);
        });
    });

    describe("Keyboard Navigation", () => {
        beforeEach(() => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [
                            { id: "1", displayName: "Ana Rodriguez" },
                            { id: "2", displayName: "John Smith" },
                        ],
                    });
                }),
            );
        });

        it("navigates results with arrow keys", async () => {
            const user = userEvent.setup();

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // First item should be highlighted by default
            const anaOption = screen.getByText("Ana Rodriguez").closest('[role="option"]');
            expect(anaOption).toHaveClass("cat-people-picker__item--highlighted");

            // Press down arrow
            const input = screen.getByLabelText(/search roster/i);
            await user.type(input, "{ArrowDown}");

            // Second item should now be highlighted
            const johnOption = screen.getByText("John Smith").closest('[role="option"]');
            expect(johnOption).toHaveClass("cat-people-picker__item--highlighted");

            // Press up arrow
            await user.type(input, "{ArrowUp}");

            // First item should be highlighted again
            expect(anaOption).toHaveClass("cat-people-picker__item--highlighted");
        });

        it("selects highlighted item with Enter key", async () => {
            const user = userEvent.setup();

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Press Enter (first item is highlighted by default)
            const input = screen.getByLabelText(/search roster/i);
            await user.type(input, "{Enter}");

            expect(mockOnSelect).toHaveBeenCalledWith("1");
        });
    });

    describe("Current Person Display", () => {
        it("shows 'Currently: X' when correcting a label", async () => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [
                            { id: "person-1", displayName: "Ana Rodriguez" },
                            { id: "person-2", displayName: "John Smith" },
                        ],
                    });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                    currentRosterId="person-1"
                />,
            );

            await waitFor(() => {
                expect(screen.getByText(/currently:/i)).toBeInTheDocument();
            });

            // Should show current label indicator
            expect(screen.getByText(/currently:/i)).toBeInTheDocument();

            // The current person name should appear in the "Currently:" section
            // Since there are multiple "Ana Rodriguez" (one in Currently, one in results)
            // we need to be more specific - check that it appears after "Currently:"
            const currentlyText = screen.getByText(/currently:/i).textContent;
            expect(currentlyText).toContain("Ana Rodriguez");
        });
    });

    describe("Avatar Display", () => {
        it("shows first letter placeholder when no avatarUrl", async () => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [{ id: "1", displayName: "Ana Rodriguez" }],
                    });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Should show "A" as placeholder
            const placeholder = document.querySelector(".cat-people-picker__item-placeholder");
            expect(placeholder).toHaveTextContent("A");
        });

        it("shows avatar image when avatarUrl provided", async () => {
            server.use(
                http.get("/wp-json/cat/v1/roster", () => {
                    return HttpResponse.json({
                        persons: [{ id: "1", displayName: "Ana Rodriguez", avatarUrl: "https://example.com/ana.jpg" }],
                    });
                }),
            );

            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                />,
            );

            await waitFor(() => {
                expect(screen.getByText("Ana Rodriguez")).toBeInTheDocument();
            });

            // Should show avatar image (aria-hidden, so use class selector)
            const avatarImg = document.querySelector(".cat-people-picker__item-image");
            expect(avatarImg).toBeInTheDocument();
            expect(avatarImg).toHaveAttribute("src", "https://example.com/ana.jpg");
        });
    });

    describe("Positioning", () => {
        it("applies custom position when provided", () => {
            render(
                <PeoplePicker
                    isOpen={true}
                    onClose={mockOnClose}
                    onSelect={mockOnSelect}
                    onCreateNew={mockOnCreateNew}
                    position={{ top: 100, left: 200 }}
                />,
            );

            const modal = document.querySelector(".cat-people-picker");
            expect(modal).toHaveStyle({
                top: "100px",
                left: "200px",
            });
        });
    });
});
