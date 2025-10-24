/**
 * usePeopleSuggestions Hook
 *
 * Manages face identification workflow:
 * - Converts raw detections to identify requests
 * - Merges backend suggestions into frontend state
 * - Handles single/bulk label submission
 * - Provides optimistic updates for UX
 * - Shows toast notifications for sync feedback
 */

import { useState, useCallback, useRef } from "react";
import type {
    DetectedFaceFE,
    RawDetection,
    Label,
    IdentifyRequest,
    DetectedFaceRequest,
    UsePeopleSuggestionsReturn,
} from "@/types/people-labeling";
import {
    identifyFaces as apiIdentifyFaces,
    submitLabel as apiSubmitLabel,
    bulkConfirm as apiBulkConfirm,
} from "@/api/recognitionApi";
import { notifySuccess, notifyError } from "@/admin/notices";

/**
 * Generate unique face ID for frontend tracking
 */
const generateFaceId = (() => {
    let counter = 0;
    return () => `face-${Date.now()}-${counter++}`;
})();

/**
 * Storage key for persisted face labels (localStorage)
 */
const STORAGE_KEY_PREFIX = 'cat_face_labels_';

/**
 * Save face labels to localStorage for client-side persistence
 * (Used when recognition service is offline and can't create real observations)
 */
const saveFaceLabelsToStorage = (attachmentId: number, faces: DetectedFaceFE[]): void => {
    try {
        const key = `${STORAGE_KEY_PREFIX}${attachmentId}`;
        const labelsToStore = faces
            .filter((f) => f.confirmedRosterId)
            .map((f) => ({
                bbox: f.bbox,
                confirmedRosterId: f.confirmedRosterId,
                labelDraft: f.labelDraft,
            }));
        
        if (labelsToStore.length > 0) {
            localStorage.setItem(key, JSON.stringify(labelsToStore));
        } else {
            localStorage.removeItem(key);
        }
    } catch (err) {
        console.warn('Failed to save face labels to localStorage:', err);
    }
};

/**
 * Load face labels from localStorage
 */
const loadFaceLabelsFromStorage = (attachmentId: number): Array<{
    bbox: { x: number; y: number; width: number; height: number };
    confirmedRosterId: string | null;
    labelDraft: Label | null;
}> => {
    try {
        const key = `${STORAGE_KEY_PREFIX}${attachmentId}`;
        const stored = localStorage.getItem(key);
        if (stored) {
            return JSON.parse(stored);
        }
    } catch (err) {
        console.warn('Failed to load face labels from localStorage:', err);
    }
    return [];
};

/**
 * Hook for managing people suggestions and labeling
 *
 * @param restNonce - WordPress REST API nonce for authentication
 * @returns Hook state and actions
 *
 * @example
 * ```tsx
 * const { faces, isLoading, error, identifyFaces, submitLabel } = usePeopleSuggestions(nonce);
 *
 * // Identify faces in image
 * await identifyFaces(123, rawDetections);
 *
 * // Submit label for face
 * await submitLabel('face-1', { rosterId: 'person-123' });
 * ```
 */
