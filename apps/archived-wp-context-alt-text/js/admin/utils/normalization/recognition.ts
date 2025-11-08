/**
 * Recognition domain normalization utilities.
 *
 * Normalizes recognition-related data structures from API responses.
 */

import { __ } from "@wordpress/i18n";
import { ensureString, toFiniteNumber, toNullableTimestamp, toUniqueNumericIds } from "./primitives";

/**
 * Error class for recognition request failures.
 */
export class RecognitionRequestError extends Error {
    public readonly status?: number;
    public readonly rejected: number[];

    public constructor(message: string, options: RecognitionErrorOptions = {}) {
        super(message);
        this.name = "RecognitionRequestError";
        this.status = options.status;
        this.rejected = Array.isArray(options.rejected)
            ? options.rejected.map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0)
            : [];

        if (options.cause !== undefined) {
            (this as unknown as { cause?: unknown }).cause = options.cause;
        }
    }
}

interface RecognitionErrorOptions {
    status?: number;
    rejected?: (number | string)[];
    cause?: unknown;
}

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

export interface RecognitionAttachmentObservations {
    jobId: string | null;
    attachmentId: number;
    updatedAt: number | null;
    context: {
        filename?: string;
        imageUrl?: string;
    };
    summary: {
        total: number;
        matched: number;
        needsReview: number;
    };
    observations: RecognitionObservationRecord[];
}

export interface RecognitionJobDetails {
    id: string;
    status: string;
    startedAt: number | null;
    completedAt: number | null;
    error: string | null;
    attachments: {
        id: number;
        filename?: string;
        imageUrl?: string;
    }[];
    rejected: number[];
    observations: RecognitionAttachmentObservations[];
}

/**
 * Normalize observation status to valid value.
 */
export const normalizeObservationStatus = (value: unknown): RecognitionObservationRecord["status"] => {
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

    const type =
        data.type ?? (typeof data.metadata === "object" ? (data.metadata as Record<string, unknown>).type : undefined);
    if (type !== undefined) {
        result.type = ensureString(type);
    }

    return Object.keys(result).length > 0 ? result : null;
};

/**
 * Normalize a single observation record from API response.
 * This version includes more sophisticated confidence resolution and face data handling.
 */
export const normalizeObservationRecord = (observation: unknown): RecognitionObservationRecord | null => {
    if (!observation || typeof observation !== "object") {
        return null;
    }

    const data = observation as Record<string, unknown>;
    const boundingBoxRaw = Array.isArray(data.boundingBox ?? data.bbox) ? (data.boundingBox ?? data.bbox) : [];
    const detectionConfidence = toFiniteNumber(data.confidence ?? 0, 0);
    const match = normalizeMatch(data.match ?? data.roster_match);

    // Handle face_data candidates (legacy format)
    const faceDataCandidates = (() => {
        const faceData = data.face_data;
        if (!faceData || typeof faceData !== "object") {
            return null;
        }

        const faceDataRecord = faceData as Record<string, unknown>;
        return Array.isArray(faceDataRecord.candidates) ? faceDataRecord.candidates : null;
    })();

    const directCandidates = Array.isArray(data.candidates) ? data.candidates : null;
    const candidates = normalizeCandidates(directCandidates ?? faceDataCandidates ?? []);

    const bestCandidateConfidence = candidates.reduce((current, candidate) => {
        if (!candidate) {
            return current;
        }

        const value = toFiniteNumber(candidate.confidence ?? candidate.similarity ?? 0, 0);
        return value > current ? value : current;
    }, 0);

    const resolvedMatchConfidence =
        match.confidence > 0 ? match.confidence : match.similarity > 0 ? match.similarity : bestCandidateConfidence;

    const normalizedConfidence = resolvedMatchConfidence > 0 ? resolvedMatchConfidence : detectionConfidence;

    return {
        observationId: ensureString(data.observationId ?? data.id ?? ""),
        label: ensureString(data.label ?? ""),
        entityType: ensureString(data.entityType ?? data.entity_type ?? ""),
        confidence: normalizedConfidence,
        detectionConfidence: detectionConfidence > 0 ? detectionConfidence : null,
        matchConfidence: resolvedMatchConfidence > 0 ? resolvedMatchConfidence : null,
        area: toFiniteNumber(data.area ?? 0, 0),
        boundingBox: (boundingBoxRaw as (number | string)[]).map((value) => toFiniteNumber(value, 0)),
        status: normalizeObservationStatus(data.status),
        source: ensureString(data.source ?? "recognition-service"),
        match,
        roster: normalizeRoster(data.roster ?? data.roster_entry),
        candidates,
    } satisfies RecognitionObservationRecord;
};

