import React from "react";
import { __ } from "@wordpress/i18n";
import type { RosterEntry } from "@/admin/types";
import { TooltipProvider, TooltipRoot, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

/**
 * Props for the StatusBadge component.
 */
export interface StatusBadgeProps {
    /**
     * The sync status of the roster entry.
     * - SYNCED: Entry is synchronized with remote
     * - LOCAL: Entry exists only locally
     * - CONFLICT: Entry has conflicting changes
     */
    status: RosterEntry["status"];
}

/**
 * Displays a status badge for a roster entry indicating its sync state.
 * Includes a tooltip with additional context about each status.
 *
 * @param props - Component props
 * @returns A styled badge element with tooltip
 *
 * @example
 * ```tsx
 * <StatusBadge status="SYNCED" />
 * <StatusBadge status="LOCAL" />
 * <StatusBadge status="CONFLICT" />
 * ```
 */
export const StatusBadge = ({ status }: StatusBadgeProps): React.JSX.Element => {
    const badgeText =
        status === "SYNCED"
            ? __("Synced", "context-alt-text")
            : status === "CONFLICT"
              ? __("Conflict", "context-alt-text")
              : __("Local", "context-alt-text");

    const tooltipText =
        status === "SYNCED"
            ? __("This entry is synchronized with the remote roster service", "context-alt-text")
            : status === "CONFLICT"
              ? __("This entry has conflicting changes between local and remote", "context-alt-text")
              : __("This entry only exists locally and hasn't been synced yet", "context-alt-text");

    return (
        <TooltipProvider>
            <TooltipRoot>
                <TooltipTrigger asChild>
                    <span className={`cat-roster__badge cat-roster__badge--${status.toLowerCase()}`}>{badgeText}</span>
                </TooltipTrigger>
                <TooltipContent>
                    <p>{tooltipText}</p>
                </TooltipContent>
            </TooltipRoot>
        </TooltipProvider>
    );
};
