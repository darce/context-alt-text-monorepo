import React from "react";

import { __, sprintf, _n } from "@wordpress/i18n";

import type { WorkbenchMediaItem, WorkbenchViewMode } from "@/components/workbench/WorkbenchApp";
import { Button } from "@/components/ui/button";
import { formatWorkbenchDate } from "@/components/workbench/utils";

const STATUS_CLASS: Record<WorkbenchMediaItem["status"], string> = {
    missing: "cat-status-chip--missing",
    draft: "cat-status-chip--draft",
    published: "cat-status-chip--published",
};

const MAX_ALT_PREVIEW_LENGTH = 160;

export interface MediaListProps {
    items: WorkbenchMediaItem[];
    selectedIds: Set<string>;
    onToggleSelect: (id: string) => void;
    viewMode: WorkbenchViewMode;
}

export const MediaList = ({ items, selectedIds, onToggleSelect, viewMode }: MediaListProps): React.JSX.Element => {
    if (items.length === 0) {
        return (
            <div className="cat-workbench__empty" role="status" aria-live="polite">
                <p>{__("No media requires attention right now. Adjust your filters once data is wired.", "context-alt-text")}</p>
            </div>
        );
    }

    return (
        <table
            className={`cat-workbench__table cat-workbench__table--${viewMode}`}
            aria-label={__("Media queue", "context-alt-text")}
        >
            <thead className="cat-workbench__thead">
                <tr>
                    <th scope="col" className="cat-workbench__cell cat-workbench__cell--checkbox">
                        <span className="cat-sr-only">{__("Select asset", "context-alt-text")}</span>
                    </th>
                    <th scope="col" className="cat-workbench__cell cat-workbench__cell--file">
                        {__("File", "context-alt-text")}
                    </th>
                    <th scope="col" className="cat-workbench__cell cat-workbench__cell--alt">
                        {__("Alt text preview", "context-alt-text")}
                    </th>
                    <th scope="col" className="cat-workbench__cell cat-workbench__cell--details">
                        {__("Details", "context-alt-text")}
                    </th>
                    <th scope="col" className="cat-workbench__cell cat-workbench__cell--actions">
                        {__("Actions", "context-alt-text")}
                    </th>
                </tr>
            </thead>
            <tbody className="cat-workbench__tbody">
                {items.map((item) => {
                    const isSelected = selectedIds.has(item.id);
                    const formattedUpdatedAt = formatWorkbenchDate(item.updatedAt);
                    const width = item.dimensions?.width;
                    const height = item.dimensions?.height;
                    const dimensions = width && height ? `${width}×${height}px` : null;
                    const recognitionMeta = getRecognitionMeta(item);

                    const handleRowClick: React.MouseEventHandler<HTMLTableRowElement> = (event) => {
                        const target = event.target as HTMLElement | null;
                        if (target?.closest("button, a, input")) {
                            return;
                        }

                        onToggleSelect(item.id);
                    };

                    const handleRowKeyDown: React.KeyboardEventHandler<HTMLTableRowElement> = (event) => {
                        if (event.key === " " || event.key === "Enter") {
                            event.preventDefault();
                            onToggleSelect(item.id);
                        }
                    };

                    return (
                        <tr
                            key={item.id}
                            className={`cat-workbench__row ${isSelected ? "cat-workbench__row--selected" : ""}`.trim()}
                            aria-selected={isSelected}
                            tabIndex={0}
                            onClick={handleRowClick}
                            onKeyDown={handleRowKeyDown}
                        >
                            <td className="cat-workbench__cell cat-workbench__cell--checkbox">
                                <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => onToggleSelect(item.id)}
                                    aria-label={sprintf(
                                        /* translators: %s: media title */
                                        __("Select %s", "context-alt-text"),
                                        item.title,
                                    )}
                                    onClick={(event) => event.stopPropagation()}
                                />
                            </td>
                            <td className="cat-workbench__cell cat-workbench__cell--file">
                                <div className="cat-workbench__file">
                                    <span className="cat-workbench__thumbnail" aria-hidden="true">
                                        {item.thumbnailUrl ? (
                                            <img src={item.thumbnailUrl} alt="" loading="lazy" />
                                        ) : (
                                            <span className="cat-workbench__thumbnailPlaceholder" />
                                        )}
                                    </span>
                                    <div className="cat-workbench__fileMeta">
                                        <span className={`cat-status-chip ${STATUS_CLASS[item.status]}`}>
                                            {getStatusCopy(item.status)}
                                        </span>
                                        <h3>
                                            {item.editUrl ? (
                                                <a href={item.editUrl}>{item.title}</a>
                                            ) : (
                                                item.title
                                            )}
                                        </h3>
                                        {recognitionMeta && (
                                            <p className="cat-workbench__fileMetaLine cat-workbench__fileMetaLine--recognition">
                                                {recognitionMeta}
                                            </p>
                                        )}
                                        {item.mimeType && <p className="cat-workbench__fileMetaLine">{item.mimeType}</p>}
                                    </div>
                                </div>
                            </td>
                            <td className="cat-workbench__cell cat-workbench__cell--alt">
                                <p className="cat-workbench__media-alt-value">
                                    {item.altText?.trim()?.length
                                        ? truncateAltText(item.altText)
                                        : __("Alt text not yet provided", "context-alt-text")}
                                </p>
                            </td>
                            <td className="cat-workbench__cell cat-workbench__cell--details">
                                <ul
                                    className="cat-workbench__metaList"
                                    aria-label={__("Media details", "context-alt-text")}
                                >
                                    {dimensions && <li>{dimensions}</li>}
                                    {formattedUpdatedAt && <li>{formattedUpdatedAt}</li>}
                                </ul>
                            </td>
                            <td className="cat-workbench__cell cat-workbench__cell--actions">
                                {item.editUrl && (
                                    <Button asChild variant="subtle" size="sm">
                                        <a href={item.editUrl}>{__("Edit", "context-alt-text")}</a>
                                    </Button>
                                )}
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
};

const getStatusCopy = (status: WorkbenchMediaItem["status"]): string => {
    switch (status) {
        case "missing":
            return __("Needs alt text", "context-alt-text");
        case "draft":
            return __("Draft available", "context-alt-text");
        case "published":
            return __("Alt text published", "context-alt-text");
        default:
            return __("Needs alt text", "context-alt-text");
    }
};

const truncateAltText = (value: string): string => {
    const trimmed = value.trim();
    if (trimmed.length <= MAX_ALT_PREVIEW_LENGTH) {
        return trimmed;
    }

    return `${trimmed.slice(0, MAX_ALT_PREVIEW_LENGTH - 3)}...`;
};

const getRecognitionMeta = (item: WorkbenchMediaItem): string | null => {
    const recognition = item.recognition;

    if (!recognition) {
        return null;
    }

    const { status, matchedCount, needsReviewCount, matchedRoster } = recognition;

    if (status === "matched" && matchedCount > 0) {
        const rosterName = matchedRoster?.displayName ?? matchedRoster?.name ?? matchedRoster?.remoteId ?? null;

        if (rosterName) {
            return sprintf(
                _n(
                    "Matched %1$d recognition (%2$s)",
                    "Matched %1$d recognitions (%2$s)",
                    matchedCount,
                    "context-alt-text",
                ),
                matchedCount,
                rosterName,
            );
        }

        return sprintf(
            _n(
                "Matched %d recognition",
                "Matched %d recognitions",
                matchedCount,
                "context-alt-text",
            ),
            matchedCount,
        );
    }

    if (status === "needs_review" && needsReviewCount > 0) {
        return sprintf(
            _n(
                "%d recognition needs review",
                "%d recognitions need review",
                needsReviewCount,
                "context-alt-text",
            ),
            needsReviewCount,
        );
    }

    return null;
};
