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

const WORKBENCH_MEDIA_FALLBACK_PATH = "/wp-json/cat/v1/workbench/media";

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

const resolveOriginCandidate = (candidate: unknown, sourceLabel: string): string | null => {
    if (typeof candidate !== "string") {
        return null;
    }

    const trimmed = candidate.trim();
    if (trimmed.length === 0) {
        return null;
    }

    const parse = (value: string, base?: string): string | null => {
        try {
            return new URL(value, base).origin;
        } catch {
            return null;
        }
    };

    const direct = parse(trimmed);
    if (direct) {
        return direct;
    }

    const baseCandidate = (() => {
        if (typeof window !== "undefined" && window.location?.href) {
            return window.location.href;
        }

        if (typeof document !== "undefined" && typeof document.baseURI === "string") {
            return document.baseURI;
        }

        return undefined;
    })();

    if (baseCandidate) {
        const relative = parse(trimmed, baseCandidate);
        if (relative) {
            return relative;
        }
    }

    console.warn(`Unable to parse ${sourceLabel} while resolving Workbench origin`, new TypeError("Invalid URL"));
    return null;
};

const isViableOrigin = (candidate: string | null | undefined): candidate is string => {
    if (typeof candidate !== "string") {
        return false;
    }

    const trimmed = candidate.trim();
    if (trimmed.length === 0) {
        return false;
    }

    if (trimmed === "about:blank" || trimmed === "null") {
        return false;
    }

    return true;
};

