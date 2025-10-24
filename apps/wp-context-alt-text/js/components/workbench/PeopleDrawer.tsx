/**
 * People Drawer Component
 *
 * Right rail drawer showing clustered unknowns and FAISS suggestions.
 * Provides quick actions for bulk labeling and face review.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React, { useState } from "react";
import { __ } from "@wordpress/i18n";
import { ClusterStack } from "./ClusterStack";
import { SuggestionStack } from "./SuggestionStack";
import type { DetectedFaceFE } from "@/types/people-labeling";
import "./PeopleDrawer.scss";

export interface PeopleDrawerProps {
    /** All detected faces with suggestions */
    faces: DetectedFaceFE[];
    /** Currently selected face/stack */
    selectedId: string | null;
    /** Callback when cluster is clicked */
    onClusterClick: (clusterId: string) => void;
    /** Callback when suggestion stack is clicked */
    onSuggestionClick: (rosterId: string) => void;
    /** Callback to review all faces in a cluster */
    onReviewCluster: (clusterId: string) => void;
    /** Callback to bulk confirm suggestion */
    onConfirmAll: (rosterId: string, faceIds: string[]) => void;
}

/**
 * Group faces by cluster ID
 */
interface ClusterGroup {
    clusterId: string;
    faces: DetectedFaceFE[];
}

/**
 * Group faces by top suggestion
 */
interface SuggestionGroup {
    rosterId: string;
    displayName: string;
    faces: DetectedFaceFE[];
    avgConfidence: number;
    avatarUrl?: string;
}

/**
 * People Drawer
 *
 * Right rail UI showing:
 * - Unknown clusters (likely same person)
 * - Suggestion stacks (FAISS matches)
 *
 * Provides bulk actions and face highlighting.
 *
 * @example
 * ```tsx
 * <PeopleDrawer
 *   faces={detectedFaces}
 *   selectedId={selectedClusterId}
 *   onClusterClick={(id) => highlightCluster(id)}
 *   onSuggestionClick={(id) => highlightSuggestions(id)}
 *   onReviewCluster={(id) => showAllFaces(id)}
 *   onConfirmAll={(rosterId, faceIds) => bulkConfirm(rosterId, faceIds)}
 * />
 * ```
 */
