/**
 * Recognition domain normalization utilities.
 *
 * Normalizes recognition-related data structures from API responses.
 */

import { ensureString, toFiniteNumber, toNullableTimestamp, toStringOrNull } from "./primitives";

export interface RecognitionObservationMatch {
    isMatch: boolean;
    similarity: number;
    confidence: number;
    threshold: number;
}

export type RecognitionObservationRoster = {
    remoteId?: string;
    name?: string;
    displayName?: string;
    type?: string;
} | null;

export interface RecognitionObservationCandidate {
    remoteId: string | null;
    name: string | null;
    similarity: number;
    meetsThreshold: boolean;
    confidence: number | null;
}

export interface RecognitionObservationRecord {
    observationId: string;
    label: string;
    entityType: string;
    confidence: number;
    detectionConfidence: number | null;
    matchConfidence: number | null;
    area: number;
    boundingBox: number[];
    status: "matched" | "needs_review" | (string & {});
    source: string;
    match: RecognitionObservationMatch;
    roster: RecognitionObservationRoster;
    candidates: RecognitionObservationCandidate[];
}

export interface RecognitionJobSummary {
    jobId: string;
    status: string;
    accepted: number;
    rejected: number[];
}

export interface RecognitionJobDetails {
    id: string;
    status: string;
    startedAt: number | null;
    completedAt: number | null;
    error: string | null;
    attachments: {
        id: number;
        recognizedAt: number | null;
        observations: number;
        matched: number;
        needsReview: number;
    }[];
}

/**
 * Normalize observation status to valid value.
 */
const normalizeObservationStatus = (
    value: unknown,
): RecognitionObservationRecord["status"] => {
    const normalized = ensureString(value ?? "needs_review");
    if (normalized === "matched" || normalized === "needs_review") {
        return normalized;
    }

    return (normalized || "needs_review") as RecognitionObservationRecord["status"];
};

/**
 * Normalize recognition observation candidates array.
 */
export const normalizeCandidates = (candidates: unknown): RecognitionObservationCandidate[] => {
    if (!Array.isArray(candidates)) {
        return [];
    }

    return candidates
        .map((candidate) => {
            if (!candidate || typeof candidate !== "object") {
                return null;
            }

            const record = candidate as Record<string, unknown>;
            const remoteIdValue = ensureString(record.remoteId ?? record.unique_id ?? "").trim();
            const nameValue = ensureString(record.name ?? "").trim();
            const similarity = toFiniteNumber(record.similarity ?? 0, 0);
            const confidenceValue = toFiniteNumber(record.confidence ?? record.similarity ?? 0, 0);

            return {
                remoteId: remoteIdValue !== "" ? remoteIdValue : null,
                name: nameValue !== "" ? nameValue : null,
                similarity,
                meetsThreshold: Boolean(record.meetsThreshold ?? record.meets_threshold ?? false),
                confidence: confidenceValue > 0 ? confidenceValue : null,
            } satisfies RecognitionObservationCandidate;
        })
        .filter((candidate): candidate is RecognitionObservationCandidate => candidate !== null);
};

/**
 * Normalize recognition observation match data.
 */
export const normalizeMatch = (match: unknown): RecognitionObservationMatch => {
    if (!match || typeof match !== "object") {
        return {
            isMatch: false,
            similarity: 0,
            confidence: 0,
            threshold: 0,
        };
    }

    const data = match as Record<string, unknown>;

    return {
        isMatch: Boolean(data.isMatch ?? data.is_match ?? false),
        similarity: toFiniteNumber(data.similarity ?? data.similarity_score ?? 0, 0),
        confidence: toFiniteNumber(data.confidence ?? data.match_confidence ?? 0, 0),
        threshold: toFiniteNumber(data.threshold ?? data.confidence_threshold ?? 0, 0),
    } satisfies RecognitionObservationMatch;
};

/**
 * Normalize roster reference in observation.
 */
export const normalizeRoster = (roster: unknown): RecognitionObservationRoster => {
    if (!roster || typeof roster !== "object") {
        return null;
    }

    const data = roster as Record<string, unknown>;
    const result: RecognitionObservationRoster = {};

    const remoteId = data.remoteId ?? data.unique_id;
    if (remoteId !== undefined) {
        result.remoteId = ensureString(remoteId);
    }

    if (data.name !== undefined) {
        result.name = ensureString(data.name);
    }

    const displayName = data.displayName ?? data.display_name;
    if (displayName !== undefined) {
        result.displayName = ensureString(displayName);
    }

    const type = data.type ?? (typeof data.metadata === "object" ? (data.metadata as Record<string, unknown>).type : undefined);
    if (type !== undefined) {
        result.type = ensureString(type);
    }

    return Object.keys(result).length > 0 ? result : null;
};

