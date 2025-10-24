/**
 * Cluster Stack Component
 *
 * Displays a group of unknown faces that are likely the same person.
 * Shows representative thumbnail with count badge and "Review" action.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { __ } from "@wordpress/i18n";

export interface ClusterStackProps {
    /** Unique cluster identifier */
    clusterId: string;
    /** Number of faces in this cluster */
    count: number;
    /** Representative face thumbnail URL */
    thumbnailUrl: string;
    /** Whether this cluster is currently selected */
    isSelected: boolean;
    /** Click handler to highlight faces in overlay */
    onClick: () => void;
    /** Callback to review all faces in this cluster */
    onReview: () => void;
}

/**
 * Cluster Stack
 *
 * Shows a group of detected faces that appear to be the same person
 * based on backend clustering. Provides quick review action.
 *
 * @example
 * ```tsx
 * <ClusterStack
 *   clusterId="cluster-abc123-0"
 *   count={12}
 *   thumbnailUrl="http://example.test/face.jpg"
 *   isSelected={false}
 *   onClick={() => highlightCluster("cluster-abc123-0")}
 *   onReview={() => showAllFaces("cluster-abc123-0")}
 * />
 * ```
 */
export const ClusterStack = ({
    clusterId,
    count,
    thumbnailUrl,
    isSelected,
    onClick,
    onReview,
}: ClusterStackProps): JSX.Element => {
    /**
     * Handle keyboard interaction for main stack
     */
    const handleKeyDown = (event: React.KeyboardEvent): void => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onClick();
        }
    };

    /**
     * Handle keyboard interaction for review button
     */
    const handleReviewKeyDown = (event: React.KeyboardEvent): void => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            event.stopPropagation();
            onReview();
        }
    };

    /**
     * Handle review button click
     */
    const handleReviewClick = (event: React.MouseEvent): void => {
        event.stopPropagation();
        onReview();
    };

    return (
        <div
            className={`cat-cluster-stack ${isSelected ? "cat-cluster-stack--selected" : ""}`}
            onClick={onClick}
            onKeyDown={handleKeyDown}
            role="button"
            tabIndex={0}
            aria-label={`${__("Likely same person", "context-alt-text")}, ${count} ${__("faces", "context-alt-text")}`}
        >
            <div className="cat-cluster-stack__thumbnail">
                {thumbnailUrl ? (
                    <img src={thumbnailUrl} alt="" aria-hidden="true" className="cat-cluster-stack__image" />
                ) : (
                    <div className="cat-cluster-stack__placeholder" aria-hidden="true">
                        <span className="cat-cluster-stack__placeholder-icon">👤</span>
                    </div>
                )}
                <span className="cat-cluster-stack__badge" aria-hidden="true">
                    {count}
                </span>
            </div>

            <div className="cat-cluster-stack__content">
                <h4 className="cat-cluster-stack__title">{__("Likely same person", "context-alt-text")}</h4>
                <p className="cat-cluster-stack__count">
                    {count} {count === 1 ? __("face", "context-alt-text") : __("faces", "context-alt-text")}
                </p>
            </div>

            <button
                type="button"
                className="cat-cluster-stack__action"
                onClick={handleReviewClick}
                onKeyDown={handleReviewKeyDown}
                aria-label={`${__("Review", "context-alt-text")} ${count} ${__("faces", "context-alt-text")}`}
            >
                {__("Review", "context-alt-text")}
            </button>
        </div>
    );
};
