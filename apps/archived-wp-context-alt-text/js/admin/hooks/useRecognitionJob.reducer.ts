/**
 * State machine reducer for useRecognitionJob hook.
 *
 * This pure reducer function handles all state transitions for the recognition job workflow.
 * It ensures atomic state updates and prevents impossible state combinations.
 */

import type { JobState, JobAction } from "./useRecognitionJob.types";

/**
 * Initial state for the job state machine.
 */
export const initialJobState: JobState = { status: "idle" };

/**
 * Pure reducer function for job state transitions.
 * Ensures atomic state updates and type-safe state transitions.
 *
 * @param state - Current job state
 * @param action - Action to dispatch
 * @returns New job state
 */
export const jobReducer = (state: JobState, action: JobAction): JobState => {
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
                lastJob: state.status === "polling" ? state.lastJob : undefined,
            };

        case "RESET":
            return { status: "idle" };

        default:
            return state;
    }
};
