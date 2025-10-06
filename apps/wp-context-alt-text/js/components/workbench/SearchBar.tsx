import React from "react";

import { __ } from "@wordpress/i18n";

export interface SearchBarProps {
    /** Current search query */
    value: string;
    /** Callback fired whenever the search query changes */
    onSearch: (query: string) => void;
    /** Placeholder text for the input */
    placeholder?: string;
    /** Whether the search request is currently loading */
    isLoading?: boolean;
    /** Accessible label for the loading spinner */
    spinnerLabel?: string;
    /** Optional error message to display beneath the input */
    error?: string | null;
    /** Retry handler when an error is present */
    onRetry?: () => void;
    /** Screen reader announcement of search status/results */
    statusMessage?: string;
}

const CLEAR_BUTTON_SYMBOL = "×";

/**
 * Workbench search bar with debounced querying and inline status affordances.
 */
export const SearchBar = ({
    value,
    onSearch,
    placeholder = __("Search by filename or alt text...", "context-alt-text"),
    isLoading = false,
    spinnerLabel = __("Searching media", "context-alt-text"),
    error = null,
    onRetry,
    statusMessage,
}: SearchBarProps): React.JSX.Element => {
    const inputId = React.useId();
    const errorId = React.useId();
    const statusId = React.useId();

    const inputRef = React.useRef<HTMLInputElement | null>(null);

    const handleChange = React.useCallback(
        (event: React.ChangeEvent<HTMLInputElement>) => {
            onSearch(event.target.value);
        },
        [onSearch],
    );

    const handleClear = React.useCallback(() => {
        onSearch("");
        if (inputRef.current) {
            inputRef.current.focus();
        }
    }, [onSearch]);

    const describedByIds: string[] = [];
    if (error) {
        describedByIds.push(errorId);
    }
    if (statusMessage) {
        describedByIds.push(statusId);
    }

    const hasValue = value.length > 0;

    return (
        <div className="cat-search-bar">
            <label htmlFor={inputId} className="screen-reader-text">
                {__("Search media", "context-alt-text")}
            </label>
            <div className="cat-search-bar__control">
                <input
                    id={inputId}
                    type="search"
                    role="searchbox"
                    className="cat-search-bar__input"
                    ref={inputRef}
                    value={value}
                    onChange={handleChange}
                    placeholder={placeholder}
                    aria-label={__("Search media", "context-alt-text")}
                    aria-invalid={Boolean(error) || undefined}
                    aria-busy={isLoading || undefined}
                    aria-describedby={describedByIds.length > 0 ? describedByIds.join(" ") : undefined}
                />
                {isLoading && (
                    <span className="cat-search-bar__spinner" role="status" aria-live="polite" aria-label={spinnerLabel} />
                )}
                {hasValue && !isLoading && (
                    <button
                        type="button"
                        className="cat-search-bar__clear"
                        onClick={handleClear}
                        aria-label={__("Clear search", "context-alt-text")}
                        title={__("Clear search", "context-alt-text")}
                    >
                        {CLEAR_BUTTON_SYMBOL}
                    </button>
                )}
            </div>
            {error && (
                <div id={errorId} className="cat-search-bar__error" role="alert">
                    <span>{error}</span>
                    {onRetry && (
                        <button type="button" className="cat-search-bar__retry" onClick={onRetry}>
                            {__("Retry search", "context-alt-text")}
                        </button>
                    )}
                </div>
            )}
            {statusMessage && (
                <div
                    id={statusId}
                    data-testid="workbench-search-status"
                    className="screen-reader-text"
                    aria-live="polite"
                >
                    {statusMessage}
                </div>
            )}
        </div>
    );
};
