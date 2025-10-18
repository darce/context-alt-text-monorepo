/**
 * ObservationPanel Component
 *
 * Displays recognition observations awaiting review with candidate matching and assignment UI.
 * Allows creating new roster entries or assigning to existing ones.
 */

import * as React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";
import { ObservationAttachmentGroup } from "./ObservationAttachmentGroup";
import { getSelectedRemoteId } from "@/utils/rosterHelpers";
import type {
    RosterEntry,
    RecognitionObservationAttachment,
    RecognitionObservationRecord,
    RecognitionObservationSummary,
} from "@/admin/types";

export interface ObservationPanelProps {
    attachments: RecognitionObservationAttachment[];
    summary: RecognitionObservationSummary;
    isLoading: boolean;
    error: Error | null;
    hasEndpoint: boolean;
    entries: RosterEntry[];
    onCreate: (record: RecognitionObservationRecord, attachment: RecognitionObservationAttachment) => void;
    onAssign: (
        record: RecognitionObservationRecord,
        attachment: RecognitionObservationAttachment,
        remoteId: string,
    ) => Promise<void> | void;
    onRefresh: () => void | Promise<void>;
}

/**
 * ObservationPanel - Main component for displaying and managing observations
 *
 * Features:
 * - Displays pending observations grouped by attachment
 * - Shows summary statistics and refresh action
 * - Orchestrates assignment and creation workflows
 * - Manages selection state across all observations
 */
export const ObservationPanel = ({
    attachments,
    summary,
    isLoading,
    error,
    hasEndpoint,
    entries,
    onCreate,
    onAssign,
    onRefresh,
}: ObservationPanelProps): React.JSX.Element => {
    const pendingCount = Math.max(0, summary.observations.needs_review);
    const attachmentCount = Math.max(0, summary.attachments);

    const assignableEntries = React.useMemo(
        () => entries.filter((entry) => entry.remoteId && entry.remoteId.trim() !== ""),
        [entries],
    );

    const assignableEntryLookup = React.useMemo(() => {
        const lookup = new Map<string, RosterEntry>();
        for (const entry of assignableEntries) {
            if (entry.remoteId) {
                lookup.set(entry.remoteId, entry);
            }
        }
        return lookup;
    }, [assignableEntries]);

    const [selection, setSelection] = React.useState<Record<string, string>>({});
    const [assigningId, setAssigningId] = React.useState<string | null>(null);

    const pendingAttachments = React.useMemo(
        () =>
            attachments
                .map((attachment) => {
                    const pending = attachment.observations.filter((record) => record.status === "needs_review");
                    return { attachment, pending };
                })
                .filter((item) => item.pending.length > 0),
        [attachments],
    );

    React.useEffect(() => {
        const validObservationIds = new Set<string>();
        for (const attachment of attachments) {
            for (const record of attachment.observations) {
                if (record.status !== "needs_review") continue;
                if (record.observationId) validObservationIds.add(record.observationId);
            }
        }
        setSelection((current) => {
            const next = { ...current };
            let changed = false;
            for (const key of Object.keys(next)) {
                if (!validObservationIds.has(key)) {
                    delete next[key];
                    changed = true;
                }
            }
            return changed ? next : current;
        });
    }, [attachments]);

    const handleAssign = React.useCallback(
        async (
            record: RecognitionObservationRecord,
            attachment: RecognitionObservationAttachment,
            suggestedRemoteId: string | null,
        ) => {
            const remoteId = getSelectedRemoteId(record, selection, suggestedRemoteId);
            if (!remoteId) return;

            try {
                setAssigningId(record.observationId ?? null);
                await Promise.resolve(onAssign(record, attachment, remoteId));
                setSelection((current) => {
                    const next = { ...current };
                    delete next[record.observationId ?? ""];
                    return next;
                });
            } finally {
                setAssigningId(null);
            }
        },
        [onAssign, selection],
    );

    const handleSelectionChange = React.useCallback((observationId: string, remoteId: string) => {
        setSelection((current) => ({
            ...current,
            [observationId]: remoteId,
        }));
    }, []);

    return (
        <section className="cat-roster__observations" aria-live="polite">
            {!hasEndpoint ? (
                <>
                    <h3>{__("Recognition observations", "context-alt-text")}</h3>
                    <p className="cat-roster__observations-status">
                        {__(
                            "Recognition observations are unavailable. Enable the recognition feature flag to manage detected faces.",
                            "context-alt-text",
                        )}
                    </p>
                </>
            ) : (
                <>
                    <header className="cat-roster__observations-header">
                        <div>
                            <h3>{__("Recognition observations awaiting review", "context-alt-text")}</h3>
                            <p>
                                {pendingCount > 0
                                    ? sprintf(
                                          _n(
                                              "%1$d face across %2$d attachment requires a roster assignment.",
                                              "%1$d faces across %2$d attachments require roster assignments.",
                                              pendingCount,
                                              "context-alt-text",
                                          ),
                                          pendingCount,
                                          attachmentCount,
                                      )
                                    : __(
                                          "Faces detected by recognition will appear here when they require review.",
                                          "context-alt-text",
                                      )}
                            </p>
                        </div>
                        <div className="cat-roster__observations-actions">
                            <button
                                type="button"
                                className="cat-button cat-button--subtle"
                                onClick={() => void onRefresh()}
                                disabled={isLoading}
                            >
                                {isLoading
                                    ? __("Re-running…", "context-alt-text")
                                    : __("Re-run recognition", "context-alt-text")}
                            </button>
                        </div>
                    </header>

                    {error && (
                        <div className="cat-alert cat-alert--error" role="alert">
                            <span>{error.message}</span>
                        </div>
                    )}

                    {isLoading && pendingAttachments.length === 0 ? (
                        <p className="cat-roster__observations-status">
                            {__("Loading observations…", "context-alt-text")}
                        </p>
                    ) : null}

                    {!isLoading && pendingAttachments.length === 0 ? (
                        <p className="cat-roster__observations-status">
                            {__("No recognition observations require review right now.", "context-alt-text")}
                        </p>
                    ) : null}

                    {pendingAttachments.length > 0 && (
                        <ul className="cat-roster__observations-list">
                            {pendingAttachments.map(({ attachment, pending }) => (
                                <ObservationAttachmentGroup
                                    key={`${attachment.attachmentId ?? "unknown"}-${attachment.jobId ?? "job"}`}
                                    attachment={attachment}
                                    pending={pending}
                                    assignableEntries={assignableEntries}
                                    assignableEntryLookup={assignableEntryLookup}
                                    selection={selection}
                                    assigningId={assigningId}
                                    onSelectionChange={handleSelectionChange}
                                    onAssign={handleAssign}
                                    onCreate={onCreate}
                                />
                            ))}
                        </ul>
                    )}
                </>
            )}
        </section>
    );
};
