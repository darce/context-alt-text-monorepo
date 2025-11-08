import React from "react";
import { useQuery } from "@tanstack/react-query";

import type { WorkbenchMediaItem } from "@/admin/types";
import { getDashboardConfig, getWorkbenchData, normalizeWorkbenchItem } from "@/admin/dashboardData";
import { buildApiUrl } from "@/admin/utils/http";

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

interface WorkbenchMediaResponse {
    items: WorkbenchMediaItem[];
    total: number;
    totalPages: number;
}

const parseTotals = (
    headers: Headers,
    fallback: { total: number; totalPages: number },
): { total: number; totalPages: number } => {
    const totalHeader = Number(headers.get("X-WP-Total"));
    const totalPagesHeader = Number(headers.get("X-WP-TotalPages"));

    return {
        total: Number.isFinite(totalHeader) && totalHeader >= 0 ? totalHeader : fallback.total,
        totalPages: Number.isFinite(totalPagesHeader) && totalPagesHeader >= 0 ? totalPagesHeader : fallback.totalPages,
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

    // Simple endpoint resolution: use config endpoint or construct fallback
    const endpoint = React.useMemo(() => {
        const configEndpoint = config.endpoints?.workbenchMedia;
        if (configEndpoint && configEndpoint.trim().length > 0) {
            return configEndpoint;
        }

        // Fallback: Use relative path (works in all contexts)
        return "/wp-json/cat/v1/workbench/media";
    }, [config.endpoints?.workbenchMedia]);

    const normalizedSearch = typeof search === "string" && search.trim().length > 0 ? search.trim() : null;

    const buildLocalResults = React.useCallback((): WorkbenchMediaResponse => {
        const matchesStatus = (item: WorkbenchMediaItem) => {
            if (!status || status === "all") {
                return true;
            }

            return item.status === status;
        };

        const normalizedQuery = normalizedSearch?.toLowerCase() ?? null;
        const matchesSearch = (item: WorkbenchMediaItem) => {
            if (!normalizedQuery) {
                return true;
            }

            const haystacks = [item.title, item.altText ?? "", item.mimeType ?? ""].map(
                (value) => value?.toLowerCase() ?? "",
            );

            return haystacks.some((value) => value.includes(normalizedQuery));
        };

        const filtered = bootstrapItems.filter((item) => matchesStatus(item) && matchesSearch(item));
        const total = filtered.length;
        const totalPages = total > 0 ? Math.ceil(total / perPage) : 0;
        const currentPage = totalPages > 0 ? Math.min(page, totalPages) : page;
        const start = Math.max(0, (currentPage - 1) * perPage);
        const end = start + perPage;

        return {
            items: filtered.slice(start, end),
            total,
            totalPages,
        };
    }, [bootstrapItems, normalizedSearch, page, perPage, status]);

    const localResults = React.useMemo(() => buildLocalResults(), [buildLocalResults]);

    const bootstrapPage = bootstrapData.pagination.page;
    const bootstrapPerPage = bootstrapData.pagination.perPage;

    const hasBootstrapPaginationGap = React.useMemo(() => {
        const total = bootstrapMeta.total;
        const totalPages = bootstrapMeta.totalPages;

        if (typeof totalPages === "number" && totalPages > 1) {
            return true;
        }

        if (typeof total === "number" && total > bootstrapItems.length) {
            return true;
        }

        return false;
    }, [bootstrapItems.length, bootstrapMeta.total, bootstrapMeta.totalPages]);

    // Simplified shouldFetchRemote: fetch if any filter is active
    const shouldFetchRemote = React.useMemo(() => {
        // Fetch from remote if:
        // - Search is active
        // - Page changed from bootstrap
        // - Per page changed from bootstrap
        // - Bootstrap has pagination gap (indicating more data)
        return (
            normalizedSearch !== null ||
            page !== bootstrapPage ||
            perPage !== bootstrapPerPage ||
            hasBootstrapPaginationGap
        );
    }, [bootstrapPerPage, bootstrapPage, hasBootstrapPaginationGap, normalizedSearch, page, perPage]);

    const queryKey = React.useMemo(
        () => [...WORKBENCH_MEDIA_QUERY_KEY, endpoint, page, perPage, status, normalizedSearch],
        [endpoint, normalizedSearch, page, perPage, status],
    );

    const query = useQuery<WorkbenchMediaResponse>({
        queryKey,
        queryFn: async ({ signal }: { signal: AbortSignal }) => {
            // Use shared buildApiUrl utility
            const url = buildApiUrl(endpoint, {
                page,
                per_page: perPage,
                status,
                ...(normalizedSearch ? { search: normalizedSearch } : {}),
            });

            const response = await fetch(url, {
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    ...(config.restNonce ? { "X-WP-Nonce": config.restNonce } : {}),
                },
                signal,
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch workbench media: ${response.status}`);
            }

            const payload: unknown = await response.json();
            const items = mapMediaResponse(payload);
            const totals = parseTotals(response.headers, bootstrapMeta);

            return {
                items,
                total: totals.total,
                totalPages: totals.totalPages,
            };
        },
        enabled: shouldFetchRemote,
        placeholderData: () => localResults,
        initialData: shouldFetchRemote ? undefined : localResults,
        staleTime: shouldFetchRemote ? 0 : Infinity,
        gcTime: 5 * 60_000,
        refetchOnMount: shouldFetchRemote ? "always" : false,
        refetchOnWindowFocus: false,
    });

    const resolvedData = shouldFetchRemote ? (query.data ?? localResults) : localResults;
    const items = resolvedData.items ?? bootstrapItems;
    const total = resolvedData.total ?? bootstrapMeta.total;
    const totalPages = resolvedData.totalPages ?? bootstrapMeta.totalPages;

    // Check if endpoint is available for external features
    const hasEndpoint = Boolean(endpoint);

    return {
        ...query,
        data: items,
        total,
        totalPages,
        page,
        perPage,
        status,
        search: normalizedSearch,
        hasEndpoint,
    };
};
