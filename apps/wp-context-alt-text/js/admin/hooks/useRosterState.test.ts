import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRosterState, rosterStateReducer, type RosterState, type RosterAction } from "./useRosterState";
import type { RosterEntry } from "@/admin/types";

describe("rosterStateReducer", () => {
    const initialState: RosterState = {
        searchInput: "",
        search: null,
        page: 1,
        perPage: 20,
        statusFilter: null,
        editing: null,
        isSubmitting: false,
        draftValues: null,
        observationPrompt: null,
        deepLinkRef: {},
    };

    describe("SET_SEARCH_INPUT", () => {
        it("updates searchInput", () => {
            const action: RosterAction = { type: "SET_SEARCH_INPUT", payload: "test query" };
            const result = rosterStateReducer(initialState, action);

            expect(result.searchInput).toBe("test query");
            expect(result).not.toBe(initialState); // New object
        });
    });

    describe("SET_SEARCH", () => {
        it("updates search query", () => {
            const action: RosterAction = { type: "SET_SEARCH", payload: "test" };
            const result = rosterStateReducer(initialState, action);

            expect(result.search).toBe("test");
        });

        it("can clear search", () => {
            const stateWithSearch = { ...initialState, search: "test" };
            const action: RosterAction = { type: "SET_SEARCH", payload: null };
            const result = rosterStateReducer(stateWithSearch, action);

            expect(result.search).toBeNull();
        });
    });

    describe("SET_PAGE", () => {
        it("updates page number", () => {
            const action: RosterAction = { type: "SET_PAGE", payload: 5 };
            const result = rosterStateReducer(initialState, action);

            expect(result.page).toBe(5);
        });
    });

    describe("SET_PER_PAGE", () => {
        it("updates perPage value", () => {
            const action: RosterAction = { type: "SET_PER_PAGE", payload: 50 };
            const result = rosterStateReducer(initialState, action);

            expect(result.perPage).toBe(50);
        });
    });

    describe("SET_STATUS_FILTER", () => {
        it("updates status filter", () => {
            const action: RosterAction = { type: "SET_STATUS_FILTER", payload: "LOCAL" };
            const result = rosterStateReducer(initialState, action);

            expect(result.statusFilter).toBe("LOCAL");
        });

        it("can clear status filter", () => {
            const stateWithFilter = { ...initialState, statusFilter: "SYNCED" as const };
            const action: RosterAction = { type: "SET_STATUS_FILTER", payload: null };
            const result = rosterStateReducer(stateWithFilter, action);

            expect(result.statusFilter).toBeNull();
        });
    });

    describe("SET_EDITING", () => {
        it("updates editing entry", () => {
            const entry: RosterEntry = {
                remoteId: "remote-123",
                label: "Test Entry",
                type: "person",
                status: "LOCAL",
                updatedAt: "2025-10-18T00:00:00Z",
                metadata: {},
                referenceImages: [],
                avatarUrl: null,
                avatarId: null,
                referenceImageCount: 0,
            };
            const action: RosterAction = { type: "SET_EDITING", payload: entry };
            const result = rosterStateReducer(initialState, action);

            expect(result.editing).toBe(entry);
        });

        it("can clear editing", () => {
            const entry: RosterEntry = {
                remoteId: "remote-123",
                label: "Test Entry",
                type: "person",
                status: "LOCAL",
                updatedAt: "2025-10-18T00:00:00Z",
                metadata: {},
                referenceImages: [],
                avatarUrl: null,
                avatarId: null,
                referenceImageCount: 0,
            };
            const stateWithEditing = { ...initialState, editing: entry };
            const action: RosterAction = { type: "SET_EDITING", payload: null };
            const result = rosterStateReducer(stateWithEditing, action);

            expect(result.editing).toBeNull();
        });
    });

    describe("SET_IS_SUBMITTING", () => {
        it("updates isSubmitting", () => {
            const action: RosterAction = { type: "SET_IS_SUBMITTING", payload: true };
            const result = rosterStateReducer(initialState, action);

            expect(result.isSubmitting).toBe(true);
        });
    });

    describe("SET_DRAFT_VALUES", () => {
        it("updates draft values", () => {
            const action: RosterAction = {
                type: "SET_DRAFT_VALUES",
                payload: { label: "Draft Label", type: "brand" },
            };
            const result = rosterStateReducer(initialState, action);

            expect(result.draftValues).toEqual({ label: "Draft Label", type: "brand" });
        });

        it("can clear draft values", () => {
            const stateWithDraft = { ...initialState, draftValues: { label: "Test", type: "person" } };
            const action: RosterAction = { type: "SET_DRAFT_VALUES", payload: null };
            const result = rosterStateReducer(stateWithDraft, action);

            expect(result.draftValues).toBeNull();
        });
    });

    describe("SET_OBSERVATION_PROMPT", () => {
        it("updates observation prompt", () => {
            const prompt = {
                observationId: "obs-123",
                attachmentId: 456,
                source: "recognition",
                remoteId: "remote-789",
                label: "Test Label",
            };
            const action: RosterAction = { type: "SET_OBSERVATION_PROMPT", payload: prompt };
            const result = rosterStateReducer(initialState, action);

            expect(result.observationPrompt).toEqual(prompt);
        });

        it("can clear observation prompt", () => {
            const prompt = {
                observationId: "obs-123",
                attachmentId: 456,
                source: "recognition",
                remoteId: null,
                label: null,
            };
            const stateWithPrompt = { ...initialState, observationPrompt: prompt };
            const action: RosterAction = { type: "SET_OBSERVATION_PROMPT", payload: null };
            const result = rosterStateReducer(stateWithPrompt, action);

            expect(result.observationPrompt).toBeNull();
        });
    });

    describe("SET_DEEP_LINK_REF", () => {
        it("updates deep link ref", () => {
            const ref = { remoteId: "remote-123", draftSignature: "sig-456" };
            const action: RosterAction = { type: "SET_DEEP_LINK_REF", payload: ref };
            const result = rosterStateReducer(initialState, action);

            expect(result.deepLinkRef).toEqual(ref);
        });
    });

    describe("RESET_PAGE", () => {
        it("resets page to 1", () => {
            const stateWithPage = { ...initialState, page: 5 };
            const action: RosterAction = { type: "RESET_PAGE" };
            const result = rosterStateReducer(stateWithPage, action);

            expect(result.page).toBe(1);
        });
    });

    describe("CLEAR_STATUS_FILTER", () => {
        it("clears status filter and resets page", () => {
            const stateWithFilter = { ...initialState, statusFilter: "SYNCED" as const, page: 3 };
            const action: RosterAction = { type: "CLEAR_STATUS_FILTER" };
            const result = rosterStateReducer(stateWithFilter, action);

            expect(result.statusFilter).toBeNull();
            expect(result.page).toBe(1);
        });
    });

    describe("DISMISS_OBSERVATION_PROMPT", () => {
        it("clears observation prompt", () => {
            const prompt = {
                observationId: "obs-123",
                attachmentId: 456,
                source: "recognition",
                remoteId: null,
                label: null,
            };
            const stateWithPrompt = { ...initialState, observationPrompt: prompt };
            const action: RosterAction = { type: "DISMISS_OBSERVATION_PROMPT" };
            const result = rosterStateReducer(stateWithPrompt, action);

            expect(result.observationPrompt).toBeNull();
        });
    });

    describe("RESET_FORM", () => {
        it("resets form-related state", () => {
            const entry: RosterEntry = {
                remoteId: "remote-123",
                label: "Test Entry",
                type: "person",
                status: "LOCAL",
                updatedAt: "2025-10-18T00:00:00Z",
                metadata: {},
                referenceImages: [],
                avatarUrl: null,
                avatarId: null,
                referenceImageCount: 0,
            };
            const stateWithForm = {
                ...initialState,
                editing: entry,
                isSubmitting: true,
                draftValues: { label: "Draft", type: "person" },
            };
            const action: RosterAction = { type: "RESET_FORM" };
            const result = rosterStateReducer(stateWithForm, action);

            expect(result.editing).toBeNull();
            expect(result.isSubmitting).toBe(false);
            expect(result.draftValues).toBeNull();
        });
    });

    describe("unknown action", () => {
        it("returns state unchanged", () => {
            const action = { type: "UNKNOWN_ACTION" } as unknown as RosterAction;
            const result = rosterStateReducer(initialState, action);

            expect(result).toBe(initialState);
        });
    });
});

