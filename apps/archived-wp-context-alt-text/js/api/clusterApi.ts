import { __ } from "@wordpress/i18n";

import { fetchApi } from "@/admin/utils/http";

export interface ConfirmClusterRequest {
    rosterId: string;
    faceIds: string[];
}

export interface ConfirmedClusterFace {
    faceId: string;
    databaseId: number | null;
    observationId: number | null;
}

export interface CascadeCandidate {
    faceId: string;
    databaseId: number | null;
    confidence: number | null;
}

export interface ConfirmClusterResponse {
    clusterId: string;
    rosterId: string;
    confirmed: ConfirmedClusterFace[];
    labeledCount: number;
    warnings: string[];
    errors: string[];
    cascade: {
        auto: CascadeCandidate[];
        candidates: CascadeCandidate[];
    };
}

const toNumber = (value: unknown): number | null => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
};

const toStringOrNull = (value: unknown): string | null => {
    if (typeof value === "string") {
        const trimmed = value.trim();
        return trimmed === "" ? null : trimmed;
    }

    if (typeof value === "number") {
        return String(value);
    }

    return null;
};

const normalizeFace = (input: unknown): ConfirmedClusterFace | null => {
    if (!input || typeof input !== "object") {
        return null;
    }

    const data = input as Record<string, unknown>;
    const faceId = toStringOrNull(data.face_id ?? data.faceId);

    if (!faceId) {
        return null;
    }

    return {
        faceId,
        databaseId: toNumber(data.database_id ?? data.databaseId),
        observationId: toNumber(data.observation_id ?? data.observationId),
    };
};

const normalizeCascadeEntry = (input: unknown): CascadeCandidate | null => {
    if (!input || typeof input !== "object") {
        return null;
    }

    const data = input as Record<string, unknown>;
    const faceId = toStringOrNull(data.face_id ?? data.faceId);

    if (!faceId) {
        return null;
    }

    return {
        faceId,
        databaseId: toNumber(data.database_id ?? data.databaseId),
        confidence: toNumber(data.confidence ?? null),
    };
};

const normalizeConfirmResponse = (input: unknown): ConfirmClusterResponse => {
    if (!input || typeof input !== "object") {
        return {
            clusterId: "",
            rosterId: "",
            confirmed: [],
            labeledCount: 0,
            warnings: [],
            errors: [__("Unable to confirm cluster.", "context-alt-text")],
            cascade: {
                auto: [],
                candidates: [],
            },
        };
    }

    const data = input as Record<string, unknown>;

    const confirmedRaw: unknown[] = Array.isArray(data.confirmed) ? data.confirmed : [];
    const cascadeRaw = data.cascade;
    const cascadeRecord =
        cascadeRaw !== null && typeof cascadeRaw === "object" ? (cascadeRaw as Record<string, unknown>) : null;

    const cascadeAutoRaw: unknown[] = Array.isArray(cascadeRecord?.auto) ? (cascadeRecord?.auto as unknown[]) : [];

    const cascadeCandidatesRaw: unknown[] = Array.isArray(cascadeRecord?.candidates)
        ? (cascadeRecord?.candidates as unknown[])
        : [];

    return {
        clusterId: toStringOrNull(data.cluster_id ?? data.clusterId) ?? "",
        rosterId: toStringOrNull(data.roster_id ?? data.rosterId) ?? "",
        confirmed: confirmedRaw
            .map((face) => normalizeFace(face))
            .filter((face): face is ConfirmedClusterFace => face !== null),
        labeledCount: Number(data.labeled_count ?? data.labeledCount ?? 0),
        warnings: Array.isArray(data.warnings)
            ? data.warnings.filter((value): value is string => typeof value === "string")
            : [],
        errors: Array.isArray(data.errors)
            ? data.errors.filter((value): value is string => typeof value === "string")
            : [],
        cascade: {
            auto: cascadeAutoRaw
                .map((entry) => normalizeCascadeEntry(entry))
                .filter((entry): entry is CascadeCandidate => entry !== null),
            candidates: cascadeCandidatesRaw
                .map((entry) => normalizeCascadeEntry(entry))
                .filter((entry): entry is CascadeCandidate => entry !== null),
        },
    };
};

export const confirmCluster = async (
    clusterId: string,
    request: ConfirmClusterRequest,
    restNonce?: string,
): Promise<ConfirmClusterResponse> => {
    const url = `/wp-json/cat/v1/clusters/${encodeURIComponent(clusterId)}/confirm`;

    const response = await fetchApi(url, {
        method: "POST",
        restNonce,
        body: {
            roster_id: request.rosterId,
            face_ids: request.faceIds,
        },
    });

    return normalizeConfirmResponse(response);
};
