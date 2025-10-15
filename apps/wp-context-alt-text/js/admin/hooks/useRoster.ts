import * as React from "react";
import {
    useQuery,
    useMutation,
    useQueryClient,
    type UseQueryResult,
} from "@tanstack/react-query";

import type { AdminConfig, RosterData, RosterEntry, RosterStats } from "@/admin/types";
import {
    normalizeRosterEntry,
    normalizeRosterStats,
} from "@/admin/dashboardData";
import { handleJsonResponse, ensureOk } from "@/admin/utils/http";

export interface RosterFilters {
    search?: string | null;
    page?: number;
    perPage?: number;
    type?: string | null;
    status?: "LOCAL" | "SYNCED" | "CONFLICT" | null;
}

export interface RosterFormValues {
    label: string;
    type: string;
    avatarUrl?: string | null;
    remoteId?: string | null;
    avatarId?: number | null;
    resolveObservation?: {
        attachmentId: number;
        observationId: string;
        status?: "matched" | "needs_review";
        label?: string | null;
        entityType?: string | null;
    } | null;
    referenceImages?: {
        attachmentId?: number | null;
        imageUrl?: string | null;
        observationId?: string | null;
        boundingBox?: number[] | null;
        metadata?: Record<string, unknown>;
    }[];
}

interface RosterQueryResult {
    entries: RosterEntry[];
    stats: RosterStats;
    total: number;
    page: number;
    perPage: number;
    totalPages: number;
    filters: RosterFilters;
    syncState: Record<string, unknown>;
}

const DEFAULT_PAGE = 1;
const DEFAULT_PER_PAGE = 20;

const buildHeaders = (config: AdminConfig, includeJson = false): HeadersInit => {
    const headers: Record<string, string> = {};

    if (includeJson) {
        headers["Content-Type"] = "application/json";
    }

    if (config.restNonce) {
        headers["X-WP-Nonce"] = config.restNonce;
    }

    return headers;
};

const buildRosterUrl = (endpoint: string, filters: RosterFilters): string => {
    try {
        const url = new URL(endpoint, typeof window !== "undefined" ? window.location.origin : undefined);
        const params = url.searchParams;
        const page = filters.page && filters.page > 0 ? filters.page : DEFAULT_PAGE;
        const perPage = filters.perPage && filters.perPage > 0 ? filters.perPage : DEFAULT_PER_PAGE;

        params.set("page", String(page));
        params.set("per_page", String(perPage));

        if (filters.search) {
            params.set("search", filters.search);
        } else {
            params.delete("search");
        }

        if (filters.type) {
            params.set("type", filters.type);
        } else {
            params.delete("type");
        }

        if (filters.status) {
            params.set("status", filters.status);
        } else {
            params.delete("status");
        }

        return url.toString();
    } catch {
        return endpoint;
    }
};

const rosterKey = (filters: RosterFilters) => ["roster", filters] as const;

const toRosterResult = (payload: Record<string, unknown>, filters: RosterFilters): RosterQueryResult => {
    const entriesRaw = Array.isArray(payload.entries) ? payload.entries : [];
    const entries: RosterEntry[] = entriesRaw
        .map((item) => normalizeRosterEntry(item as Partial<RosterEntry>))
        .filter((item): item is RosterEntry => item !== null);

    const stats = normalizeRosterStats(payload.stats as Partial<RosterStats> | undefined);
    const total = Number(payload.total);
    const perPage = Number(payload.perPage ?? payload.per_page);
    const page = Number(payload.page ?? DEFAULT_PAGE);
    const totalPages = Number(payload.totalPages ?? payload.total_pages ?? 0);

    return {
        entries,
        stats,
        total: Number.isFinite(total) && total >= 0 ? total : entries.length,
        page: Number.isFinite(page) && page > 0 ? page : DEFAULT_PAGE,
        perPage: Number.isFinite(perPage) && perPage > 0 ? perPage : DEFAULT_PER_PAGE,
        totalPages: Number.isFinite(totalPages) && totalPages >= 0 ? totalPages : 0,
        filters,
        syncState: typeof payload.syncState === "object" && payload.syncState !== null
            ? (payload.syncState as Record<string, unknown>)
            : {},
    };
};

const rosterResultFromBootstrap = (bootstrap: RosterData, filters: RosterFilters): RosterQueryResult => ({
    entries: bootstrap.entries,
    stats: bootstrap.stats,
    total: bootstrap.entries.length,
    page: filters.page && filters.page > 0 ? filters.page : DEFAULT_PAGE,
    perPage: filters.perPage && filters.perPage > 0 ? filters.perPage : DEFAULT_PER_PAGE,
    totalPages: bootstrap.entries.length > 0
        ? Math.ceil(bootstrap.entries.length / (filters.perPage ?? DEFAULT_PER_PAGE))
        : 0,
    filters,
    syncState: {},
});

