import React from "react";
import { __, sprintf, _n } from "@wordpress/i18n";
import { StatusBadge } from "./StatusBadge";
import type { RosterEntry } from "@/admin/types";

/**
 * Props for the RosterTable component.
 */
export interface RosterTableProps {
    /**
     * Array of roster entries to display in the table.
     */
    entries: RosterEntry[];

    /**
     * Whether the table is currently loading data.
     */
    isLoading: boolean;

    /**
     * Handler called when the user clicks the "Edit" button for an entry.
     */
    onEdit: (entry: RosterEntry) => void;

    /**
     * Handler called when the user clicks the "Delete" button for an entry.
     * Only entries with remoteId can be deleted.
     */
    onDelete: (remoteId: string) => Promise<void> | void;
}

/**
 * Displays a table of roster entries with avatar, label, type, status, and actions.
 *
 * Shows an empty state when there are no entries. Supports editing and deleting entries.
 * Only synced entries (with remoteId) can be deleted.
 *
 * @param props - Component props
 * @returns A table element or empty state message
 *
 * @example
 * ```tsx
 * <RosterTable
 *     entries={rosterEntries}
 *     isLoading={false}
 *     onEdit={(entry) => setEditing(entry)}
 *     onDelete={(remoteId) => handleDelete(remoteId)}
 * />
 * ```
 */
export const RosterTable = ({ entries, isLoading, onEdit, onDelete }: RosterTableProps): React.JSX.Element => {
    if (entries.length === 0) {
        return (
            <div className="cat-roster__table cat-roster__table--empty">
                {isLoading ? (
                    <p>{__("Loading roster entries…", "context-alt-text")}</p>
                ) : (
                    <p>{__("No roster entries yet. Create one to get started.", "context-alt-text")}</p>
                )}
            </div>
        );
    }

    return (
        <div className="cat-roster__table" role="region" aria-live="polite">
            <table>
                <thead>
                    <tr>
                        <th scope="col">{__("Avatar", "context-alt-text")}</th>
                        <th scope="col">{__("Label", "context-alt-text")}</th>
                        <th scope="col">{__("Type", "context-alt-text")}</th>
                        <th scope="col">{__("Status", "context-alt-text")}</th>
                        <th scope="col">{__("Updated", "context-alt-text")}</th>
                        <th scope="col">{__("Images", "context-alt-text")}</th>
                        <th scope="col" className="screen-reader-text">
                            {__("Actions", "context-alt-text")}
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {entries.map((entry) => (
                        <tr key={entry.remoteId ?? `${entry.label}-${entry.type}`}>
                            <td>
                                {entry.avatarUrl ? (
                                    <img
                                        src={entry.avatarUrl}
                                        alt={sprintf(
                                            __("Avatar for %s", "context-alt-text"),
                                            entry.label?.trim() ? entry.label : (entry.remoteId ?? "—"),
                                        )}
                                        className="cat-roster__avatar"
                                    />
                                ) : (
                                    <span className="cat-roster__avatar cat-roster__avatar--placeholder" aria-hidden>
                                        {entry.label ? entry.label.charAt(0).toUpperCase() : "?"}
                                    </span>
                                )}
                            </td>
                            <td>
                                <strong>{entry.label?.trim() ? entry.label : (entry.remoteId ?? "—")}</strong>
                                <div className="cat-roster__meta">
                                    {entry.remoteId ? (
                                        <span>{entry.remoteId}</span>
                                    ) : (
                                        <span>{__("Local draft", "context-alt-text")}</span>
                                    )}
                                </div>
                            </td>
                            <td>{entry.type?.trim() ? entry.type : "—"}</td>
                            <td>
                                <StatusBadge status={entry.status} />
                            </td>
                            <td>{entry.updatedAt ? new Date(entry.updatedAt).toLocaleString() : "—"}</td>
                            <td>
                                {sprintf(
                                    _n("%d image", "%d images", entry.referenceImageCount, "context-alt-text"),
                                    entry.referenceImageCount,
                                )}
                            </td>
                            <td className="cat-roster__actions">
                                <button
                                    type="button"
                                    className="cat-button cat-button--link"
                                    onClick={() => onEdit(entry)}
                                >
                                    {__("Edit", "context-alt-text")}
                                </button>
                                {entry.remoteId && (
                                    <button
                                        type="button"
                                        className="cat-button cat-button--link cat-button--danger"
                                        onClick={() => {
                                            void onDelete(entry.remoteId!);
                                        }}
                                    >
                                        {__("Delete", "context-alt-text")}
                                    </button>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};
