import React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";

import type { ClusterSummary } from "@/types/face-clustering";
import { getFaceDragData, hasFaceDragData } from "@/components/workbench/dragTypes";
import "./ClusterCard.scss";

export interface ClusterCardProps {
    cluster: ClusterSummary;
    onClick?: (clusterId: string) => void;
    isSelected?: boolean;
    onDropFaces?: (clusterId: string, payload: { clusterId: string; faceIds: string[] }) => void;
    onDragEnter?: (clusterId: string) => void;
    onDragLeave?: (clusterId: string) => void;
    isDropTarget?: boolean;
}

const getConfidenceLabel = (confidence: number | null | undefined): string | null => {
    if (confidence === null || confidence === undefined || Number.isNaN(confidence)) {
        return null;
    }

    if (confidence >= 0.85) {
        return __("High confidence", "context-alt-text");
    }

    if (confidence >= 0.6) {
        return __("Medium confidence", "context-alt-text");
    }

    return __("Low confidence", "context-alt-text");
};

export const ClusterCard = ({
    cluster,
    onClick,
    isSelected = false,
    onDropFaces,
    onDragEnter,
    onDragLeave,
    isDropTarget = false,
}: ClusterCardProps): React.JSX.Element => {
    const faceCountLabel = sprintf(
        _n("%d face", "%d faces", cluster.faceCount, "context-alt-text"),
        cluster.faceCount,
    );

    const ariaLabel = sprintf(
        /* translators: 1: cluster id, 2: face count label */
        __("Review cluster %1$s (%2$s)", "context-alt-text"),
        cluster.id,
        faceCountLabel,
    );

    const suggestion = cluster.suggestion ?? null;
    const confidenceLabel = getConfidenceLabel(suggestion?.confidence ?? null);
    const selected = Boolean(isSelected);
    const classes = ["cat-cluster-card"];

    if (selected) {
        classes.push("cat-cluster-card--selected");
    }

    if (isDropTarget) {
        classes.push("cat-cluster-card--drop-target");
    }

    const handleDragOver = React.useCallback(
        (event: React.DragEvent<HTMLButtonElement>) => {
            if (!onDropFaces || !hasFaceDragData(event.dataTransfer)) {
                return;
            }

            event.preventDefault();
            try {
                event.dataTransfer.dropEffect = "move";
            } catch (error) {
                // Ignore
            }
        },
        [onDropFaces],
    );

    const handleDragEnterInternal = React.useCallback(
        (event: React.DragEvent<HTMLButtonElement>) => {
            if (!onDropFaces || !hasFaceDragData(event.dataTransfer)) {
                return;
            }

            event.preventDefault();
            onDragEnter?.(cluster.id);
        },
        [cluster.id, onDragEnter, onDropFaces],
    );

    const handleDragLeaveInternal = React.useCallback(() => {
        onDragLeave?.(cluster.id);
    }, [cluster.id, onDragLeave]);

    const handleDrop = React.useCallback(
        (event: React.DragEvent<HTMLButtonElement>) => {
            if (!onDropFaces) {
                return;
            }

            event.preventDefault();

            const payload = getFaceDragData(event.dataTransfer);
            if (!payload) {
                onDragLeave?.(cluster.id);
                return;
            }

            onDragLeave?.(cluster.id);

            if (payload.clusterId === cluster.id || payload.faceIds.length === 0) {
                return;
            }

            onDropFaces(cluster.id, payload);
        },
        [cluster.id, onDragLeave, onDropFaces],
    );

    return (
        <button
            type="button"
            className={classes.join(" ")}
            onClick={() => onClick?.(cluster.id)}
            aria-label={ariaLabel}
            aria-pressed={selected}
            data-selected={selected || undefined}
            data-drop-target={isDropTarget || undefined}
            data-testid={`cluster-card-${cluster.id}`}
            onDragOver={handleDragOver}
            onDragEnter={handleDragEnterInternal}
            onDragLeave={handleDragLeaveInternal}
            onDrop={handleDrop}
        >
            <div className="cat-cluster-card__media" aria-hidden="true">
                {cluster.sampleFace.thumbnailUrl ? (
                    <img
                        src={cluster.sampleFace.thumbnailUrl}
                        alt={__("Representative face for this cluster", "context-alt-text")}
                        className="cat-cluster-card__image"
                    />
                ) : (
                    <div className="cat-cluster-card__placeholder" role="presentation">
                        <span aria-hidden="true">👤</span>
                        <span className="screen-reader-text">
                            {__("No thumbnail available for this cluster", "context-alt-text")}
                        </span>
                    </div>
                )}
            </div>
            <div className="cat-cluster-card__content">
                <h3 className="cat-cluster-card__title">
                    {__("Unknown person", "context-alt-text")}
                    <span className="cat-cluster-card__identifier">{cluster.id}</span>
                </h3>
                <p className="cat-cluster-card__detail">{faceCountLabel}</p>
                {suggestion && (
                    <p className="cat-cluster-card__suggestion">
                        {confidenceLabel ? `${confidenceLabel} • ` : ""}
                        {sprintf(
                            /* translators: %s: suggested roster display name */
                            __("Suggested: %s", "context-alt-text"),
                            suggestion.displayName,
                        )}
                    </p>
                )}
            </div>
        </button>
    );
};
