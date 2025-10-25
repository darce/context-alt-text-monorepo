/**
 * People Overlay Component
 *
 * Displays detected faces with interactive label chips on an image.
 * Integrates with usePeopleSuggestions hook and PeoplePicker modal.
 *
 * Features:
 * - Reuses FaceDetectionDisplay positioning logic
 * - Interactive "Who is this?" chips on each face
 * - Shows suggestion names with confidence scores
 * - Keyboard navigation (Tab cycles faces, Enter opens picker)
 * - Accessibility (ARIA labels, screen reader support)
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React, { useRef, useEffect, useState } from "react";
import { __ } from "@wordpress/i18n";
import type { DetectedFaceFE } from "@/types/people-labeling";
import { FaceChip } from "./FaceChip";
import "./PeopleOverlay.scss";

export interface PeopleOverlayProps {
    /** Image URL to display */
    imageUrl: string;
    /** Alt text for the image */
    imageAlt: string;
    /** Detected faces with suggestions and labels */
    faces: DetectedFaceFE[];
    /** Currently selected face index (for highlighting) */
    selectedFaceIndex: number | null;
    /** Callback when face chip is clicked */
    onFaceClick: (index: number) => void;
    /** Callback when image loads (passes img element) */
    onImageLoad?: (image: HTMLImageElement) => void;
    /** Maximum display width */
    maxWidth?: number;
    /** Maximum display height */
    maxHeight?: number;
}

/**
 * People Overlay
 *
 * Displays an image with interactive chips for face labeling.
 * Each chip shows the current label status (unknown/suggested/confirmed).
 *
 * @example
 * ```tsx
 * <PeopleOverlay
 *   imageUrl="https://example.com/photo.jpg"
 *   imageAlt="Family photo"
 *   faces={detectedFaces}
 *   selectedFaceIndex={0}
 *   onFaceClick={(index) => setSelectedFace(index)}
 *   onImageLoad={(img) => detectFaces(img)}
 * />
 * ```
 */