export const usePeopleSuggestions = (restNonce?: string): UsePeopleSuggestionsReturn => {
    const [faces, setFaces] = useState<DetectedFaceFE[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<Error | null>(null);

    // Track current attachment ID for validation
    const attachmentIdRef = useRef<number | null>(null);

    /**
     * Convert raw detections to identify request faces
     */
    const rawDetectionsToRequest = useCallback((detections: RawDetection[]): DetectedFaceRequest[] => {
        return detections.map((detection) => ({
            bbox: detection.boundingBox,
            faceId: generateFaceId(),
        }));
    }, []);

    /**
     * Merge identify response into frontend face state
     */
    const mergeResponse = useCallback(
        (attachmentId: number, requestFaces: DetectedFaceRequest[], responseFaces: DetectedFaceFE[]) => {
            // Load any previously saved labels from localStorage
            const savedLabels = loadFaceLabelsFromStorage(attachmentId);
            
            // Create map of faceId -> response data
            const responseMap = new Map(responseFaces.map((face) => [face.faceId, face]));

            // Helper to match saved label to current face by bbox
            const findSavedLabel = (bbox: { x: number; y: number; width: number; height: number }) => {
                return savedLabels.find(
                    (saved) =>
                        Math.abs(saved.bbox.x - bbox.x) < 5 &&
                        Math.abs(saved.bbox.y - bbox.y) < 5 &&
                        Math.abs(saved.bbox.width - bbox.width) < 5 &&
                        Math.abs(saved.bbox.height - bbox.height) < 5
                );
            };

            // Merge with request faces to ensure all faces are included
            const mergedFaces: DetectedFaceFE[] = requestFaces.map((reqFace, index) => {
                const respFace = responseMap.get(reqFace.faceId ?? "");
                const faceId = reqFace.faceId ?? generateFaceId();

                // If backend didn't provide clusterId (e.g., recognition service offline),
                // generate a default one so face appears in drawer
                const clusterId = respFace?.clusterId ?? `unknown-${attachmentId}-${index}`;

                // Check for saved label from localStorage
                const savedLabel = findSavedLabel(reqFace.bbox);

                return {
                    faceId,
                    bbox: reqFace.bbox,
                    attachmentId,
                    confidence: 0.9, // Default confidence (not provided in identify response)
                    clusterId,
                    suggestions: respFace?.suggestions ?? [],
                    labelDraft: savedLabel?.labelDraft ?? reqFace.label ?? null,
                    confirmedRosterId: savedLabel?.confirmedRosterId ?? reqFace.label?.rosterId ?? null,
                };
            });

            return mergedFaces;
        },
        [],
    );

    /**
     * Submit faces for identification (get suggestions and clusters)
     */
    const identifyFaces = useCallback(
        async (attachmentId: number, detections: RawDetection[]): Promise<void> => {
            setIsLoading(true);
            setError(null);
            attachmentIdRef.current = attachmentId;

            try {
                const requestFaces = rawDetectionsToRequest(detections);
                const request: IdentifyRequest = {
                    attachmentId,
                    faces: requestFaces,
                    imageCoordinateSystem: "pixels", // MediaPipe returns pixel coordinates
                };

                console.log("[DEBUG] identifyFaces - request:", JSON.stringify(request, null, 2));
                console.log("[DEBUG] identifyFaces - attachmentId type:", typeof request.attachmentId);

                const response = await apiIdentifyFaces(request, restNonce);

                if (response.error) {
                    throw new Error(response.error);
                }

                const mergedFaces = mergeResponse(
                    attachmentId,
                    requestFaces,
                    response.faces as unknown as DetectedFaceFE[],
                );
                setFaces(mergedFaces);
            } catch (err) {
                const error = err instanceof Error ? err : new Error("Failed to identify faces");
                setError(error);
                console.error("Identify faces error:", error);

                // Show error toast
                notifyError("Failed to identify faces. Please try again.", {
                    isDismissible: true,
                });

                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [restNonce, rawDetectionsToRequest, mergeResponse],
    );

    /**
     * Submit label for single face
     */
    const submitLabel = useCallback(
        async (faceId: string, label: Label): Promise<void> => {
            if (!attachmentIdRef.current) {
                throw new Error("No attachment ID set. Call identifyFaces first.");
            }

            const face = faces.find((f) => f.faceId === faceId);
            if (!face) {
                throw new Error(`Face not found: ${faceId}`);
            }

            setIsLoading(true);
            setError(null);

            // Optimistic update
            const previousFaces = [...faces];
            setFaces((prev) =>
                prev.map((f) =>
                    f.faceId === faceId ? { ...f, labelDraft: label, confirmedRosterId: label.rosterId ?? null } : f,
                ),
            );

            try {
                const request: IdentifyRequest = {
                    attachmentId: attachmentIdRef.current,
                    faces: [
                        {
                            bbox: face.bbox,
                            faceId,
                            label,
                        },
                    ],
                };

                const response = await apiSubmitLabel(request, restNonce);

                if (response.error) {
                    throw new Error(response.error);
                }

                // Update with server response (observation ID, sync status, rosterId)
                const responseFace = response.faces[0];
                const confirmedRosterId = responseFace?.rosterId ?? label.rosterId ?? null;
                
                setFaces((prev) => {
                    const updated = prev.map((f) =>
                        f.faceId === faceId
                            ? {
                                  ...f,
                                  labelDraft: label,
                                  confirmedRosterId,
                                  // Store observation ID if needed (could extend type)
                              }
                            : f,
                    );
                    
                    // Save to localStorage for client-side persistence
                    if (attachmentIdRef.current) {
                        saveFaceLabelsToStorage(attachmentIdRef.current, updated);
                    }
                    
                    return updated;
                });

                // Show success toast
                const personName = label.newName ?? "person";
                notifySuccess(`Face added to ${personName}'s profile`, {
                    isDismissible: true,
                });
            } catch (err) {
                // Revert optimistic update
                setFaces(previousFaces);

                const error = err instanceof Error ? err : new Error("Failed to submit label");
                setError(error);
                console.error("Submit label error:", error);

                // Show error toast
                notifyError("Failed to sync face. Please try again.", {
                    isDismissible: true,
                });

                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [faces, restNonce],
    );

    /**
     * Bulk confirm multiple faces with same roster ID
     */
    const bulkConfirm = useCallback(
        async (rosterId: string, faceIds: string[]): Promise<void> => {
            if (!attachmentIdRef.current) {
                throw new Error("No attachment ID set. Call identifyFaces first.");
            }

            const targetFaces = faces.filter((f) => faceIds.includes(f.faceId));
            if (targetFaces.length === 0) {
                throw new Error("No matching faces found for bulk confirm");
            }

            setIsLoading(true);
            setError(null);

            // Optimistic update
            const previousFaces = [...faces];
            setFaces((prev) =>
                prev.map((f) =>
                    faceIds.includes(f.faceId) ? { ...f, labelDraft: { rosterId }, confirmedRosterId: rosterId } : f,
                ),
            );

            try {
                const request: IdentifyRequest = {
                    attachmentId: attachmentIdRef.current,
                    faces: targetFaces.map((face) => ({
                        bbox: face.bbox,
                        faceId: face.faceId,
                        label: { rosterId },
                    })),
                };

                const response = await apiBulkConfirm(request, restNonce);

                if (response.error) {
                    throw new Error(response.error);
                }

                // Update with server response
                setFaces((prev) =>
                    prev.map((f) =>
                        faceIds.includes(f.faceId)
                            ? { ...f, labelDraft: { rosterId }, confirmedRosterId: rosterId }
                            : f,
                    ),
                );

                // Show success toast
                const count = faceIds.length;
                notifySuccess(`${count} face${count > 1 ? "s" : ""} confirmed`, {
                    isDismissible: true,
                });
            } catch (err) {
                // Revert optimistic update
                setFaces(previousFaces);

                const error = err instanceof Error ? err : new Error("Failed to bulk confirm");
                setError(error);
                console.error("Bulk confirm error:", error);

                // Show error toast
                notifyError("Failed to sync faces. Please try again.", {
                    isDismissible: true,
                });

                throw error;
            } finally {
                setIsLoading(false);
            }
        },
        [faces, restNonce],
    );

    /**
     * Reset hook state
     */
    const reset = useCallback(() => {
        setFaces([]);
        setIsLoading(false);
        setError(null);
        attachmentIdRef.current = null;
    }, []);

    return {
        faces,
        isLoading,
        error,
        identifyFaces,
        submitLabel,
        bulkConfirm,
        reset,
    };
};
