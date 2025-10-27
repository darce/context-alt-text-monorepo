import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import type { ClusterSuggestion } from "@/types/face-clustering";

interface ClusterSuggestionsResponse {
    cluster_id?: string;
    suggestions?: Array<Record<string, unknown>>;
}

interface UseClusterSuggestionsResult {
    suggestions: ClusterSuggestion[];
    isLoading: boolean;
    error: Error | null;
    refetch: () => Promise<unknown>;
}

const toNumber = (value: unknown, fallback = 0): number => {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
        return numeric;
    }

    return fallback;
};

const toStringOrNull = (value: unknown): string | null => {
    if (typeof value === "string") {
        return value.trim() === "" ? null : value.trim();
    }

    if (typeof value === "number") {
        return String(value);
    }

    return null;
};

const normalizeSuggestion = (input: Record<string, unknown>, clusterId: string): ClusterSuggestion | null => {
    const rosterId = toStringOrNull(input.roster_id ?? input.rosterId);
    const displayName = toStringOrNull(input.display_name ?? input.displayName);

    if (!rosterId || !displayName) {
        return null;
    }

    const faceIdsRaw = input.face_ids ?? input.faceIds;
    const faceIds = Array.isArray(faceIdsRaw)
        ? faceIdsRaw.filter((value) => typeof value === "string" && value.trim() !== "")
        : [];

    return {
        clusterId,
        rosterId,
        displayName,
        confidence: Number(input.confidence ?? 0),
        confidenceLevel: toStringOrNull(input.confidence_level ?? input.confidenceLevel) as
            | "high"
            | "medium"
            | "low"
            | null
            | undefined,
        matchCount: toNumber(input.match_count ?? input.matchCount ?? faceIds.length, faceIds.length),
        faceIds,
        reason: toStringOrNull(input.reason),
    };
};

export const useClusterSuggestions = (clusterId: string): UseClusterSuggestionsResult => {
    const trimmedClusterId = clusterId.trim();
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters ?? null;
    const restNonce = config.restNonce;
    const enabled = Boolean(endpoint) && trimmedClusterId !== "";

    const fallback = useMemo(
        () => ({
            suggestions: [] as ClusterSuggestion[],
        }),
        [],
    );

    const query = useQuery({
        queryKey: ["cluster-suggestions", endpoint, trimmedClusterId],
        enabled,
        staleTime: 30_000,
        queryFn: async () => {
            const base = endpoint!.endsWith("/") ? endpoint!.slice(0, -1) : endpoint!;
            const url = `${base}/${encodeURIComponent(trimmedClusterId)}/suggestions`;

            const response = await fetchApi<ClusterSuggestionsResponse>(url, {
                restNonce,
            });

            const suggestionsRaw = Array.isArray(response?.suggestions) ? response!.suggestions : [];
            const mapped = suggestionsRaw
                .map((item) => normalizeSuggestion(item, trimmedClusterId))
                .filter((item): item is ClusterSuggestion => item !== null);

            return { suggestions: mapped };
        },
    });

    const data = enabled ? query.data ?? fallback : fallback;

    return {
        suggestions: data.suggestions,
        isLoading: enabled ? query.isFetching : false,
        error: (query.error as Error | null) ?? null,
        refetch: enabled ? query.refetch : async () => undefined,
    };
};

export type { UseClusterSuggestionsResult };
