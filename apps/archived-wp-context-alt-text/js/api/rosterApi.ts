/**
 * Roster API
 *
 * API client for roster person management.
 * Communicates with WordPress REST API endpoints.
 * Data structures aligned with recognition service format.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import { fetchApi } from "@/admin/utils/http";
import type { RosterPerson } from "@/types/people-labeling";

/**
 * Response from roster endpoints
 */
export interface RosterSearchResponse {
    /** Array of roster persons (recognition service-aligned format) */
    entries: RosterPerson[];
    /** Total count (before pagination) */
    total: number;
    /** Current page number */
    page: number;
    /** Items per page */
    perPage: number;
    /** Total number of pages */
    totalPages: number;
}

/**
 * Search roster persons by name
 *
 * @param query - Search query string
 * @param restNonce - Optional WordPress REST nonce
 * @returns Promise resolving to search results
 *
 * @example
 * ```typescript
 * const results = await searchRoster("Ana", nonce);
 * console.log(results.entries); // [{ uniqueId: "uuid-123", displayName: "Ana Rodriguez", ... }]
 * ```
 */
export const searchRoster = async (query: string, restNonce?: string): Promise<RosterSearchResponse> => {
    return fetchApi<RosterSearchResponse>("/wp-json/cat/v1/roster", {
        method: "GET",
        params: {
            search: query,
            per_page: 20,
        },
        restNonce,
    });
};

/**
 * Get all roster persons
 *
 * @param restNonce - Optional WordPress REST nonce
 * @returns Promise resolving to all roster persons
 *
 * @example
 * ```typescript
 * const results = await getAllRoster(nonce);
 * console.log(results.entries); // [{ uniqueId: "uuid-123", ... }, ...]
 * ```
 */
export const getAllRoster = async (restNonce?: string): Promise<RosterSearchResponse> => {
    return fetchApi<RosterSearchResponse>("/wp-json/cat/v1/roster", {
        method: "GET",
        restNonce,
    });
};

/**
 * Create a new roster person
 *
 * @param displayName - Display name for the new person
 * @param restNonce - Optional WordPress REST nonce
 * @returns Promise resolving to created person
 *
 * @example
 * ```typescript
 * const newPerson = await createRosterPerson("Ana Rodriguez", nonce);
 * console.log(newPerson.uniqueId); // "uuid-456"
 * ```
 */
export const createRosterPerson = async (displayName: string, restNonce?: string): Promise<RosterPerson> => {
    const response = await fetchApi<{ entry: RosterPerson }>("/wp-json/cat/v1/roster", {
        method: "POST",
        body: { displayName },
        restNonce,
    });

    return response.entry;
};
