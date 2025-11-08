import React from "react";

import { __, sprintf, _n } from "@wordpress/i18n";

import { SelectionToolbar } from "@/components/workbench/SelectionToolbar";
import { MediaList } from "@/components/workbench/MediaList";
import { FaceScanActions } from "@/components/workbench/FaceScanActions";
import { UnknownPeoplePanel } from "@/components/workbench/UnknownPeoplePanel";
import { ClusterDetailView } from "@/components/workbench/ClusterDetailView";
import type { WorkbenchMediaItem as WorkbenchMediaItemType } from "@/admin/types";
import { notifySuccess, notifyError } from "@/admin/notices";
import { useWorkbenchActions } from "./useWorkbenchActions";
import { useMoveFaces } from "@/hooks/useMoveFaces";
import { ToastProvider } from "@/contexts/ToastContext";

export type WorkbenchViewMode = "grid" | "list";
export type WorkbenchMediaItem = WorkbenchMediaItemType;

export interface WorkbenchAppProps {
    items?: WorkbenchMediaItem[];
    viewMode?: WorkbenchViewMode;
    onGenerateAltText?: (ids: string[]) => void;
    onRegenerateAltText?: (ids: string[]) => void;
    onMarkReviewed?: (ids: string[]) => void;
}

interface FaceScanSummary {
    jobId: string;
    queuedCount: number;
}

export const WorkbenchAppContent = ({
    items,
    viewMode = "list",
    onGenerateAltText,
    onRegenerateAltText,
    onMarkReviewed,
}: WorkbenchAppProps): React.JSX.Element => {
    const mediaItems = React.useMemo<WorkbenchMediaItem[]>(() => items ?? [], [items]);
    const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
    const [activeClusterId, setActiveClusterId] = React.useState<string | null>(null);

    const moveFacesMutation = useMoveFaces();

    const selectedList = React.useMemo(() => Array.from(selectedIds), [selectedIds]);
    const selectedIdsNumeric = React.useMemo(
        () => selectedList.map((id) => Number.parseInt(id, 10)).filter((value) => Number.isFinite(value)),
        [selectedList],
    );

    React.useEffect(() => {
        setSelectedIds((previous) => {
            if (mediaItems.length === 0) {
                return previous.size === 0 ? previous : new Set();
            }

            const validIds = new Set(mediaItems.map((item) => item.id));
            const filtered = new Set<string>();

            previous.forEach((id) => {
                if (validIds.has(id)) {
                    filtered.add(id);
                }
            });

            return filtered.size === previous.size ? previous : filtered;
        });
    }, [mediaItems]);

    const actions = useWorkbenchActions({
        selectedList,
        setSelectedIds,
        onGenerateAltText,
        onRegenerateAltText,
        onMarkReviewed,
    });

    const handleScanComplete = React.useCallback(({ jobId, queuedCount }: FaceScanSummary) => {
        const message = sprintf(
            _n(
                "Queued %1$d image for face detection. Job ID: %2$s.",
                "Queued %1$d images for face detection. Job ID: %2$s.",
                queuedCount,
                "context-alt-text",
            ),
            queuedCount,
            jobId,
        );

        notifySuccess(message, { isDismissible: true });
    }, []);

    const handleMoveFaces = React.useCallback(
        ({
            targetClusterId,
            sourceClusterId,
            faceIds,
        }: {
            targetClusterId: string;
            sourceClusterId: string;
            faceIds: string[];
        }) => {
            // Convert string IDs to numbers for the API
            const numericFaceIds = faceIds.map((id) => Number.parseInt(id, 10)).filter((id) => !Number.isNaN(id));

            if (numericFaceIds.length === 0) {
                notifyError(__("No valid face IDs to move", "context-alt-text"));
                return;
            }

            moveFacesMutation.mutate(
                {
                    faceIds: numericFaceIds,
                    sourceClusterId,
                    targetClusterId,
                },
                {
                    onSuccess: (data) => {
                        const message = sprintf(
                            _n(
                                "Moved %d face to cluster %s",
                                "Moved %d faces to cluster %s",
                                data.moved_count,
                                "context-alt-text",
                            ),
                            data.moved_count,
                            targetClusterId,
                        );
                        notifySuccess(message, { isDismissible: true });
                    },
                    onError: (error) => {
                        notifyError(
                            sprintf(
                                __("Failed to move faces: %s", "context-alt-text"),
                                error instanceof Error ? error.message : String(error),
                            ),
                        );
                    },
                },
            );
        },
        [moveFacesMutation],
    );

    return (
        <div className="cat-workbench" aria-label={__("Alt-Text Workbench", "context-alt-text")}>
            <SelectionToolbar
                selectionCount={selectedIds.size}
                onGenerate={actions.handleGenerateAltText}
                onRegenerate={actions.handleRegenerateAltText}
                onMarkReviewed={actions.handleMarkReviewed}
                onClearSelection={actions.clearSelection}
            />

            <div className="cat-workbench__layout">
                <div className="cat-workbench__sidebar">
                    <FaceScanActions selectedIds={selectedIdsNumeric} onScanComplete={handleScanComplete} />
                    <UnknownPeoplePanel
                        onSelectCluster={setActiveClusterId}
                        selectedClusterId={activeClusterId}
                        onMoveFaces={handleMoveFaces}
                    />
                    {activeClusterId && (
                        <ClusterDetailView
                            clusterId={activeClusterId}
                            onClose={() => setActiveClusterId(null)}
                            onRequestConfirm={() => {
                                /* Cluster detail handles confirmation flow internally. */
                            }}
                            onReviewLater={() => {
                                /* Future enhancement: persist review-later queue. */
                            }}
                        />
                    )}
                </div>
                <MediaList
                    items={mediaItems}
                    selectedIds={selectedIds}
                    onToggleSelect={actions.handleToggleSelection}
                    viewMode={viewMode}
                />
            </div>
        </div>
    );
};

interface WorkbenchAppProvidersProps {
    children: React.ReactNode;
}

export const WorkbenchAppProviders = ({ children }: WorkbenchAppProvidersProps): React.JSX.Element => {
    return <ToastProvider>{children}</ToastProvider>;
};

export const WorkbenchApp = (props: WorkbenchAppProps): React.JSX.Element => {
    return (
        <WorkbenchAppProviders>
            <WorkbenchAppContent {...props} />
        </WorkbenchAppProviders>
    );
};