const isInitialFilters = (filters: RosterFilters): boolean => {
    return (
        !filters.search
        && !filters.type
        && !filters.status
        && (!filters.page || filters.page === DEFAULT_PAGE)
    );
};

const encodeRosterBody = (values: RosterFormValues): Record<string, unknown> => {
    const metadata: Record<string, unknown> = {};
    const referenceImages: Record<string, unknown>[] = [];

    if (values.avatarUrl) {
        metadata.avatarUrl = values.avatarUrl;
        referenceImages.push({ image_url: values.avatarUrl });
    }

    if (typeof values.avatarId === "number" && Number.isFinite(values.avatarId) && values.avatarId > 0) {
        metadata.avatarAttachmentId = values.avatarId;
        if (referenceImages.length > 0) {
            referenceImages[0] = {
                ...referenceImages[0],
                attachment_id: String(values.avatarId),
            };
        }
    }

    const payload: Record<string, unknown> = {
        label: values.label,
        type: values.type,
    };

    if (Array.isArray(values.referenceImages)) {
        for (const candidate of values.referenceImages) {
            if (!candidate) {
                continue;
            }

            const normalized: Record<string, unknown> = {};
            const imageUrl = typeof candidate.imageUrl === "string" ? candidate.imageUrl.trim() : "";

            if (imageUrl !== "") {
                normalized.image_url = imageUrl;
            }

            if (typeof candidate.attachmentId === "number" && Number.isFinite(candidate.attachmentId) && candidate.attachmentId > 0) {
                normalized.attachment_id = String(candidate.attachmentId);
            }

            if (candidate.boundingBox && Array.isArray(candidate.boundingBox)) {
                const box = candidate.boundingBox
                    .slice(0, 4)
                    .map((value) => (typeof value === "number" && Number.isFinite(value) ? value : Number(value)))
                    .filter((value) => typeof value === "number" && Number.isFinite(value));

                if (box.length === 4) {
                    normalized.bounding_box = box;
                }
            }

            const metadataPayload: Record<string, unknown> = {
                source: "recognition",
            };

            if (candidate.observationId) {
                metadataPayload.observationId = candidate.observationId;
            }

            if (candidate.metadata && typeof candidate.metadata === "object") {
                Object.assign(metadataPayload, candidate.metadata);
            }

            Object.keys(metadataPayload).forEach((key) => {
                if (metadataPayload[key] === null || metadataPayload[key] === undefined) {
                    delete metadataPayload[key];
                }
            });

            if (Object.keys(metadataPayload).length > 0) {
                normalized.metadata = metadataPayload;
            }

            if (Object.keys(normalized).length > 0) {
                referenceImages.push(normalized);
            }
        }
    }

    const resolution = values.resolveObservation;
    if (resolution) {
        const attachmentId = Math.trunc(resolution.attachmentId);
        const observationId = typeof resolution.observationId === "string"
            ? resolution.observationId.trim()
            : "";

        if (attachmentId > 0 && observationId !== "") {
            const update: Record<string, unknown> = {
                attachmentId,
                observationId,
            };

            const status = resolution.status;
            if (status === "matched" || status === "needs_review") {
                update.status = status;
            } else {
                update.status = "matched";
            }

            const label = typeof resolution.label === "string" ? resolution.label.trim() : "";
            if (label !== "") {
                update.label = label;
            }

            const entityType = typeof resolution.entityType === "string" ? resolution.entityType.trim() : "";
            if (entityType !== "") {
                update.entityType = entityType;
            }

            payload.resolveObservation = update;
        }
    }

    if (Object.keys(metadata).length > 0) {
        payload.metadata = metadata;
    }

    if (referenceImages.length > 0) {
        payload.referenceImages = referenceImages;
    }

    return payload;
};

interface UseRosterArgs {
    initialData: RosterData;
    config: AdminConfig;
    filters: RosterFilters;
}

interface UseRosterResult {
    query: UseQueryResult<RosterQueryResult, Error>;
    hasEndpoint: boolean;
    createEntry: (values: RosterFormValues) => Promise<RosterEntry | null>;
    updateEntry: (values: RosterFormValues) => Promise<RosterEntry | null>;
    deleteEntry: (remoteId: string) => Promise<boolean>;
    syncRoster: () => Promise<RosterQueryResult>;
    isSyncing: boolean;
}

