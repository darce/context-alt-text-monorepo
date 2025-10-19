import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { __, sprintf, _n } from "@wordpress/i18n";
import type { RosterEntry, RecognitionObservationAttachment, RecognitionObservationRecord } from "@/admin/types";
import type { RosterFormValues } from "@/admin/hooks/useRoster";
import type { RosterStateActions } from "@/admin/hooks/useRosterState";
import { dispatchNotice, notifyError } from "@/admin/notices";
import { buildObservationSearchParams } from "@/admin/utils/rosterHelpers";

/**
 * Options for useRosterEventHandlers hook.
 */
export interface UseRosterEventHandlersOptions {
    /** Array of roster entries */
    entries: RosterEntry[];
    /** Current search input value */
    searchInput: string;
    /** Current observation prompt state */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    observationPrompt: any;
    /** Currently editing entry */
    editing: RosterEntry | null;
    /** State management actions from useRosterState */
    actions: RosterStateActions;
    /** Function to create a new roster entry */
    createEntry: (values: RosterFormValues) => Promise<{ entry: RosterEntry | null; autoMatched?: any[] } | null>; // eslint-disable-line @typescript-eslint/no-explicit-any
    /** Function to update an existing roster entry */
    updateEntry: (values: RosterFormValues) => Promise<RosterEntry | null>;
    /** Function to delete a roster entry */
    deleteEntry: (remoteId: string) => Promise<boolean>;
    /** Function to sync roster with server */
    syncRoster: () => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    /** Function to refetch observations */
    refetchObservations: () => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
    /** Whether observation endpoint is available */
    hasObservationEndpoint: boolean;
}

/**
 * Return type for useRosterEventHandlers hook.
 */
export interface UseRosterEventHandlersResult {
    /** Handle observation selection and populate form */
    handleObservationSelect: (
        record: RecognitionObservationRecord,
        attachment: RecognitionObservationAttachment,
    ) => void;
    /** Handle assigning observation to roster entry */
    handleAssignToRoster: (
        record: RecognitionObservationRecord,
        attachment: RecognitionObservationAttachment,
        remoteId: string,
    ) => Promise<void>;
    /** Handle form submission (create or update) */
    handleSubmit: (values: RosterFormValues) => Promise<void>;
    /** Handle deleting a roster entry */
    handleDelete: (remoteId: string) => Promise<void>;
    /** Handle syncing roster with server */
    handleSync: () => Promise<void>;
    /** Handle clearing status filter */
    handleClearStatusFilter: () => void;
}

/**
 * Custom hook that encapsulates all event handler logic for RosterRoute.
 * Extracts complex handlers to reduce main component complexity.
 *
 * @param options - Configuration options
 * @returns Event handler functions
 */
