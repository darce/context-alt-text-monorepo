/**
 * usePeopleSuggestions Hook
 *
 * Coordinates frontend state with the recognition service:
 * - Hydrates faces returned by recognition jobs or identify requests
 * - Submits single/bulk labels back to the WordPress endpoint
 * - Persists draft labels locally when the service is unavailable
 * - Provides optimistic updates for a responsive UX
 */

import { useState, useCallback, useRef } from "react";
import type {
    DetectedFaceFE,
    Label,
    IdentifyRequest,
    DetectedFaceRequest,
    DetectedFaceResponse,
    UsePeopleSuggestionsReturn,
} from "@/types/people-labeling";
import {
    identifyFaces as apiIdentifyFaces,
    submitLabel as apiSubmitLabel,
    bulkConfirm as apiBulkConfirm,
} from "@/api/recognitionApi";
import { notifySuccess, notifyError } from "@/admin/notices";

export interface StoredFaceLabel {
    bbox: { x: number; y: number; width: number; height: number };
    confirmedRosterId: string | null;
    labelDraft: Label | null;
}

const STORAGE_KEY_PREFIX = "cat_face_labels_";

const generateFaceId = (() => {
    let counter = 0;
    return () => `face-${Date.now()}-${counter++}`;
})();

const saveFaceLabelsToStorage = (attachmentId: number, faces: DetectedFaceFE[]): void => {
    try {
        const key = `${STORAGE_KEY_PREFIX}${attachmentId}`;
        const labelsToStore = faces
            .filter((face) => face.confirmedRosterId != null || face.labelDraft != null)
            .map(
                (face): StoredFaceLabel => ({
                    bbox: face.bbox,
                    confirmedRosterId: face.confirmedRosterId ?? null,
                    labelDraft: face.labelDraft ?? null,
                }),
            );

        if (labelsToStore.length > 0) {
            localStorage.setItem(key, JSON.stringify(labelsToStore));
        } else {
            localStorage.removeItem(key);
        }
    } catch (err) {
        console.warn("Failed to save face labels to localStorage:", err);
    }
};

const loadFaceLabelsFromStorage = (attachmentId: number): StoredFaceLabel[] => {
    try {
        const stored = localStorage.getItem(`${STORAGE_KEY_PREFIX}${attachmentId}`);
        if (!stored) {
            return [];
        }

        const parsed: unknown = JSON.parse(stored);
        if (!Array.isArray(parsed)) {
            return [];
        }

        return parsed
            .map((entry) => {
                if (!entry || typeof entry !== "object") {
                    return null;
                }

                const bboxCandidate = (entry as { bbox?: unknown }).bbox;
                if (!bboxCandidate || typeof bboxCandidate !== "object") {
                    return null;
                }

                const { x, y, width, height } = bboxCandidate as Record<string, unknown>;
                if (
                    typeof x !== "number" ||
                    typeof y !== "number" ||
                    typeof width !== "number" ||
                    typeof height !== "number"
                ) {
                    return null;
                }

                const confirmedCandidate = (entry as { confirmedRosterId?: unknown }).confirmedRosterId;
                const confirmedRosterId =
                    typeof confirmedCandidate === "string" && confirmedCandidate.trim() !== ""
                        ? confirmedCandidate
                        : null;

                const labelCandidate = (entry as { labelDraft?: unknown }).labelDraft;
                const labelDraft =
                    labelCandidate && typeof labelCandidate === "object" ? (labelCandidate as Label) : null;

                return {
                    bbox: { x, y, width, height },
                    confirmedRosterId,
                    labelDraft,
                } as StoredFaceLabel;
            })
            .filter((entry): entry is StoredFaceLabel => entry !== null);
    } catch (err) {
        console.warn("Failed to load face labels from localStorage:", err);
        return [];
    }
};

const areBoundingBoxesClose = (
    a: { x: number; y: number; width: number; height: number },
    b: { x: number; y: number; width: number; height: number },
): boolean => {
    const threshold = 5;
    return (
        Math.abs(a.x - b.x) < threshold &&
        Math.abs(a.y - b.y) < threshold &&
        Math.abs(a.width - b.width) < threshold &&
        Math.abs(a.height - b.height) < threshold
    );
};

const ensureFaceIds = (faces: DetectedFaceRequest[]): DetectedFaceRequest[] =>
    faces.map((face) => ({
        ...face,
        faceId: face.faceId ?? generateFaceId(),
    }));

const snapshotResponses = (faces: DetectedFaceFE[]): DetectedFaceResponse[] =>
    faces.map((face) => ({
        faceId: face.faceId,
        clusterId: face.clusterId ?? undefined,
        suggestions: face.suggestions,
        observationId: face.observationId ?? undefined,
        rosterId: face.confirmedRosterId ?? undefined,
    }));

