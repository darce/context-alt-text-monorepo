import React from "react";
import { emitDashboardEvent } from "@/admin/analytics";
import type { WorkbenchData } from "@/admin/types";

/**
 * Props for useWorkbenchAnalytics hook
 */
interface UseWorkbenchAnalyticsProps {
    bootstrap: WorkbenchData;
    perPage: number;
    filters: {
        status: string | null;
        search: string | null;
    };
}

/**
 * Custom hook for tracking workbench analytics events
 *
 * Sends a one-time "workbench_seen" analytics event when the component mounts
 * with pagination state, view mode, and active filters.
 *
 * @param props - Analytics tracking parameters
 *
 * @example
 * ```tsx
 * useWorkbenchAnalytics({
 *   bootstrap,
 *   perPage: 20,
 *   filters: { status: null, search: "" }
 * });
 * ```
 */
export function useWorkbenchAnalytics({ bootstrap, perPage, filters }: UseWorkbenchAnalyticsProps): void {
    const eventSent = React.useRef(false);

    React.useEffect(() => {
        if (eventSent.current) {
            return;
        }

        eventSent.current = true;

        emitDashboardEvent("cat_workbench_seen", {
            pagination: {
                page: bootstrap.pagination?.page ?? 1,
                perPage,
            },
            viewMode: bootstrap.viewMode,
            filters,
        });
    }, [bootstrap.pagination?.page, bootstrap.viewMode, perPage, filters]);
}
