/**
 * People Picker Component
 *
 * Modal for selecting or creating roster persons when labeling faces.
 * Features typeahead search with keyboard navigation.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React, { useEffect, useRef, useState } from "react";
import { __ } from "@wordpress/i18n";
import { useRosterSearch } from "@/hooks/useRosterSearch";
import type { RosterPerson } from "@/types/people-labeling";
import "./PeoplePicker.scss";

export interface PeoplePickerProps {
    /** Whether picker is open */
    isOpen: boolean;
    /** Callback to close picker */
    onClose: () => void;
    /** Callback when user selects existing person */
    onSelect: (rosterId: string, displayName: string) => void;
    /** Callback when user creates new person */
    onCreateNew: (displayName: string) => void;
    /** Currently assigned roster ID (for corrections) */
    currentRosterId?: string;
    /** WordPress REST nonce */
    restNonce?: string;
    /** Position hint for modal placement */
    position?: {
        top: number;
        left: number;
    };
}

/**
 * People Picker
 *
 * Search modal for assigning faces to roster persons.
 * Shows typeahead results with keyboard navigation.
 *
 * @example
 * ```tsx
 * <PeoplePicker
 *   isOpen={showPicker}
 *   onClose={() => setShowPicker(false)}
 *   onSelect={(id) => handleLabel(id)}
 *   onCreateNew={(name) => handleCreate(name)}
 *   currentRosterId="person-123"
 *   restNonce={window.catAltText?.restNonce}
 * />
 * ```
 */
