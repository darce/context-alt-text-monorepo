/* eslint-disable @typescript-eslint/no-unsafe-assignment */
import React from "react";
import { useLocation } from "react-router-dom";
import { __ } from "@wordpress/i18n";
import { RosterToolbar } from "./RosterToolbar";
import { RosterTable } from "./RosterTable";
import { RosterPagination } from "./RosterPagination";
import { RosterEditor } from "./RosterEditor";
import { ObservationPanel } from "./ObservationPanel";
import { ObservationAssignmentDialog } from "./ObservationAssignmentDialog";

import type { AdminConfig, RosterData, RosterEntry } from "@/admin/types";
import { useRoster } from "@/admin/hooks/useRoster";
import { useRosterState } from "@/admin/hooks/useRosterState";
import { useObservationWorkflow } from "@/admin/hooks/useObservationWorkflow";
import { useRosterDeepLinks } from "@/admin/hooks/useRosterDeepLinks";
import { useRosterEventHandlers } from "@/admin/hooks/useRosterEventHandlers";
import { dispatchNotice, notifyError } from "@/admin/notices";

interface RosterRouteProps {
    bootstrap: RosterData;
    config: AdminConfig;
}

export const RosterRoute = ({ bootstrap, config }: RosterRouteProps): React.JSX.Element => {
    // NEW: Custom hooks for state management
    const rosterState = useRosterState({
        searchDebounceMs: 300,
    });

    // Destructure for easier access throughout the component
    const editing = rosterState.state.editing;
    const isSubmitting = rosterState.state.isSubmitting;
    const draftValues = rosterState.state.draftValues;
    const observationPrompt = rosterState.state.observationPrompt;
    const observationDialogDismissed = rosterState.state.observationDialogDismissed;

    const location = useLocation();

    // Use filters from rosterState hook (replaces manual filter computation)
    const filters = rosterState.filters;

    const roster = useRoster({ initialData: bootstrap, config, filters });
    const { query, hasEndpoint, createEntry, updateEntry, deleteEntry, syncRoster, isSyncing } = roster;

    // Get roster data first (needed for observation workflow)
    const data = query.data ?? {
        entries: bootstrap.entries,
        stats: bootstrap.stats,
        total: bootstrap.entries.length,
        page: rosterState.state.page,
        perPage: rosterState.state.perPage,
        totalPages: bootstrap.entries.length > 0 ? Math.ceil(bootstrap.entries.length / rosterState.state.perPage) : 0,
        filters,
        syncState: {},
    };
    const entries = data.entries;

    // Observation workflow hook - handles observation data fetching and assignment logic
    const observationWorkflow = useObservationWorkflow({
        config,
        entries,
        updateEntry: updateEntry as any, // eslint-disable-line @typescript-eslint/no-explicit-any
    });

    // Destructure observation workflow data for easier access
    const observationItems = observationWorkflow.observationItems;
    const observationSummary = observationWorkflow.observationSummary;
    const observationsError = observationWorkflow.observationsError;
    const observationsLoading = observationWorkflow.observationsLoading;
    const observationIndex = observationWorkflow.observationIndex;
    const hasObservationEndpoint = observationWorkflow.hasObservationEndpoint;
    const refetchObservations = observationWorkflow.refetchObservations;
    const retryRecognition = observationWorkflow.retryRecognition;

    // Event handlers hook - consolidates all event handler logic
    const handlers = useRosterEventHandlers({
        entries,
        searchInput: rosterState.state.searchInput,
        observationPrompt: rosterState.state.observationPrompt,
        editing: rosterState.state.editing,
        actions: rosterState.actions,
        createEntry,
        updateEntry: updateEntry as any, // eslint-disable-line @typescript-eslint/no-explicit-any
        deleteEntry,
        syncRoster,
        refetchObservations,
        hasObservationEndpoint,
    });

    // Destructure handlers for easier access
    const {
        handleObservationSelect,
        handleAssignToRoster,
        handleSubmit,
        handleDelete,
        handleSync,
        handleClearStatusFilter,
    } = handlers;

    // Derived values
    const isLoading = query.isFetching;

    // Local handlers that weren't extracted
    const handleCreateNew = React.useCallback(() => {
        rosterState.actions.setEditing(null);
        rosterState.actions.setDraftValues(null);
        rosterState.actions.setObservationPrompt(null);
    }, [rosterState.actions]);

    const handleEdit = React.useCallback(
        (entry: RosterEntry) => {
            rosterState.actions.setEditing(entry);
            rosterState.actions.setDraftValues(null);
        },
        [rosterState.actions],
    );

    const handlePageChange = React.useCallback(
        (nextPage: number) => {
            if (nextPage <= 1) {
                rosterState.actions.setPage(1);
                return;
            }

            if (data.totalPages > 0 && nextPage > data.totalPages) {
                rosterState.actions.setPage(data.totalPages);
                return;
            }

            if (Number.isFinite(nextPage)) {
                rosterState.actions.setPage(nextPage);
            }
        },
        [data.totalPages, rosterState.actions],
    );

    const handleDismissObservationPrompt = React.useCallback(() => {
        rosterState.actions.setObservationDialogDismissed(true);
    }, [rosterState.actions]);

    const handlePerPageChange = React.useCallback(
        (value: number) => {
            if (rosterState.state.perPage !== value) {
                rosterState.actions.setPerPage(value);
                rosterState.actions.setPage(1);
            }
        },
        [rosterState.state.perPage, rosterState.actions],
    );

    // Handle deep link URL parameters and navigation
    useRosterDeepLinks({
        location,
        entries,
        editing,
        searchInput: rosterState.state.searchInput,
        statusFilter: rosterState.state.statusFilter,
        observationPrompt: rosterState.state.observationPrompt,
        actions: rosterState.actions,
    });

    React.useEffect(() => {
        const result = query.data;

        if (!result || query.isFetching) {
            return;
        }

        const resultFilters = result.filters ?? {};
        const requestedSearch = filters.search ?? null;
        const requestedStatus = filters.status ?? null;
        const resultSearch = resultFilters.search ?? null;
        const resultStatus = resultFilters.status ?? null;

        const filtersMatch = resultSearch === requestedSearch && resultStatus === requestedStatus;

        if (!filtersMatch) {
            return;
        }

        if (Number.isFinite(result.perPage) && result.perPage > 0 && result.perPage !== rosterState.state.perPage) {
            rosterState.actions.setPerPage(result.perPage);
        }

        if (Number.isFinite(result.page) && result.page > 0 && result.page !== rosterState.state.page) {
            rosterState.actions.setPage(result.page);
        }

        if (resultStatus !== rosterState.state.statusFilter) {
            rosterState.actions.setStatusFilter(resultStatus);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- filters is derived from rosterState.filters
    }, [
        rosterState.filters,
        rosterState.state.page,
        rosterState.state.perPage,
        query.data,
        query.isFetching,
        rosterState.state.statusFilter,
        rosterState.actions,
    ]);

    React.useEffect(() => {
        if (!query.error) {
            return;
        }

        notifyError(query.error.message, { id: "cat-roster-error" });
    }, [query.error]);

    return (
        <div className="cat-roster">
            <RosterToolbar
                searchInput={rosterState.state.searchInput}
                onSearchChange={rosterState.actions.setSearchInput}
                statusFilter={rosterState.state.statusFilter}
                onClearStatusFilter={handleClearStatusFilter}
                isLoading={isLoading}
                isSubmitting={isSubmitting}
                isSyncing={isSyncing}
                hasEndpoint={hasEndpoint}
                onCreateNew={handleCreateNew}
                onSync={() => void handleSync()}
                stats={data.stats}
            />

            {!hasEndpoint && (
                <p className="cat-roster__warning" role="alert">
                    {__(
                        "Roster endpoints are unavailable. Confirm REST routes are registered and you have required permissions.",
                        "context-alt-text",
                    )}
                </p>
            )}

            <ObservationPanel
                attachments={observationItems}
                summary={observationSummary}
                isLoading={observationsLoading}
                error={observationsError}
                hasEndpoint={hasObservationEndpoint}
                entries={entries}
                onCreate={handleObservationSelect}
                onAssign={handleAssignToRoster}
                onRefresh={async () => {
                    if (!hasObservationEndpoint) {
                        return;
                    }

                    try {
                        // Trigger re-recognition for pending observations
                        const result = await retryRecognition();

                        dispatchNotice("success", result.message, {
                            id: "cat-observations-retry",
                        });

                        // Refetch after a delay to allow recognition jobs to start
                        setTimeout(() => {
                            void refetchObservations();
                        }, 2000);
                    } catch (error) {
                        const message = error instanceof Error ? error.message : String(error);
                        notifyError(message, { id: "cat-observations-retry-error" });
                    }
                }}
            />

            <section className="cat-roster__layout">
                <RosterTable entries={data.entries} isLoading={isLoading} onEdit={handleEdit} onDelete={handleDelete} />
                <RosterEditor
                    entry={editing}
                    draftValues={draftValues}
                    observationPrompt={observationPrompt}
                    observationDetails={
                        observationPrompt ? observationIndex.get(observationPrompt.observationId) : undefined
                    }
                    onSubmit={handleSubmit}
                    submitting={isSubmitting}
                />
            </section>

            {observationPrompt && (
                <ObservationAssignmentDialog
                    isOpen={!observationDialogDismissed}
                    prompt={observationPrompt}
                    details={observationIndex.get(observationPrompt.observationId)}
                    onDismiss={handleDismissObservationPrompt}
                />
            )}

            <RosterPagination
                page={data.page}
                totalPages={data.totalPages}
                total={data.total}
                perPage={data.perPage}
                onPageChange={handlePageChange}
                onPerPageChange={handlePerPageChange}
                disabled={isLoading}
            />
        </div>
    );
};
