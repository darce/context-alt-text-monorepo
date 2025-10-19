/**
 * ObservationAssignmentDialog Component
 *
 * Modal dialog for displaying observation details that require roster assignment review.
 * Uses Radix Dialog primitive for accessible modal behavior.
 */

import * as React from "react";
import { __ } from "@wordpress/i18n";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { RecognitionObservationAttachment, RecognitionObservationRecord } from "@/admin/types";
import type { ObservationPromptState } from "@/admin/hooks/useRosterState";
import { getTopCandidate, getRosterConfidenceValue, formatPercentage } from "@/admin/utils/rosterHelpers";

export interface ObservationAssignmentDialogProps {
    /** Whether the dialog is open */
    isOpen: boolean;
    /** The observation prompt state containing basic observation info */
    prompt: ObservationPromptState | null;
    /** Optional detailed observation and attachment data */
    details?: {
        record: RecognitionObservationRecord;
        attachment: RecognitionObservationAttachment;
    } | null;
    /** Callback when dialog should be dismissed */
    onDismiss: () => void;
}

/**
 * ObservationAssignmentDialog - Displays observation details in a modal dialog
 */
export const ObservationAssignmentDialog = ({
    isOpen,
    prompt,
    details,
    onDismiss,
}: ObservationAssignmentDialogProps): React.JSX.Element => {
    // Don't compute anything if no prompt
    if (!prompt) {
        // Return empty dialog that won't render
        return (
            <Dialog open={false} onOpenChange={onDismiss}>
                <DialogContent>
                    <DialogTitle>{""}</DialogTitle>
                </DialogContent>
            </Dialog>
        );
    }

    // Resolve source label
    const sourceLabel = (() => {
        if (!prompt.source) {
            return __("Unknown", "context-alt-text");
        }

        if (prompt.source.toLowerCase() === "recognition") {
            return __("Recognition workbench", "context-alt-text");
        }

        return prompt.source;
    })();

    // Build details list
    const detailItems: { label: string; value: string }[] = [
        { label: __("Observation ID", "context-alt-text"), value: prompt.observationId },
    ];

    if (prompt.attachmentId) {
        detailItems.push({
            label: __("Attachment ID", "context-alt-text"),
            value: String(prompt.attachmentId),
        });
    }

    if (prompt.label) {
        detailItems.push({
            label: __("Suggested label", "context-alt-text"),
            value: prompt.label,
        });
    }

    if (prompt.source) {
        detailItems.push({
            label: __("Source", "context-alt-text"),
            value: sourceLabel,
        });
    }

    if (details?.attachment?.context?.filename) {
        detailItems.push({
            label: __("Filename", "context-alt-text"),
            value: details.attachment.context.filename,
        });
    }

    const topCandidate = details?.record ? getTopCandidate(details.record) : null;
    const suggestedMatchLabel = details?.record
        ? (details.record.roster?.displayName ??
          details.record.roster?.name ??
          topCandidate?.name ??
          topCandidate?.remoteId ??
          null)
        : null;

    if (suggestedMatchLabel) {
        detailItems.push({
            label: __("Suggested match", "context-alt-text"),
            value: suggestedMatchLabel,
        });
    }

    const confidenceDisplay = details?.record
        ? formatPercentage(getRosterConfidenceValue(details.record, topCandidate))
        : null;

    if (confidenceDisplay) {
        detailItems.push({
            label: __("Match confidence", "context-alt-text"),
            value: confidenceDisplay,
        });
    }

    const similarityDisplay = details?.record?.match ? formatPercentage(details.record.match.similarity) : null;

    if (similarityDisplay) {
        detailItems.push({
            label: __("Match similarity", "context-alt-text"),
            value: similarityDisplay,
        });
    }

    const thresholdDisplay = details?.record?.match ? formatPercentage(details.record.match.threshold) : null;

    if (thresholdDisplay) {
        detailItems.push({
            label: __("Match threshold", "context-alt-text"),
            value: thresholdDisplay,
        });
    }

    const message = prompt.remoteId
        ? __(
              "This observation is linked to an existing roster entry. Review and save to continue embedding processing.",
              "context-alt-text",
          )
        : __(
              "Create or update the roster entry to kick off embedding generation for this observation.",
              "context-alt-text",
          );

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onDismiss()}>
            <DialogContent className="cat-dialog-content--large">
                <DialogTitle>{__("Observation requires roster review", "context-alt-text")}</DialogTitle>
                <DialogDescription>{message}</DialogDescription>

                <div className="cat-roster__observation-callout-body">
                    {detailItems.length > 0 && (
                        <dl className="cat-roster__observation-details">
                            {detailItems.map((item) => (
                                <div key={`${item.label}-${item.value}`}>
                                    <dt>{item.label}</dt>
                                    <dd>{item.value}</dd>
                                </div>
                            ))}
                        </dl>
                    )}
                </div>

                <div className="cat-dialog-footer">
                    <button type="button" className="cat-button cat-button--subtle" onClick={onDismiss}>
                        {__("Dismiss prompt", "context-alt-text")}
                    </button>
                </div>
            </DialogContent>
        </Dialog>
    );
};
