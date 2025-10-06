import React from "react";

import { __, sprintf } from "@wordpress/i18n";

import { Button } from "@/components/ui/button";

export interface PaginationControlsProps {
    page: number;
    perPage: number;
    total: number;
    totalPages: number;
    isLoading?: boolean;
    onPageChange: (page: number) => void;
    onPerPageChange?: (perPage: number) => void;
    perPageOptions?: number[];
}

export const PaginationControls = ({
    page,
    perPage,
    total,
    totalPages,
    isLoading = false,
    onPageChange,
    onPerPageChange,
    perPageOptions = [10, 20, 50],
}: PaginationControlsProps): React.JSX.Element | null => {
    if (total === 0) {
        return (
            <nav
                className="cat-pagination"
                aria-label={__("Workbench pagination", "context-alt-text")}
            >
                <p className="cat-pagination__status">
                    {__("No media items found", "context-alt-text")}
                </p>
            </nav>
        );
    }

    const safePage = Math.max(1, Math.min(page, Math.max(totalPages, 1)));
    const start = total === 0 ? 0 : (safePage - 1) * perPage + 1;
    const end = total === 0 ? 0 : Math.min(total, safePage * perPage);

    const showNavigationButtons = totalPages > 1 || total > perPage;

    const [pageInputValue, setPageInputValue] = React.useState<string>(() => String(safePage));

    React.useEffect(() => {
        setPageInputValue(String(safePage));
    }, [safePage]);

    const availablePerPageOptions = React.useMemo(() => {
        const unique = Array.from(new Set([...perPageOptions, perPage])).filter((value) => value > 0);
        return unique.sort((a, b) => a - b);
    }, [perPage, perPageOptions]);

    const handlePrevious = () => {
        if (safePage > 1) {
            onPageChange(safePage - 1);
        }
    };

    const handleNext = () => {
        if (totalPages === 0 || safePage < totalPages) {
            onPageChange(safePage + 1);
        }
    };

    const handlePerPageChange: React.ChangeEventHandler<HTMLSelectElement> = (event) => {
        const nextPerPage = Number.parseInt(event.target.value, 10);
        if (Number.isFinite(nextPerPage) && nextPerPage > 0 && nextPerPage !== perPage) {
            onPerPageChange?.(nextPerPage);
        }
    };

    const handlePageInputChange: React.ChangeEventHandler<HTMLInputElement> = (event) => {
        setPageInputValue(event.target.value);
    };

    const handlePageSubmit: React.FormEventHandler<HTMLFormElement> = (event) => {
        event.preventDefault();

        const nextPage = Number.parseInt(pageInputValue, 10);
        if (!Number.isFinite(nextPage)) {
            setPageInputValue(String(safePage));
            return;
        }

        const clamped = (() => {
            if (totalPages > 0) {
                return Math.min(Math.max(nextPage, 1), totalPages);
            }

            return Math.max(nextPage, 1);
        })();

        if (clamped !== safePage) {
            onPageChange(clamped);
        }

        setPageInputValue(String(clamped));
    };

    const baseStatus = total === 0
        ? ""
        : sprintf(
            /* translators: 1: first item index in the current page, 2: last item index in the current page, 3: total number of items */
            __("Showing %1$d-%2$d of %3$d", "context-alt-text"),
            start,
            end,
            total,
        );

    const statusMessage = total === 0
        ? __("No media items found", "context-alt-text")
        : isLoading
            ? sprintf(
                /* translators: 1: pagination status message, 2: indicates data is updating */
                __("%1$s (%2$s)", "context-alt-text"),
                baseStatus,
                __("updating", "context-alt-text"),
            )
            : baseStatus;

    const pageSummary = totalPages > 0
        ? sprintf(
            /* translators: 1: current page number, 2: total number of pages */
            __("Page %1$d of %2$d", "context-alt-text"),
            safePage,
            totalPages,
        )
        : sprintf(
            /* translators: %d: current page number */
            __("Page %d", "context-alt-text"),
            safePage,
        );

    return (
        <nav
            className="cat-pagination"
            aria-label={__("Workbench pagination", "context-alt-text")}
        >
            <p className="cat-pagination__status">{statusMessage}</p>
            <div
                className="cat-pagination__controls"
                role="group"
                aria-label={__("Pagination controls", "context-alt-text")}
            >
                <div className="cat-pagination__cluster">
                    <label htmlFor="cat-pagination-per-page" className="cat-pagination__label">
                        {__("Items per page", "context-alt-text")}
                    </label>
                    <select
                        id="cat-pagination-per-page"
                        className="cat-pagination__select"
                        value={perPage}
                        onChange={handlePerPageChange}
                        disabled={isLoading}
                    >
                        {availablePerPageOptions.map((option) => (
                            <option key={option} value={option}>
                                {option}
                            </option>
                        ))}
                    </select>
                </div>
                <form className="cat-pagination__jump" onSubmit={handlePageSubmit}>
                    <label htmlFor="cat-pagination-jump" className="cat-pagination__label">
                        {__("Jump to page", "context-alt-text")}
                    </label>
                    <div className="cat-pagination__jump-container">
                        <input
                            id="cat-pagination-jump"
                            type="number"
                            inputMode="numeric"
                            min={1}
                            max={totalPages > 0 ? totalPages : undefined}
                            value={pageInputValue}
                            onChange={handlePageInputChange}
                            className="cat-pagination__input"
                            aria-label={__("Jump to page", "context-alt-text")}
                            disabled={isLoading || total === 0}
                        />
                        <Button
                            type="submit"
                            variant="subtle"
                            size="sm"
                            disabled={isLoading || total === 0}
                        >
                            {__("Go", "context-alt-text")}
                        </Button>
                    </div>
                </form>
                <div className="cat-pagination__buttons">
                    <Button
                        variant="subtle"
                        size="sm"
                        onClick={handlePrevious}
                        disabled={!showNavigationButtons || safePage <= 1 || isLoading}
                    >
                        {__("Previous", "context-alt-text")}
                    </Button>
                    <span className="cat-pagination__page" aria-live="polite">
                        {pageSummary}
                    </span>
                    <Button
                        variant="subtle"
                        size="sm"
                        onClick={handleNext}
                        disabled={!showNavigationButtons || (totalPages > 0 && safePage >= totalPages) || total === 0 || isLoading}
                    >
                        {__("Next", "context-alt-text")}
                    </Button>
                </div>
            </div>
        </nav>
    );
};
