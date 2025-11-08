import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import type { ClusterSummary, ClusterSampleFace } from "@/types/face-clustering";

export interface UseUnknownClustersOptions {
    page?: number;
    perPage?: number;
    enabled?: boolean;
}

export interface UseUnknownClustersResult {
    clusters: ClusterSummary[];
    total: number;
    page: number;
    perPage: number;
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<unknown>;
}

interface ClusterListResponse {
    clusters?: ApiCluster[];
    total?: number;
    page?: number;
    per_page?: number;
}

interface ApiCluster {
    id?: string;
    face_count?: number;
    sample_face?: {
        attachment_id?: number;
        thumbnail_url?: string | null;
        bbox?: ApiBoundingBox | null;
    } | null;
    /** New paginated API format - array of preview faces */
    preview_faces?: {
        id?: string;
        attachment_id?: number;
        thumbnail_url?: string | null;
        bbox?: ApiBoundingBox | null;
    }[];
    suggestion?: {
        roster_id?: string;
        display_name?: string;
        confidence?: number | string | null;
        reason?: string | null;
    } | null;
    created_at?: string | null;
    updated_at?: string | null;
}

type ApiBoundingBox = Record<string, unknown> | null | undefined;

const toNumber = (value: unknown, fallback: number): number => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
};

const normalizeBoundingBox = (bbox: ApiBoundingBox): ClusterSampleFace["bbox"] => {
    if (!bbox || typeof bbox !== "object") {
        return null;
    }

    const x = Number(bbox.x);
    const y = Number(bbox.y);
    const width = Number(bbox.width);
    const height = Number(bbox.height);

    if ([x, y, width, height].some((value) => !Number.isFinite(value))) {
        return null;
    }

    return {
        x,
        y,
        width,
        height,
    };
};

const mapSuggestion = (input: ApiCluster["suggestion"]): ClusterSummary["suggestion"] => {
    if (!input) {
        return null;
    }

    const rosterId = typeof input.roster_id === "string" ? input.roster_id : "";
    const displayName = typeof input.display_name === "string" ? input.display_name : "";

    if (!rosterId && !displayName) {
        return null;
    }

    const confidence =
        typeof input.confidence === "number"
            ? input.confidence
            : typeof input.confidence === "string"
              ? Number.parseFloat(input.confidence)
              : null;

    return {
        rosterId,
        displayName,
        confidence: Number.isFinite(confidence) ? confidence! : null,
        reason: typeof input.reason === "string" ? input.reason : null,
    };
};

const mapSampleFace = (input: ApiCluster["sample_face"]): ClusterSampleFace => {
    return {
        attachmentId: toNumber(input?.attachment_id, 0),
        thumbnailUrl: typeof input?.thumbnail_url === "string" ? input.thumbnail_url : null,
        bbox: normalizeBoundingBox(input?.bbox),
    };
};

const mapPreviewFaces = (input: ApiCluster["preview_faces"]): ClusterSampleFace[] => {
    if (!Array.isArray(input)) {
        return [];
    }

    return input.map((face) => ({
        attachmentId: toNumber(face?.attachment_id, 0),
        thumbnailUrl: typeof face?.thumbnail_url === "string" ? face.thumbnail_url : null,
        bbox: normalizeBoundingBox(face?.bbox),
    }));
};

const mapCluster = (cluster: ApiCluster): ClusterSummary => {
    const previewFaces = mapPreviewFaces(cluster.preview_faces);

    // Use preview_faces if available (new API), otherwise fall back to sample_face (old API)
    const sampleFace = previewFaces.length > 0 ? previewFaces[0] : mapSampleFace(cluster.sample_face);

    return {
        id: typeof cluster.id === "string" && cluster.id.trim() !== "" ? cluster.id : "unknown",
        faceCount: toNumber(cluster.face_count, 0),
        sampleFace: sampleFace ?? null,
        previewFaces: previewFaces.length > 0 ? previewFaces : undefined,
        suggestion: mapSuggestion(cluster.suggestion),
        createdAt: typeof cluster.created_at === "string" ? cluster.created_at : null,
        updatedAt: typeof cluster.updated_at === "string" ? cluster.updated_at : null,
    };
};

const transformResponse = (
    response: ClusterListResponse,
    defaults: { page: number; perPage: number },
): {
    clusters: ClusterSummary[];
    total: number;
    page: number;
    perPage: number;
} => {
    const clusters = Array.isArray(response.clusters) ? response.clusters.map(mapCluster) : ([] as ClusterSummary[]);

    const total = toNumber(response.total, clusters.length);
    const page = toNumber(response.page, defaults.page);
    const perPage = toNumber(response.per_page, defaults.perPage);

    return {
        clusters,
        total,
        page,
        perPage,
    };
};

export const useUnknownClusters = (options: UseUnknownClustersOptions = {}): UseUnknownClustersResult => {
    const page = options.page ?? 1;
    const perPage = options.perPage ?? 20;
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters;
    const restNonce = config.restNonce;
    const enabled = Boolean(endpoint) && (options.enabled ?? true);

    const fallback = useMemo(
        () => ({
            clusters: [] as ClusterSummary[],
            total: 0,
            page,
            perPage,
        }),
        [page, perPage],
    );

    const query = useQuery({
        queryKey: ["unknown-clusters", endpoint, page, perPage],
        enabled,
        queryFn: async () => {
            const response = await fetchApi<ClusterListResponse>(endpoint!, {
                params: {
                    page,
                    per_page: perPage,
                },
                restNonce,
            });

            return transformResponse(response, { page, perPage });
        },
        staleTime: 30_000,
    });

    const data = enabled ? (query.data ?? fallback) : fallback;

    return {
        clusters: data.clusters,
        total: data.total,
        page: data.page,
        perPage: data.perPage,
        isLoading: enabled ? query.isFetching : false,
        error: query.error ?? null,
        refetch: enabled ? query.refetch : () => Promise.resolve(undefined),
    };
};