const takeFirstOrigin = (candidates: (string | null | undefined)[]): string | null => {
    for (const candidate of candidates) {
        if (isViableOrigin(candidate)) {
            return candidate.trim();
        }
    }

    return null;
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

    const configuredEndpoint = React.useMemo(() => {
        const endpoint = config.endpoints?.workbenchMedia;
        if (typeof endpoint === "string" && endpoint.trim().length > 0) {
            return endpoint.trim();
        }

        return null;
    }, [config.endpoints?.workbenchMedia]);

    const fallbackEndpoint = React.useMemo(() => {
        if (typeof window === "undefined") {
            return null;
        }

        try {
            const { location } = window;
            const originCandidate = (() => {
                if (!location) {
                    return null;
                }

                if (location.origin && location.origin !== "null" && location.origin !== "about:blank") {
                    return resolveOriginCandidate(location.origin, "window.location.origin");
                }

                if (location.protocol && location.host) {
                    return resolveOriginCandidate(`${location.protocol}//${location.host}`, "window.location");
                }

                return null;
            })();

            const fallbackOrigin = takeFirstOrigin([
                originCandidate,
                resolveOriginCandidate(
                    typeof document !== "undefined" ? document.baseURI : null,
                    "document.baseURI",
                ),
                resolveOriginCandidate(
                    (window as unknown as { wpApiSettings?: { root?: string } })?.wpApiSettings?.root,
                    "wpApiSettings.root",
                ),
                resolveOriginCandidate(
                    (window as unknown as { ajaxurl?: string })?.ajaxurl,
                    "window.ajaxurl",
                ),
            ]);

            const fallbackPath = WORKBENCH_MEDIA_FALLBACK_PATH;

            if (fallbackOrigin) {
                try {
                    return new URL(fallbackPath, fallbackOrigin).toString();
                } catch (error) {
                    console.warn("Unable to construct fallback Workbench endpoint from origin", error);
                }
            }

            if (fallbackPath.startsWith("/")) {
                return fallbackPath;
            }

            return `/${fallbackPath}`;
        } catch (error) {
            console.warn("Unable to resolve fallback Workbench endpoint", error);
            return null;
        }
    }, []);

    const resolvedEndpoint = configuredEndpoint ?? fallbackEndpoint;
    const hasConfiguredEndpoint = Boolean(configuredEndpoint);
    const hasResolvedEndpoint = typeof resolvedEndpoint === "string" && resolvedEndpoint.length > 0;

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

            const haystacks = [item.title, item.altText ?? "", item.mimeType ?? ""]
                .map((value) => value?.toLowerCase() ?? "");

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

    const shouldFetchRemote = React.useMemo(() => {
        if (!hasResolvedEndpoint) {
            return false;
        }

        if (normalizedSearch !== null) {
            return true;
        }

        if (bootstrapItems.length === 0) {
            return true;
        }

        if (page !== bootstrapPage) {
            return true;
        }

        if (perPage !== bootstrapPerPage) {
            return true;
        }

        if (hasBootstrapPaginationGap) {
            return true;
        }

        return false;
    }, [bootstrapItems.length, bootstrapPage, bootstrapPerPage, hasBootstrapPaginationGap, hasResolvedEndpoint, normalizedSearch, page, perPage]);

    const runtimeProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
    if (runtimeProcess?.env?.NODE_ENV === "test") {
         
        console.info("useWorkbenchMedia", {
            hasResolvedEndpoint,
            normalizedSearch,
            page,
            perPage,
            shouldFetchRemote,
            resolvedEndpoint,
        });
    }

    const buildRequestUrl = React.useCallback(
        (endpoint: string) => {
            try {
                return new URL(endpoint);
            } catch {
                const fallbackBase = (() => {
                    if (typeof window !== "undefined" && window.location?.href) {
                        return window.location.href;
                    }

                    if (typeof document !== "undefined" && typeof document.baseURI === "string") {
                        return document.baseURI;
                    }

                    return null;
                })();

                if (fallbackBase) {
                    return new URL(endpoint, fallbackBase);
                }

                throw new TypeError("Unable to resolve workbench media endpoint");
            }
        },
        [],
    );

    const queryKey = React.useMemo(
        () => [
            ...WORKBENCH_MEDIA_QUERY_KEY,
            hasResolvedEndpoint ? resolvedEndpoint : "bootstrap",
            page,
            perPage,
            status,
            normalizedSearch,
        ],
        [hasResolvedEndpoint, normalizedSearch, page, perPage, resolvedEndpoint, status],
    );

    const shouldEnableRemoteFetch = hasResolvedEndpoint && shouldFetchRemote;

    const query = useQuery<WorkbenchMediaResponse>({
        queryKey,
        queryFn: async ({ signal }) => {
            if (!hasResolvedEndpoint || !resolvedEndpoint) {
                return localResults;
            }

            const url = buildRequestUrl(resolvedEndpoint);
            url.searchParams.set("page", String(page));
            url.searchParams.set("per_page", String(perPage));
            url.searchParams.set("status", status);

            if (normalizedSearch) {
                url.searchParams.set("search", normalizedSearch);
            }

            if (runtimeProcess?.env?.NODE_ENV === "test") {
                console.info("workbench media fetch", {
                    endpoint: url.toString(),
                    page,
                    perPage,
                    status,
                    search: normalizedSearch,
                });
            }

            const response = await fetch(url.toString(), {
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
        enabled: shouldEnableRemoteFetch,
        placeholderData: () => localResults,
        initialData: shouldEnableRemoteFetch ? undefined : localResults,
        staleTime: shouldEnableRemoteFetch ? 0 : Infinity,
        gcTime: 5 * 60_000,
        refetchOnMount: shouldEnableRemoteFetch ? "always" : false,
        refetchOnWindowFocus: false,
    });

    const resolvedData = shouldEnableRemoteFetch || hasConfiguredEndpoint ? query.data ?? localResults : localResults;
    const items = resolvedData.items ?? bootstrapItems;
    const total = resolvedData.total ?? bootstrapMeta.total;
    const totalPages = resolvedData.totalPages ?? bootstrapMeta.totalPages;

    return {
        ...query,
        data: items,
        total,
        totalPages,
        page,
        perPage,
        status,
        search: normalizedSearch,
        hasEndpoint: hasResolvedEndpoint,
    };
};
