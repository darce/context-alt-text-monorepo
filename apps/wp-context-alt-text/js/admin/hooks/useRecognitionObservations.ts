import * as React from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import type {
    AdminConfig,
    RecognitionObservationAttachment,
    RecognitionObservationCandidate,
    RecognitionObservationRecord,
    RecognitionObservationsResult,
    RecognitionObservationSummary,
} from "@/admin/types";
import { handleJsonResponse, ensureOk, buildHeaders } from "@/admin/utils/http";
import { toFiniteNumber, toNumberOrNull, toStringOrNull } from "@/admin/utils/normalization/primitives";

export interface RecognitionObservationFilters {
    status?: "matched" | "needs_review" | null;
    perPage?: number;
    page?: number;
    attachmentIds?: number[];
}

export interface UpdateObservationArgs {
    attachmentId: number;
    observationId: string;
    status?: "matched" | "needs_review";
    roster?: {
        remoteId?: string | null;
        name?: string | null;
        displayName?: string | null;
    } | null;
}

export interface UseRecognitionObservationsArgs {
    config: AdminConfig;
    filters: RecognitionObservationFilters;
}

export interface UseRecognitionObservationsResult {
    query: UseQueryResult<RecognitionObservationsResult, Error>;
    hasEndpoint: boolean;
    canUpdateObservation: boolean;
    updateObservation: (args: UpdateObservationArgs) => Promise<RecognitionObservationAttachment>;
    isUpdating: boolean;
    retryRecognition: () => Promise<{ success: boolean; submitted: number; message: string }>;
    isRetrying: boolean;
}

const DEFAULT_PER_PAGE = 20;

const defaultSummary: RecognitionObservationSummary = {
    attachments: 0,
    observations: {
        total: 0,
        matched: 0,
        needs_review: 0,
    },
};

const defaultResult: RecognitionObservationsResult = {
    items: [],
    total: 0,
    page: 1,
    perPage: DEFAULT_PER_PAGE,
    totalPages: 1,
    summary: defaultSummary,
};

const observationsKey = (endpoint: string, filters: RecognitionObservationFilters) =>
    ["recognition-observations", endpoint, filters] as const;

const buildObservationsUrl = (endpoint: string, filters: RecognitionObservationFilters): string => {
    try {
        const url = new URL(endpoint, typeof window !== "undefined" ? window.location.origin : undefined);
        const params = url.searchParams;
        const perPage = filters.perPage && filters.perPage > 0 ? filters.perPage : DEFAULT_PER_PAGE;

        params.set("per_page", String(perPage));

        const page = filters.page && filters.page > 0 ? filters.page : 1;
        params.set("page", String(page));

        if (filters.status) {
            params.set("status", filters.status);
        } else {
            params.delete("status");
        }

        if (filters.attachmentIds && filters.attachmentIds.length > 0) {
            params.set("attachment_ids", filters.attachmentIds.join(","));
        } else {
            params.delete("attachment_ids");
        }

        return url.toString();
    } catch {
        return endpoint;
    }
};

const normalizeRoster = (candidate: unknown): RecognitionObservationRecord["roster"] => {
    if (!candidate || typeof candidate !== "object") {
        return null;
    }

    const roster = candidate as Record<string, unknown>;
    const remoteId = toStringOrNull(roster.remoteId);
    const name = toStringOrNull(roster.name);
    const displayName = toStringOrNull(roster.displayName);

    if (!remoteId && !name && !displayName) {
        return null;
    }

    return {
        remoteId,
        name,
        displayName,
    };
};

const normalizeCandidate = (candidate: Record<string, unknown>): RecognitionObservationCandidate | null => {
    const remoteId = toStringOrNull(candidate.remoteId ?? candidate.unique_id);
    const name = toStringOrNull(candidate.name);
    const confidence = toNumberOrNull(candidate.confidence ?? candidate.similarity);
    const similarity = toFiniteNumber(candidate.similarity, 0);
    const meetsThreshold = Boolean(candidate.meetsThreshold ?? candidate.meets_threshold);

    if (!remoteId && !name && confidence === null && similarity <= 0) {
        return null;
    }

    return {
        remoteId,
        name,
        confidence,
        similarity,
        meetsThreshold,
    };
};

