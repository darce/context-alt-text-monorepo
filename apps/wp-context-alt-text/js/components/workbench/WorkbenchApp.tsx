import React from "react";

import { SelectionToolbar } from "@/components/workbench/SelectionToolbar";
import { MediaList } from "@/components/workbench/MediaList";
import { BulkAltTextPanel } from "@/components/workbench/BulkAltTextPanel";
import { RecognitionActions } from "@/components/workbench/RecognitionActions";
import { MediaPreview } from "@/components/workbench/MediaPreview";

export type WorkbenchViewMode = "grid" | "list";

export interface WorkbenchMediaItem {
    id: string;
    title: string;
    status: "missing" | "draft" | "published";
    thumbnailUrl?: string;
    updatedAt?: string;
    altText?: string | null;
    mimeType?: string | null;
    dimensions?: {
        width: number;
        height: number;
    } | null;
    editUrl?: string | null;
}

export interface WorkbenchAppProps {
    items?: WorkbenchMediaItem[];
    viewMode?: WorkbenchViewMode;
    recognitionEnabled?: boolean;
    bulkAIEnabled?: boolean;
    onGenerateAltText?: (ids: string[]) => void;
    onRegenerateAltText?: (ids: string[]) => void;
    onMarkReviewed?: (ids: string[]) => void;
    onTriggerRecognition?: (ids: string[]) => void;
    onGenerateDrafts?: (ids: string[]) => void;
    onPublishDrafts?: (ids: string[]) => void;
}

export const WorkbenchApp = ({
    items = [],
    viewMode = "list",
    recognitionEnabled = false,
    bulkAIEnabled = false,
    onGenerateAltText,
    onRegenerateAltText,
    onMarkReviewed,
    onTriggerRecognition,
    onGenerateDrafts,
    onPublishDrafts,
}: WorkbenchAppProps): React.JSX.Element => {
    const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
    const selectedList = React.useMemo(() => Array.from(selectedIds), [selectedIds]);

    React.useEffect(() => {
        setSelectedIds(new Set());
    }, [items]);

    const handleToggleSelection = React.useCallback(
        (id: string) => {
            setSelectedIds((prev) => {
                const next = new Set(prev);
                if (next.has(id)) {
                    next.delete(id);
                } else {
                    next.add(id);
                }
                return next;
            });
        },
        [setSelectedIds],
    );

    const clearSelection = React.useCallback(() => setSelectedIds(new Set()), []);

    const handleGenerateAltText = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onGenerateAltText?.(selectedList);
    }, [onGenerateAltText, selectedList]);

    const handleRegenerateAltText = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onRegenerateAltText?.(selectedList);
    }, [onRegenerateAltText, selectedList]);

    const handleMarkReviewed = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onMarkReviewed?.(selectedList);
    }, [onMarkReviewed, selectedList]);

    const handleTriggerRecognition = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onTriggerRecognition?.(selectedList);
    }, [onTriggerRecognition, selectedList]);

    const handleGenerateDrafts = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onGenerateDrafts?.(selectedList);
    }, [onGenerateDrafts, selectedList]);

    const handlePublishDrafts = React.useCallback(() => {
        if (selectedList.length === 0) {
            return;
        }
        onPublishDrafts?.(selectedList);
    }, [onPublishDrafts, selectedList]);

    return (
        <div className="cat-workbench" aria-label="Alt-Text Workbench">
            <SelectionToolbar
                selectionCount={selectedIds.size}
                onGenerate={handleGenerateAltText}
                onRegenerate={handleRegenerateAltText}
                onMarkReviewed={handleMarkReviewed}
                onClearSelection={clearSelection}
            />

            <div className="cat-workbench__layout">
                <MediaList
                    items={items}
                    selectedIds={selectedIds}
                    onToggleSelect={handleToggleSelection}
                    viewMode={viewMode}
                />

                <aside className="cat-workbench__sidebar">
                    {recognitionEnabled && (
                        <RecognitionActions
                            disabled={selectedIds.size === 0}
                            onTriggerRecognition={handleTriggerRecognition}
                            selectionCount={selectedIds.size}
                        />
                    )}
                    <BulkAltTextPanel
                        selectionCount={selectedIds.size}
                        onGenerateDrafts={handleGenerateDrafts}
                        onPublishDrafts={handlePublishDrafts}
                        enableGeneration={bulkAIEnabled}
                    />
                    <MediaPreview selectedIds={selectedIds} items={items} />
                </aside>
            </div>
        </div>
    );
};