describe("useRosterState", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("initializes with default state", () => {
        const { result } = renderHook(() => useRosterState());

        expect(result.current.state.searchInput).toBe("");
        expect(result.current.state.search).toBeNull();
        expect(result.current.state.page).toBe(1);
        expect(result.current.state.perPage).toBe(20);
        expect(result.current.state.statusFilter).toBeNull();
        expect(result.current.state.editing).toBeNull();
        expect(result.current.state.isSubmitting).toBe(false);
        expect(result.current.state.draftValues).toBeNull();
        expect(result.current.state.observationPrompt).toBeNull();
    });

    it("accepts initial state override", () => {
        const { result } = renderHook(() =>
            useRosterState({
                initialState: {
                    page: 3,
                    perPage: 50,
                    searchInput: "initial",
                },
            }),
        );

        expect(result.current.state.page).toBe(3);
        expect(result.current.state.perPage).toBe(50);
        expect(result.current.state.searchInput).toBe("initial");
    });

    it("provides stable action creators", () => {
        const { result, rerender } = renderHook(() => useRosterState());

        const initialActions = result.current.actions;
        rerender();
        const nextActions = result.current.actions;

        expect(initialActions).toBe(nextActions); // Same reference
    });

    it("derives filters from state", () => {
        const { result } = renderHook(() => useRosterState());

        expect(result.current.filters).toEqual({
            search: null,
            page: 1,
            perPage: 20,
        });
    });

    it("includes status filter when set", () => {
        const { result } = renderHook(() => useRosterState());

        act(() => {
            result.current.actions.setStatusFilter("LOCAL");
        });

        expect(result.current.filters).toEqual({
            search: null,
            page: 1,
            perPage: 20,
            status: "LOCAL",
        });
    });

    describe("search debouncing", () => {
        it("debounces search input updates", async () => {
            const { result } = renderHook(() => useRosterState({ searchDebounceMs: 400 }));

            act(() => {
                result.current.actions.setSearchInput("test");
            });

            // Search should not update immediately
            expect(result.current.state.searchInput).toBe("test");
            expect(result.current.state.search).toBeNull();
            expect(result.current.state.page).toBe(1);

            // Advance timers and wait for effect
            await act(async () => {
                vi.advanceTimersByTime(400);
                await Promise.resolve(); // Allow effect to run
            });

            // Search should now be updated
            expect(result.current.state.search).toBe("test");
        });

        it("resets page when search updates", async () => {
            const { result } = renderHook(() => useRosterState({ searchDebounceMs: 400 }));

            act(() => {
                result.current.actions.setPage(3);
            });

            expect(result.current.state.page).toBe(3);

            act(() => {
                result.current.actions.setSearchInput("test");
            });

            // Advance timers and wait for effect
            await act(async () => {
                vi.advanceTimersByTime(400);
                await Promise.resolve(); // Allow effect to run
            });

            expect(result.current.state.search).toBe("test");
            expect(result.current.state.page).toBe(1); // Reset to 1
        });

        it("trims search input", async () => {
            const { result } = renderHook(() => useRosterState({ searchDebounceMs: 400 }));

            act(() => {
                result.current.actions.setSearchInput("  test  ");
            });

            // Advance timers and wait for effect
            await act(async () => {
                vi.advanceTimersByTime(400);
                await Promise.resolve(); // Allow effect to run
            });

            expect(result.current.state.search).toBe("test");
        });

        it("treats empty/whitespace as null search", async () => {
            const { result } = renderHook(() => useRosterState({ searchDebounceMs: 400 }));

            act(() => {
                result.current.actions.setSearchInput("   ");
            });

            // Advance timers and wait for effect
            await act(async () => {
                vi.advanceTimersByTime(400);
                await Promise.resolve(); // Allow effect to run
            });

            expect(result.current.state.search).toBeNull();
        });

        it("can disable debouncing with 0ms", () => {
            const { result } = renderHook(() => useRosterState({ searchDebounceMs: 0 }));

            act(() => {
                result.current.actions.setSearchInput("test");
            });

            // Should update immediately
            expect(result.current.state.search).toBe("test");
        });
    });

    describe("status filter page reset", () => {
        it("resets page when status filter changes", () => {
            const { result } = renderHook(() => useRosterState());

            act(() => {
                result.current.actions.setPage(5);
            });

            expect(result.current.state.page).toBe(5);

            act(() => {
                result.current.actions.setStatusFilter("LOCAL");
            });

            expect(result.current.state.page).toBe(1);
        });

        it("does not reset page on subsequent renders with same filter", () => {
            const { result, rerender } = renderHook(() => useRosterState());

            act(() => {
                result.current.actions.setStatusFilter("LOCAL");
            });

            // Wait for the effect to run and page to reset to 1
            expect(result.current.state.page).toBe(1);

            // Now set page to 3
            act(() => {
                result.current.actions.setPage(3);
            });

            expect(result.current.state.page).toBe(3);

            // Rerender should not reset page since filter hasn't changed
            rerender();

            // Page should still be 3
            expect(result.current.state.page).toBe(3);
        });
    });

    describe("action creators", () => {
        it("setSearchInput updates searchInput", () => {
            const { result } = renderHook(() => useRosterState());

            act(() => {
                result.current.actions.setSearchInput("new search");
            });

            expect(result.current.state.searchInput).toBe("new search");
        });

        it("setPage updates page", () => {
            const { result } = renderHook(() => useRosterState());

            act(() => {
                result.current.actions.setPage(10);
            });

            expect(result.current.state.page).toBe(10);
        });

        it("setPerPage updates perPage", () => {
            const { result } = renderHook(() => useRosterState());

            act(() => {
                result.current.actions.setPerPage(50);
            });

            expect(result.current.state.perPage).toBe(50);
        });

        it("setEditing updates editing", () => {
            const { result } = renderHook(() => useRosterState());
            const entry: RosterEntry = {
                remoteId: "remote-123",
                label: "Test",
                type: "person",
                status: "LOCAL",
                updatedAt: "2025-10-18T00:00:00Z",
                metadata: {},
                referenceImages: [],
                avatarUrl: null,
                avatarId: null,
                referenceImageCount: 0,
            };

            act(() => {
                result.current.actions.setEditing(entry);
            });

            expect(result.current.state.editing).toBe(entry);
        });

        it("resetForm clears form state", () => {
            const { result } = renderHook(() => useRosterState());
            const entry: RosterEntry = {
                remoteId: "remote-123",
                label: "Test",
                type: "person",
                status: "LOCAL",
                updatedAt: "2025-10-18T00:00:00Z",
                metadata: {},
                referenceImages: [],
                avatarUrl: null,
                avatarId: null,
                referenceImageCount: 0,
            };

            act(() => {
                result.current.actions.setEditing(entry);
                result.current.actions.setIsSubmitting(true);
                result.current.actions.setDraftValues({ label: "Draft", type: "person" });
            });

            expect(result.current.state.editing).toBe(entry);
            expect(result.current.state.isSubmitting).toBe(true);
            expect(result.current.state.draftValues).toEqual({ label: "Draft", type: "person" });

            act(() => {
                result.current.actions.resetForm();
            });

            expect(result.current.state.editing).toBeNull();
            expect(result.current.state.isSubmitting).toBe(false);
            expect(result.current.state.draftValues).toBeNull();
        });

        it("clearStatusFilter clears filter and resets page", () => {
            const { result } = renderHook(() => useRosterState());

            act(() => {
                result.current.actions.setStatusFilter("SYNCED");
            });

            // Page resets to 1 when filter is set
            expect(result.current.state.statusFilter).toBe("SYNCED");
            expect(result.current.state.page).toBe(1);

            // Set page to 5 after filter is set
            act(() => {
                result.current.actions.setPage(5);
            });

            expect(result.current.state.page).toBe(5);

            act(() => {
                result.current.actions.clearStatusFilter();
            });

            expect(result.current.state.statusFilter).toBeNull();
            expect(result.current.state.page).toBe(1);
        });
    });
});
