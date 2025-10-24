/**
 * Recognition API Client
 *
 * Provides typed API wrappers for face recognition endpoints.
 * Used by usePeopleSuggestions hook and other recognition features.
 */

import type { IdentifyRequest, IdentifyResponse } from "@/types/people-labeling";
import { fetchApi } from "@/admin/utils/http";

/**
 * API endpoints
 */
const ENDPOINTS = {
    identify: "/wp-json/cat/v1/recognition/identify",
} as const;

/**
 * Submit faces for identification (embeddings, suggestions, clustering).
 *
 * @param request - Identify request with attachment ID and detected faces
 * @param restNonce - WordPress REST API nonce for authentication
 * @returns Identify response with suggestions and cluster IDs
 * @throws Error if request fails (network error, 4xx/5xx response)
 *
 * @example
 * ```ts
 * const response = await identifyFaces({
 *     attachmentId: 123,
 *     faces: [{ bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 } }]
 * }, nonce);
 * ```
 */
export const identifyFaces = async (request: IdentifyRequest, restNonce?: string): Promise<IdentifyResponse> => {
    return fetchApi<IdentifyResponse>(ENDPOINTS.identify, {
        method: "POST",
        body: request,
        restNonce,
    });
};

/**
 * Submit label for a single face (creates observation and syncs to FAISS).
 *
 * This is a convenience wrapper around identifyFaces for single-face labeling.
 * Use bulkConfirm for labeling multiple faces at once.
 *
 * @param request - Identify request with label field populated
 * @param restNonce - WordPress REST API nonce for authentication
 * @returns Response with observation ID and sync status
 *
 * @example
 * ```ts
 * const response = await submitLabel({
 *     attachmentId: 123,
 *     faces: [{
 *         bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.4 },
 *         faceId: 'face-1',
 *         label: { rosterId: 'person-123' }
 *     }]
 * }, nonce);
 * ```
 */
export const submitLabel = async (request: IdentifyRequest, restNonce?: string): Promise<IdentifyResponse> => {
    return identifyFaces(request, restNonce);
};

/**
 * Bulk confirm multiple faces with same roster ID.
 *
 * Submits multiple faces in single request for efficiency.
 * Backend will create observations and sync embeddings for all faces.
 *
 * @param request - Identify request with multiple faces labeled
 * @param restNonce - WordPress REST API nonce for authentication
 * @returns Response with observation IDs and sync statuses
 *
 * @example
 * ```ts
 * const response = await bulkConfirm({
 *     attachmentId: 123,
 *     faces: [
 *         { bbox: {...}, faceId: 'face-1', label: { rosterId: 'person-123' } },
 *         { bbox: {...}, faceId: 'face-2', label: { rosterId: 'person-123' } }
 *     ]
 * }, nonce);
 * ```
 */
export const bulkConfirm = async (request: IdentifyRequest, restNonce?: string): Promise<IdentifyResponse> => {
    return identifyFaces(request, restNonce);
};
