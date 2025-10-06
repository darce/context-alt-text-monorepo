import React from "react";

import { __ } from "@wordpress/i18n";

import { SelectionToolbar } from "@/components/workbench/SelectionToolbar";
import { MediaList } from "@/components/workbench/MediaList";

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
    onGenerateAltText?: (ids: string[]) => void;
    onRegenerateAltText?: (ids: string[]) => void;
    onMarkReviewed?: (ids: string[]) => void;
}

export const WorkbenchApp = ({
    items = [],
    viewMode = "list",
    onGenerateAltText,
    onRegenerateAltText,
    onMarkReviewed,
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

    return (
        <div
            className="cat-workbench"
            aria-label={__("Alt-Text Workbench", "context-alt-text")}
        >
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
            </div>
        </div>
    );
};