/**
 * Normalize a single observation record from API response.
 */
export const normalizeObservationRecord = (observation: unknown): RecognitionObservationRecord | null => {
    if (!observation || typeof observation !== "object") {
        return null;
    }

    const data = observation as Record<string, unknown>;

    const observationIdValue = ensureString(data.observationId ?? data.observation_id ?? "").trim();
    if (observationIdValue === "") {
        return null;
    }

    const labelValue = ensureString(data.label ?? "");
    const entityTypeValue = ensureString(data.entityType ?? data.entity_type ?? "unknown");
    const confidenceValue = toFiniteNumber(data.confidence ?? 0, 0);
    const detectionConfidenceValue = toFiniteNumber(data.detectionConfidence ?? data.detection_confidence ?? 0, 0);
    const matchConfidenceValue = toFiniteNumber(data.matchConfidence ?? data.match_confidence ?? 0, 0);
    const areaValue = toFiniteNumber(data.area ?? 0, 0);

    let boundingBoxValue: number[] = [];
    if (Array.isArray(data.boundingBox ?? data.bounding_box)) {
        boundingBoxValue = (data.boundingBox ?? data.bounding_box) as number[];
    }

    const statusValue = normalizeObservationStatus(data.status);
    const sourceValue = ensureString(data.source ?? "detection");
    const matchValue = normalizeMatch(data.match);
    const rosterValue = normalizeRoster(data.roster);
    const candidatesValue = normalizeCandidates(data.candidates ?? []);

    return {
        observationId: observationIdValue,
        label: labelValue,
        entityType: entityTypeValue,
        confidence: confidenceValue,
        detectionConfidence: detectionConfidenceValue > 0 ? detectionConfidenceValue : null,
        matchConfidence: matchConfidenceValue > 0 ? matchConfidenceValue : null,
        area: areaValue,
        boundingBox: boundingBoxValue,
        status: statusValue,
        source: sourceValue,
        match: matchValue,
        roster: rosterValue,
        candidates: candidatesValue,
    } satisfies RecognitionObservationRecord;
};

/**
 * Normalize job summary from API response.
 */
export const normalizeJobSummary = (data: unknown): RecognitionJobSummary | null => {
    if (!data || typeof data !== "object") {
        return null;
    }

    const record = data as Record<string, unknown>;

    const jobId = ensureString(record.jobId ?? record.job_id ?? "").trim();
    if (jobId === "") {
        return null;
    }

    const status = ensureString(record.status ?? "unknown");
    const accepted = toFiniteNumber(record.accepted ?? 0, 0);

    let rejected: number[] = [];
    if (Array.isArray(record.rejected)) {
        rejected = record.rejected
            .map((id) => toFiniteNumber(id, 0))
            .filter((id) => id > 0);
    }

    return {
        jobId,
        status,
        accepted,
        rejected,
    };
};

/**
 * Normalize job details from API response.
 */
export const normalizeJobDetails = (data: unknown): RecognitionJobDetails | null => {
    if (!data || typeof data !== "object") {
        return null;
    }

    const record = data as Record<string, unknown>;

    const id = ensureString(record.id ?? record.job_id ?? "").trim();
    if (id === "") {
        return null;
    }

    const status = ensureString(record.status ?? "unknown");
    const startedAt = toNullableTimestamp(record.startedAt ?? record.started_at);
    const completedAt = toNullableTimestamp(record.completedAt ?? record.completed_at);
    const error = toStringOrNull(record.error);

    let attachments: RecognitionJobDetails["attachments"] = [];
    if (Array.isArray(record.attachments)) {
        attachments = record.attachments
            .map((attachment) => {
                if (!attachment || typeof attachment !== "object") {
                    return null;
                }

                const attachmentRecord = attachment as Record<string, unknown>;
                const attachmentId = toFiniteNumber(attachmentRecord.id ?? attachmentRecord.attachment_id ?? 0, 0);

                if (attachmentId <= 0) {
                    return null;
                }

                return {
                    id: attachmentId,
                    recognizedAt: toNullableTimestamp(attachmentRecord.recognizedAt ?? attachmentRecord.recognized_at),
                    observations: toFiniteNumber(attachmentRecord.observations ?? 0, 0),
                    matched: toFiniteNumber(attachmentRecord.matched ?? 0, 0),
                    needsReview: toFiniteNumber(attachmentRecord.needsReview ?? attachmentRecord.needs_review ?? 0, 0),
                };
            })
            .filter((attachment): attachment is NonNullable<typeof attachment> => attachment !== null);
    }

    return {
        id,
        status,
        startedAt,
        completedAt,
        error,
        attachments,
    };
};
