/**
 * Roster Search Hook
 *
 * Manages roster search state with debounced API calls.
 * Provides typeahead search functionality for PeoplePicker.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { searchRoster, getAllRoster } from "@/api/rosterApi";
import type { RosterPerson } from "@/types/people-labeling";

/**
 * Hook configuration options
 */
export interface UseRosterSearchOptions {
    /** Debounce delay in milliseconds (default: 300) */
    debounceMs?: number;
    /** WordPress REST nonce for API calls */
    restNonce?: string;
    /** Minimum query length to trigger search (default: 1) */
    minQueryLength?: number;
}

/**
 * Hook return value
 */
export interface UseRosterSearchReturn {
    /** Search query string */
    query: string;
    /** Set search query */
    setQuery: (query: string) => void;
    /** Search results */
    results: RosterPerson[];
    /** Whether search is in progress */
    isLoading: boolean;
    /** Error from last search */
    error: Error | null;
    /** Reset search state */
    reset: () => void;
}

/**
 * Roster Search Hook
 *
 * Manages debounced search of roster persons.
 * Automatically fetches all roster on mount.
 *
 * @param options - Configuration options
 * @returns Search state and actions
 *
 * @example
 * ```typescript
 * const { query, setQuery, results, isLoading } = useRosterSearch({
 *     debounceMs: 300,
 *     restNonce: window.catAltText?.restNonce
 * });
 *
 * // User types "Ana"
 * setQuery("Ana");
 * // After 300ms, API call triggers
 * // results updates with matching persons
 * ```
 */
export const useRosterSearch = (options: UseRosterSearchOptions = {}): UseRosterSearchReturn => {
    const { debounceMs = 300, restNonce, minQueryLength = 1 } = options;

    const [query, setQuery] = useState("");
    const [results, setResults] = useState<RosterPerson[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<Error | null>(null);

    const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const abortControllerRef = useRef<AbortController | null>(null);

    /**
     * Fetch all roster persons (initial load)
     */
    const fetchAll = useCallback(async (): Promise<void> => {
        setIsLoading(true);
        setError(null);

        try {
            const response = await getAllRoster(restNonce);
            setResults(response.persons);
        } catch (err) {
            setError(err instanceof Error ? err : new Error("Failed to load roster"));
            setResults([]);
        } finally {
            setIsLoading(false);
        }
    }, [restNonce]);

    /**
     * Search roster with current query
     */
    const performSearch = useCallback(
        async (searchQuery: string): Promise<void> => {
            // Cancel previous request
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }

            // Empty query: show all
            if (searchQuery.trim().length === 0) {
                void fetchAll();
                return;
            }

            // Query too short: clear results
            if (searchQuery.trim().length < minQueryLength) {
                setResults([]);
                setIsLoading(false);
                return;
            }

            setIsLoading(true);
            setError(null);

            abortControllerRef.current = new AbortController();

            try {
                const response = await searchRoster(searchQuery, restNonce);
                setResults(response.persons);
            } catch (err) {
                // Ignore abort errors
                if (err instanceof Error && err.name === "AbortError") {
                    return;
                }

                setError(err instanceof Error ? err : new Error("Failed to search roster"));
                setResults([]);
            } finally {
                setIsLoading(false);
                abortControllerRef.current = null;
            }
        },
        [restNonce, minQueryLength, fetchAll],
    );

    /**
     * Debounce search when query changes
     */
    useEffect(() => {
        // Clear existing timer
        if (debounceTimerRef.current) {
            clearTimeout(debounceTimerRef.current);
        }

        // Set new timer
        debounceTimerRef.current = setTimeout(() => {
            void performSearch(query);
        }, debounceMs);

        // Cleanup
        return () => {
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
        };
    }, [query, debounceMs, performSearch]);

    /**
     * Load all roster on mount
     */
    useEffect(() => {
        void fetchAll();
    }, [fetchAll]);

    /**
     * Cleanup on unmount
     */
    useEffect(() => {
        return () => {
            if (abortControllerRef.current) {
                abortControllerRef.current.abort();
            }
            if (debounceTimerRef.current) {
                clearTimeout(debounceTimerRef.current);
            }
        };
    }, []);

    /**
     * Reset search state
     */
    const reset = useCallback((): void => {
        setQuery("");
        setError(null);
        void fetchAll();
    }, [fetchAll]);

    return {
        query,
        setQuery,
        results,
        isLoading,
        error,
        reset,
    };
};
