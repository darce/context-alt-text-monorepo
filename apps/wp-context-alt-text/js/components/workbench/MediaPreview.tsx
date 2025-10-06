import React from "react";

import { __ } from "@wordpress/i18n";

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
            <section
                className="cat-workbench__panel"
                aria-label={__("Media preview", "context-alt-text")}
            >
                <p>
                    {__(
                        "Select an item to preview metadata, recognition insights, and draft alt text.",
                        "context-alt-text",
                    )}
                </p>
            </section>
        );
    }

    const formattedUpdated = formatWorkbenchDate(item.updatedAt) ?? __("Not available", "context-alt-text");
    const dimensions = item.dimensions
        ? `${item.dimensions.width}×${item.dimensions.height}px`
        : __("Unknown", "context-alt-text");

    return (
        <section
            className="cat-workbench__panel"
            aria-label={__("Media preview", "context-alt-text")}
        >
            <header>
                <h2>{item.title}</h2>
                <p className="cat-status-line">{getStatusLabel(item.status)}</p>
            </header>
            {item.thumbnailUrl ? (
                <img className="cat-workbench__preview-image" src={item.thumbnailUrl} alt="" />
            ) : (
                <div className="cat-workbench__preview-placeholder" aria-hidden="true" />
            )}
            <dl className="cat-workbench__preview-meta">
                <dt>{__("Last updated", "context-alt-text")}</dt>
                <dd>{formattedUpdated}</dd>
                <dt>{__("Dimensions", "context-alt-text")}</dt>
                <dd>{dimensions}</dd>
                <dt>{__("MIME type", "context-alt-text")}</dt>
                <dd>{item.mimeType ?? __("Unknown", "context-alt-text")}</dd>
            </dl>
            <div>
                <h3 className="cat-workbench__media-alt-label">{__("Alt text", "context-alt-text")}</h3>
                <p className="cat-workbench__media-alt-value">
                    {item.altText && item.altText.trim().length > 0
                        ? item.altText
                        : __("Not provided yet.", "context-alt-text")}
                </p>
            </div>
        </section>
    );
};

const getStatusLabel = (status: WorkbenchMediaItem["status"]): string => {
    switch (status) {
        case "missing":
            return __("Needs alt text", "context-alt-text");
        case "draft":
            return __("Draft available", "context-alt-text");
        case "published":
            return __("Alt text published", "context-alt-text");
        default:
            return status;
    }
};
