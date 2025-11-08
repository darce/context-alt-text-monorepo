import React from "react";
import { __, sprintf } from "@wordpress/i18n";
import type { RosterFilters } from "@/admin/hooks/useRoster";
import type { RosterStats as RosterStatsType } from "@/admin/types";

/**
 * Props for RosterToolbar component
 */
export interface RosterToolbarProps {
    /** Current search input value */
    searchInput: string;
    /** Handler for search input changes */
    onSearchChange: (value: string) => void;
    /** Current status filter (LOCAL, SYNCED, CONFLICT, or null) */
    statusFilter: RosterFilters["status"];
    /** Handler to clear status filter */
    onClearStatusFilter: () => void;
    /** Whether data is currently loading */
    isLoading: boolean;
    /** Whether submission is in progress */
    isSubmitting: boolean;
    /** Whether sync operation is in progress */
    isSyncing: boolean;
    /** Whether the roster endpoint is available */
    hasEndpoint: boolean;
    /** Handler for creating a new roster entry */
    onCreateNew: () => void;
    /** Handler for syncing roster from remote */
    onSync: () => void;
    /** Roster statistics to display */
    stats: RosterStatsType;
}

/**
 * RosterToolbar - Header, search, and filter controls for the roster
 *
 * This component provides:
 * - Page header with title and description
 * - Action buttons (Add Entry, Sync from Remote)
 * - Search input with live status indicator
 * - Active status filter badge with clear button
 * - Roster statistics display
 *
 * @example
 * ```tsx
 * <RosterToolbar
 *   searchInput={rosterState.state.searchInput}
 *   onSearchChange={rosterState.actions.setSearchInput}
 *   statusFilter={rosterState.state.statusFilter}
 *   onClearStatusFilter={handleClearStatusFilter}
 *   isLoading={isLoading}
 *   isSubmitting={isSubmitting}
 *   isSyncing={isSyncing}
 *   hasEndpoint={hasEndpoint}
 *   onCreateNew={handleCreateNew}
 *   onSync={handleSync}
 *   stats={data.stats}
 * />
 * ```
 */
export const RosterToolbar: React.FC<RosterToolbarProps> = ({
    searchInput,
    onSearchChange,
    statusFilter,
    onClearStatusFilter,
    isLoading,
    isSubmitting,
    isSyncing,
    hasEndpoint,
    onCreateNew,
    onSync,
    stats,
}) => {
    return (
        <>
            <header className="cat-roster__header">
                <div>
                    <h2>{__("Roster Manager", "context-alt-text")}</h2>
                    <p>
                        {__(
                            "Manage labeled faces and entities synchronized with the recognition service.",
                            "context-alt-text",
                        )}
                    </p>
                </div>
                <div className="cat-roster__header-actions">
                    <button type="button" className="cat-button" onClick={onCreateNew} disabled={isSubmitting}>
                        {__("Add Entry", "context-alt-text")}
                    </button>
                    <button
                        type="button"
                        className="cat-button cat-button--primary"
                        onClick={() => {
                            void onSync();
                        }}
                        disabled={!hasEndpoint || isSyncing}
                    >
                        {isSyncing ? __("Syncing…", "context-alt-text") : __("Sync from Remote", "context-alt-text")}
                    </button>
                </div>
            </header>

            <section className="cat-roster__summary">
                <RosterStats stats={stats} />
                <div className="cat-roster__search">
                    <label htmlFor="cat-roster-search" className="screen-reader-text">
                        {__("Search roster", "context-alt-text")}
                    </label>
                    <input
                        id="cat-roster-search"
                        type="search"
                        value={searchInput}
                        placeholder={__("Search by label or type", "context-alt-text")}
                        onChange={(event) => onSearchChange(event.target.value)}
                        className="cat-roster__search-input"
                    />
                    {isLoading && (
                        <span className="cat-roster__search-status" role="status" aria-live="polite">
                            {__("Searching…", "context-alt-text")}
                        </span>
                    )}
                </div>
                {statusFilter && (
                    <div className="cat-roster__filter" role="status" aria-live="polite">
                        <span>
                            {sprintf(
                                __("Filtered by status: %s", "context-alt-text"),
                                statusFilter === "LOCAL"
                                    ? __("Local", "context-alt-text")
                                    : statusFilter === "SYNCED"
                                      ? __("Synced", "context-alt-text")
                                      : __("Conflict", "context-alt-text"),
                            )}
                        </span>
                        <button
                            type="button"
                            className="cat-button cat-button--link"
                            onClick={onClearStatusFilter}
                            disabled={isLoading}
                        >
                            {__("Clear", "context-alt-text")}
                        </button>
                    </div>
                )}
            </section>
        </>
    );
};

/**
 * RosterStats - Display roster entry statistics
 */
interface RosterStatsProps {
    stats: RosterStatsType;
}

const RosterStats: React.FC<RosterStatsProps> = ({ stats }) => {
    return (
        <div className="cat-roster__stats" role="status" aria-live="polite">
            <dl>
                <div>
                    <dt>{__("Total", "context-alt-text")}</dt>
                    <dd>{stats.total}</dd>
                </div>
                <div>
                    <dt>{__("Synced", "context-alt-text")}</dt>
                    <dd>{stats.synced}</dd>
                </div>
                <div>
                    <dt>{__("Local", "context-alt-text")}</dt>
                    <dd>{stats.local}</dd>
                </div>
                {stats.conflicts > 0 && (
                    <div>
                        <dt>{__("Conflicts", "context-alt-text")}</dt>
                        <dd>{stats.conflicts}</dd>
                    </div>
                )}
            </dl>
            <p className="cat-roster__stats-sync">
                {stats.lastSyncHuman
                    ? sprintf(__("Last synced %s ago.", "context-alt-text"), stats.lastSyncHuman)
                    : __("Roster has not been synced yet.", "context-alt-text")}
            </p>
        </div>
    );
};