export const useRosterEventHandlers = ({
    entries,
    searchInput,
    observationPrompt,
    editing,
    actions,
    createEntry,
    updateEntry,
    deleteEntry,
    syncRoster,
    refetchObservations,
    hasObservationEndpoint,
}: UseRosterEventHandlersOptions): UseRosterEventHandlersResult => {
    const location = useLocation();
    const navigate = useNavigate();

    /**
     * Handle observation selection - populates form with observation data
     * and updates URL parameters for deep linking.
     */
    const handleObservationSelect = React.useCallback(
        (record: RecognitionObservationRecord, attachment: RecognitionObservationAttachment) => {
            if (!record?.observationId) {
                return;
            }

            const params = buildObservationSearchParams(record, attachment.attachmentId ?? null);
            const nextPrompt = {
                observationId: record.observationId,
                attachmentId: attachment.attachmentId ?? null,
                source: "recognition",
                remoteId: record.roster?.remoteId ?? null,
                label: record.label ?? null,
            };

            actions.setObservationPrompt(nextPrompt);

            const nextDraft = {
                label: record.label ?? undefined,
                type: record.entityType ?? undefined,
                avatarUrl: attachment.context?.imageUrl ?? null,
                avatarId: null,
            };
            actions.setDraftValues(nextDraft);

            // Set editing state based on roster match
            if (record.roster?.remoteId) {
                const match = entries.find((entry) => entry.remoteId === record.roster?.remoteId) ?? null;
                actions.setEditing(match);
            } else {
                const existing =
                    entries.find((entry) => entry.label === nextDraft.label && entry.type === nextDraft.type) ?? null;
                if (existing) {
                    actions.setEditing(existing);
                } else {
                    actions.setEditing(null);
                }
            }

            // Update search input with observation label
            const labelValue = nextDraft.label ?? "";
            if (labelValue && searchInput !== labelValue) {
                actions.setSearchInput(labelValue);
            }

            // Update URL with observation params
            const nextSearch = params.toString();
            const nextUrl = nextSearch ? `${location.pathname}?${nextSearch}` : location.pathname;
            void navigate(nextUrl, { replace: true });
        },
        [entries, location.pathname, navigate, searchInput, actions],
    );

    /**
     * Handle assigning an observation to a roster entry.
     * Updates the entry with observation resolution details.
     */
    const handleAssignToRoster = React.useCallback(
        async (
            record: RecognitionObservationRecord,
            attachment: RecognitionObservationAttachment,
            remoteId: string,
        ) => {
            if (!record.observationId || !attachment.attachmentId) {
                notifyError(__("Unable to resolve observation details.", "context-alt-text"), {
                    id: "cat-roster-observation-assign-error",
                });
                return;
            }

            const entry = entries.find((item) => item.remoteId === remoteId) ?? null;

            if (!entry) {
                notifyError(__("Select a roster entry with a remote ID to assign.", "context-alt-text"), {
                    id: "cat-roster-observation-assign-error",
                });
                return;
            }

            try {
                await updateEntry({
                    remoteId,
                    label: entry.label,
                    type: entry.type,
                    resolveObservation: {
                        attachmentId: attachment.attachmentId,
                        observationId: record.observationId,
                        status: "matched",
                        label: entry.label ?? record.label ?? null,
                        entityType: entry.type ?? record.entityType ?? null,
                    },
                });

                dispatchNotice(
                    "success",
                    sprintf(
                        /* translators: %s is a roster entry label. */
                        __("Observation matched to %s.", "context-alt-text"),
                        entry.label,
                    ),
                    { id: "cat-roster-observation-assign-success" },
                );

                if (hasObservationEndpoint) {
                    void refetchObservations();
                }

                // Update prompt state and editing state
                actions.setObservationPrompt({
                    observationId: record.observationId,
                    attachmentId: attachment.attachmentId,
                    source: "recognition",
                    remoteId,
                    label: entry.label ?? record.label ?? null,
                });

                actions.setDraftValues(null);
                actions.setEditing(entry);
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                notifyError(message, { id: "cat-roster-observation-assign-error" });
            }
        },
        [entries, updateEntry, actions, hasObservationEndpoint, refetchObservations],
    );

    /**
     * Handle form submission - creates or updates a roster entry.
     * Includes special handling for observation resolution.
     */
    const handleSubmit = React.useCallback(
        async (values: RosterFormValues) => {
            try {
                actions.setIsSubmitting(true);

                if (values.remoteId) {
                    // Update existing entry
                    const entry = await updateEntry(values);
                    if (entry) {
                        dispatchNotice("success", __("Roster entry saved.", "context-alt-text"), {
                            id: "cat-roster-save",
                        });
                        actions.setEditing(null);
                    } else {
                        dispatchNotice("success", __("Roster entry processed.", "context-alt-text"), {
                            id: "cat-roster-save-generic",
                        });
                    }
                } else {
                    // Create new entry
                    const result = await createEntry(values);
                    const entry = result?.entry ?? null;
                    const autoMatched = result?.autoMatched ?? [];

                    if (entry) {
                        const matchCount = autoMatched.length;
                        if (matchCount > 0) {
                            dispatchNotice(
                                "success",
                                sprintf(
                                    _n(
                                        "Roster entry created and %d observation auto-matched.",
                                        "Roster entry created and %d observations auto-matched.",
                                        matchCount,
                                        "context-alt-text",
                                    ),
                                    matchCount,
                                ),
                                { id: "cat-roster-save" },
                            );
                        } else {
                            dispatchNotice("success", __("Roster entry saved.", "context-alt-text"), {
                                id: "cat-roster-save",
                            });
                        }
                        actions.setEditing(null);
                    } else {
                        dispatchNotice("success", __("Roster entry processed.", "context-alt-text"), {
                            id: "cat-roster-save-generic",
                        });
                    }
                }

                // Clear observation prompt after successful submission
                if (observationPrompt) {
                    actions.setObservationPrompt(null);
                    actions.setObservationDialogDismissed(false);

                    // Remove observation-related URL parameters
                    const params = new URLSearchParams(location.search ?? "");
                    params.delete("observationId");
                    params.delete("attachmentId");
                    params.delete("source");
                    params.delete("mode");
                    params.delete("label");
                    params.delete("type");
                    params.delete("remoteId");
                    const nextSearch = params.toString();
                    const nextUrl = nextSearch ? `${location.pathname}?${nextSearch}` : location.pathname;
                    void navigate(nextUrl, { replace: true });
                }

                actions.setDraftValues(null);
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                notifyError(message, { id: "cat-roster-save-error" });
            } finally {
                actions.setIsSubmitting(false);
            }
        },
        [actions, updateEntry, createEntry, observationPrompt, location, navigate],
    );

    /**
     * Handle deleting a roster entry with confirmation.
     */
    const handleDelete = React.useCallback(
        async (remoteId: string) => {
            if (!window.confirm(__("Are you sure you want to delete this roster entry?", "context-alt-text"))) {
                return;
            }

            try {
                actions.setIsSubmitting(true);
                await deleteEntry(remoteId);
                dispatchNotice("success", __("Roster entry deleted.", "context-alt-text"), {
                    id: "cat-roster-delete",
                });
                if (editing?.remoteId === remoteId) {
                    actions.setEditing(null);
                    actions.setDraftValues(null);
                }
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                notifyError(message, { id: "cat-roster-delete-error" });
            } finally {
                actions.setIsSubmitting(false);
            }
        },
        [actions, deleteEntry, editing],
    );

    /**
     * Handle syncing roster with server and refreshing observations.
     */
    const handleSync = React.useCallback(async () => {
        try {
            await syncRoster();
            if (hasObservationEndpoint) {
                void refetchObservations();
            }
            dispatchNotice("success", __("Roster sync completed.", "context-alt-text"), {
                id: "cat-roster-sync",
            });
        } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            notifyError(message, { id: "cat-roster-sync-error" });
        }
    }, [syncRoster, hasObservationEndpoint, refetchObservations]);

    /**
     * Handle clearing status filter and updating URL.
     */
    const handleClearStatusFilter = React.useCallback(() => {
        actions.setStatusFilter(null);
        const params = new URLSearchParams(location.search ?? "");

        if (!params.has("filter")) {
            return;
        }

        params.delete("filter");
        const nextSearch = params.toString();
        const nextUrl = nextSearch ? `${location.pathname}?${nextSearch}` : location.pathname;
        void navigate(nextUrl, { replace: true });
    }, [location.pathname, location.search, navigate, actions]);

    return {
        handleObservationSelect,
        handleAssignToRoster,
        handleSubmit,
        handleDelete,
        handleSync,
        handleClearStatusFilter,
    };
};