export const PeoplePicker = ({
    isOpen,
    onClose,
    onSelect,
    onCreateNew,
    currentRosterId,
    restNonce,
    position,
}: PeoplePickerProps): JSX.Element | null => {
    const { query, setQuery, results, isLoading, reset } = useRosterSearch({
        debounceMs: 300,
        restNonce,
    });

    const [highlightedIndex, setHighlightedIndex] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);

    /**
     * Get current person name (if correcting)
     */
    const currentPerson = results?.find((p) => p.uniqueId === currentRosterId);

    /**
     * Compute options list (create new + search results)
     */
    const options: (RosterPerson | { uniqueId: "__create__"; displayName: string })[] = React.useMemo(() => {
        const opts: (RosterPerson | { uniqueId: "__create__"; displayName: string })[] = [];

        // "Create new" option (always first)
        if (query.trim().length > 0) {
            opts.push({
                uniqueId: "__create__",
                displayName: query.trim(),
            });
        }

        // Search results (guard against undefined)
        if (results) {
            opts.push(...results);
        }

        return opts;
    }, [query, results]);

    /**
     * Focus input when opened
     */
    useEffect(() => {
        if (isOpen && inputRef.current) {
            inputRef.current.focus();
        }
    }, [isOpen]);

    /**
     * Reset state when opened
     */
    useEffect(() => {
        if (isOpen) {
            reset();
            setHighlightedIndex(0);
        }
    }, [isOpen, reset]);

    /**
     * Scroll highlighted item into view
     */
    useEffect(() => {
        if (listRef.current) {
            const items = listRef.current.querySelectorAll(".cat-people-picker__item");
            const highlightedItem = items[highlightedIndex];
            if (highlightedItem) {
                highlightedItem.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }
        }
    }, [highlightedIndex]);

    /**
     * Handle keyboard navigation
     */
    const handleKeyDown = (event: React.KeyboardEvent): void => {
        if (event.key === "Escape") {
            event.preventDefault();
            onClose();
            return;
        }

        if (event.key === "ArrowDown") {
            event.preventDefault();
            setHighlightedIndex((prev) => Math.min(prev + 1, options.length - 1));
            return;
        }

        if (event.key === "ArrowUp") {
            event.preventDefault();
            setHighlightedIndex((prev) => Math.max(prev - 1, 0));
            return;
        }

        if (event.key === "Enter") {
            event.preventDefault();
            const selectedOption = options[highlightedIndex];
            if (selectedOption) {
                handleSelect(selectedOption);
            }
            return;
        }
    };

    /**
     * Handle option selection
     */
    const handleSelect = (option: RosterPerson | { uniqueId: "__create__"; displayName: string }): void => {
        if (option.uniqueId === "__create__") {
            onCreateNew(option.displayName);
        } else {
            onSelect(option.uniqueId, option.displayName);
        }
        onClose();
    };

    /**
     * Handle overlay click (close on click outside)
     */
    const handleOverlayClick = (event: React.MouseEvent): void => {
        if (event.target === event.currentTarget) {
            onClose();
        }
    };

    if (!isOpen) {
        return null;
    }

    return (
        <div className="cat-people-picker-overlay" onClick={handleOverlayClick} role="presentation">
            <div
                className="cat-people-picker"
                style={
                    position
                        ? {
                              top: `${position.top}px`,
                              left: `${position.left}px`,
                          }
                        : undefined
                }
                role="dialog"
                aria-modal="true"
                aria-labelledby="cat-people-picker-title"
            >
                <div className="cat-people-picker__header">
                    <h3 id="cat-people-picker-title" className="cat-people-picker__title">
                        {__("Who is this?", "context-alt-text")}
                    </h3>
                    {currentPerson && (
                        <p className="cat-people-picker__current">
                            {__("Currently:", "context-alt-text")} <strong>{currentPerson.displayName}</strong>
                        </p>
                    )}
                </div>

                <div className="cat-people-picker__search">
                    <input
                        ref={inputRef}
                        type="text"
                        className="cat-people-picker__input"
                        placeholder={__("Search or create new person", "context-alt-text")}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onKeyDown={handleKeyDown}
                        aria-label={__("Search roster", "context-alt-text")}
                        aria-autocomplete="list"
                        aria-controls="cat-people-picker-list"
                        aria-activedescendant={
                            options[highlightedIndex] ? `cat-people-picker-option-${highlightedIndex}` : undefined
                        }
                    />
                </div>

                <div ref={listRef} id="cat-people-picker-list" className="cat-people-picker__results" role="listbox">
                    {isLoading && (
                        <div className="cat-people-picker__loading">
                            <span className="cat-people-picker__spinner" aria-hidden="true" />
                            <span>{__("Searching...", "context-alt-text")}</span>
                        </div>
                    )}

                    {!isLoading && options.length === 0 && query.trim().length === 0 && (
                        <div className="cat-people-picker__empty">
                            <p>{__("Start typing to search", "context-alt-text")}</p>
                        </div>
                    )}

                    {!isLoading && options.length === 0 && query.trim().length > 0 && (
                        <div className="cat-people-picker__empty">
                            <p>{__("No results found", "context-alt-text")}</p>
                        </div>
                    )}

                    {!isLoading &&
                        options.map((option, index) => {
                            const isCreateNew = option.uniqueId === "__create__";
                            const isHighlighted = index === highlightedIndex;

                            return (
                                <div
                                    key={option.uniqueId}
                                    id={`cat-people-picker-option-${index}`}
                                    className={`cat-people-picker__item ${
                                        isHighlighted ? "cat-people-picker__item--highlighted" : ""
                                    } ${isCreateNew ? "cat-people-picker__item--create-new" : ""}`}
                                    role="option"
                                    aria-selected={isHighlighted}
                                    onClick={() => handleSelect(option)}
                                    onMouseEnter={() => setHighlightedIndex(index)}
                                >
                                    <div className="cat-people-picker__item-avatar">
                                        {isCreateNew ? (
                                            <span className="cat-people-picker__item-icon" aria-hidden="true">
                                                +
                                            </span>
                                        ) : (
                                            <>
                                                {"avatarUrl" in option && option.avatarUrl ? (
                                                    <img
                                                        src={option.avatarUrl}
                                                        alt=""
                                                        aria-hidden="true"
                                                        className="cat-people-picker__item-image"
                                                    />
                                                ) : (
                                                    <div
                                                        className="cat-people-picker__item-placeholder"
                                                        aria-hidden="true"
                                                    >
                                                        {option.displayName.charAt(0).toUpperCase()}
                                                    </div>
                                                )}
                                            </>
                                        )}
                                    </div>

                                    <div className="cat-people-picker__item-content">
                                        {isCreateNew ? (
                                            <>
                                                <span className="cat-people-picker__item-label">
                                                    {__("Create new:", "context-alt-text")}
                                                </span>
                                                <span className="cat-people-picker__item-name">
                                                    {option.displayName}
                                                </span>
                                            </>
                                        ) : (
                                            <span className="cat-people-picker__item-name">{option.displayName}</span>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                </div>

                <div className="cat-people-picker__footer">
                    <p className="cat-people-picker__hint">
                        {__("Use ↑↓ to navigate, Enter to select, Esc to cancel", "context-alt-text")}
                    </p>
                </div>
            </div>
        </div>
    );
};
