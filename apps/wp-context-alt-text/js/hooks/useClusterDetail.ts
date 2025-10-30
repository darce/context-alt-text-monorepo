import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import type { ClusterSummary, ClusterSampleFace, ClusterFaceDetail, ClusterBoundingBox } from "@/types/face-clustering";

interface ClusterDetailResponse {
    cluster?: Record<string, unknown>;
    faces?: Record<string, unknown>[];
}

interface UseClusterDetailResult {
    cluster: ClusterSummary;
    faces: ClusterFaceDetail[];
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<unknown>;
}

const createFallbackCluster = (clusterId: string): ClusterSummary => ({
    id: clusterId,
    faceCount: 0,
    createdAt: null,
    updatedAt: null,
    sampleFace: null,
    suggestion: null,
});

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

const normalizeSampleFace = (
    input: unknown,
    fallbackAttachmentId: number,
    fallbackThumbnail: string | null,
    fallbackBbox: ClusterBoundingBox | null,
): ClusterSampleFace | null => {
    if (!input || typeof input !== "object") {
        if (fallbackAttachmentId === 0 && !fallbackThumbnail && !fallbackBbox) {
            return null;
        }

        return {
            attachmentId: fallbackAttachmentId,
            thumbnailUrl: fallbackThumbnail,
            bbox: fallbackBbox,
        };
    }

    const data = input as Record<string, unknown>;
    return {
        attachmentId:
            toNumber(data.attachment_id ?? data.attachmentId ?? fallbackAttachmentId, fallbackAttachmentId) ?? 0,
        thumbnailUrl: toStringOrNull(data.thumbnail_url ?? data.thumbnailUrl) ?? fallbackThumbnail,
        bbox: normalizeBoundingBox(data.bbox ?? fallbackBbox ?? null),
    };
};

const normalizeSuggestion = (input: unknown): ClusterSummary["suggestion"] => {
    if (!input || typeof input !== "object") {
        return null;
    }

    const data = input as Record<string, unknown>;
    const rosterId = toStringOrNull(data.roster_id ?? data.rosterId);
    const displayName = toStringOrNull(data.display_name ?? data.displayName);

    if (!rosterId && !displayName) {
        return null;
    }

    const confidence = toNumber(data.confidence ?? null, null);

    return {
        rosterId: rosterId ?? "",
        displayName: displayName ?? "",
        confidence: confidence ?? null,
        reason: toStringOrNull(data.reason),
    };
};

const normalizeCluster = (input: unknown, clusterId: string, faces: ClusterFaceDetail[]): ClusterSummary => {
    const fallbackFace = faces[0] ?? null;

    const defaults: ClusterSummary = {
        id: clusterId,
        faceCount: faces.length,
        createdAt: fallbackFace?.detectedAt ?? null,
        updatedAt: fallbackFace?.detectedAt ?? null,
        sampleFace: fallbackFace
            ? {
                  attachmentId: fallbackFace.attachmentId,
                  thumbnailUrl: fallbackFace.thumbnailUrl ?? null,
                  bbox: fallbackFace.bbox,
              }
            : null,
        suggestion: null,
    };

    if (!input || typeof input !== "object") {
        return defaults;
    }

    const data = input as Record<string, unknown>;
    const sample = normalizeSampleFace(
        data.sample_face ?? data.sampleFace ?? null,
        fallbackFace?.attachmentId ?? 0,
        fallbackFace?.thumbnailUrl ?? null,
        fallbackFace?.bbox ?? null,
    );

    return {
        id: toStringOrNull(data.id) ?? clusterId,
        faceCount: toNumber(data.face_count ?? data.faceCount ?? faces.length, faces.length) ?? faces.length,
        createdAt: toStringOrNull(data.created_at ?? data.createdAt) ?? defaults.createdAt,
        updatedAt: toStringOrNull(data.updated_at ?? data.updatedAt) ?? defaults.updatedAt,
        sampleFace: sample,
        suggestion: normalizeSuggestion(data.suggestion ?? null),
    };
};

const transformResponse = (response: ClusterDetailResponse, clusterId: string) => {
    const faces = Array.isArray(response.faces)
        ? response.faces.map((face) => normalizeFace(face)).filter((face) => face.id !== "")
        : [];

    const cluster = normalizeCluster(response.cluster ?? null, clusterId, faces);

    return { cluster, faces };
};

export const useClusterDetail = (clusterId: string): UseClusterDetailResult => {
    const trimmedClusterId = clusterId.trim();
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters ?? null;
    const restNonce = config.restNonce;
    const enabled = Boolean(endpoint) && trimmedClusterId !== "";
    const fallback = useMemo(
        () => ({
            cluster: createFallbackCluster(trimmedClusterId),
            faces: [] as ClusterFaceDetail[],
        }),
        [trimmedClusterId],
    );

    const query = useQuery({
        queryKey: ["cluster-detail", endpoint, trimmedClusterId],
        enabled,
        queryFn: async () => {
            const base = endpoint!.endsWith("/") ? endpoint!.slice(0, -1) : endpoint!;
            const url = `${base}/${encodeURIComponent(trimmedClusterId)}`;

            const response = await fetchApi<ClusterDetailResponse>(url, {
                restNonce,
            });

            return transformResponse(response ?? {}, trimmedClusterId);
        },
        staleTime: 30_000,
    });

    const data = enabled ? (query.data ?? fallback) : fallback;

    return {
        cluster: data.cluster,
        faces: data.faces,
        isLoading: enabled ? query.isFetching : false,
        error: query.error instanceof Error ? query.error : null,
        refetch: enabled ? query.refetch : () => Promise.resolve(undefined),
    };
};

export type { UseClusterDetailResult, ClusterFaceDetail };
