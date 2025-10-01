import React from "react";
import { useQuery } from "@tanstack/react-query";

import type { WorkbenchMediaItem } from "@/admin/types";
import { getDashboardConfig, getWorkbenchData, normalizeWorkbenchItem } from "@/admin/dashboardData";

export const WORKBENCH_MEDIA_QUERY_KEY = ["workbench", "media"] as const;

interface UseWorkbenchMediaOptions {
    initialItems?: WorkbenchMediaItem[];
    initialMeta?: {
        total: number;
        totalPages: number;
    };
    page: number;
    perPage: number;
    status?: string;
    search?: string | null;
}

const mapMediaResponse = (payload: unknown): WorkbenchMediaItem[] => {
    if (!Array.isArray(payload)) {
        return [];
    }

    return payload
        .map((candidate) => normalizeWorkbenchItem(candidate as Partial<WorkbenchMediaItem>))
        .filter((candidate): candidate is WorkbenchMediaItem => candidate !== null);
};

type WorkbenchMediaResponse = {
    items: WorkbenchMediaItem[];
    total: number;
    totalPages: number;
};

const parseTotals = (
    headers: Headers,
    fallback: { total: number; totalPages: number },
): { total: number; totalPages: number } => {
    const totalHeader = Number(headers.get("X-WP-Total"));
    const totalPagesHeader = Number(headers.get("X-WP-TotalPages"));

    return {
        total: Number.isFinite(totalHeader) && totalHeader >= 0 ? totalHeader : fallback.total,
        totalPages:
            Number.isFinite(totalPagesHeader) && totalPagesHeader >= 0
                ? totalPagesHeader
                : fallback.totalPages,
    };
};

export const useWorkbenchMedia = ({
    initialItems,
    initialMeta,
    page,
    perPage,
    status = "missing",
    search = null,
}: UseWorkbenchMediaOptions) => {
    const bootstrapData = getWorkbenchData();
    const bootstrapItems = initialItems ?? bootstrapData.items;
    const bootstrapMeta = initialMeta ?? {
        total: bootstrapData.pagination.total,
        totalPages: bootstrapData.pagination.totalPages,
    };

    const config = React.useMemo(() => getDashboardConfig(), []);
    const endpoint = config.endpoints?.workbenchMedia ?? null;

    const normalizedSearch = typeof search === "string" && search.trim().length > 0 ? search.trim() : null;

    const query = useQuery<WorkbenchMediaResponse>({
        queryKey: [...WORKBENCH_MEDIA_QUERY_KEY, endpoint, page, perPage, status, normalizedSearch],
        queryFn: async () => {
            if (!endpoint) {
                return {
                    items: bootstrapItems,
                    total: bootstrapMeta.total,
                    totalPages: bootstrapMeta.totalPages,
                };
            }

            const url = new URL(endpoint);
            url.searchParams.set("page", String(page));
            url.searchParams.set("per_page", String(perPage));
            url.searchParams.set("status", status);

            if (normalizedSearch) {
                url.searchParams.set("search", normalizedSearch);
            }

            const response = await fetch(url.toString(), {
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                },
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch workbench media: ${response.status}`);
            }

            const payload = await response.json();
            const items = mapMediaResponse(payload);
            const totals = parseTotals(response.headers, bootstrapMeta);

            return {
                items,
                total: totals.total,
                totalPages: totals.totalPages,
            };
        },
        initialData: {
            items: bootstrapItems,
            total: bootstrapMeta.total,
            totalPages: bootstrapMeta.totalPages,
        },
        enabled: Boolean(endpoint),
        keepPreviousData: true,
        staleTime: 60_000,
        gcTime: 5 * 60_000,
    });

    const items = query.data?.items ?? bootstrapItems;
    const total = query.data?.total ?? bootstrapMeta.total;
    const totalPages = query.data?.totalPages ?? bootstrapMeta.totalPages;

    return {
        ...query,
        data: items,
        total,
        totalPages,
        page,
        perPage,
        status,
        search: normalizedSearch,
        hasEndpoint: Boolean(endpoint),
    };
};
