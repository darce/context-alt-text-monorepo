import React from "react";
import type { RosterEntry } from "@/admin/types";
import type { RosterFilters } from "@/admin/hooks/useRoster";

/**
 * State shape for roster UI management.
 *
 * Consolidates all roster interface state into a single object managed by useReducer.
 * This replaces 16 separate useState hooks to enable atomic state updates and prevent
 * race conditions.
 *
 * @interface RosterState
 */
export interface RosterState {
    // Search & Filters
    searchInput: string;
    search: string | null;
    page: number;
    perPage: number;
    statusFilter: RosterFilters["status"];

    // Form State
    editing: RosterEntry | null;
    isSubmitting: boolean;
    draftValues: { label?: string; type?: string } | null;

    // Dialog State
    observationPrompt: ObservationPromptState | null;
    observationDialogDismissed: boolean;

    // Internal State
    deepLinkRef: { remoteId?: string | null; draftSignature?: string | null };
}

/**
 * Observation prompt dialog state.
 *
 * Represents data needed to show the observation assignment dialog when
 * a recognition observation needs to be matched to a roster entry.
 *
 * @interface ObservationPromptState
 */
export interface ObservationPromptState {
    observationId: string;
    attachmentId: number | null;
    source: string | null;
    remoteId?: string | null;
    label?: string | null;
}

/**
 * Actions for roster state management.
 *
 * Discriminated union of all possible state transitions in the roster interface.
 * Each action type corresponds to a specific user interaction or data change.
 *
 * @typedef {Object} RosterAction
 */
export type RosterAction =
    | { type: "SET_SEARCH_INPUT"; payload: string }
    | { type: "SET_SEARCH"; payload: string | null }
    | { type: "SET_PAGE"; payload: number }
    | { type: "SET_PER_PAGE"; payload: number }
    | { type: "SET_STATUS_FILTER"; payload: RosterFilters["status"] }
    | { type: "SET_EDITING"; payload: RosterEntry | null }
    | { type: "SET_IS_SUBMITTING"; payload: boolean }
    | { type: "SET_DRAFT_VALUES"; payload: { label?: string; type?: string } | null }
    | { type: "SET_OBSERVATION_PROMPT"; payload: ObservationPromptState | null }
    | { type: "SET_OBSERVATION_DIALOG_DISMISSED"; payload: boolean }
    | { type: "SET_DEEP_LINK_REF"; payload: { remoteId?: string | null; draftSignature?: string | null } }
    | { type: "RESET_PAGE" }
    | { type: "CLEAR_STATUS_FILTER" }
    | { type: "DISMISS_OBSERVATION_PROMPT" }
    | { type: "RESET_FORM" };

/**
 * Reducer for roster state management
 */
export const rosterStateReducer = (state: RosterState, action: RosterAction): RosterState => {
    switch (action.type) {
        case "SET_SEARCH_INPUT":
            return { ...state, searchInput: action.payload };

        case "SET_SEARCH":
            return { ...state, search: action.payload };

        case "SET_PAGE":
            return { ...state, page: action.payload };

        case "SET_PER_PAGE":
            return { ...state, perPage: action.payload };

        case "SET_STATUS_FILTER":
            return { ...state, statusFilter: action.payload };

        case "SET_EDITING":
            return { ...state, editing: action.payload };

        case "SET_IS_SUBMITTING":
            return { ...state, isSubmitting: action.payload };

        case "SET_DRAFT_VALUES":
            return { ...state, draftValues: action.payload };

        case "SET_OBSERVATION_PROMPT":
            return { ...state, observationPrompt: action.payload };

        case "SET_OBSERVATION_DIALOG_DISMISSED":
            return { ...state, observationDialogDismissed: action.payload };

        case "SET_DEEP_LINK_REF":
            return { ...state, deepLinkRef: action.payload };

        case "RESET_PAGE":
            return { ...state, page: 1 };

        case "CLEAR_STATUS_FILTER":
            return { ...state, statusFilter: null, page: 1 };

        case "DISMISS_OBSERVATION_PROMPT":
            return { ...state, observationPrompt: null };

        case "RESET_FORM":
            return {
                ...state,
                editing: null,
                isSubmitting: false,
                draftValues: null,
            };

        default:
            return state;
    }
};

/**
 * Action creators for roster state
 */
export interface RosterStateActions {
    setSearchInput: (value: string) => void;
    setSearch: (value: string | null) => void;
    setPage: (value: number) => void;
    setPerPage: (value: number) => void;
    setStatusFilter: (value: RosterFilters["status"]) => void;
    setEditing: (value: RosterEntry | null) => void;
    setIsSubmitting: (value: boolean) => void;
    setDraftValues: (value: { label?: string; type?: string } | null) => void;
    setObservationPrompt: (value: ObservationPromptState | null) => void;
    setObservationDialogDismissed: (value: boolean) => void;
    setDeepLinkRef: (value: { remoteId?: string | null; draftSignature?: string | null }) => void;
    resetPage: () => void;
    clearStatusFilter: () => void;
    dismissObservationPrompt: () => void;
    resetForm: () => void;
}

/**
 * Options for useRosterState hook
 */
export interface UseRosterStateOptions {
    initialState?: Partial<RosterState>;
    searchDebounceMs?: number;
}