export const useRoster = ({ initialData, config, filters }: UseRosterArgs): UseRosterResult => {
    const queryClient = useQueryClient();
    const rosterEndpoint = config.endpoints?.rosterEntries ?? "";
    const syncEndpoint = config.endpoints?.rosterSync ?? "";
    const hasEndpoint = Boolean(rosterEndpoint);
    const invalidateObservations = React.useCallback(
        (payload: unknown) => {
            if (!payload || typeof payload !== "object") {
                return;
            }

            const record = payload as Record<string, unknown>;
            if (record.observation && typeof record.observation === "object") {
                void queryClient.invalidateQueries({ queryKey: ["recognition-observations"] });
                return;
            }

            if (Array.isArray(record.autoMatched) && record.autoMatched.length > 0) {
                void queryClient.invalidateQueries({ queryKey: ["recognition-observations"] });
            }
        },
        [queryClient],
    );

    const query = useQuery<RosterQueryResult, Error>({
        queryKey: rosterKey(filters),
        enabled: hasEndpoint,
        initialData: hasEndpoint && isInitialFilters(filters)
            ? rosterResultFromBootstrap(initialData, filters)
            : undefined,
        queryFn: async () => {
            if (!rosterEndpoint) {
                return rosterResultFromBootstrap(initialData, filters);
            }

            const url = buildRosterUrl(rosterEndpoint, filters);
            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: buildHeaders(config),
            });

            const payload = await handleJsonResponse(await ensureOk(response));

            return toRosterResult(payload as Record<string, unknown>, filters);
        },
        staleTime: 30_000,
    });

    const refreshRoster = React.useCallback(() => {
        void queryClient.invalidateQueries({ queryKey: ["roster"] });
    }, [queryClient]);

    const createEntry = useMutation({
        mutationFn: async (values: RosterFormValues) => {
            if (!rosterEndpoint) {
                throw new Error("Roster endpoint is unavailable.");
            }

            const response = await fetch(rosterEndpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: buildHeaders(config, true),
                body: JSON.stringify(encodeRosterBody(values)),
            });

            const payload = await handleJsonResponse(await ensureOk(response));
            const entry = normalizeRosterEntry((payload as Record<string, unknown>).entry as Partial<RosterEntry> | undefined);

            invalidateObservations(payload);

            return entry;
        },
        onSuccess: () => {
            refreshRoster();
        },
    });

    const updateEntry = useMutation({
        mutationFn: async (values: RosterFormValues) => {
            if (!values.remoteId) {
                throw new Error("A roster entry ID is required for updates.");
            }

            if (!rosterEndpoint) {
                throw new Error("Roster endpoint is unavailable.");
            }

            const endpoint = rosterEndpoint.replace(/\/$/, "") + "/" + encodeURIComponent(values.remoteId);
            const response = await fetch(endpoint, {
                method: "PATCH",
                credentials: "same-origin",
                headers: buildHeaders(config, true),
                body: JSON.stringify(encodeRosterBody(values)),
            });

            const payload = await handleJsonResponse(await ensureOk(response));
            const entry = normalizeRosterEntry((payload as Record<string, unknown>).entry as Partial<RosterEntry> | undefined);

            invalidateObservations(payload);

            return entry;
        },
        onSuccess: () => {
            refreshRoster();
        },
    });

    const deleteEntry = useMutation({
        mutationFn: async (remoteId: string) => {
            if (!remoteId) {
                throw new Error("A roster entry ID is required for deletion.");
            }

            if (!rosterEndpoint) {
                throw new Error("Roster endpoint is unavailable.");
            }

            const endpoint = rosterEndpoint.replace(/\/$/, "") + "/" + encodeURIComponent(remoteId);
            const response = await fetch(endpoint, {
                method: "DELETE",
                credentials: "same-origin",
                headers: buildHeaders(config),
            });

            await ensureOk(response);
            return true;
        },
        onSuccess: () => {
            refreshRoster();
        },
    });

    const syncRoster = useMutation({
        mutationFn: async () => {
            if (!syncEndpoint) {
                throw new Error("Roster sync endpoint is unavailable.");
            }

            const response = await fetch(syncEndpoint, {
                method: "POST",
                credentials: "same-origin",
                headers: buildHeaders(config),
            });

            const payload = await handleJsonResponse(await ensureOk(response));
            const result = toRosterResult(payload as Record<string, unknown>, filters);

            invalidateObservations(payload);

            queryClient.setQueryData(rosterKey(filters), result);
            return result;
        },
    });

    return {
        query,
        hasEndpoint,
        createEntry: createEntry.mutateAsync,
        updateEntry: updateEntry.mutateAsync,
        deleteEntry: deleteEntry.mutateAsync,
        syncRoster: syncRoster.mutateAsync,
        isSyncing: syncRoster.isPending,
    };
};
