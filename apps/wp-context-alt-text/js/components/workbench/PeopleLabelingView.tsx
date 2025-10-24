/**
 * People Labeling View
 *
 * Single-image view for labeling faces with PeopleOverlay and PeopleDrawer.
 * Integrates useFaceDetection and usePeopleSuggestions hooks.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React, { useState, useEffect, useCallback } from "react";
import { __ } from "@wordpress/i18n";
import { useFaceDetection } from "@/hooks/useFaceDetection";
import { usePeopleSuggestions } from "@/hooks/usePeopleSuggestions";
import { PeopleOverlay } from "./PeopleOverlay";
import { PeopleDrawer } from "./PeopleDrawer";
import { PeoplePicker } from "./PeoplePicker";
import type { WorkbenchMediaItem } from "@/admin/types";
import type { DetectedFaceFE } from "@/types/people-labeling";
import "./PeopleLabelingView.scss";

export interface PeopleLabelingViewProps {
    /** Media item to label */
    item: WorkbenchMediaItem;
    /** WordPress REST nonce */
    restNonce?: string;
    /** Callback when user closes the view */
    onClose: () => void;
}

/**
 * People Labeling View
 *
 * Full-screen single-image labeling interface.
 * Detects faces, shows suggestions, allows labeling.
 *
 * @example
 * ```tsx
 * <PeopleLabelingView
 *   item={selectedMediaItem}
 *   restNonce={window.catAltText?.restNonce}
 *   onClose={() => setShowLabeling(false)}
 * />
 * ```
 */
