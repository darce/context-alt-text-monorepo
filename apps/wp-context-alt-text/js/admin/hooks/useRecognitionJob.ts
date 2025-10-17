import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import { getDashboardConfig } from "@/admin/dashboardData";
import {
    toUniqueNumericIds,
    toFiniteNumber,
    toNullableTimestamp,
    ensureString,
} from "@/admin/utils/normalization";

export interface RecognitionJobSummary {
    jobId: string;
    status: string;
    accepted: number;
    rejected: number[];
}

interface RecognitionErrorOptions {
    status?: number;
    rejected?: (number | string)[];
    cause?: unknown;
}

export class RecognitionRequestError extends Error {
    public readonly status?: number;
    public readonly rejected: number[];

    public constructor(message: string, options: RecognitionErrorOptions = {}) {
        super(message);
        this.name = "RecognitionRequestError";
        this.status = options.status;
        this.rejected = Array.isArray(options.rejected)
            ? options.rejected
                  .map((value) => Number(value))
                  .filter((value) => Number.isFinite(value) && value > 0)
            : [];

        if (options.cause !== undefined) {
             
            (this as unknown as { cause?: unknown }).cause = options.cause;
        }
    }
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

// ============================================================================
// State Machine Types
// ============================================================================

/**
 * Job state machine using discriminated unions for type safety.
 * Ensures impossible states are impossible (e.g., can't be submitting AND have error).
 */
type JobState =
    | { status: "idle" }
    | { status: "submitting"; attachmentIds: number[] }
    | { 
        status: "polling"; 
        jobId: string; 
        attempts: number;
        lastJob: RecognitionJobSummary;
    }
    | { status: "complete"; details: RecognitionJobDetails }
    | { status: "error"; error: RecognitionRequestError; retryable: boolean };

type JobAction =
    | { type: "SUBMIT_START"; attachmentIds: number[] }
    | { type: "SUBMIT_SUCCESS"; job: RecognitionJobSummary }
    | { type: "SUBMIT_ERROR"; error: RecognitionRequestError }
    | { type: "POLL_UPDATE"; attempts: number }
    | { type: "POLL_COMPLETE"; details: RecognitionJobDetails }
    | { type: "POLL_ERROR"; error: RecognitionRequestError }
    | { type: "RESET" };

// ============================================================================
// State Machine Reducer
// ============================================================================

/**
 * Pure reducer function for job state transitions.
 * Ensures atomic state updates and type-safe state transitions.
 */
const jobReducer = (state: JobState, action: JobAction): JobState => {
    switch (action.type) {
        case "SUBMIT_START":
            return { status: "submitting", attachmentIds: action.attachmentIds };

        case "SUBMIT_SUCCESS":
            return {
                status: "polling",
                jobId: action.job.jobId,
                attempts: 0,
                lastJob: action.job,
            };

        case "SUBMIT_ERROR":
            return {
                status: "error",
                error: action.error,
                retryable: true,
            };

        case "POLL_UPDATE":
            if (state.status !== "polling") return state;
            return {
                ...state,
                attempts: action.attempts,
            };

        case "POLL_COMPLETE":
            return {
                status: "complete",
                details: action.details,
            };

        case "POLL_ERROR":
            return {
                status: "error",
                error: action.error,
                retryable: false,
            };

        case "RESET":
            return { status: "idle" };

        default:
            return state;
    }
}

// ============================================================================
// Normalization Utilities (Domain-specific)
// ============================================================================

type PollState = "idle" | "polling";

const normalizeObservationStatus = (
    value: unknown,
): RecognitionObservationRecord["status"] => {
    const normalized = ensureString(value ?? "needs_review");
    if (normalized === "matched" || normalized === "needs_review") {
        return normalized;
    }

    return (normalized || "needs_review") as RecognitionObservationRecord["status"];
};

const normalizeCandidates = (candidates: unknown): RecognitionObservationCandidate[] => {
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

const normalizeMatch = (match: unknown): RecognitionObservationMatch => {
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

const normalizeRoster = (roster: unknown): RecognitionObservationRoster => {
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

const normalizeObservationRecord = (observation: unknown): RecognitionObservationRecord | null => {
    if (!observation || typeof observation !== "object") {
        return null;
    }

    const data = observation as Record<string, unknown>;
    const boundingBoxRaw = Array.isArray(data.boundingBox ?? data.bbox) ? (data.boundingBox ?? data.bbox) : [];
    const detectionConfidence = toFiniteNumber(data.confidence ?? 0, 0);
    const match = normalizeMatch(data.match ?? data.roster_match);
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

    const resolvedMatchConfidence = match.confidence > 0
        ? match.confidence
        : match.similarity > 0
            ? match.similarity
            : bestCandidateConfidence;

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

const normalizeAttachmentSummaries = (input: unknown): RecognitionAttachmentObservations[] => {
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

const normalizeJobDetails = (payload: Record<string, unknown>, fallbackId?: string | null): RecognitionJobDetails => {
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

const maybeParseJson = async (response: Response): Promise<unknown> => {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.toLowerCase().includes("application/json")) {
        try {
            return await response.json();
        } catch (error) {
            throw new RecognitionRequestError(
                __("Recognition service returned malformed JSON.", "context-alt-text"),
                { cause: error },
            );
        }
    }

    return null;
};

const DEFAULT_POLL_INTERVAL_MS = 3000;
const TEST_POLL_INTERVAL_MS = 50;
const POLL_INTERVAL_MS = import.meta.env?.MODE === "test" ? TEST_POLL_INTERVAL_MS : DEFAULT_POLL_INTERVAL_MS;

export const useRecognitionJob = () => {
    const config = React.useMemo(() => getDashboardConfig(), []);

    const analyzeEndpoint = React.useMemo(() => {
        const candidate = config.endpoints?.recognitionAnalyze;
        if (typeof candidate !== "string") {
            return null;
        }

        const trimmed = candidate.trim();
        return trimmed.length > 0 ? trimmed : null;
    }, [config.endpoints?.recognitionAnalyze]);

    const jobEndpoint = React.useMemo(() => {
        const candidate = config.endpoints?.recognitionJob;
        if (typeof candidate !== "string") {
            return null;
        }

        const trimmed = candidate.trim();
        if (trimmed === "") {
            return null;
        }

        return trimmed.endsWith("/") ? trimmed : `${trimmed}/`;
    }, [config.endpoints?.recognitionJob]);

    const restNonce = config.restNonce;
    const featureEnabled = Boolean(config.featureFlags?.workbenchRecognition);
    const canSubmit = featureEnabled && Boolean(analyzeEndpoint);

    const [lastJob, setLastJob] = React.useState<RecognitionJobSummary | null>(null);
    const [lastError, setLastError] = React.useState<RecognitionRequestError | null>(null);
    const [jobDetails, setJobDetails] = React.useState<RecognitionJobDetails | null>(null);
    const [isSubmitting, setIsSubmitting] = React.useState(false);
    const [pollState, setPollState] = React.useState<PollState>("idle");
    const [currentJobId, setCurrentJobId] = React.useState<string | null>(null);

    const pollTimeoutRef = React.useRef<{ timer: ReturnType<typeof setTimeout> | null; resolve?: () => void }>({
        timer: null,
    });
    const activeJobRef = React.useRef<string | null>(null);

    const clearPendingPoll = React.useCallback(() => {
        const handle = pollTimeoutRef.current;
        if (handle.timer !== null) {
            clearTimeout(handle.timer);
            handle.timer = null;
        }
        if (handle.resolve) {
            handle.resolve();
            handle.resolve = undefined;
        }
    }, []);

    const pollJob = React.useCallback(
        async (jobId: string) => {
            if (!jobEndpoint) {
                setLastError(
                    new RecognitionRequestError(
                        __("Recognition job polling endpoint is unavailable.", "context-alt-text"),
                    ),
                );
                setPollState("idle");
                return;
            }

            const fetchUrl = `${jobEndpoint}${encodeURIComponent(jobId)}`;

            try {
                setPollState("polling");

                const response = await fetch(fetchUrl, {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        Accept: "application/json",
                        ...(restNonce ? { "X-WP-Nonce": restNonce } : {}),
                    },
                });

                const payload = await maybeParseJson(response);

                if (!response.ok) {
                    const message = typeof (payload as { message?: unknown })?.message === "string"
                        ? String((payload as { message?: unknown }).message)
                        : sprintf(
                              __("Failed to poll recognition job (status %d).", "context-alt-text"),
                              response.status,
                          );

                    throw new RecognitionRequestError(message, { status: response.status });
                }

                if (!payload || typeof payload !== "object") {
                    throw new RecognitionRequestError(
                        __("Recognition job response was malformed.", "context-alt-text"),
                    );
                }

                const details = normalizeJobDetails(payload as Record<string, unknown>, jobId);
                setJobDetails(details);
                setLastJob({
                    jobId: details.id,
                    status: details.status,
                    accepted: details.attachments.length,
                    rejected: details.rejected,
                });
                setLastError(null);

                if (details.status === "complete" || details.status === "error") {
                    setPollState("idle");
                    clearPendingPoll();
                } else {
                    clearPendingPoll();

                    const delay = POLL_INTERVAL_MS > 0 ? POLL_INTERVAL_MS : 1;

                    await new Promise<void>((resolve) => {
                        const timer = setTimeout(() => {
                            if (pollTimeoutRef.current.timer === timer) {
                                pollTimeoutRef.current.timer = null;
                                pollTimeoutRef.current.resolve = undefined;
                            }
                            resolve();
                        }, delay);

                        pollTimeoutRef.current.timer = timer;
                        pollTimeoutRef.current.resolve = resolve;
                    });

                    if (activeJobRef.current !== jobId) {
                        return;
                    }

                    await pollJob(jobId);
                }
            } catch (error) {
                const recognitionError =
                    error instanceof RecognitionRequestError
                        ? error
                        : new RecognitionRequestError(
                              __("Recognition job failed to load.", "context-alt-text"),
                              { cause: error },
                          );

                setLastError(recognitionError);
                setPollState("idle");
                clearPendingPoll();
            }
        },
        [clearPendingPoll, jobEndpoint, restNonce],
    );

    const triggerRecognition = React.useCallback(
        (ids: (number | string)[]) => {
            if (!canSubmit) {
                const error = new RecognitionRequestError(
                    __("Recognition service is currently unavailable.", "context-alt-text"),
                );
                setLastError(error);
                throw error;
            }

            const normalized = toUniqueNumericIds(ids);

            if (normalized.length === 0) {
                const error = new RecognitionRequestError(
                    __("Select at least one valid attachment before triggering recognition.", "context-alt-text"),
                );
                setLastError(error);
                throw error;
            }

            if (!analyzeEndpoint) {
                const error = new RecognitionRequestError(
                    __("Recognition service endpoint is unavailable.", "context-alt-text"),
                );
                setLastError(error);
                throw error;
            }

            clearPendingPoll();
            setLastError(null);
            setLastJob(null);
            setJobDetails(null);
            setCurrentJobId(null);
            activeJobRef.current = null;

            setIsSubmitting(true);

            const performMutation = async () => {
                try {
                    const response = await fetch(analyzeEndpoint, {
                        method: "POST",
                        credentials: "same-origin",
                        headers: {
                            Accept: "application/json",
                            "Content-Type": "application/json",
                            ...(restNonce ? { "X-WP-Nonce": restNonce } : {}),
                        },
                        body: JSON.stringify({ attachment_ids: normalized }),
                    });

                    const payload = await maybeParseJson(response);

                    if (!response.ok) {
                        const message = typeof (payload as { message?: unknown })?.message === "string"
                            ? String((payload as { message?: unknown }).message)
                            : sprintf(
                                  __("Recognition request failed with status %d.", "context-alt-text"),
                                  response.status,
                              );

                        const rejectedCandidates =
                            (payload as { data?: { rejected?: (number | string)[] } })?.data?.rejected ?? [];

                        throw new RecognitionRequestError(message, {
                            status: response.status,
                            rejected: Array.isArray(rejectedCandidates) ? rejectedCandidates : [],
                        });
                    }

                    if (!payload || typeof payload !== "object") {
                        throw new RecognitionRequestError(
                            __("Recognition service returned an unexpected response.", "context-alt-text"),
                        );
                    }

                    const body = payload as Record<string, unknown>;

                    const accepted = Number(body.accepted ?? 0);
                    const rejectedCandidates = Array.isArray(body.rejected) ? body.rejected : [];
                    const normalizedJobId = ensureString(body.jobId).trim();
                    const summary: RecognitionJobSummary = {
                        jobId: normalizedJobId,
                        status: typeof body.status === "string" ? body.status : "processing",
                        accepted: Number.isFinite(accepted) && accepted >= 0 ? accepted : 0,
                        rejected: Array.isArray(rejectedCandidates)
                            ? rejectedCandidates
                                  .map((value) => Number(value))
                                  .filter((value) => Number.isFinite(value) && value > 0)
                            : [],
                    };

                    setLastJob(summary);
                    setCurrentJobId(normalizedJobId);
                    activeJobRef.current = normalizedJobId !== "" ? normalizedJobId : null;
                    setPollState(activeJobRef.current ? "polling" : "idle");

                    if (activeJobRef.current) {
                        void pollJob(activeJobRef.current);
                    }

                    return summary;
                } catch (error) {
                    const recognitionError =
                        error instanceof RecognitionRequestError
                            ? error
                            : new RecognitionRequestError(
                                  __("Recognition request failed.", "context-alt-text"),
                                  { cause: error },
                              );

                    setLastError(recognitionError);
                    throw recognitionError;
                } finally {
                    setIsSubmitting(false);
                }
            };

            return performMutation();
        },
        [analyzeEndpoint, canSubmit, clearPendingPoll, pollJob, restNonce],
    );

    const reset = React.useCallback(() => {
        clearPendingPoll();
        setLastJob(null);
        setLastError(null);
        setJobDetails(null);
        setIsSubmitting(false);
        setPollState("idle");
        setCurrentJobId(null);
        activeJobRef.current = null;
    }, [clearPendingPoll]);

    const isPolling = pollState === "polling";

    return {
        canSubmit,
        triggerRecognition,
        isSubmitting,
        isPolling,
        lastJob,
        jobDetails,
        error: lastError,
        reset,
        refetchJob: currentJobId ? () => pollJob(currentJobId) : () => Promise.resolve(),
    };
};
