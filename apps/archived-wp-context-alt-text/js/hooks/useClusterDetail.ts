import { useEffect, useMemo, useRef } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import type { ClusterFaceDetail, ClusterBoundingBox } from "@/types/face-clustering";

interface ClusterDetailPageResponse {
    faces: Record<string, unknown>[];
    pagination: {
        current_page: number;
        per_page: number;
        total_pages: number;
        total_faces?: number;
        has_more: boolean;
    };
}

interface UseClusterDetailResult {
    faces: ClusterFaceDetail[];
    fetchNextPage: () => Promise<unknown>;
    hasNextPage: boolean;
    isLoading: boolean;
    isFetchingNextPage: boolean;
    error: Error | null;
    refetch: () => Promise<unknown>;
}

const toNumber = (value: unknown, fallback: number | null = 0): number | null => {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
        return numeric;
    }

    return fallback;
};

const toStringOrNull = (value: unknown): string | null => {
    if (typeof value === "string") {
        return value;
    }

    if (typeof value === "number" || typeof value === "boolean") {
        return String(value);
    }

    return null;
};

const normalizeBoundingBox = (input: unknown): ClusterBoundingBox => {
    if (!input || typeof input !== "object") {
        return { x: 0, y: 0, width: 0, height: 0 };
    }

    const bbox = input as Record<string, unknown>;
    const normalized: ClusterBoundingBox = {
        x: Number(toNumber(bbox.x, 0)),
        y: Number(toNumber(bbox.y, 0)),
        width: Number(toNumber(bbox.width, 0)),
        height: Number(toNumber(bbox.height, 0)),
    };

    const imageWidth = toNumber(bbox.imageWidth ?? bbox.image_width, null);
    const imageHeight = toNumber(bbox.imageHeight ?? bbox.image_height, null);

    if (imageWidth !== null) {
        normalized.imageWidth = imageWidth;
    }

    if (imageHeight !== null) {
        normalized.imageHeight = imageHeight;
    }

    return normalized;
};

const normalizeFace = (input: Record<string, unknown>): ClusterFaceDetail => {
    const attachmentId = toNumber(input.attachmentId ?? input.attachment_id ?? null, 0) ?? 0;
    const bbox = normalizeBoundingBox(input.bbox ?? null);

    return {
        id: toStringOrNull(input.id) ?? "",
        attachmentId,
        databaseId: toNumber(input.databaseId ?? input.database_id ?? null, null),
        bbox,
        thumbnailUrl: toStringOrNull(input.thumbnail_url ?? input.thumbnailUrl),
        clusterId: toStringOrNull(input.clusterId ?? input.cluster_id),
        detectedAt: toStringOrNull(input.detectedAt ?? input.detected_at),
        resolvedAt: toStringOrNull(input.resolvedAt ?? input.resolved_at),
        rosterId: toStringOrNull(input.rosterId ?? input.roster_id),
        embeddingId: toStringOrNull(input.embeddingId ?? input.embedding_id),
    };
};

export const useClusterDetail = (clusterId: string): UseClusterDetailResult => {
    const trimmedClusterId = clusterId.trim();
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters ?? null;
    const restNonce = config.restNonce;
    const enabled = Boolean(endpoint) && trimmedClusterId !== "";
    const queryClient = useQueryClient();
    const hasPrefetchedRef = useRef(false);

    const query = useInfiniteQuery({
        queryKey: ["cluster-detail", endpoint, trimmedClusterId],
        enabled,
        queryFn: async ({ pageParam = 1 }) => {
            const base = endpoint!.endsWith("/") ? endpoint!.slice(0, -1) : endpoint!;
            const url = `${base}/${encodeURIComponent(trimmedClusterId)}?page=${pageParam}`;

            const response = await fetchApi<ClusterDetailPageResponse>(url, {
                restNonce,
            });

            if (!response) {
                return { faces: [], pagination: { has_more: false, current_page: pageParam } };
            }

            const faces = Array.isArray(response.faces)
                ? response.faces.map((face) => normalizeFace(face)).filter((face) => face.id !== "")
                : [];

            return {
                faces,
                pagination: response.pagination,
            };
        },
        getNextPageParam: (lastPage) => {
            if (!lastPage.pagination.has_more) {
                return undefined;
            }
            return (lastPage.pagination.current_page ?? 0) + 1;
        },
        initialPageParam: 1,
        staleTime: 30_000,
    });

    // Automatic prefetch of page 2 when page 1 loads
    useEffect(() => {
        if (enabled && query.data?.pages?.[0]?.pagination?.has_more && !query.isFetching && !hasPrefetchedRef.current) {
            hasPrefetchedRef.current = true;
            const base = endpoint!.endsWith("/") ? endpoint!.slice(0, -1) : endpoint!;
            const url = `${base}/${encodeURIComponent(trimmedClusterId)}?page=2`;

            // Prefetch page 2 in the background without modifying current query data
            void queryClient.prefetchQuery({
                queryKey: ["cluster-detail-page-2", endpoint, trimmedClusterId],
                queryFn: async () => {
                    const response = await fetchApi<ClusterDetailPageResponse>(url, {
                        restNonce,
                    });
                    return response;
                },
                staleTime: 30_000,
            });
        }
    }, [enabled, query.data, query.isFetching, endpoint, trimmedClusterId, restNonce, queryClient]);

    const allFaces = useMemo(() => {
        if (!query.data?.pages) {
            return [];
        }
        return query.data.pages.flatMap((page) => page.faces);
    }, [query.data]);

    return {
        faces: allFaces,
        fetchNextPage: () => query.fetchNextPage(),
        hasNextPage: query.hasNextPage ?? false,
        isLoading: enabled ? query.isFetching && !query.isFetchingNextPage : false,
        isFetchingNextPage: query.isFetchingNextPage,
        error: query.error instanceof Error ? query.error : null,
        refetch: () => query.refetch(),
    };
};

export type { UseClusterDetailResult, ClusterFaceDetail };
