/**
 * ObservationPreview Component
 *
 * Displays observation image with bounding box highlight overlay.
 * Shows a placeholder if no image is available.
 */

import * as React from "react";
import { __, sprintf } from "@wordpress/i18n";
import type { RecognitionObservationRecord, RecognitionObservationAttachment } from "@/admin/types";

export interface ObservationPreviewProps {
    /** Observation record containing bounding box coordinates */
    record: RecognitionObservationRecord;
    /** Attachment with image URL and context */
    attachment: RecognitionObservationAttachment;
}

/**
 * ObservationPreview - Displays observation image with bounding box highlight
 *
 * Features:
 * - Loads image and tracks natural dimensions
 * - Overlays bounding box highlight based on coordinates
 * - Shows placeholder with initial letter if no image
 * - Maintains aspect ratio based on actual image dimensions
 */
export const ObservationPreview = ({ record, attachment }: ObservationPreviewProps): React.JSX.Element => {
    const [dimensions, setDimensions] = React.useState<{ width: number; height: number } | null>(null);

    const handleLoad = React.useCallback((event: React.SyntheticEvent<HTMLImageElement>) => {
        const target = event.currentTarget;
        setDimensions({
            width: target.naturalWidth,
            height: target.naturalHeight,
        });
    }, []);

    const highlightStyle = React.useMemo(() => {
        if (!dimensions || !record.boundingBox || record.boundingBox.length < 4) {
            return null;
        }

        const coords = record.boundingBox.slice(0, 4).map((value) => Number(value));
        if (coords.some((value) => !Number.isFinite(value))) {
            return null;
        }

        const [x1, y1, x2, y2] = coords as [number, number, number, number];
        const width = Math.max(0, x2 - x1);
        const height = Math.max(0, y2 - y1);

        if (!dimensions.width || !dimensions.height || width <= 0 || height <= 0) {
            return null;
        }

        return {
            left: `${(x1 / dimensions.width) * 100}%`,
            top: `${(y1 / dimensions.height) * 100}%`,
            width: `${(width / dimensions.width) * 100}%`,
            height: `${(height / dimensions.height) * 100}%`,
        };
    }, [dimensions, record.boundingBox]);

    const imageUrl = attachment.context?.imageUrl ?? null;
    const label = record.label || record.entityType || __("Observation", "context-alt-text");
    const altText = sprintf(
        /* translators: %s is the observation label. */
        __("%s preview", "context-alt-text"),
        label,
    );

    return (
        <div
            className="cat-roster__observations-thumb"
            style={
                dimensions
                    ? {
                          aspectRatio: `${dimensions.width} / ${dimensions.height}`,
                      }
                    : { aspectRatio: "1 / 1" }
            }
        >
            {imageUrl ? (
                <>
                    <img src={imageUrl} alt={altText} onLoad={handleLoad} />
                    {highlightStyle && <span className="cat-roster__observations-highlight" style={highlightStyle} />}
                </>
            ) : (
                <span className="cat-roster__observations-thumb-placeholder" aria-hidden="true">
                    {label.charAt(0).toUpperCase()}
                </span>
            )}
        </div>
    );
};
