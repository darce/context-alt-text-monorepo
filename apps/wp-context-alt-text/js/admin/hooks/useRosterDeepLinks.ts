import React from "react";
import type { RosterEntry } from "@/admin/types";
import type { RosterFilters } from "@/admin/hooks/useRoster";
import type { ObservationPromptState, RosterStateActions } from "@/admin/hooks/useRosterState";

/**
 * Options for useRosterDeepLinks hook
 */
export interface UseRosterDeepLinksOptions {
    /**
     * Current URL location object from react-router
     */
    location: { search: string | null };

    /**
     * Available roster entries for matching against remoteId
     */
    entries: RosterEntry[];

    /**
     * Currently editing roster entry (if any)
     */
    editing: RosterEntry | null;

    /**
     * Current search input value
     */
    searchInput: string;

    /**
     * Current status filter value
     */
    statusFilter: RosterFilters["status"];

    /**
     * Current observation prompt state
     */
    observationPrompt: ObservationPromptState | null;

    /**
     * Actions from useRosterState for updating state
     */
    actions: RosterStateActions;
}

/**
 * Custom hook for handling deep link URL parameters and navigation
 *
 * Handles:
 * - URL parameter parsing (filter, remoteId, mode, label, type, observationId, etc.)
 * - Status filter synchronization from URL
 * - Entry editing from remoteId parameter
 * - Draft creation from mode=create parameter
 * - Observation prompt state from observationId parameter
 * - Deep link deduplication via ref tracking
 *
 * @param options - Configuration options
 *
 * @example
 * ```tsx
 * const location = useLocation();
 * const roster = useRoster(...);
 * const { state, actions } = useRosterState();
 *
 * // Automatically syncs URL params with roster state
 * useRosterDeepLinks({
 *   location,
 *   entries: roster.query.data?.entries ?? [],
 *   editing: state.editing,
 *   searchInput: state.searchInput,
 *   statusFilter: state.statusFilter,
 *   observationPrompt: state.observationPrompt,
 *   actions,
 * });
 * ```
 */
export const useRosterDeepLinks = ({
    location,
    entries,
    editing,
    searchInput,
    statusFilter,
    observationPrompt,
    actions,
}: UseRosterDeepLinksOptions): void => {
    // Track deep link state to prevent duplicate processing
    const deepLinkRef = React.useRef<{
        remoteId?: string | null;
        draftSignature?: string | null;
    }>({});

    React.useEffect(() => {
        const params = new URLSearchParams(location.search ?? "");

        // Extract all URL parameters
        const filterParam = (params.get("filter") ?? "").toLowerCase();
        const remoteIdParam = params.get("remoteId");
        const modeParam = params.get("mode");
        const rawLabel = params.get("label");
        const rawType = params.get("type");
        const observationIdParam = params.get("observationId");
        const attachmentIdParam = params.get("attachmentId");
        const sourceParam = params.get("source");

        const labelValue = rawLabel ? rawLabel.trim() : "";
        const typeValue = rawType ? rawType.trim() : "";

        // Normalize attachment ID (must be positive number)
        const normalizedAttachmentId = (() => {
            if (!attachmentIdParam) {
                return null;
            }

            const parsed = Number(attachmentIdParam);
            return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
        })();

        // Normalize source (must be non-empty string)
        const normalizedSource = (() => {
            if (!sourceParam) {
                return null;
            }

            const trimmed = sourceParam.trim();
            return trimmed.length > 0 ? trimmed : null;
        })();

        // Normalize remote ID (must be non-empty string)
        const normalizedRemoteId = (() => {
            if (!remoteIdParam) {
                return null;
            }

            const trimmed = remoteIdParam.trim();
            return trimmed.length > 0 ? trimmed : null;
        })();

        const normalizedLabel = labelValue.length > 0 ? labelValue : null;

        // Build observation prompt state from URL params
        const nextObservationPrompt: ObservationPromptState | null = observationIdParam
            ? {
                  observationId: observationIdParam,
                  attachmentId: normalizedAttachmentId,
                  source: normalizedSource,
                  remoteId: normalizedRemoteId,
                  label: normalizedLabel,
              }
            : null;

        // Update observation prompt if changed
        const current = observationPrompt;
        if (current || nextObservationPrompt) {
            const shouldUpdate =
                !current ||
                !nextObservationPrompt ||
                current.observationId !== nextObservationPrompt.observationId ||
                current.attachmentId !== nextObservationPrompt.attachmentId ||
                current.source !== nextObservationPrompt.source ||
                current.remoteId !== nextObservationPrompt.remoteId ||
                current.label !== nextObservationPrompt.label;

            if (shouldUpdate) {
                actions.setObservationPrompt(nextObservationPrompt);
            }
        }

        // Map filter param to status filter type
        const statusMap: Record<string, RosterFilters["status"]> = {
            pending: "LOCAL",
            local: "LOCAL",
            synced: "SYNCED",
            conflict: "CONFLICT",
            conflicts: "CONFLICT",
        };

        // Clear deep link tracking when params are removed
        if (!normalizedRemoteId && deepLinkRef.current.remoteId) {
            deepLinkRef.current.remoteId = null;
        }

        if (!modeParam && deepLinkRef.current.draftSignature) {
            deepLinkRef.current.draftSignature = null;
        }

        // Sync status filter from URL
        if (filterParam) {
            const mapped = statusMap[filterParam];
            if (mapped && mapped !== statusFilter) {
                actions.setStatusFilter(mapped);
            }
        } else if (statusFilter) {
            actions.setStatusFilter(null);
        }

        // Handle remoteId parameter - edit existing entry
        if (normalizedRemoteId) {
            // Skip if already processing this remoteId
            if (deepLinkRef.current.remoteId === normalizedRemoteId && editing?.remoteId === normalizedRemoteId) {
                return;
            }

            // Find matching entry
            const match = entries.find((entry) => entry.remoteId === normalizedRemoteId);
            if (match) {
                // Found entry - set for editing
                actions.setEditing(match);
                actions.setDraftValues(null);
                deepLinkRef.current.remoteId = normalizedRemoteId;
            } else {
                // Entry not found - trigger search
                if (searchInput !== normalizedRemoteId) {
                    actions.setSearchInput(normalizedRemoteId);
                }
            }

            return;
        }

        // Handle mode=create parameter - create new entry with draft values
        if (modeParam === "create") {
            const signature = `${labelValue}|${typeValue}`;

            // Skip if already processing this draft
            if (deepLinkRef.current.draftSignature === signature) {
                return;
            }

            deepLinkRef.current.draftSignature = signature;

            // Set draft mode
            actions.setEditing(null);
            const nextDraft = {
                label: labelValue !== "" ? labelValue : undefined,
                type: typeValue !== "" ? typeValue : undefined,
            };
            actions.setDraftValues(nextDraft);

            // Pre-fill search with label if provided
            if (labelValue) {
                if (searchInput !== labelValue) {
                    actions.setSearchInput(labelValue);
                }
            }
        }
    }, [location.search, entries, editing?.remoteId, searchInput, statusFilter, observationPrompt, actions]);
};