const normalizeObservationRecord = (candidate: Record<string, unknown>): RecognitionObservationRecord => {
    const boundingBoxRaw = Array.isArray(candidate.boundingBox) ? candidate.boundingBox : [];
    const boundingBox = boundingBoxRaw.slice(0, 4).map((value) => toFiniteNumber(value, 0));
    const statusRaw = toStringOrNull(candidate.status);
    const status = statusRaw === "matched" || statusRaw === "needs_review" ? statusRaw : "needs_review";
    const source =
        typeof candidate.source === "object" && candidate.source !== null
            ? (candidate.source as Record<string, unknown>)
            : null;

    const matchInput =
        typeof candidate.match === "object" && candidate.match !== null
            ? (candidate.match as Record<string, unknown>)
            : {};

    const candidatesInput = Array.isArray(candidate.candidates)
        ? candidate.candidates.filter(
              (item): item is Record<string, unknown> => typeof item === "object" && item !== null,
          )
        : [];

    const detectionConfidence = toFiniteNumber(candidate.confidence, 0);

    const matchConfidenceRaw = toFiniteNumber(matchInput.confidence, 0);
    const matchSimilarity = toFiniteNumber(matchInput.similarity, 0);
    const normalizedCandidates = candidatesInput
        .map((entry) => normalizeCandidate(entry))
        .filter((entry): entry is RecognitionObservationCandidate => entry !== null);

    const bestCandidateConfidence = normalizedCandidates.reduce((current, entry) => {
        const candidateConfidence = entry.confidence ?? entry.similarity;
        return candidateConfidence > current ? candidateConfidence : current;
    }, 0);

    const resolvedMatchConfidence =
        matchConfidenceRaw > 0 ? matchConfidenceRaw : matchSimilarity > 0 ? matchSimilarity : bestCandidateConfidence;

    const normalizedConfidence = resolvedMatchConfidence > 0 ? resolvedMatchConfidence : detectionConfidence;

    const normalizedMatch = {
        isMatch: Boolean(matchInput.isMatch),
        similarity: matchSimilarity,
        confidence: matchConfidenceRaw,
        threshold: toFiniteNumber(matchInput.threshold, 0),
    };

    return {
        observationId: toStringOrNull(candidate.observationId) ?? "",
        label: toStringOrNull(candidate.label) ?? "",
        entityType: toStringOrNull(candidate.entityType) ?? "",
        confidence: normalizedConfidence,
        detectionConfidence: detectionConfidence > 0 ? detectionConfidence : null,
        matchConfidence: resolvedMatchConfidence > 0 ? resolvedMatchConfidence : null,
        area: toFiniteNumber(candidate.area, 0),
        boundingBox,
        status,
        source,
        match: normalizedMatch,
        roster: normalizeRoster(candidate.roster ?? null),
        candidates: normalizedCandidates,
    };
};

const normalizeObservationAttachment = (candidate: Record<string, unknown>): RecognitionObservationAttachment => {
    const summaryInput =
        typeof candidate.summary === "object" && candidate.summary !== null
            ? (candidate.summary as Record<string, unknown>)
            : {};

    const summary = {
        total: toFiniteNumber(summaryInput.total, 0),
        matched: toFiniteNumber(summaryInput.matched, 0),
        needs_review: toFiniteNumber(summaryInput.needs_review, 0),
    };

    const observationsInput = Array.isArray(candidate.observations)
        ? candidate.observations.filter(
              (item): item is Record<string, unknown> => typeof item === "object" && item !== null,
          )
        : [];

    const statusRaw = toStringOrNull(candidate.status);
    const status =
        statusRaw === "matched" || statusRaw === "needs_review"
            ? statusRaw
            : summary.needs_review > 0
              ? "needs_review"
              : "matched";

    const contextInput =
        typeof candidate.context === "object" && candidate.context !== null
            ? (candidate.context as Record<string, unknown>)
            : {};

    return {
        attachmentId: toNumberOrNull(candidate.attachmentId),
        jobId: toStringOrNull(candidate.jobId),
        updatedAt: toNumberOrNull(candidate.updatedAt),
        status,
        summary,
        context: {
            filename: toStringOrNull(contextInput.filename) ?? undefined,
            imageUrl: toStringOrNull(contextInput.imageUrl) ?? undefined,
        },
        observations: observationsInput.map((item) => normalizeObservationRecord(item)),
        confidenceScore: toFiniteNumber(candidate.confidenceScore, 0),
        sourceRemoteId: toStringOrNull(candidate.sourceRemoteId),
    };
};

const buildSummary = (items: RecognitionObservationAttachment[]): RecognitionObservationSummary => {
    return items.reduce<RecognitionObservationSummary>(
        (accumulator, item) => {
            return {
                attachments: accumulator.attachments + 1,
                observations: {
                    total: accumulator.observations.total + item.summary.total,
                    matched: accumulator.observations.matched + item.summary.matched,
                    needs_review: accumulator.observations.needs_review + item.summary.needs_review,
                },
            };
        },
        {
            attachments: 0,
            observations: {
                total: 0,
                matched: 0,
                needs_review: 0,
            },
        },
    );
};

