/**
 * Face Chip Component
 *
 * Interactive chip displayed on detected faces showing their label status.
 * Clickable to open PeoplePicker modal for labeling.
 *
 * States:
 * - Unknown: "Who is this?" (no label)
 * - Suggested: "Ana Rodriguez?" (FAISS suggestion)
 * - Confirmed: "Ana Rodriguez" (user-confirmed)
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import React from "react";
import { __ } from "@wordpress/i18n";
import "./FaceChip.scss";

export interface FaceChipProps {
    /** Display text (person name or "Who is this?") */
    label: string;
    /** Chip variant based on label status */
    variant: "unknown" | "suggested" | "confirmed";
    /** Whether this chip is currently focused/selected */
    isSelected: boolean;
    /** Click handler to open PeoplePicker */
    onClick: () => void;
    /** Position relative to parent container */
    position: {
        /** Top position in pixels */
        top: number;
        /** Left position in pixels */
        left: number;
    };
    /** Optional suggestion confidence score (0-1) */
    confidence?: number;
}

/**
 * Face Chip
 *
 * Shows the current label status for a detected face.
 * Clicking opens the PeoplePicker modal to assign/change the label.
 *
 * @example
 * ```tsx
 * <FaceChip
 *   label="Ana Rodriguez?"
 *   variant="suggested"
 *   isSelected={false}
 *   onClick={() => openPicker()}
 *   position={{ top: 100, left: 150 }}
 *   confidence={0.95}
 * />
 * ```
 */
export const FaceChip = ({ label, variant, isSelected, onClick, position, confidence }: FaceChipProps): JSX.Element => {
    /**
     * Handle keyboard interaction
     */
    const handleKeyDown = (event: React.KeyboardEvent): void => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onClick();
        }
    };

    /**
     * Get appropriate ARIA label based on variant
     */
    const getAriaLabel = (): string => {
        if (variant === "unknown") {
            return __("Unlabeled face. Press Enter to identify.", "context-alt-text");
        }
        if (variant === "suggested") {
            const confidenceText = confidence
                ? ` ${Math.round(confidence * 100)}% ${__("confidence", "context-alt-text")}`
                : "";
            return `${__("Suggested:", "context-alt-text")} ${label}${confidenceText}. ${__("Press Enter to confirm or change.", "context-alt-text")}`;
        }
        return `${__("Confirmed:", "context-alt-text")} ${label}. ${__("Press Enter to change.", "context-alt-text")}`;
    };

    return (
        <button
            type="button"
            className={`cat-face-chip cat-face-chip--${variant} ${isSelected ? "cat-face-chip--selected" : ""}`}
            style={{
                top: `${position.top}px`,
                left: `${position.left}px`,
            }}
            onClick={onClick}
            onKeyDown={handleKeyDown}
            aria-label={getAriaLabel()}
        >
            <span className="cat-face-chip__label">{label}</span>
            {variant === "suggested" && confidence !== undefined && (
                <span className="cat-face-chip__confidence" aria-hidden="true">
                    {Math.round(confidence * 100)}%
                </span>
            )}
        </button>
    );
};