const topSuggestionScore = (suggestions: DetectedFaceResponse["suggestions"]): number => suggestions?.[0]?.score ?? 0;

export const usePeopleSuggestions = (restNonce?: string): UsePeopleSuggestionsReturn => {
    const [faces, setFaces] = useState<DetectedFaceFE[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<Error | null>(null);
    const attachmentIdRef = useRef<number | null>(null);

    const mergeResponse = useCallback(
        (
            attachmentId: number,
            requestFaces: DetectedFaceRequest[],
            responseFaces: DetectedFaceResponse[],
        ): DetectedFaceFE[] => {
            const storedLabels = loadFaceLabelsFromStorage(attachmentId);
            const responseMap = new Map(responseFaces.map((face) => [face.faceId, face]));

            return requestFaces.map((requestFace, index) => {
                const faceId = requestFace.faceId ?? generateFaceId();
                const responseFace = responseMap.get(faceId);
                const storedMatch =
                    storedLabels.find((entry) => areBoundingBoxesClose(entry.bbox, requestFace.bbox)) ?? null;

                const responseRosterId =
                    typeof responseFace?.rosterId === "string" && responseFace.rosterId.trim() !== ""
                        ? responseFace.rosterId
                        : null;

                const confirmedRosterId =
                    storedMatch?.confirmedRosterId ?? responseRosterId ?? requestFace.label?.rosterId ?? null;

                const fallbackLabel: Label | null = confirmedRosterId
                    ? {
                          rosterId: confirmedRosterId,
                          ...(typeof requestFace.label?.displayName === "string"
                              ? { displayName: requestFace.label.displayName }
                              : {}),
                      }
                    : null;

                const labelDraft: Label | null = storedMatch?.labelDraft ?? requestFace.label ?? fallbackLabel;

                return {
                    faceId,
                    bbox: requestFace.bbox,
                    attachmentId,
                    confidence: topSuggestionScore(responseFace?.suggestions ?? []),
                    clusterId: responseFace?.clusterId ?? `unknown-${attachmentId}-${index}`,
                    suggestions: responseFace?.suggestions ?? [],
                    labelDraft,
                    confirmedRosterId,
                    observationId: responseFace?.observationId ?? requestFace.observationId ?? null,
                } as DetectedFaceFE;
            });
        },
        [],
    );

    const identifyFaces = useCallback(
        async (attachmentId: number, facesInput: DetectedFaceRequest[]): Promise<void> => {
            setIsLoading(true);
            setError(null);
            attachmentIdRef.current = attachmentId;

            try {
                const requestFaces = ensureFaceIds(facesInput);
                const request: IdentifyRequest = {
                    attachmentId,
                    faces: requestFaces,
                    imageCoordinateSystem: "pixels",
                };

                const response = await apiIdentifyFaces(request, restNonce);
                if (response.error) {
                    throw new Error(response.error);
                }

                const mergedFaces = mergeResponse(attachmentId, requestFaces, response.faces ?? []);

                setFaces(mergedFaces);
                saveFaceLabelsToStorage(attachmentId, mergedFaces);
            } catch (err) {
                const failure = err instanceof Error ? err : new Error("Failed to identify faces");
                setError(failure);
                notifyError("Failed to identify faces. Please try again.", { isDismissible: true });
                throw failure;
            } finally {
                setIsLoading(false);
            }
        },
        [mergeResponse, restNonce],
    );

    const hydrateFaces = useCallback(
        (attachmentId: number, incomingFaces: DetectedFaceFE[]): void => {
            attachmentIdRef.current = attachmentId;

            const requestFaces = ensureFaceIds(
                incomingFaces.map(
                    (face): DetectedFaceRequest => ({
                        bbox: face.bbox,
                        faceId: face.faceId,
                        observationId: face.observationId ?? undefined,
                        label: face.labelDraft ?? undefined,
                    }),
                ),
            );

            const responseFaces = snapshotResponses(incomingFaces);
            const mergedFaces = mergeResponse(attachmentId, requestFaces, responseFaces);

            setFaces(mergedFaces);
            setIsLoading(false);
            setError(null);
            saveFaceLabelsToStorage(attachmentId, mergedFaces);
        },
        [mergeResponse],
    );

    const submitLabel = useCallback(
        async (faceId: string, label: Label): Promise<void> => {
            if (!attachmentIdRef.current) {
                throw new Error("No attachment ID set. Call identifyFaces first.");
            }

            const previousFaces = faces;
            const optimisticFaces = faces.map((face) =>
                face.faceId === faceId
                    ? {
                          ...face,
                          labelDraft: label,
                          confirmedRosterId: label.rosterId ?? face.confirmedRosterId,
                      }
                    : face,
            );

            if (optimisticFaces === faces) {
                throw new Error(`Face not found: ${faceId}`);
            }

            setFaces(optimisticFaces);
            setIsLoading(true);
            setError(null);

            try {
                const targetFace = previousFaces.find((face) => face.faceId === faceId);
                if (!targetFace) {
                    throw new Error(`Face not found: ${faceId}`);
                }

                const request: IdentifyRequest = {
                    attachmentId: attachmentIdRef.current,
                    faces: [
                        {
                            bbox: targetFace.bbox,
                            faceId,
                            label,
                            observationId: targetFace.observationId ?? undefined,
                        },
                    ],
                };

                const response = await apiSubmitLabel(request, restNonce);
                if (response.error) {
                    throw new Error(response.error);
                }

                const responseFace = response.faces?.find((face) => face.faceId === faceId);
                const finalFaces = optimisticFaces.map((face) => {
                    if (face.faceId !== faceId) {
                        return face;
                    }

                    const confirmedRosterId =
                        responseFace?.rosterId ?? label.rosterId ?? face.confirmedRosterId ?? null;

                    return {
                        ...face,
                        labelDraft: label,
                        confirmedRosterId,
                        observationId: responseFace?.observationId ?? face.observationId ?? null,
                        clusterId: responseFace?.clusterId ?? face.clusterId,
                    } as DetectedFaceFE;
                });

                setFaces(finalFaces);
                saveFaceLabelsToStorage(attachmentIdRef.current, finalFaces);

                const personName = label.newName ?? label.displayName ?? "person";
                notifySuccess(`Face added to ${personName}'s profile`, { isDismissible: true });
            } catch (err) {
                setFaces(previousFaces);
                const failure = err instanceof Error ? err : new Error("Failed to submit label");
                setError(failure);
                notifyError("Failed to sync face. Please try again.", { isDismissible: true });
                throw failure;
            } finally {
                setIsLoading(false);
            }
        },
        [faces, restNonce],
    );

    const bulkConfirm = useCallback(
        async (rosterId: string, faceIds: string[]): Promise<void> => {
            if (!attachmentIdRef.current) {
                throw new Error("No attachment ID set. Call identifyFaces first.");
            }

            const previousFaces = faces;
            const optimisticFaces = faces.map((face) =>
                faceIds.includes(face.faceId)
                    ? {
                          ...face,
                          labelDraft: { rosterId },
                          confirmedRosterId: rosterId,
                      }
                    : face,
            );

            setFaces(optimisticFaces);
            setIsLoading(true);
            setError(null);

            try {
                const requestFaces = optimisticFaces
                    .filter((face) => faceIds.includes(face.faceId))
                    .map(
                        (face): DetectedFaceRequest => ({
                            bbox: face.bbox,
                            faceId: face.faceId,
                            label: { rosterId },
                            observationId: face.observationId ?? undefined,
                        }),
                    );

                const request: IdentifyRequest = {
                    attachmentId: attachmentIdRef.current,
                    faces: requestFaces,
                };

                const response = await apiBulkConfirm(request, restNonce);
                if (response.error) {
                    throw new Error(response.error);
                }

                const responseMap = new Map((response.faces ?? []).map((face) => [face.faceId, face]));

                const finalFaces = optimisticFaces.map((face) => {
                    if (!faceIds.includes(face.faceId)) {
                        return face;
                    }

                    const responseFace = responseMap.get(face.faceId);
                    return {
                        ...face,
                        observationId: responseFace?.observationId ?? face.observationId ?? null,
                        clusterId: responseFace?.clusterId ?? face.clusterId,
                    } as DetectedFaceFE;
                });

                setFaces(finalFaces);
                saveFaceLabelsToStorage(attachmentIdRef.current, finalFaces);

                const count = faceIds.length;
                notifySuccess(`${count} face${count === 1 ? "" : "s"} confirmed`, { isDismissible: true });
            } catch (err) {
                setFaces(previousFaces);
                const failure = err instanceof Error ? err : new Error("Failed to bulk confirm");
                setError(failure);
                notifyError("Failed to sync faces. Please try again.", { isDismissible: true });
                throw failure;
            } finally {
                setIsLoading(false);
            }
        },
        [faces, restNonce],
    );

    const reset = useCallback(() => {
        if (attachmentIdRef.current != null) {
            saveFaceLabelsToStorage(attachmentIdRef.current, []);
        }
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
        hydrateFaces,
        submitLabel,
        bulkConfirm,
        reset,
    };
};
