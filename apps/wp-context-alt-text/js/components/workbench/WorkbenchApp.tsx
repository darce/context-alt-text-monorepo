import React from "react";

import { __, sprintf, _n } from "@wordpress/i18n";

import { SelectionToolbar } from "@/components/workbench/SelectionToolbar";
import { MediaList } from "@/components/workbench/MediaList";
import { FaceScanActions } from "@/components/workbench/FaceScanActions";
import { UnknownPeoplePanel } from "@/components/workbench/UnknownPeoplePanel";
import { ClusterDetailView } from "@/components/workbench/ClusterDetailView";
import type { WorkbenchMediaItem as WorkbenchMediaItemType } from "@/admin/types";
import { notifySuccess } from "@/admin/notices";
import { useWorkbenchActions } from "./useWorkbenchActions";

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

export const WorkbenchApp = ({
    items,
    viewMode = "list",
    onGenerateAltText,
    onRegenerateAltText,
    onMarkReviewed,
}: WorkbenchAppProps): React.JSX.Element => {
    const mediaItems = React.useMemo<WorkbenchMediaItem[]>(() => items ?? [], [items]);
    const [selectedIds, setSelectedIds] = React.useState<Set<string>>(() => new Set());
    const [activeClusterId, setActiveClusterId] = React.useState<string | null>(null);

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
                    <UnknownPeoplePanel onSelectCluster={setActiveClusterId} selectedClusterId={activeClusterId} />
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
