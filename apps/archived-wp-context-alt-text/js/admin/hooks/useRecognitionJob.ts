import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import { getDashboardConfig } from "@/admin/dashboardData";
import { toUniqueNumericIds, ensureString } from "@/admin/utils/normalization";
import {
    type RecognitionJobSummary,
    normalizeJobDetails,
    maybeParseJson,
    RecognitionRequestError,
} from "@/admin/utils/normalization/recognition";
import { jobReducer, initialJobState } from "./useRecognitionJob.reducer";

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

    // State machine using useReducer
    // This ensures atomic state updates and prevents impossible states
    const [state, dispatch] = React.useReducer(jobReducer, initialJobState);

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
                dispatch({
                    type: "POLL_ERROR",
                    error: new RecognitionRequestError(
                        __("Recognition job polling endpoint is unavailable.", "context-alt-text"),
                    ),
                });
                return;
            }

            const fetchUrl = `${jobEndpoint}${encodeURIComponent(jobId)}`;

            try {
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
                    const message =
                        typeof (payload as { message?: unknown })?.message === "string"
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

                if (details.status === "complete" || details.status === "error") {
                    dispatch({ type: "POLL_COMPLETE", details });
                    clearPendingPoll();
                } else {
                    dispatch({ type: "POLL_UPDATE", attempts: state.status === "polling" ? state.attempts + 1 : 1 });
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
                        : new RecognitionRequestError(__("Recognition job failed to load.", "context-alt-text"), {
                              cause: error,
                          });

                dispatch({ type: "POLL_ERROR", error: recognitionError });
                clearPendingPoll();
            }
        },
        [clearPendingPoll, jobEndpoint, restNonce, state],
    );

    const triggerRecognition = React.useCallback(
        (ids: (number | string)[]) => {
            if (!canSubmit) {
                const error = new RecognitionRequestError(
                    __("Recognition service is currently unavailable.", "context-alt-text"),
                );
                dispatch({ type: "SUBMIT_ERROR", error });
                throw error;
            }

            const normalized = toUniqueNumericIds(ids);

            if (normalized.length === 0) {
                const error = new RecognitionRequestError(
                    __("Select at least one valid attachment before triggering recognition.", "context-alt-text"),
                );
                dispatch({ type: "SUBMIT_ERROR", error });
                throw error;
            }

            if (!analyzeEndpoint) {
                const error = new RecognitionRequestError(
                    __("Recognition service endpoint is unavailable.", "context-alt-text"),
                );
                dispatch({ type: "SUBMIT_ERROR", error });
                throw error;
            }

            clearPendingPoll();
            dispatch({ type: "RESET" });
            activeJobRef.current = null;

            dispatch({ type: "SUBMIT_START", attachmentIds: normalized });

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
                        const message =
                            typeof (payload as { message?: unknown })?.message === "string"
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

                    dispatch({ type: "SUBMIT_SUCCESS", job: summary });
                    activeJobRef.current = normalizedJobId !== "" ? normalizedJobId : null;

                    if (activeJobRef.current) {
                        void pollJob(activeJobRef.current);
                    }

                    return summary;
                } catch (error) {
                    const recognitionError =
                        error instanceof RecognitionRequestError
                            ? error
                            : new RecognitionRequestError(__("Recognition request failed.", "context-alt-text"), {
                                  cause: error,
                              });

                    dispatch({ type: "SUBMIT_ERROR", error: recognitionError });
                    throw recognitionError;
                }
            };

            return performMutation();
        },
        [analyzeEndpoint, canSubmit, clearPendingPoll, pollJob, restNonce],
    );

    const reset = React.useCallback(() => {
        clearPendingPoll();
        dispatch({ type: "RESET" });
        activeJobRef.current = null;
    }, [clearPendingPoll]);

    // Derive computed values from state
    const isSubmitting = state.status === "submitting";
    const isPolling = state.status === "polling";

    // Derive lastJob - when complete, construct from jobDetails for component compatibility
    const lastJob =
        state.status === "polling"
            ? state.lastJob
            : state.status === "complete"
              ? {
                    jobId: state.details.id,
                    status: state.details.status,
                    accepted: state.details.attachments.length,
                    rejected: state.details.rejected,
                }
              : state.status === "error"
                ? (state.lastJob ?? null)
                : null;

    const jobDetails = state.status === "complete" ? state.details : null;
    const lastError = state.status === "error" ? state.error : null;
    const currentJobId = state.status === "polling" ? state.jobId : null;

    // Derive status for backward compatibility with components
    const status =
        state.status === "submitting"
            ? "processing"
            : state.status === "polling"
              ? "processing"
              : state.status === "complete"
                ? "complete"
                : state.status === "error"
                  ? "error"
                  : "idle";

    return {
        canSubmit,
        triggerRecognition,
        isSubmitting,
        isPolling,
        lastJob,
        jobDetails,
        status, // Add status field for component compatibility
        error: lastError,
        reset,
        refetchJob: currentJobId ? () => pollJob(currentJobId) : () => Promise.resolve(),
    };
};
