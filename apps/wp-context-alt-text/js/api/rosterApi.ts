/**
 * Roster API
 *
 * API client for roster person management.
 * Communicates with WordPress REST API endpoints.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import { fetchApi } from "@/admin/utils/http";
import type { RosterPerson } from "@/types/people-labeling";

/**
 * Response from roster search endpoint
 */
export interface RosterSearchResponse {
    /** Array of matching roster persons */
    persons: RosterPerson[];
    /** Total count (before pagination) */
    total: number;
}

/**
 * Search roster persons by name or alias
 *
 * @param query - Search query string
 * @param restNonce - Optional WordPress REST nonce
 * @returns Promise resolving to search results
 *
 * @example
 * ```typescript
 * const results = await searchRoster("Ana", nonce);
 * console.log(results.persons); // [{ id: "person-123", displayName: "Ana Rodriguez", ... }]
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
 * console.log(results.persons); // [{ id: "person-123", ... }, ...]
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
 * console.log(newPerson.id); // "person-456"
 * ```
 */
export const createRosterPerson = async (displayName: string, restNonce?: string): Promise<RosterPerson> => {
    return fetchApi<RosterPerson>("/wp-json/cat/v1/roster", {
        method: "POST",
        body: { displayName },
        restNonce,
    });
};
