import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import type {
    AdminConfig,
    RecognitionObservationAttachment,
    RecognitionObservationRecord,
    RecognitionObservationSummary,
    RosterEntry,
} from "@/admin/types";
import { useRecognitionObservations } from "@/admin/hooks/useRecognitionObservations";
import { dispatchNotice, notifyError } from "@/admin/notices";

/**
 * Default observation summary when no data is available
 */
const DEFAULT_OBSERVATION_SUMMARY: RecognitionObservationSummary = {
    attachments: 0,
    observations: { total: 0, matched: 0, needs_review: 0 },
};

/**
 * Observation index entry combining record and attachment
 */
export interface ObservationIndexEntry {
    record: RecognitionObservationRecord;
    attachment: RecognitionObservationAttachment;
}

/**
 * Options for useObservationWorkflow hook
 */
export interface UseObservationWorkflowOptions {
    /**
     * Admin configuration with endpoints
     */
    config: AdminConfig;

    /**
     * Available roster entries for assignment
     */
    entries: RosterEntry[];

    /**
     * Callback to update a roster entry
     */
    updateEntry: (values: {
        remoteId: string;
        label: string;
        type: string;
        resolveObservation?: {
            attachmentId: number;
            observationId: string;
            status?: "matched" | "needs_review";
            label?: string | null;
            entityType?: string | null;
        };
    }) => Promise<void>;
}

/**
 * Return type for useObservationWorkflow hook
 */
export interface UseObservationWorkflowReturn {
    /**
     * Observation items (attachments with observations)
     */
    observationItems: RecognitionObservationAttachment[];

    /**
     * Summary statistics for observations
     */
    observationSummary: RecognitionObservationSummary;

    /**
     * Map of observation ID to observation details for quick lookup
     */
    observationIndex: Map<string, ObservationIndexEntry>;

    /**
     * Error from observation query (if any)
     */
    observationsError: Error | null;

    /**
     * Whether observations are currently loading
     */
    observationsLoading: boolean;

    /**
     * Whether observation endpoint is available
     */
    hasObservationEndpoint: boolean;

    /**
     * Refetch observations from server
     */
    refetchObservations: () => Promise<unknown>;

    /**
     * Retry recognition for observations that need review
     */
    retryRecognition: () => Promise<{ success: boolean; message: string }>;

    /**
     * Whether retry recognition operation is in progress
     */
    isRetrying: boolean;

    /**
     * Assign an observation to a roster entry
     * @param record - Observation record to assign
     * @param attachment - Attachment containing the observation
     * @param remoteId - Remote ID of roster entry to assign to
     */
    handleAssignToRoster: (
        record: RecognitionObservationRecord,
        attachment: RecognitionObservationAttachment,
        remoteId: string,
    ) => Promise<void>;
}

/**
 * Custom hook for managing recognition observation workflow
 *
 * Handles:
 * - Fetching observations that need review
 * - Indexing observations for quick lookup
 * - Assigning observations to roster entries
 * - Error handling and notifications
 *
 * @param options - Configuration options
 * @returns Observation data and actions
 *
 * @example
 * ```tsx
 * const observation = useObservationWorkflow({
 *   config,
 *   entries: roster.entries,
 *   updateEntry: roster.updateEntry,
 * });
 *
 * // Use observation data
 * <ObservationPanel
 *   items={observation.observationItems}
 *   loading={observation.observationsLoading}
 *   onAssign={observation.handleAssignToRoster}
 * />
 * ```
 */
export const useObservationWorkflow = ({
    config,
    entries,
    updateEntry,
}: UseObservationWorkflowOptions): UseObservationWorkflowReturn => {
    // Observation filters - always fetch items needing review
    const observationFilters = React.useMemo(
        () => ({
            status: "needs_review" as const,
            perPage: 10,
        }),
        [],
    );

    // Fetch observation data
    const observations = useRecognitionObservations({ config, filters: observationFilters });
    const observationResult = observations.query.data;

    // Extract observation items
    const observationItems = React.useMemo(() => observationResult?.items ?? [], [observationResult?.items]);

    // Get summary or use default
    const observationSummary = observationResult?.summary ?? DEFAULT_OBSERVATION_SUMMARY;

    // Extract error and loading states
    const observationsError = observations.query.error ?? null;
    const observationsLoading = observations.query.isFetching || observations.query.isLoading;

    // Build observation index for O(1) lookup by observation ID
    const observationIndex = React.useMemo(() => {
        const index = new Map<string, ObservationIndexEntry>();

        for (const attachment of observationItems) {
            if (!attachment || !Array.isArray(attachment.observations)) {
                continue;
            }

            for (const record of attachment.observations) {
                if (!record || typeof record !== "object") {
                    continue;
                }

                if (record.observationId) {
                    index.set(record.observationId, { record, attachment });
                }
            }
        }

        return index;
    }, [observationItems]);

    /**
     * Assign an observation to a roster entry
     */
    const handleAssignToRoster = React.useCallback(
        async (
            record: RecognitionObservationRecord,
            attachment: RecognitionObservationAttachment,
            remoteId: string,
        ) => {
            // Validate observation details
            if (!record.observationId || !attachment.attachmentId) {
                notifyError(__("Unable to resolve observation details.", "context-alt-text"), {
                    id: "cat-roster-observation-assign-error",
                });
                return;
            }

            // Find the roster entry
            const entry = entries.find((item) => item.remoteId === remoteId) ?? null;

            if (!entry) {
                notifyError(__("Select a roster entry with a remote ID to assign.", "context-alt-text"), {
                    id: "cat-roster-observation-assign-error",
                });
                return;
            }

            try {
                // Update the roster entry with observation assignment
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

                // Show success notification
                dispatchNotice(
                    "success",
                    sprintf(
                        /* translators: %s is a roster entry label. */
                        __("Observation matched to %s.", "context-alt-text"),
                        entry.label,
                    ),
                    { id: "cat-roster-observation-assign-success" },
                );

                // Refetch observations if endpoint is available
                if (observations.hasEndpoint) {
                    void observations.query.refetch();
                }
            } catch (error) {
                const message = error instanceof Error ? error.message : String(error);
                notifyError(message, { id: "cat-roster-observation-assign-error" });
            }
        },
        [entries, observations, updateEntry],
    );

    return {
        observationItems,
        observationSummary,
        observationIndex,
        observationsError,
        observationsLoading,
        hasObservationEndpoint: observations.hasEndpoint,
        refetchObservations: observations.query.refetch,
        retryRecognition: observations.retryRecognition,
        isRetrying: observations.isRetrying,
        handleAssignToRoster,
    };
};