/**
 * Return type for useRosterState hook
 */
export interface UseRosterStateReturn {
    state: RosterState;
    actions: RosterStateActions;
    filters: RosterFilters;
}

/**
 * Default initial state
 */
const DEFAULT_INITIAL_STATE: RosterState = {
    searchInput: "",
    search: null,
    page: 1,
    perPage: 20,
    statusFilter: null,
    editing: null,
    isSubmitting: false,
    draftValues: null,
    observationPrompt: null,
    observationDialogDismissed: false,
    deepLinkRef: {},
};

/**
 * Custom hook for managing roster UI state
 *
 * Consolidates 16 useState hooks into a single useReducer-based state management solution.
 * Provides action creators for state updates and derived filters for data fetching.
 *
 * @param options - Configuration options
 * @returns State, actions, and derived filters
 *
 * @example
 * ```tsx
 * const { state, actions, filters } = useRosterState({
 *   searchDebounceMs: 400
 * });
 *
 * // Update state
 * actions.setSearchInput("John Doe");
 * actions.setPage(2);
 * actions.setEditing(entry);
 *
 * // Use filters for data fetching
 * const roster = useRoster({ filters });
 * ```
 */
export const useRosterState = (options: UseRosterStateOptions = {}): UseRosterStateReturn => {
    const { initialState = {}, searchDebounceMs = 400 } = options;

    // Initialize state with reducer
    const [state, dispatch] = React.useReducer(rosterStateReducer, {
        ...DEFAULT_INITIAL_STATE,
        ...initialState,
    });

    // Create stable action creators
    const actions = React.useMemo<RosterStateActions>(
        () => ({
            setSearchInput: (value: string) => dispatch({ type: "SET_SEARCH_INPUT", payload: value }),
            setSearch: (value: string | null) => dispatch({ type: "SET_SEARCH", payload: value }),
            setPage: (value: number) => dispatch({ type: "SET_PAGE", payload: value }),
            setPerPage: (value: number) => dispatch({ type: "SET_PER_PAGE", payload: value }),
            setStatusFilter: (value: RosterFilters["status"]) =>
                dispatch({ type: "SET_STATUS_FILTER", payload: value }),
            setEditing: (value: RosterEntry | null) => dispatch({ type: "SET_EDITING", payload: value }),
            setIsSubmitting: (value: boolean) => dispatch({ type: "SET_IS_SUBMITTING", payload: value }),
            setDraftValues: (value: { label?: string; type?: string } | null) =>
                dispatch({ type: "SET_DRAFT_VALUES", payload: value }),
            setObservationPrompt: (value: ObservationPromptState | null) =>
                dispatch({ type: "SET_OBSERVATION_PROMPT", payload: value }),
            setObservationDialogDismissed: (value: boolean) =>
                dispatch({ type: "SET_OBSERVATION_DIALOG_DISMISSED", payload: value }),
            setDeepLinkRef: (value: { remoteId?: string | null; draftSignature?: string | null }) =>
                dispatch({ type: "SET_DEEP_LINK_REF", payload: value }),
            resetPage: () => dispatch({ type: "RESET_PAGE" }),
            clearStatusFilter: () => dispatch({ type: "CLEAR_STATUS_FILTER" }),
            dismissObservationPrompt: () => dispatch({ type: "DISMISS_OBSERVATION_PROMPT" }),
            resetForm: () => dispatch({ type: "RESET_FORM" }),
        }),
        [],
    );

    // Effect: Search input debouncing
    React.useEffect(() => {
        if (searchDebounceMs <= 0) {
            const value = state.searchInput.trim();
            dispatch({ type: "SET_SEARCH", payload: value.length > 0 ? value : null });
            dispatch({ type: "RESET_PAGE" });
            return;
        }

        const timer = window.setTimeout(() => {
            const value = state.searchInput.trim();
            dispatch({ type: "SET_SEARCH", payload: value.length > 0 ? value : null });
            dispatch({ type: "RESET_PAGE" });
        }, searchDebounceMs);

        return () => window.clearTimeout(timer);
    }, [state.searchInput, searchDebounceMs]);

    // Effect: Reset dialog dismissed state when observation prompt changes
    React.useEffect(() => {
        if (state.observationPrompt) {
            dispatch({ type: "SET_OBSERVATION_DIALOG_DISMISSED", payload: false });
        }
    }, [state.observationPrompt?.observationId]); // eslint-disable-line react-hooks/exhaustive-deps

    // Effect: Reset page when status filter changes
    const previousStatusRef = React.useRef<RosterFilters["status"]>(null);
    React.useEffect(() => {
        if (previousStatusRef.current === state.statusFilter) {
            return;
        }

        previousStatusRef.current = state.statusFilter ?? null;
        dispatch({ type: "RESET_PAGE" });
    }, [state.statusFilter]);

    // Derive filters for data fetching
    const filters = React.useMemo<RosterFilters>(() => {
        const base: RosterFilters = {
            search: state.search,
            page: state.page,
            perPage: state.perPage,
        };

        if (state.statusFilter) {
            base.status = state.statusFilter;
        }

        return base;
    }, [state.search, state.page, state.perPage, state.statusFilter]);

    return {
        state,
        actions,
        filters,
    };
};
