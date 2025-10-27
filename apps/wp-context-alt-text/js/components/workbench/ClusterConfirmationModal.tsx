import React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";
import { useQueryClient } from "@tanstack/react-query";

import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { SuggestionChip } from "@/components/workbench/SuggestionChip";
import { FaceThumbnailGrid } from "@/components/workbench/FaceThumbnailGrid";
import { PeoplePicker } from "@/components/workbench/PeoplePicker";
import { dispatchNotice } from "@/admin/notices";
import { confirmCluster as confirmClusterApi } from "@/api/clusterApi";
import { getDashboardConfig } from "@/admin/dashboardData";
import type { ClusterFaceDetail, ClusterSuggestion } from "@/types/face-clustering";
import "./ClusterConfirmationModal.scss";

export interface ClusterConfirmationModalProps {
    isOpen: boolean;
    clusterId: string;
    faces: ClusterFaceDetail[];
    selectedFaceIds: string[];
    suggestions: ClusterSuggestion[];
    onClose: () => void;
}

interface RosterSelection {
    id: string;
    displayName: string;
}

export const ClusterConfirmationModal = ({
    isOpen,
    clusterId,
    faces,
    selectedFaceIds,
    suggestions,
    onClose,
}: ClusterConfirmationModalProps): React.JSX.Element => {
    const [roster, setRoster] = React.useState<RosterSelection | null>(null);
    const [activeSuggestionRosterId, setActiveSuggestionRosterId] = React.useState<string | null>(null);
    const [includedFaceIds, setIncludedFaceIds] = React.useState<Set<string>>(new Set());
    const [isPickerOpen, setPickerOpen] = React.useState(false);
    const [isSubmitting, setIsSubmitting] = React.useState(false);
    const [errorMessage, setErrorMessage] = React.useState<string | null>(null);

    const config = getDashboardConfig();
    const restNonce = config?.restNonce;
    const queryClient = useQueryClient();
    const clustersEndpoint = config?.endpoints?.unknownClusters ?? null;

    const faceMap = React.useMemo(() => {
        const map = new Map<string, ClusterFaceDetail>();
        faces.forEach((face) => {
            map.set(face.id, face);
        });
        return map;
    }, [faces]);

    React.useEffect(() => {
        if (!isOpen) {
            return;
        }

        const initialFaces = selectedFaceIds.length > 0 ? selectedFaceIds : faces.map((face) => face.id);
        setIncludedFaceIds(new Set(initialFaces));

        if (suggestions.length > 0) {
            const primary = suggestions[0];
            setRoster({
                id: primary.rosterId,
                displayName: primary.displayName,
            });
            setActiveSuggestionRosterId(primary.rosterId);
        } else {
            setRoster(null);
            setActiveSuggestionRosterId(null);
        }

        setErrorMessage(null);
    }, [isOpen, selectedFaceIds, faces, suggestions]);

    const handleToggleFace = React.useCallback((faceId: string) => {
        setIncludedFaceIds((previous) => {
            const next = new Set(previous);
            if (next.has(faceId)) {
                next.delete(faceId);
            } else {
                next.add(faceId);
            }
            return next;
        });
    }, []);

    const handleSelectAll = React.useCallback(() => {
        setIncludedFaceIds(new Set(faces.map((face) => face.id)));
    }, [faces]);

    const handleClearSelection = React.useCallback(() => {
        setIncludedFaceIds(new Set());
    }, []);

    const handleSuggestionSelect = React.useCallback(
        (suggestion: ClusterSuggestion) => {
            setRoster({
                id: suggestion.rosterId,
                displayName: suggestion.displayName,
            });
            setActiveSuggestionRosterId(suggestion.rosterId);
            dispatchNotice(
                "info",
                sprintf(
                    /* translators: %s: roster display name */
                    __("Selected %s as the cluster match.", "context-alt-text"),
                    suggestion.displayName,
                ),
            );
        },
        [],
    );

    const handlePickerSelect = React.useCallback((rosterId: string, displayName: string) => {
        setRoster({ id: rosterId, displayName });
        setActiveSuggestionRosterId(null);
    }, []);

    const handlePickerCreate = React.useCallback((displayName: string) => {
        dispatchNotice(
            "warning",
            sprintf(
                /* translators: %s: display name */
                __("Creating new roster entries is not yet supported from this modal. Please select an existing person for %s.", "context-alt-text"),
                displayName,
            ),
        );
    }, []);

    const faceCount = includedFaceIds.size;
    const confirmDisabled = roster === null || faceCount === 0 || isSubmitting;

    const handleSubmit = React.useCallback(async () => {
        if (!roster || faceCount === 0) {
            return;
        }

        setIsSubmitting(true);
        setErrorMessage(null);

        try {
            const response = await confirmClusterApi(
                clusterId,
                {
                    rosterId: roster.id,
                    faceIds: Array.from(includedFaceIds),
                },
                restNonce,
            );

            if (response.errors.length > 0 && response.labeledCount === 0) {
                throw new Error(response.errors[0] ?? __("Unable to confirm cluster.", "context-alt-text"));
            }

            dispatchNotice(
                "success",
                sprintf(
                    /* translators: %d: number of faces */
                    _n(
                        "Labeled %d face successfully.",
                        "Labeled %d faces successfully.",
                        response.labeledCount,
                        "context-alt-text",
                    ),
                    response.labeledCount,
                ),
            );

            if (clustersEndpoint) {
                await Promise.all([
                    queryClient.invalidateQueries({
                        queryKey: ["cluster-detail", clustersEndpoint, clusterId],
                    }),
                    queryClient.invalidateQueries({
                        predicate: ({ queryKey }) =>
                            Array.isArray(queryKey) && queryKey[0] === "unknown-clusters" && queryKey[1] === clustersEndpoint,
                    }),
                ]);
            }

            setIncludedFaceIds(new Set());
            onClose();
        } catch (error) {
            const message =
                error instanceof Error ? error.message : __("Unable to confirm cluster.", "context-alt-text");
            setErrorMessage(message);
        } finally {
            setIsSubmitting(false);
        }
    }, [clusterId, clustersEndpoint, faceCount, includedFaceIds, onClose, queryClient, restNonce, roster]);

    const selectedFaces = React.useMemo(() => Array.from(includedFaceIds), [includedFaceIds]);

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="cat-dialog-content--large cat-cluster-confirmation">
                <DialogTitle>{__("Confirm identity", "context-alt-text")}</DialogTitle>
                <DialogDescription>
                    {__("Select the correct person and refine which faces to label in this batch.", "context-alt-text")}
                </DialogDescription>

                <section className="cat-cluster-confirmation__section">
                    <header>
                        <h3>{__("Suggestions", "context-alt-text")}</h3>
                    </header>
                    {suggestions.length === 0 ? (
                        <p className="cat-cluster-confirmation__empty">
                            {__("No suggestions available for this cluster yet.", "context-alt-text")}
                        </p>
                    ) : (
                        <div className="cat-cluster-confirmation__suggestions">
                            {suggestions.map((suggestion) => {
                                const isActive = activeSuggestionRosterId === suggestion.rosterId;

                                return (
                                    <div
                                        key={suggestion.rosterId}
                                        className={`cat-cluster-confirmation__suggestion${
                                            isActive ? " cat-cluster-confirmation__suggestion--active" : ""
                                        }`}
                                    >
                                        <SuggestionChip
                                            displayName={suggestion.displayName}
                                            confidence={suggestion.confidence}
                                            reason={
                                                suggestion.reason ??
                                                (typeof suggestion.matchCount === "number"
                                                    ? sprintf(
                                                          /* translators: %d: match count */
                                                          _n(
                                                              "%d face matched this person.",
                                                              "%d faces matched this person.",
                                                              suggestion.matchCount,
                                                              "context-alt-text",
                                                          ),
                                                          suggestion.matchCount,
                                                      )
                                                    : undefined)
                                            }
                                            onSelect={() => handleSuggestionSelect(suggestion)}
                                            disabled={isSubmitting}
                                        />
                                        {isActive && (
                                            <span className="cat-cluster-confirmation__suggestion-active">
                                                {__("Selected", "context-alt-text")}
                                            </span>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                    <div className="cat-cluster-confirmation__picker">
                        <p>
                            {roster
                                ? sprintf(
                                      /* translators: %s roster display name */
                                      __("Labeling as %s", "context-alt-text"),
                                      roster.displayName,
                                  )
                                : __("No person selected yet.", "context-alt-text")}
                        </p>
                        <Button
                            variant="subtle"
                            size="sm"
                            onClick={() => setPickerOpen(true)}
                            disabled={isSubmitting}
                        >
                            {roster
                                ? __("Choose a different person", "context-alt-text")
                                : __("Select a person", "context-alt-text")}
                        </Button>
                    </div>
                </section>

                <section className="cat-cluster-confirmation__section">
                    <header className="cat-cluster-confirmation__faces-header">
                        <h3>{__("Faces to label", "context-alt-text")}</h3>
                        <div className="cat-cluster-confirmation__faces-actions">
                            <Button variant="ghost" size="sm" onClick={handleSelectAll} disabled={isSubmitting}>
                                {__("Select all", "context-alt-text")}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={handleClearSelection} disabled={isSubmitting}>
                                {__("Clear", "context-alt-text")}
                            </Button>
                        </div>
                    </header>
                    <p className="cat-cluster-confirmation__faces-summary">
                        {sprintf(
                            /* translators: %1$d selected count; %2$d total faces */
                            __("%1$d of %2$d faces selected", "context-alt-text"),
                            selectedFaces.length,
                            faces.length,
                        )}
                    </p>
                    <FaceThumbnailGrid
                        faces={faces}
                        selectedFaceIds={selectedFaces}
                        onToggleFace={handleToggleFace}
                    />
                </section>

                {errorMessage && <p className="cat-cluster-confirmation__error">{errorMessage}</p>}

                <footer className="cat-dialog-footer">
                    <Button variant="subtle" onClick={onClose} disabled={isSubmitting}>
                        {__("Cancel", "context-alt-text")}
                    </Button>
                    <Button variant="primary" onClick={handleSubmit} disabled={confirmDisabled}>
                        {isSubmitting
                            ? __("Labeling…", "context-alt-text")
                            : sprintf(
                                  /* translators: %d face count */
                                  _n("Label %d face", "Label %d faces", faceCount, "context-alt-text"),
                                  faceCount,
                              )}
                    </Button>
                </footer>
            </DialogContent>

            <PeoplePicker
                isOpen={isPickerOpen}
                onClose={() => setPickerOpen(false)}
                onSelect={(id, displayName) => {
                    handlePickerSelect(id, displayName);
                    setPickerOpen(false);
                }}
                onCreateNew={(displayName) => {
                    handlePickerCreate(displayName);
                    setPickerOpen(false);
                }}
                restNonce={restNonce}
            />
        </Dialog>
    );
};