/**
 * Normalize attachment summaries array from job details.
 */
export const normalizeAttachmentSummaries = (input: unknown): RecognitionAttachmentObservations[] => {
    if (!Array.isArray(input)) {
        return [];
    }

    const normalized: RecognitionAttachmentObservations[] = [];

    for (const item of input) {
        if (!item || typeof item !== "object") {
            continue;
        }

        const data = item as Record<string, unknown>;
        const summary = (data.summary ?? {}) as Record<string, unknown>;
        const context = (data.context ?? {}) as Record<string, unknown>;
        const observationsRaw = Array.isArray(data.observations) ? data.observations : [];

        normalized.push({
            jobId: data.jobId != null ? ensureString(data.jobId) : null,
            attachmentId: toFiniteNumber(data.attachmentId ?? data.attachment_id ?? 0, 0),
            updatedAt: toNullableTimestamp(data.updatedAt ?? data.updated_at ?? null),
            context: {
                filename: context.filename ? ensureString(context.filename) : undefined,
                imageUrl: context.imageUrl ? ensureString(context.imageUrl) : undefined,
            },
            summary: {
                total: toFiniteNumber(summary.total ?? 0, 0),
                matched: toFiniteNumber(summary.matched ?? 0, 0),
                needsReview: toFiniteNumber(summary.needsReview ?? summary.needs_review ?? 0, 0),
            },
            observations: (observationsRaw as unknown[])
                .map((record) => normalizeObservationRecord(record))
                .filter((record): record is RecognitionObservationRecord => record !== null),
        });
    }

    return normalized;
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
        rejected = record.rejected.map((id) => toFiniteNumber(id, 0)).filter((id) => id > 0);
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
 * Supports optional fallbackId for cases where job ID is not in the payload.
 */
export const normalizeJobDetails = (
    payload: Record<string, unknown>,
    fallbackId?: string | null,
): RecognitionJobDetails => {
    const attachmentsRaw = Array.isArray(payload.attachments) ? payload.attachments : [];
    const attachments: { id: number; filename?: string; imageUrl?: string }[] = [];

    for (const item of attachmentsRaw) {
        if (!item || typeof item !== "object") {
            continue;
        }

        const data = item as Record<string, unknown>;

        attachments.push({
            id: toFiniteNumber(data.id ?? 0, 0),
            filename: data.filename ? ensureString(data.filename) : undefined,
            imageUrl: data.imageUrl ? ensureString(data.imageUrl) : undefined,
        });
    }

    const rejected = Array.isArray(payload.rejected) ? payload.rejected : [];
    const status = ensureString(payload.status ?? "processing");
    const error = payload.error != null ? ensureString(payload.error) : null;
    const idCandidate = ensureString(payload.id ?? payload.jobId ?? fallbackId ?? "");

    return {
        id: idCandidate,
        status,
        startedAt: toNullableTimestamp(payload.startedAt ?? payload.started_at ?? null),
        completedAt: toNullableTimestamp(payload.completedAt ?? payload.completed_at ?? null),
        error,
        attachments,
        rejected: toUniqueNumericIds(rejected as (number | string)[]),
        observations: normalizeAttachmentSummaries(payload.observations ?? []),
    } satisfies RecognitionJobDetails;
};

/**
 * Attempts to parse JSON from a Response, throwing a RecognitionRequestError if parsing fails.
 * Returns null if the response is not JSON.
 */
export const maybeParseJson = async (response: Response): Promise<unknown> => {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.toLowerCase().includes("application/json")) {
        try {
            return await response.json();
        } catch (error) {
            throw new RecognitionRequestError(__("Recognition service returned malformed JSON.", "context-alt-text"), {
                cause: error,
            });
        }
    }

    return null;
};