export const PeopleOverlay = ({
    imageUrl,
    imageAlt,
    faces,
    selectedFaceIndex,
    onFaceClick,
    onImageLoad,
    maxWidth = 1200,
    maxHeight = 800,
}: PeopleOverlayProps): JSX.Element => {
    const containerRef = useRef<HTMLDivElement>(null);
    const imageRef = useRef<HTMLImageElement>(null);
    const [imageLoaded, setImageLoaded] = useState(false);
    const [imageDimensions, setImageDimensions] = useState({
        width: 0,
        height: 0,
    });
    const hasCalledOnImageLoad = useRef(false);

    /**
     * Handle image load
     */
    useEffect(() => {
        // Reset when image URL changes
        hasCalledOnImageLoad.current = false;
        setImageLoaded(false);
    }, [imageUrl]);

    useEffect(() => {
        const img = imageRef.current;
        if (img === null) {
            return;
        }

        const handleLoad = (): void => {
            // Calculate displayed dimensions (respecting max constraints)
            let width = img.naturalWidth;
            let height = img.naturalHeight;
            const aspectRatio = width / height;

            if (width > maxWidth) {
                width = maxWidth;
                height = width / aspectRatio;
            }

            if (height > maxHeight) {
                height = maxHeight;
                width = height * aspectRatio;
            }

            setImageDimensions({ width, height });
            setImageLoaded(true);

            // Pass image element to parent (only once!)
            if (onImageLoad !== undefined && !hasCalledOnImageLoad.current) {
                hasCalledOnImageLoad.current = true;
                onImageLoad(img);
            }
        };

        if (img.complete) {
            handleLoad();
        } else {
            img.addEventListener("load", handleLoad);
            return () => {
                img.removeEventListener("load", handleLoad);
            };
        }
    }, [imageUrl, maxWidth, maxHeight, onImageLoad]);

    /**
     * Get chip label and variant for a face
     */
    const getChipProps = (face: DetectedFaceFE): { label: string; variant: "unknown" | "suggested" | "confirmed" } => {
        // Confirmed label (user has labeled this face)
        if (face.confirmedRosterId || face.labelDraft) {
            console.log("[getChipProps] Confirmed face:", {
                confirmedRosterId: face.confirmedRosterId,
                labelDraft: face.labelDraft,
                suggestions: face.suggestions,
            });

            const labelText =
                face.labelDraft?.newName ??
                face.labelDraft?.displayName ??
                face.suggestions.find((s) => s.rosterId === face.confirmedRosterId)?.display ??
                __("Labeled", "context-alt-text");

            console.log("[getChipProps] Resolved labelText:", labelText);
            return { label: labelText, variant: "confirmed" };
        }

        // Suggested label (FAISS match above threshold)
        if (face.suggestions.length > 0) {
            const topSuggestion = face.suggestions[0];
            if (topSuggestion) {
                return { label: `${topSuggestion.display}?`, variant: "suggested" };
            }
        }

        // Unknown (no label or suggestion)
        return { label: __("Who is this?", "context-alt-text"), variant: "unknown" };
    };

    /**
     * Calculate chip position (centered below face bounding box)
     */
    const getChipPosition = (face: DetectedFaceFE): { top: number; left: number } => {
        const { x, y, height, width } = face.bbox;

        // Detect if coordinates are normalized (0-1) or pixels (>1)
        // MediaPipe returns pixels, backend might return normalized
        const isNormalized = x <= 1 && y <= 1 && width <= 1 && height <= 1;

        // Convert to pixels if needed
        const boxLeft = isNormalized ? x * imageDimensions.width : x;
        const boxTop = isNormalized ? y * imageDimensions.height : y;
        const boxWidth = isNormalized ? width * imageDimensions.width : width;
        const boxHeight = isNormalized ? height * imageDimensions.height : height;

        // Center horizontally, position below box
        const chipLeft = boxLeft + boxWidth / 2;
        const chipTop = boxTop + boxHeight + 8; // 8px gap below box

        return { top: chipTop, left: chipLeft };
    };

    return (
        <div className="cat-people-overlay" ref={containerRef}>
            {!imageLoaded && (
                <div className="cat-people-overlay__loading" role="status">
                    <span className="cat-spinner" aria-hidden="true" />
                    <span className="screen-reader-text">{__("Loading image...", "context-alt-text")}</span>
                </div>
            )}

            <div
                className="cat-people-overlay__container"
                style={{
                    width: imageDimensions.width || "auto",
                    height: imageDimensions.height || "auto",
                    display: imageLoaded ? "block" : "none",
                }}
            >
                {/* The actual image */}
                <img
                    ref={imageRef}
                    src={imageUrl}
                    alt={imageAlt}
                    className="cat-people-overlay__image"
                    crossOrigin="anonymous"
                    style={{
                        maxWidth: `${maxWidth}px`,
                        maxHeight: `${maxHeight}px`,
                    }}
                />

                {/* Bounding boxes (visual indicators) */}
                {faces.map((face, index) => {
                    const isSelected = index === selectedFaceIndex;
                    const { x, y, width, height } = face.bbox;

                    // Detect if coordinates are normalized (0-1) or pixels (>1)
                    const isNormalized = x <= 1 && y <= 1 && width <= 1 && height <= 1;

                    // Convert to pixels if needed
                    const boxLeft = isNormalized ? x * imageDimensions.width : x;
                    const boxTop = isNormalized ? y * imageDimensions.height : y;
                    const boxWidth = isNormalized ? width * imageDimensions.width : width;
                    const boxHeight = isNormalized ? height * imageDimensions.height : height;

                    return (
                        <div
                            key={face.faceId}
                            className={`cat-people-overlay__box ${
                                isSelected ? "cat-people-overlay__box--selected" : ""
                            }`}
                            style={{
                                left: `${boxLeft}px`,
                                top: `${boxTop}px`,
                                width: `${boxWidth}px`,
                                height: `${boxHeight}px`,
                            }}
                            aria-hidden="true"
                        />
                    );
                })}

                {/* Interactive chips */}
                {faces.map((face, index) => {
                    const { label, variant } = getChipProps(face);
                    const position = getChipPosition(face);
                    const isSelected = index === selectedFaceIndex;
                    const topSuggestion = face.suggestions[0];

                    return (
                        <FaceChip
                            key={face.faceId}
                            label={label}
                            variant={variant}
                            isSelected={isSelected}
                            onClick={() => onFaceClick(index)}
                            position={position}
                            confidence={topSuggestion?.score}
                        />
                    );
                })}
            </div>

            {imageLoaded && faces.length > 0 && (
                <div className="cat-people-overlay__help" role="region" aria-live="polite">
                    {`${faces.length} ${faces.length === 1 ? __("face", "context-alt-text") : __("faces", "context-alt-text")} ${__("detected", "context-alt-text")}`}
                    {" • "}
                    {__("Click or Tab to select, Enter to label", "context-alt-text")}
                </div>
            )}
        </div>
    );
};