export const PeopleLabelingView = ({ item, restNonce, onClose }: PeopleLabelingViewProps): JSX.Element => {
    const [selectedFaceIndex, setSelectedFaceIndex] = useState<number | null>(null);
    const [showPicker, setShowPicker] = useState(false);
    const [pickerPosition, setPickerPosition] = useState<{ top: number; left: number } | undefined>();

    const faceDetection = useFaceDetection({ autoLoad: true });
    const peopleSuggestions = usePeopleSuggestions(restNonce);

    /**
     * Run face detection when image loads
     */
    const handleImageLoad = useCallback(
        async (image: HTMLImageElement): Promise<void> => {
            if (faceDetection.state === "idle" || faceDetection.state === "success") {
                try {
                    const detections = await faceDetection.detect(image);

                    // Convert MediaPipe detections to RawDetection format
                    const rawDetections = detections.map((detection) => ({
                        boundingBox: {
                            x: detection.boundingBox.originX,
                            y: detection.boundingBox.originY,
                            width: detection.boundingBox.width,
                            height: detection.boundingBox.height,
                        },
                        confidence: detection.confidence,
                        keypoints: detection.keypoints?.map((kp) => ({
                            x: kp.x,
                            y: kp.y,
                        })),
                    }));

                    // Convert attachment ID and identify faces
                    console.log("[DEBUG] item.id:", item.id, "typeof:", typeof item.id);
                    const attachmentId = parseInt(item.id, 10);
                    console.log(
                        "[DEBUG] attachmentId:",
                        attachmentId,
                        "typeof:",
                        typeof attachmentId,
                        "isNaN:",
                        isNaN(attachmentId),
                    );

                    if (!isNaN(attachmentId)) {
                        console.log("[DEBUG] Calling identifyFaces with attachmentId:", attachmentId);
                        await peopleSuggestions.identifyFaces(attachmentId, rawDetections);
                    } else {
                        console.error("[ERROR] Invalid attachmentId - item.id was:", item.id);
                    }
                } catch (error) {
                    console.error("Face detection failed:", error);
                }
            }
        },
        [faceDetection, peopleSuggestions, item.id],
    );

    /**
     * Handle face chip click - open picker
     */
    const handleFaceClick = useCallback((index: number): void => {
        setSelectedFaceIndex(index);
        setShowPicker(true);
        // TODO: Calculate picker position based on chip location
        setPickerPosition(undefined); // Center modal for now
    }, []);

    /**
     * Handle picker selection - submit label
     */
    const handlePickerSelect = useCallback(
        async (rosterId: string): Promise<void> => {
            if (selectedFaceIndex === null) {
                return;
            }

            const face = peopleSuggestions.faces[selectedFaceIndex];
            if (!face) {
                return;
            }

            await peopleSuggestions.submitLabel(face.faceId, { rosterId });
            setShowPicker(false);
            setSelectedFaceIndex(null);
        },
        [selectedFaceIndex, peopleSuggestions],
    );

    /**
     * Handle picker create new - submit with new name
     */
    const handlePickerCreateNew = useCallback(
        async (displayName: string): Promise<void> => {
            if (selectedFaceIndex === null) {
                return;
            }

            const face = peopleSuggestions.faces[selectedFaceIndex];
            if (!face) {
                return;
            }

            await peopleSuggestions.submitLabel(face.faceId, { newName: displayName });
            setShowPicker(false);
            setSelectedFaceIndex(null);
        },
        [selectedFaceIndex, peopleSuggestions],
    );

    /**
     * Handle cluster click - highlight faces in overlay
     */
    const handleClusterClick = useCallback(
        (clusterId: string): void => {
            // Find first face with this cluster ID
            const faceIndex = peopleSuggestions.faces.findIndex((f) => f.clusterId === clusterId);
            if (faceIndex >= 0) {
                setSelectedFaceIndex(faceIndex);
            }
        },
        [peopleSuggestions.faces],
    );

    /**
     * Handle suggestion stack click - highlight faces in overlay
     */
    const handleSuggestionClick = useCallback(
        (rosterId: string): void => {
            // Find first face with this suggestion
            const faceIndex = peopleSuggestions.faces.findIndex(
                (f) => f.suggestions.length > 0 && f.suggestions[0]?.rosterId === rosterId,
            );
            if (faceIndex >= 0) {
                setSelectedFaceIndex(faceIndex);
            }
        },
        [peopleSuggestions.faces],
    );

    /**
     * Handle review cluster - show all faces in cluster (TODO: future enhancement)
     */
    const handleReviewCluster = useCallback((clusterId: string): void => {
        console.log("Review cluster:", clusterId);
        // TODO: Implement cluster review UI
    }, []);

    /**
     * Handle bulk confirm - submit multiple labels
     */
    const handleConfirmAll = useCallback(
        async (rosterId: string, faceIds: string[]): Promise<void> => {
            await peopleSuggestions.bulkConfirm(rosterId, faceIds);
        },
        [peopleSuggestions],
    );

    /**
     * Get selected cluster/suggestion ID for drawer highlighting
     */
    const getSelectedId = (): string | null => {
        if (selectedFaceIndex === null) {
            return null;
        }

        const face = peopleSuggestions.faces[selectedFaceIndex];
        if (!face) {
            return null;
        }

        // Prioritize cluster ID
        if (face.clusterId) {
            return face.clusterId;
        }

        // Fall back to top suggestion roster ID
        if (face.suggestions.length > 0) {
            return face.suggestions[0]?.rosterId ?? null;
        }

        return null;
    };

    /**
     * Get current roster ID for picker (when correcting label)
     */
    const getCurrentRosterId = (): string | undefined => {
        if (selectedFaceIndex === null) {
            return undefined;
        }

        const face = peopleSuggestions.faces[selectedFaceIndex];
        return face?.confirmedRosterId ?? undefined;
    };

    return (
        <div className="cat-people-labeling-view">
            <div className="cat-people-labeling-view__header">
                <h2 className="cat-people-labeling-view__title">{__("Label People", "context-alt-text")}</h2>
                <button
                    type="button"
                    className="cat-people-labeling-view__close"
                    onClick={onClose}
                    aria-label={__("Close labeling view", "context-alt-text")}
                >
                    ×
                </button>
            </div>

            <div className="cat-people-labeling-view__content">
                <div className="cat-people-labeling-view__main">
                    {faceDetection.state === "loading" && (
                        <div className="cat-people-labeling-view__loading">
                            <span className="cat-people-labeling-view__spinner" />
                            <p>{__("Loading face detector...", "context-alt-text")}</p>
                        </div>
                    )}

                    {faceDetection.state === "error" && (
                        <div className="cat-people-labeling-view__error">
                            <p>
                                {__("Face detection failed:", "context-alt-text")} {faceDetection.error}
                            </p>
                            <button type="button" onClick={() => faceDetection.reset()} className="cat-button">
                                {__("Try Again", "context-alt-text")}
                            </button>
                        </div>
                    )}

                    {faceDetection.isReady && (
                        <PeopleOverlay
                            imageUrl={item.thumbnailUrl || ""}
                            imageAlt={item.altText || item.title}
                            faces={peopleSuggestions.faces}
                            selectedFaceIndex={selectedFaceIndex}
                            onFaceClick={handleFaceClick}
                            onImageLoad={handleImageLoad}
                        />
                    )}
                </div>

                <PeopleDrawer
                    faces={peopleSuggestions.faces}
                    selectedId={getSelectedId()}
                    onClusterClick={handleClusterClick}
                    onSuggestionClick={handleSuggestionClick}
                    onReviewCluster={handleReviewCluster}
                    onConfirmAll={handleConfirmAll}
                />
            </div>

            <PeoplePicker
                isOpen={showPicker}
                onClose={() => setShowPicker(false)}
                onSelect={handlePickerSelect}
                onCreateNew={handlePickerCreateNew}
                currentRosterId={getCurrentRosterId()}
                restNonce={restNonce}
                position={pickerPosition}
            />
        </div>
    );
};
