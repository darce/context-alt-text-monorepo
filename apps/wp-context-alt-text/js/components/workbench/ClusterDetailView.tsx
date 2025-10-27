import React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";

import { useClusterDetail } from "@/hooks/useClusterDetail";
import { useClusterSuggestions } from "@/hooks/useClusterSuggestions";
import { FaceGrid } from "@/components/workbench/FaceGrid";
import type { FaceGridRangeSelection } from "@/components/workbench/FaceGrid";
import { Button } from "@/components/ui/button";
import { SuggestionChip } from "@/components/workbench/SuggestionChip";
import { ClusterConfirmationModal } from "@/components/workbench/ClusterConfirmationModal";
import { setFaceDragData } from "@/components/workbench/dragTypes";
import "./ClusterDetailView.scss";

export interface ClusterDetailViewProps {
    clusterId: string;
    onClose?: () => void;
    onSelectionChange?: (faceIds: string[]) => void;
    onRequestConfirm?: (clusterId: string, faceIds: string[]) => void;
    onReviewLater?: (clusterId: string, faceIds: string[]) => void;
}

export const ClusterDetailView = ({
    clusterId,
    onClose,
    onSelectionChange,
    onRequestConfirm,
    onReviewLater,
}: ClusterDetailViewProps): React.JSX.Element => {
    const { cluster, faces, isLoading, error, refetch } = useClusterDetail(clusterId);
    const [selectedFaceIds, setSelectedFaceIds] = React.useState<string[]>([]);
    const faceIds = React.useMemo(() => faces.map((face) => face.id), [faces]);
    const { suggestions } = useClusterSuggestions(clusterId);
    const [isConfirmationOpen, setConfirmationOpen] = React.useState(false);
    const [pendingFaceIds, setPendingFaceIds] = React.useState<string[]>([]);
    const [activeSuggestionRosterId, setActiveSuggestionRosterId] = React.useState<string | null>(null);
    const [selectionAnchorIndex, setSelectionAnchorIndex] = React.useState<number | null>(null);

    const faceMap = React.useMemo(() => {
        const map = new Map<string, (typeof faces)[number]>();
        faces.forEach((face) => {
            map.set(face.id, face);
        });

        return map;
    }, [faces]);

    const headerSuggestion = React.useMemo(() => {
        if (suggestions.length === 0 && cluster.suggestion) {
            return {
                displayName: cluster.suggestion.displayName,
                confidence: cluster.suggestion.confidence ?? undefined,
                reason: cluster.suggestion.reason ?? undefined,
            };
        }

        return null;
    }, [cluster.suggestion, suggestions]);

    React.useEffect(() => {
        if (suggestions.length === 0) {
            setActiveSuggestionRosterId(null);
            return;
        }

        if (!suggestions.some((suggestion) => suggestion.rosterId === activeSuggestionRosterId)) {
            setActiveSuggestionRosterId(null);
        }
    }, [activeSuggestionRosterId, suggestions]);

    React.useEffect(() => {
        setSelectedFaceIds((prev) => {
            if (faceIds.length === 0) {
                if (prev.length === 0) {
                    return prev;
                }

                setSelectionAnchorIndex(null);
                return [];
            }

            if (prev.length === 0) {
                const nextSelection = [...faceIds];
                setSelectionAnchorIndex(nextSelection.length > 0 ? 0 : null);
                return nextSelection;
            }

            const nextSelection = faceIds.filter((id) => prev.includes(id));
            const finalSelection = nextSelection.length > 0 ? nextSelection : [...faceIds];

            if (
                finalSelection.length === prev.length &&
                finalSelection.every((id, index) => prev[index] === id)
            ) {
                return prev;
            }

            setSelectionAnchorIndex(finalSelection.length > 0 ? faceIds.indexOf(finalSelection[0]) : null);
            return finalSelection;
        });
    }, [faceIds]);

    React.useEffect(() => {
        onSelectionChange?.(selectedFaceIds);
    }, [onSelectionChange, selectedFaceIds]);

    const handleToggleFace = React.useCallback(
        (faceId: string, options?: { index: number }) => {
            setActiveSuggestionRosterId(null);
            setSelectedFaceIds((prev) => {
                const isSelected = prev.includes(faceId);
                if (isSelected) {
                    const next = prev.filter((id) => id !== faceId);
                    const ordered = faceIds.filter((id) => next.includes(id));
                    setSelectionAnchorIndex(ordered.length > 0 ? faceIds.indexOf(ordered[0]) : null);
                    return ordered;
                }

                const next = [...prev, faceId];
                const ordered = faceIds.filter((id) => next.includes(id));
                const targetIndex =
                    typeof options?.index === "number" && options.index >= 0
                        ? options.index
                        : faceIds.indexOf(faceId);
                setSelectionAnchorIndex(targetIndex >= 0 ? targetIndex : ordered.length > 0 ? faceIds.indexOf(ordered[0]) : null);
                return ordered;
            });
        },
        [faceIds],
    );

    const handleSelectAll = React.useCallback(() => {
        setActiveSuggestionRosterId(null);
        setSelectedFaceIds([...faceIds]);
        setSelectionAnchorIndex(faceIds.length > 0 ? 0 : null);
    }, [faceIds]);

    const handleClearSelection = React.useCallback(() => {
        setActiveSuggestionRosterId(null);
        setSelectedFaceIds([]);
        setSelectionAnchorIndex(null);
    }, []);

    const handleRangeSelect = React.useCallback(
        ({ faceIds: rangeFaceIds, startIndex }: FaceGridRangeSelection) => {
            setActiveSuggestionRosterId(null);
            setSelectedFaceIds(rangeFaceIds);
            setSelectionAnchorIndex(startIndex);
            setPendingFaceIds(rangeFaceIds);
        },
        [],
    );

    const handleFaceDragStart = React.useCallback(
        (faceId: string, index: number, event: React.DragEvent<HTMLButtonElement>) => {
            setActiveSuggestionRosterId(null);
            setSelectedFaceIds((previous) => {
                const isAlreadySelected = previous.includes(faceId);
                const nextSelection = isAlreadySelected ? previous : [faceId];

                try {
                    event.dataTransfer.effectAllowed = "move";
                } catch (error) {
                    // Ignore browsers that do not support programmatic effectAllowed.
                }

                setFaceDragData(event.dataTransfer, {
                    clusterId: cluster.id,
                    faceIds: nextSelection,
                });

                setPendingFaceIds(nextSelection);
                setSelectionAnchorIndex(isAlreadySelected ? selectionAnchorIndex : index);

                return isAlreadySelected ? previous : nextSelection;
            });
        },
        [cluster.id, selectionAnchorIndex],
    );

    const handleModalClose = React.useCallback(() => {
        setConfirmationOpen(false);
        setPendingFaceIds([]);
    }, []);

    const handleRequestConfirm = React.useCallback(() => {
        if (selectedFaceIds.length === 0) {
            return;
        }
        setPendingFaceIds(selectedFaceIds);
        setConfirmationOpen(true);
        onRequestConfirm?.(cluster.id, selectedFaceIds);
    }, [cluster.id, onRequestConfirm, selectedFaceIds]);

    const handleSuggestionSelect = React.useCallback(
        (suggestionId: string, faceIdsFromSuggestion: readonly string[] | undefined) => {
            const intersectingFaces = (faceIdsFromSuggestion ?? []).filter((faceId) => faceMap.has(faceId));
            const orderedSelection = (intersectingFaces.length > 0 ? intersectingFaces : faceIds).filter((id) =>
                faceMap.has(id),
            );

            setActiveSuggestionRosterId(suggestionId);
            setSelectedFaceIds(orderedSelection);
            setPendingFaceIds(orderedSelection);
            setSelectionAnchorIndex(
                orderedSelection.length > 0 ? faceIds.indexOf(orderedSelection[0]) : null,
            );
            setConfirmationOpen(true);
            onRequestConfirm?.(cluster.id, orderedSelection);
        },
        [cluster.id, faceIds, faceMap, onRequestConfirm],
    );

    const handleReviewLater = React.useCallback(() => {
        onReviewLater?.(cluster.id, selectedFaceIds);
    }, [cluster.id, onReviewLater, selectedFaceIds]);

    if (isLoading) {
        return (
            <section className="cat-cluster-detail" aria-live="polite">
                <p className="cat-cluster-detail__status" role="status">
                    {__("Loading cluster faces…", "context-alt-text")}
                </p>
            </section>
        );
    }

    if (error) {
        return (
            <section className="cat-cluster-detail" aria-live="assertive">
                <div className="cat-cluster-detail__error" role="alert">
                    <p>{__("Unable to load faces for this cluster.", "context-alt-text")}</p>
                    <button type="button" onClick={() => void refetch()}>
                        {__("Retry", "context-alt-text")}
                    </button>
                </div>
            </section>
        );
    }

    const faceCountLabel = sprintf(
        _n("%d face ready for review", "%d faces ready for review", cluster.faceCount, "context-alt-text"),
        cluster.faceCount,
    );

    const selectedCountLabel = sprintf(
        _n("%d face selected", "%d faces selected", selectedFaceIds.length, "context-alt-text"),
        selectedFaceIds.length,
    );

    return (
        <>
            <section
                className="cat-cluster-detail"
                aria-labelledby={`cat-cluster-detail-heading-${cluster.id}`}
                data-cluster-id={cluster.id}
            >
            <header className="cat-cluster-detail__header">
                <div className="cat-cluster-detail__heading">
                    <h2 id={`cat-cluster-detail-heading-${cluster.id}`}>
                        {__("Cluster Detail", "context-alt-text")}
                    </h2>
                    <p>{faceCountLabel}</p>
                </div>
                {headerSuggestion && (
                    <SuggestionChip
                        displayName={headerSuggestion.displayName}
                        confidence={headerSuggestion.confidence ?? undefined}
                        reason={headerSuggestion.reason ?? undefined}
                    />
                )}
                {onClose && (
                    <button
                        type="button"
                        className="cat-cluster-detail__close"
                        onClick={onClose}
                        aria-label={__("Close cluster detail", "context-alt-text")}
                    >
                        {__("Close", "context-alt-text")}
                    </button>
                )}
            </header>

            {faces.length === 0 ? (
                <p className="cat-cluster-detail__empty">
                    {__("All faces in this cluster have been resolved.", "context-alt-text")}
                </p>
            ) : (
                <>
                    {suggestions.length > 0 && (
                        <div className="cat-cluster-detail__suggestions" aria-live="polite">
                            {suggestions.map((suggestion) => {
                                const suggestionReason =
                                    suggestion.reason ??
                                    (typeof suggestion.matchCount === "number"
                                        ? sprintf(
                                              /* translators: %d: face count */
                                              _n(
                                                  "%d face matched this person.",
                                                  "%d faces matched this person.",
                                                  suggestion.matchCount,
                                                  "context-alt-text",
                                              ),
                                              suggestion.matchCount,
                                          )
                                        : undefined);

                                const isActive = activeSuggestionRosterId === suggestion.rosterId;

                                return (
                                    <div
                                        key={suggestion.rosterId}
                                        className={`cat-cluster-detail__suggestion${
                                            isActive ? " cat-cluster-detail__suggestion--active" : ""
                                        }`}
                                    >
                                        <SuggestionChip
                                            displayName={suggestion.displayName}
                                            confidence={suggestion.confidence}
                                            reason={suggestionReason}
                                            disabled={faces.length === 0}
                                            onSelect={() =>
                                                handleSuggestionSelect(
                                                    suggestion.rosterId,
                                                    suggestion.faceIds ?? undefined,
                                                )
                                            }
                                        />
                                    </div>
                                );
                            })}
                        </div>
                    )}
                    <div className="cat-cluster-detail__toolbar" aria-live="polite">
                        <div className="cat-cluster-detail__toolbar-selection">
                            <strong>{selectedCountLabel}</strong>
                            <span aria-hidden="true">•</span>
                            <button
                                type="button"
                                className="cat-cluster-detail__toolbar-link"
                                onClick={handleSelectAll}
                                disabled={selectedFaceIds.length === faceIds.length}
                            >
                                {__("Select all", "context-alt-text")}
                            </button>
                            <span aria-hidden="true">/</span>
                            <button
                                type="button"
                                className="cat-cluster-detail__toolbar-link"
                                onClick={handleClearSelection}
                                disabled={selectedFaceIds.length === 0}
                            >
                                {__("Clear", "context-alt-text")}
                            </button>
                        </div>
                        <div className="cat-cluster-detail__toolbar-actions">
                            <Button
                                variant="subtle"
                                size="sm"
                                onClick={handleReviewLater}
                                disabled={!onReviewLater}
                            >
                                {__("Review Later", "context-alt-text")}
                            </Button>
                            <Button
                                variant="primary"
                                size="sm"
                                onClick={handleRequestConfirm}
                                disabled={selectedFaceIds.length === 0 || !onRequestConfirm}
                            >
                                {__("Label Selected", "context-alt-text")}
                            </Button>
                        </div>
                    </div>
                    <FaceGrid
                        faces={faces}
                        selectedFaceIds={selectedFaceIds}
                        selectionAnchorIndex={selectionAnchorIndex}
                        onToggleFace={handleToggleFace}
                        onRangeSelect={handleRangeSelect}
                        onSelectAll={handleSelectAll}
                        onDragStart={handleFaceDragStart}
                    />
                </>
            )}
            </section>

            <ClusterConfirmationModal
                isOpen={isConfirmationOpen}
                clusterId={cluster.id}
                faces={faces}
                selectedFaceIds={pendingFaceIds.length > 0 ? pendingFaceIds : selectedFaceIds}
                suggestions={suggestions}
                onClose={handleModalClose}
            />
        </>
    );
};
