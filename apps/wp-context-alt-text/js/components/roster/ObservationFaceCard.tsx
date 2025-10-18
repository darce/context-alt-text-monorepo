/**
 * ObservationFaceCard Component
 *
 * Displays a single face observation with preview, metadata, and assignment actions.
 * Allows assigning to existing roster entry or creating a new one.
 */

import * as React from "react";
import { __, sprintf } from "@wordpress/i18n";
import { ObservationPreview } from "./ObservationPreview";
import {
    getTopCandidate,
    resolveSuggestedMatchLabel,
    getRosterConfidenceValue,
    formatPercentage,
    resolveSuggestedRemoteId,
    getSelectedRemoteId,
} from "@/utils/rosterHelpers";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import type { RosterEntry, RecognitionObservationAttachment, RecognitionObservationRecord } from "@/admin/types";

export interface ObservationFaceCardProps {
    /** Observation record for this face */
    record: RecognitionObservationRecord;
    /** Parent attachment containing this observation */
    attachment: RecognitionObservationAttachment;
    /** All roster entries for assignment selection */
    assignableEntries: RosterEntry[];
    /** Lookup map for fast entry retrieval */
    assignableEntryLookup: Map<string, RosterEntry>;
    /** Current user selection state */
    selection: Record<string, string>;
    /** Whether this observation is currently being assigned */
    isAssigning: boolean;
    /** Callback when user changes roster selection */
    onSelectionChange: (observationId: string, remoteId: string) => void;
    /** Callback to assign observation to selected entry */
    onAssign: (
        record: RecognitionObservationRecord,
        attachment: RecognitionObservationAttachment,
        suggestedRemoteId: string | null,
    ) => Promise<void> | void;
    /** Callback to create new roster entry from observation */
    onCreate: (record: RecognitionObservationRecord, attachment: RecognitionObservationAttachment) => void;
}

/**
 * ObservationFaceCard - Individual face observation card
 *
 * Features:
 * - Displays face preview with bounding box highlight
 * - Shows suggested roster match with confidence
 * - Provides dropdown to select assignment target
 * - Offers "Assign" and "Create new" action buttons
 * - Handles loading states during assignment
 */
export const ObservationFaceCard = ({
    record,
    attachment,
    assignableEntries,
    assignableEntryLookup,
    selection,
    isAssigning,
    onSelectionChange,
    onAssign,
    onCreate,
}: ObservationFaceCardProps): React.JSX.Element => {
    const displayLabel = record.label || record.entityType || __("Observation", "context-alt-text");

    const topCandidate = React.useMemo(() => getTopCandidate(record), [record]);

    const rosterMatch = React.useMemo(
        () => resolveSuggestedMatchLabel(record, assignableEntryLookup, topCandidate),
        [record, assignableEntryLookup, topCandidate],
    );

    const rosterConfidenceValue = React.useMemo(
        () => getRosterConfidenceValue(record, topCandidate),
        [record, topCandidate],
    );

    const confidenceDisplay = React.useMemo(() => formatPercentage(rosterConfidenceValue), [rosterConfidenceValue]);

    const suggestedRemoteId = React.useMemo(
        () => resolveSuggestedRemoteId(record, assignableEntryLookup, topCandidate),
        [record, assignableEntryLookup, topCandidate],
    );

    const selectedRemoteId = React.useMemo(
        () => getSelectedRemoteId(record, selection, suggestedRemoteId),
        [record, selection, suggestedRemoteId],
    );

    const handleAssign = React.useCallback(() => {
        void onAssign(record, attachment, suggestedRemoteId);
    }, [record, attachment, suggestedRemoteId, onAssign]);

    const handleCreate = React.useCallback(() => {
        onCreate(record, attachment);
    }, [record, attachment, onCreate]);

    const handleSelectionChange = React.useCallback(
        (value: string) => {
            onSelectionChange(record.observationId ?? "", value);
        },
        [record.observationId, onSelectionChange],
    );

    const placeholderText =
        assignableEntries.length === 0
            ? __("No synced roster entries available", "context-alt-text")
            : __("Select roster entry", "context-alt-text");

    return (
        <li key={record.observationId} className="cat-roster__observations-face">
            <ObservationPreview record={record} attachment={attachment} />

            <div className="cat-roster__observations-face-details">
                <span className="cat-roster__observations-label">{displayLabel}</span>

                {rosterMatch && (
                    <span className="cat-roster__observations-meta">
                        {sprintf(__("Suggested match: %s", "context-alt-text"), rosterMatch)}
                    </span>
                )}

                {confidenceDisplay && (
                    <span className="cat-roster__observations-meta">
                        {sprintf(__("Match confidence %s", "context-alt-text"), confidenceDisplay)}
                    </span>
                )}
            </div>

            <div className="cat-roster__observations-face-actions">
                <Select
                    value={selectedRemoteId}
                    onValueChange={handleSelectionChange}
                    disabled={assignableEntries.length === 0 || isAssigning}
                >
                    <SelectTrigger aria-label={__("Select roster entry", "context-alt-text")}>
                        <SelectValue placeholder={placeholderText} />
                    </SelectTrigger>
                    <SelectContent>
                        {assignableEntries.map((entryOption) => (
                            <SelectItem key={entryOption.remoteId ?? ""} value={entryOption.remoteId ?? ""}>
                                {entryOption.label} ({entryOption.type})
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>

                <button
                    type="button"
                    className="cat-button cat-button--primary"
                    onClick={handleAssign}
                    disabled={assignableEntries.length === 0 || !selectedRemoteId || isAssigning}
                >
                    {isAssigning
                        ? __("Assigning…", "context-alt-text")
                        : __("Assign existing entry", "context-alt-text")}
                </button>

                <button
                    type="button"
                    className="cat-button cat-button--subtle"
                    onClick={handleCreate}
                    disabled={isAssigning}
                >
                    {__("Create new entry", "context-alt-text")}
                </button>
            </div>
        </li>
    );
};