const normalizeResponse = (payload: Record<string, unknown>): RecognitionObservationsResult => {
    const itemsInput = Array.isArray(payload.items)
        ? payload.items.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
        : [];

    const items = itemsInput.map((item) => normalizeObservationAttachment(item));
    const summaryInput =
        typeof payload.summary === "object" && payload.summary !== null
            ? (payload.summary as Record<string, unknown>)
            : {};

    const observationsSummaryInput =
        typeof summaryInput.observations === "object" && summaryInput.observations !== null
            ? (summaryInput.observations as Record<string, unknown>)
            : {};

    const summary: RecognitionObservationSummary = {
        attachments: toFiniteNumber(summaryInput.attachments, items.length),
        observations: {
            total: toFiniteNumber(observationsSummaryInput.total, 0),
            matched: toFiniteNumber(observationsSummaryInput.matched, 0),
            needs_review: toFiniteNumber(observationsSummaryInput.needs_review, 0),
        },
    };

    if (summary.attachments === 0 && items.length > 0) {
        summary.attachments = items.length;
    }

    const total = toFiniteNumber(payload.total, items.length);
    const pageInput = toFiniteNumber(payload.page, 1);
    const perPageInput = toFiniteNumber(payload.per_page ?? payload.perPage, DEFAULT_PER_PAGE);
    const totalPagesInput = toFiniteNumber(payload.total_pages ?? payload.totalPages, 1);

    const normalizedPage = pageInput > 0 ? Math.trunc(pageInput) : 1;
    const normalizedPerPage = perPageInput > 0 ? Math.trunc(perPageInput) : DEFAULT_PER_PAGE;
    const normalizedTotalPages = totalPagesInput > 0 ? Math.trunc(totalPagesInput) : 1;

    return {
        items,
        total,
        page: normalizedPage,
        perPage: normalizedPerPage,
        totalPages: normalizedTotalPages,
        summary: summary.attachments > 0 ? summary : buildSummary(items),
    };
};

export const useRecognitionObservations = ({
    config,
    filters,
}: UseRecognitionObservationsArgs): UseRecognitionObservationsResult => {
    const queryClient = useQueryClient();
    const endpoint = config.endpoints?.recognitionObservations ?? "";
    const updateEndpoint = config.endpoints?.recognitionObservationUpdate ?? "";
    const hasEndpoint = Boolean(endpoint);
    const canUpdateObservation = Boolean(updateEndpoint);
    const queryKey = observationsKey(endpoint, filters);

    const query = useQuery<RecognitionObservationsResult, Error>({
        queryKey,
        enabled: hasEndpoint,
        initialData: defaultResult,
        queryFn: async () => {
            if (!endpoint) {
                return defaultResult;
            }

            const url = buildObservationsUrl(endpoint, filters);
            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: buildHeaders(config.restNonce),
            });

            const payload = await handleJsonResponse(await ensureOk(response));
            return normalizeResponse(payload as Record<string, unknown>);
        },
        refetchOnMount: "always",
        refetchOnWindowFocus: hasEndpoint,
        staleTime: 0,
        refetchInterval: hasEndpoint ? 15_000 : false,
    });

    const refreshObservations = React.useCallback(() => {
        void queryClient.invalidateQueries({ queryKey });
    }, [queryClient, queryKey]);

    const updateObservation = useMutation({
        mutationFn: async ({ attachmentId, observationId, status, roster }: UpdateObservationArgs) => {
            if (!canUpdateObservation || !updateEndpoint) {
                throw new Error("Observation update endpoint is unavailable.");
            }

            if (!attachmentId || !observationId) {
                throw new Error("An attachment and observation identifier are required.");
            }

            const base = updateEndpoint.replace(/\/+$/, "");
            const target = `${base}/${encodeURIComponent(String(attachmentId))}/${encodeURIComponent(observationId)}`;
            const payload: Record<string, unknown> = {};

            if (status) {
                payload.status = status;
            }

            if (typeof roster !== "undefined") {
                payload.roster = roster;
            }

            if (Object.keys(payload).length === 0) {
                throw new Error("No updates were provided for the observation.");
            }

            const response = await fetch(target, {
                method: "PATCH",
                credentials: "same-origin",
                headers: buildHeaders(config.restNonce, true),
                body: JSON.stringify(payload),
            });

            const data = await handleJsonResponse(await ensureOk(response));
            const record = (data as Record<string, unknown>).record;

            if (!record || typeof record !== "object") {
                throw new Error("Observation update response was missing data.");
            }

            return normalizeObservationAttachment(record as Record<string, unknown>);
        },
        onSuccess: () => {
            refreshObservations();
        },
    });

    const retryRecognition = useMutation({
        mutationFn: async () => {
            if (!hasEndpoint) {
                throw new Error("Observations endpoint is unavailable.");
            }

            const retryEndpoint = config.endpoints?.observationsRetry;
            if (!retryEndpoint) {
                throw new Error("Retry endpoint is not configured.");
            }

            const response = await fetch(retryEndpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: buildHeaders(config.restNonce, true),
            });

            const data = await handleJsonResponse(await ensureOk(response));
            return data as { success: boolean; submitted: number; message: string };
        },
        onSuccess: () => {
            // Refresh observations after a delay to allow recognition jobs to start
            setTimeout(() => {
                refreshObservations();
            }, 2000);
        },
    });

    return {
        query,
        hasEndpoint,
        canUpdateObservation,
        updateObservation: updateObservation.mutateAsync,
        isUpdating: updateObservation.isPending,
        retryRecognition: retryRecognition.mutateAsync,
        isRetrying: retryRecognition.isPending,
    };
};
