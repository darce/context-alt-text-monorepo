import React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Label } from "@/components/ui/label";

/**
 * Props for the RosterPagination component.
 */
export interface RosterPaginationProps {
    /**
     * Current page number (1-based).
     */
    page: number;

    /**
     * Total number of pages available.
     */
    totalPages: number;

    /**
     * Total number of items across all pages.
     */
    total: number;

    /**
     * Number of items displayed per page.
     */
    perPage: number;

    /**
     * Handler called when the user navigates to a different page.
     */
    onPageChange: (page: number) => void;

    /**
     * Handler called when the user changes the number of items per page.
     */
    onPerPageChange: (perPage: number) => void;

    /**
     * Whether pagination controls should be disabled.
     */
    disabled: boolean;
}

/**
 * Pagination controls for the roster table.
 *
 * Displays previous/next buttons, current page info, rows per page selector,
 * and total entry count. Automatically hides when there's only one page or less.
 *
 * @param props - Component props
 * @returns Pagination controls or empty container
 *
 * @example
 * ```tsx
 * <RosterPagination
 *     page={2}
 *     totalPages={5}
 *     total={47}
 *     perPage={10}
 *     onPageChange={(page) => setPage(page)}
 *     onPerPageChange={(perPage) => setPerPage(perPage)}
 *     disabled={isLoading}
 * />
 * ```
 */
export const RosterPagination = ({
    page,
    totalPages,
    total,
    perPage,
    onPageChange,
    onPerPageChange,
    disabled,
}: RosterPaginationProps): React.JSX.Element => {
    const showPaginationControls = totalPages > 1 || total > perPage;
    const canPrev = page > 1;
    const canNext = totalPages === 0 ? true : page < totalPages;

    return (
        <div className="cat-roster__pagination" aria-live="polite">
            {showPaginationControls && (
                <div className="cat-roster__pagination-controls">
                    <button
                        type="button"
                        className="cat-button"
                        onClick={() => onPageChange(page - 1)}
                        disabled={disabled || !canPrev}
                    >
                        {__("Previous", "context-alt-text")}
                    </button>
                    <span>
                        {sprintf(__("Page %1$d of %2$d", "context-alt-text"), page, totalPages === 0 ? 1 : totalPages)}
                    </span>
                    <button
                        type="button"
                        className="cat-button"
                        onClick={() => onPageChange(page + 1)}
                        disabled={disabled || !canNext}
                    >
                        {__("Next", "context-alt-text")}
                    </button>
                </div>
            )}
            <div className="cat-roster__pagination-meta">
                {showPaginationControls && (
                    <>
                        <Label htmlFor="cat-roster-per-page">{__("Rows per page", "context-alt-text")}</Label>
                        <Select
                            value={String(perPage)}
                            onValueChange={(value) => onPerPageChange(Number(value))}
                            disabled={disabled}
                        >
                            <SelectTrigger id="cat-roster-per-page">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {[10, 20, 50].map((value) => (
                                    <SelectItem key={value} value={String(value)}>
                                        {value}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </>
                )}
                <span>{sprintf(_n("%d entry", "%d entries", total, "context-alt-text"), total)}</span>
            </div>
        </div>
    );
};
