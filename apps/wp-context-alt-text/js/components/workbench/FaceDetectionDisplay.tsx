/**
 * Face Detection Display Component
 *
 * Displays an image with CSS-based bounding box overlays for detected faces.
 *
 * Architecture (per MediaPipe docs):
 * 1. HTMLImageElement: Source for MediaPipe FaceDetector.detect() (in parent)
 * 2. CSS positioned divs: Visual bounding boxes (this component)
 * 3. Separation: Detection logic lives in parent, display logic here
 *
 * NO CANVAS NEEDED - Just use CSS borders on positioned divs!
 *
 * Accessibility:
 * - Semantic HTML (img + div overlays)
 * - Keyboard navigation for selecting faces
 * - ARIA labels for screen readers
 *
 * @package ContextAltText
 * @since 1.0.0
 */

import React, { useRef, useEffect, useState } from "react";
import { __ } from "@wordpress/i18n";
import type { FaceDetection } from "../../utils/mediaPipeLoader";
import "./FaceDetectionDisplay.scss";

export interface FaceDetectionDisplayProps {
    /** Image URL to display */
    imageUrl: string;
    /** Alt text for the image */
    imageAlt: string;
    /** Detected faces with bounding boxes (from MediaPipe FaceDetector) */
    detections: FaceDetection[];
    /** Currently selected face index (for highlighting) */
    selectedIndex: number | null;
    /** Callback when face is clicked */
    onFaceClick?: (index: number) => void;
    /** Callback when image loads (passes img element for MediaPipe detection) */
    onImageLoad?: (image: HTMLImageElement) => void;
    /** Whether to show confidence scores */
    showConfidence?: boolean;
    /** Maximum display width (image will be scaled to fit) */
    maxWidth?: number;
    /** Maximum display height (image will be scaled to fit) */
    maxHeight?: number;
}

/**
 * Face Detection Display
 *
 * Displays an image with CSS-based bounding boxes overlaid on detected faces.
 * Parent component handles MediaPipe detection, this component only displays results.
 *
 * @example
 * ```tsx
 * <FaceDetectionDisplay
 *   imageUrl="https://example.com/photo.jpg"
 *   imageAlt="Family photo"
 *   detections={[
 *     { boundingBox: { originX: 0.2, originY: 0.3, width: 0.15, height: 0.2 }, confidence: 0.95 }
 *   ]}
 *   selectedIndex={0}
 *   onImageLoad={(img) => runDetection(img)}
 *   onFaceClick={(index) => console.log(`Face ${index} clicked`)}
 *   showConfidence={true}
 * />
 * ```
 */
export const FaceDetectionDisplay = ({
    imageUrl,
    imageAlt,
    detections,
    selectedIndex,
    onFaceClick,
    onImageLoad,
    showConfidence = false,
    maxWidth = 1200,
    maxHeight = 800,
}: FaceDetectionDisplayProps): JSX.Element => {
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

            // Pass image element to parent for MediaPipe detection (only once!)
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
     * Handle face click
     */
    const handleFaceClick = (index: number): void => {
        if (onFaceClick !== undefined) {
            onFaceClick(index);
        }
    };

    /**
     * Handle keyboard navigation
     */
    const handleFaceKeyDown = (event: React.KeyboardEvent, index: number): void => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            handleFaceClick(index);
        }
    };

    return (
        <div className="cat-face-detection" ref={containerRef}>
            {!imageLoaded && (
                <div className="cat-face-detection__loading" role="status">
                    <span className="cat-spinner" aria-hidden="true" />
                    <span className="screen-reader-text">{__("Loading image...", "context-alt-text")}</span>
                </div>
            )}

            <div
                className="cat-face-detection__container"
                style={{
                    width: imageDimensions.width || "auto",
                    height: imageDimensions.height || "auto",
                    display: imageLoaded ? "block" : "none",
                }}
            >
                {/* The actual image - MediaPipe detects on this element */}
                <img
                    ref={imageRef}
                    src={imageUrl}
                    alt={imageAlt}
                    className="cat-face-detection__image"
                    crossOrigin="anonymous"
                    style={{
                        maxWidth: `${maxWidth}px`,
                        maxHeight: `${maxHeight}px`,
                    }}
                />

                {detections.map((detection, index) => {
                    const isSelected = index === selectedIndex;
                    const { originX, originY, width, height } = detection.boundingBox;

                    // Coordinates are already absolute pixels from MediaPipe
                    // Just use them directly, no multiplication needed
                    const leftPixel = originX;
                    const topPixel = originY;
                    const widthPixel = width;
                    const heightPixel = height;

                    return (
                        <div
                            key={index}
                            className={`cat-face-detection__box ${
                                isSelected ? "cat-face-detection__box--selected" : ""
                            }`}
                            style={{
                                left: `${leftPixel}px`,
                                top: `${topPixel}px`,
                                width: `${widthPixel}px`,
                                height: `${heightPixel}px`,
                            }}
                            onClick={() => handleFaceClick(index)}
                            onKeyDown={(e) => handleFaceKeyDown(e, index)}
                            role="button"
                            tabIndex={0}
                            aria-label={`${__("Face", "context-alt-text")} ${index + 1}${
                                showConfidence ? ` (${Math.round(detection.confidence * 100)}%)` : ""
                            }`}
                        >
                            {showConfidence && (
                                <span className="cat-face-detection__confidence">
                                    {Math.round(detection.confidence * 100)}%
                                </span>
                            )}
                        </div>
                    );
                })}
            </div>

            {imageLoaded && detections.length > 0 && (
                <div className="cat-face-detection__help">
                    {__("Click or press Enter on a face to select it", "context-alt-text")}
                </div>
            )}
        </div>
    );
};
