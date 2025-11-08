import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import "./SuggestionChip.scss";

export interface SuggestionChipProps {
    displayName: string;
    confidence?: number | null;
    reason?: string | null;
    onSelect?: () => void;
    disabled?: boolean;
}

const formatConfidence = (confidence: number | null | undefined): string | null => {
    if (typeof confidence !== "number" || Number.isNaN(confidence)) {
        return null;
    }

    const percent = Math.round(Math.max(0, Math.min(confidence, 1)) * 100);
    return sprintf(__("%d%% confidence", "context-alt-text"), percent);
};

export const SuggestionChip = ({
    displayName,
    confidence = null,
    reason,
    onSelect,
    disabled = false,
}: SuggestionChipProps): React.JSX.Element => {
    const confidenceLabel = formatConfidence(confidence);
    const label = __("Suggested match", "context-alt-text");

    if (onSelect) {
        return (
            <button
                type="button"
                className="cat-suggestion-chip cat-suggestion-chip--interactive"
                onClick={onSelect}
                disabled={disabled}
                aria-label={`${label}: ${displayName}${confidenceLabel ? `, ${confidenceLabel}` : ""}`}
            >
                <span className="cat-suggestion-chip__label">{label}</span>
                <span className="cat-suggestion-chip__name">{displayName}</span>
                {confidenceLabel && <span className="cat-suggestion-chip__confidence">{confidenceLabel}</span>}
                {reason && <span className="cat-suggestion-chip__reason">{reason}</span>}
            </button>
        );
    }

    return (
        <div className="cat-suggestion-chip" role="note" aria-label={label}>
            <span className="cat-suggestion-chip__label">{label}</span>
            <span className="cat-suggestion-chip__name">{displayName}</span>
            {confidenceLabel && <span className="cat-suggestion-chip__confidence">{confidenceLabel}</span>}
            {reason && <span className="cat-suggestion-chip__reason">{reason}</span>}
        </div>
    );
};
