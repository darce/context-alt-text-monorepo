import React from "react";

import type { WorkbenchMediaItem } from "@/components/workbench/WorkbenchApp";
import { formatWorkbenchDate } from "@/components/workbench/utils";

export interface MediaPreviewProps {
    selectedIds: Set<string>;
    items: WorkbenchMediaItem[];
}

export const MediaPreview = ({ selectedIds, items }: MediaPreviewProps): React.JSX.Element => {
    const [firstSelection] = React.useMemo(() => Array.from(selectedIds), [selectedIds]);
    const item = React.useMemo(() => items.find((candidate) => candidate.id === firstSelection), [items, firstSelection]);

    if (!item) {
        return (
            <section className="cat-workbench__panel" aria-label="Media preview">
                <p>Select an item to preview metadata, recognition insights, and draft alt text.</p>
            </section>
        );
    }

    const formattedUpdated = formatWorkbenchDate(item.updatedAt) ?? "Not available";
    const dimensions = item.dimensions ? `${item.dimensions.width}×${item.dimensions.height}px` : "Unknown";

    return (
        <section className="cat-workbench__panel" aria-label="Media preview">
            <header>
                <h2>{item.title}</h2>
                <p className="cat-status-line">{item.status}</p>
            </header>
            {item.thumbnailUrl ? (
                <img className="cat-workbench__preview-image" src={item.thumbnailUrl} alt="" />
            ) : (
                <div className="cat-workbench__preview-placeholder" aria-hidden="true" />
            )}
            <dl className="cat-workbench__preview-meta">
                <dt>Last updated</dt>
                <dd>{formattedUpdated}</dd>
                <dt>Dimensions</dt>
                <dd>{dimensions}</dd>
                <dt>MIME type</dt>
                <dd>{item.mimeType ?? "Unknown"}</dd>
            </dl>
            <div>
                <h3 className="cat-workbench__media-alt-label">Alt text</h3>
                <p className="cat-workbench__media-alt-value">
                    {item.altText && item.altText.trim().length > 0 ? item.altText : "Not provided yet."}
                </p>
            </div>
        </section>
    );
};