export const PeopleDrawer = ({
    faces,
    selectedId,
    onClusterClick,
    onSuggestionClick,
    onReviewCluster,
    onConfirmAll,
}: PeopleDrawerProps): JSX.Element => {
    const [isCollapsed, setIsCollapsed] = useState(false);

    /**
     * Group unknown faces by cluster ID
     */
    const clusterGroups: ClusterGroup[] = React.useMemo(() => {
        const groups = new Map<string, DetectedFaceFE[]>();

        faces.forEach((face) => {
            // Only include faces without confirmed labels or suggestions
            if (!face.confirmedRosterId && !face.labelDraft && face.suggestions.length === 0 && face.clusterId) {
                const existing = groups.get(face.clusterId) ?? [];
                groups.set(face.clusterId, [...existing, face]);
            }
        });

        return Array.from(groups.entries())
            .map(([clusterId, clusterFaces]) => ({
                clusterId,
                faces: clusterFaces,
            }))
            .sort((a, b) => b.faces.length - a.faces.length); // Sort by count descending
    }, [faces]);

    /**
     * Group faces with suggestions by top match
     */
    const suggestionGroups: SuggestionGroup[] = React.useMemo(() => {
        const groups = new Map<string, DetectedFaceFE[]>();

        faces.forEach((face) => {
            // Only include faces with suggestions that aren't confirmed yet
            if (!face.confirmedRosterId && !face.labelDraft && face.suggestions.length > 0) {
                const topSuggestion = face.suggestions[0];
                if (topSuggestion) {
                    const existing = groups.get(topSuggestion.rosterId) ?? [];
                    groups.set(topSuggestion.rosterId, [...existing, face]);
                }
            }
        });

        const result: SuggestionGroup[] = [];

        groups.forEach((groupFaces, rosterId) => {
            const topSuggestion = groupFaces[0]?.suggestions[0];
            if (!topSuggestion) {
                return;
            }

            const avgConfidence =
                groupFaces.reduce((sum, f) => sum + (f.suggestions[0]?.score ?? 0), 0) / groupFaces.length;

            result.push({
                rosterId,
                displayName: topSuggestion.display,
                faces: groupFaces,
                avgConfidence,
                avatarUrl: topSuggestion.avatarUrl,
            });
        });

        return result.sort((a, b) => b.avgConfidence - a.avgConfidence); // Sort by confidence descending
    }, [faces]);

    /**
     * Toggle drawer collapsed state
     */
    const handleToggle = (): void => {
        setIsCollapsed(!isCollapsed);
    };

    /**
     * Get thumbnail URL for cluster representative
     */
    const getClusterThumbnail = (clusterId: string): string => {
        // TODO: Generate actual face crop thumbnail from bbox and attachment
        // For now, return empty string so ClusterStack shows a placeholder icon
        return "";
    };

    /**
     * Handle confirm all for suggestion group
     */
    const handleConfirmAll = (rosterId: string): void => {
        const group = suggestionGroups.find((g) => g.rosterId === rosterId);
        if (group) {
            const faceIds = group.faces.map((f) => f.faceId);
            onConfirmAll(rosterId, faceIds);
        }
    };

    const hasUnknowns = clusterGroups.length > 0;
    const hasSuggestions = suggestionGroups.length > 0;
    const isEmpty = !hasUnknowns && !hasSuggestions;
    const hasConfirmedFaces = faces.some((f) => f.confirmedRosterId);

    return (
        <div className={`cat-people-drawer ${isCollapsed ? "cat-people-drawer--collapsed" : ""}`}>
            <div className="cat-people-drawer__header">
                <h3 className="cat-people-drawer__title">{__("People", "context-alt-text")}</h3>
                <button
                    type="button"
                    className="cat-people-drawer__toggle"
                    onClick={handleToggle}
                    aria-label={
                        isCollapsed
                            ? __("Expand drawer", "context-alt-text")
                            : __("Collapse drawer", "context-alt-text")
                    }
                    aria-expanded={!isCollapsed}
                >
                    <span className="cat-people-drawer__toggle-icon" aria-hidden="true">
                        {isCollapsed ? "›" : "‹"}
                    </span>
                </button>
            </div>

            {!isCollapsed && (
                <div className="cat-people-drawer__content">
                    {isEmpty && (
                        <div className="cat-people-drawer__empty">
                            <p>
                                {hasConfirmedFaces
                                    ? __("All faces labeled", "context-alt-text")
                                    : __("No faces detected yet", "context-alt-text")}
                            </p>
                            {!hasConfirmedFaces && (
                                <p className="cat-people-drawer__empty-hint">
                                    {__("Run face detection to identify people in this image", "context-alt-text")}
                                </p>
                            )}
                        </div>
                    )}

                    {hasSuggestions && (
                        <section className="cat-people-drawer__section">
                            <h4 className="cat-people-drawer__section-title">
                                {__("Suggestions", "context-alt-text")}
                            </h4>
                            <p className="cat-people-drawer__section-hint">
                                {__("Faces matching people in your roster", "context-alt-text")}
                            </p>
                            <div className="cat-people-drawer__stacks">
                                {suggestionGroups.map((group) => (
                                    <SuggestionStack
                                        key={group.rosterId}
                                        rosterId={group.rosterId}
                                        displayName={group.displayName}
                                        count={group.faces.length}
                                        confidence={group.avgConfidence}
                                        avatarUrl={group.avatarUrl}
                                        isSelected={selectedId === group.rosterId}
                                        onClick={() => onSuggestionClick(group.rosterId)}
                                        onConfirmAll={() => handleConfirmAll(group.rosterId)}
                                    />
                                ))}
                            </div>
                        </section>
                    )}

                    {hasUnknowns && (
                        <section className="cat-people-drawer__section">
                            <h4 className="cat-people-drawer__section-title">{__("Unknown", "context-alt-text")}</h4>
                            <p className="cat-people-drawer__section-hint">
                                {__("Faces grouped by similarity", "context-alt-text")}
                            </p>
                            <div className="cat-people-drawer__stacks">
                                {clusterGroups.map((group) => (
                                    <ClusterStack
                                        key={group.clusterId}
                                        clusterId={group.clusterId}
                                        count={group.faces.length}
                                        thumbnailUrl={getClusterThumbnail(group.clusterId)}
                                        isSelected={selectedId === group.clusterId}
                                        onClick={() => onClusterClick(group.clusterId)}
                                        onReview={() => onReviewCluster(group.clusterId)}
                                    />
                                ))}
                            </div>
                        </section>
                    )}
                </div>
            )}
        </div>
    );
};
