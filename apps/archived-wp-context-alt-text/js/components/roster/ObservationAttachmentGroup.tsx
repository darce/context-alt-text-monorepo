/**
 * ObservationAttachmentGroup Component
 *
 * Groups face observations by their parent attachment/media item.
 * Displays attachment header with metadata and renders child face cards.
 */

import * as React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";
import { ObservationFaceCard } from "./ObservationFaceCard";
import type { RosterEntry, RecognitionObservationAttachment, RecognitionObservationRecord } from "@/admin/types";

export interface ObservationAttachmentGroupProps {
    /** Attachment containing observations */
    attachment: RecognitionObservationAttachment;
    /** Pending observations needing review */
    pending: RecognitionObservationRecord[];
    /** All roster entries for assignment selection */
    assignableEntries: RosterEntry[];
    /** Lookup map for fast entry retrieval */
    assignableEntryLookup: Map<string, RosterEntry>;
    /** Current user selection state */
    selection: Record<string, string>;
    /** ID of observation currently being assigned */
    assigningId: string | null;
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
 * ObservationAttachmentGroup - Groups observations by attachment
 *
 * Features:
 * - Displays attachment name and link to media
 * - Shows count of pending faces
 * - Renders individual face cards for each observation
 * - Manages selection and assignment state per face
 */
export const ObservationAttachmentGroup = ({
    attachment,
    pending,
    assignableEntries,
    assignableEntryLookup,
    selection,
    assigningId,
    onSelectionChange,
    onAssign,
    onCreate,
}: ObservationAttachmentGroupProps): React.JSX.Element => {
    const attachmentId = attachment.attachmentId;
    const displayName =
        attachment.context?.filename ??
        (attachmentId
            ? sprintf(__("Attachment %d", "context-alt-text"), attachmentId)
            : __("Media item", "context-alt-text"));
    const unresolved = pending.length;

    return (
        <li key={`${attachmentId ?? "unknown"}-${attachment.jobId ?? "job"}`} className="cat-roster__observations-item">
            <div className="cat-roster__observations-attachment">
                <div>
                    <strong>{displayName}</strong>
                    {attachment.context?.imageUrl && (
                        <a
                            href={attachment.context.imageUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="cat-roster__observations-link"
                        >
                            {__("Open", "context-alt-text")}
                        </a>
                    )}
                </div>
                <span className="cat-roster__observations-count">
                    {sprintf(
                        _n("%d face needs review", "%d faces need review", unresolved, "context-alt-text"),
                        unresolved,
                    )}
                </span>
            </div>

            <ul className="cat-roster__observations-faces">
                {pending.map((record) => (
                    <ObservationFaceCard
                        key={record.observationId}
                        record={record}
                        attachment={attachment}
                        assignableEntries={assignableEntries}
                        assignableEntryLookup={assignableEntryLookup}
                        selection={selection}
                        isAssigning={assigningId === (record.observationId ?? null)}
                        onSelectionChange={onSelectionChange}
                        onAssign={onAssign}
                        onCreate={onCreate}
                    />
                ))}
            </ul>
        </li>
    );
};
