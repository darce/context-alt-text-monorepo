/**
 * Type definitions for useRecognitionJob hook.
 *
 * This file contains the state machine types used by the recognition job workflow.
 * The state machine ensures type-safe state transitions and prevents impossible states.
 */

import type { RecognitionJobSummary, RecognitionJobDetails } from "./useRecognitionJob";

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

/**
 * Job state machine using discriminated unions for type safety.
 * Ensures impossible states are impossible (e.g., can't be submitting AND have error).
 */
export type JobState =
    | { status: "idle" }
    | { status: "submitting"; attachmentIds: number[] }
    | {
          status: "polling";
          jobId: string;
          attempts: number;
          lastJob: RecognitionJobSummary;
      }
    | { status: "complete"; details: RecognitionJobDetails }
    | {
          status: "error";
          error: RecognitionRequestError;
          retryable: boolean;
          lastJob?: RecognitionJobSummary;
      };

/**
 * Actions that can be dispatched to the job state machine.
 * Each action represents a state transition event.
 */
export type JobAction =
    | { type: "SUBMIT_START"; attachmentIds: number[] }
    | { type: "SUBMIT_SUCCESS"; job: RecognitionJobSummary }
    | { type: "SUBMIT_ERROR"; error: RecognitionRequestError }
    | { type: "POLL_UPDATE"; attempts: number }
    | { type: "POLL_COMPLETE"; details: RecognitionJobDetails }
    | { type: "POLL_ERROR"; error: RecognitionRequestError }
    | { type: "RESET" };
