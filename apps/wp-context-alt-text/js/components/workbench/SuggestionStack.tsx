/**
 * Suggestion Stack Component
 *
 * Displays a group of faces matching the same roster person.
 * Shows person avatar, confidence score, and "Confirm All" action.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { __ } from "@wordpress/i18n";

export interface SuggestionStackProps {
    /** Roster person identifier */
    rosterId: string;
    /** Person's display name */
    displayName: string;
    /** Number of faces matching this person */
    count: number;
    /** Average confidence score (0-1) */
    confidence: number;
    /** Person's avatar URL */
    avatarUrl?: string;
    /** Whether this stack is currently selected */
    isSelected: boolean;
    /** Click handler to highlight faces in overlay */
    onClick: () => void;
    /** Callback to confirm all faces as this person */
    onConfirmAll: () => void;
}

/**
 * Suggestion Stack
 *
 * Shows faces that FAISS suggests match a specific roster person.
 * Provides bulk confirmation action for efficient labeling.
 *
 * @example
 * ```tsx
 * <SuggestionStack
 *   rosterId="person-123"
 *   displayName="Ana Rodriguez"
 *   count={54}
 *   confidence={0.95}
 *   avatarUrl="http://example.test/avatar.jpg"
 *   isSelected={false}
 *   onClick={() => highlightSuggestions("person-123")}
 *   onConfirmAll={() => bulkConfirm("person-123", [...])}
 * />
 * ```
 */
export const SuggestionStack = ({
    rosterId,
    displayName,
    count,
    confidence,
    avatarUrl,
    isSelected,
    onClick,
    onConfirmAll,
}: SuggestionStackProps): JSX.Element => {
    /**
     * Handle keyboard interaction for main stack
     */
    const handleKeyDown = (event: React.KeyboardEvent): void => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onClick();
        }
    };

    /**
     * Handle keyboard interaction for confirm button
     */
    const handleConfirmKeyDown = (event: React.KeyboardEvent): void => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            event.stopPropagation();
            onConfirmAll();
        }
    };

    /**
     * Handle confirm button click
     */
    const handleConfirmClick = (event: React.MouseEvent): void => {
        event.stopPropagation();
        onConfirmAll();
    };

    /**
     * Format confidence as percentage
     */
    const confidencePercent = Math.round(confidence * 100);

    return (
        <div
            className={`cat-suggestion-stack ${isSelected ? "cat-suggestion-stack--selected" : ""}`}
            onClick={onClick}
            onKeyDown={handleKeyDown}
            role="button"
            tabIndex={0}
            aria-label={`${displayName}, ${confidencePercent}% ${__("confidence", "context-alt-text")}, ${count} ${__("faces", "context-alt-text")}`}
        >
            <div className="cat-suggestion-stack__avatar">
                {avatarUrl ? (
                    <img src={avatarUrl} alt="" aria-hidden="true" className="cat-suggestion-stack__image" />
                ) : (
                    <div className="cat-suggestion-stack__placeholder" aria-hidden="true">
                        {displayName.charAt(0).toUpperCase()}
                    </div>
                )}
                <span className="cat-suggestion-stack__badge" aria-hidden="true">
                    {count}
                </span>
            </div>

            <div className="cat-suggestion-stack__content">
                <h4 className="cat-suggestion-stack__title">{displayName}?</h4>
                <p className="cat-suggestion-stack__meta">
                    <span className="cat-suggestion-stack__confidence">
                        {confidencePercent}% {__("confidence", "context-alt-text")}
                    </span>
                    <span className="cat-suggestion-stack__separator" aria-hidden="true">
                        •
                    </span>
                    <span className="cat-suggestion-stack__count">
                        {count} {count === 1 ? __("face", "context-alt-text") : __("faces", "context-alt-text")}
                    </span>
                </p>
            </div>

            <button
                type="button"
                className="cat-suggestion-stack__action"
                onClick={handleConfirmClick}
                onKeyDown={handleConfirmKeyDown}
                aria-label={`${__("Confirm all as", "context-alt-text")} ${displayName}`}
            >
                {__("Confirm All", "context-alt-text")}
            </button>
        </div>
    );
};
