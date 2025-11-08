import { useState, useCallback, useMemo } from "react";
import { __ } from "@wordpress/i18n";

import { getDashboardConfig } from "@/admin/dashboardData";

export interface FaceScanResult {
    jobId: string;
    queuedCount: number;
    priority: "normal" | "high";
}

export interface FaceScanOptions {
    priority?: "normal" | "high";
}

export interface FaceScanError {
    message: string;
    code?: string;
    status?: number;
}

export interface UseFaceScanReturn {
    scanFaces: (attachmentIds: number[], options?: FaceScanOptions) => Promise<void>;
    isScanning: boolean;
    error: FaceScanError | null;
    result: FaceScanResult | null;
    reset: () => void;
}

const MAX_BATCH_SIZE = 50;

interface FaceScanResponseRaw {
    job_id?: unknown;
    jobId?: unknown;
    queued_count?: unknown;
    queuedCount?: unknown;
    priority?: unknown;
}

interface FaceScanErrorPayload {
    message?: unknown;
}

const toFiniteNumber = (value: unknown, fallback: number): number => {
    if (typeof value === "number" && Number.isFinite(value)) {
        return value;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

const toPriority = (value: unknown): FaceScanResult["priority"] => (value === "high" ? "high" : "normal");

const extractMessage = (input: unknown): string | null => {
    if (!input || typeof input !== "object") {
        return null;
    }

    const record = input as FaceScanErrorPayload;
    const { message } = record;

    if (typeof message === "string" && message.trim() !== "") {
        return message;
    }

    return null;
};

const normalizeScanResult = (input: unknown, fallbackQueuedCount: number): FaceScanResult => {
    if (!input || typeof input !== "object") {
        return {
            jobId: "",
            queuedCount: fallbackQueuedCount,
            priority: "normal",
        };
    }

    const data = input as FaceScanResponseRaw;
    const jobIdRaw = data.job_id ?? data.jobId;
    const queuedCountRaw = data.queued_count ?? data.queuedCount;
    const priorityRaw = data.priority;

    return {
        jobId: typeof jobIdRaw === "string" ? jobIdRaw : "",
        queuedCount: toFiniteNumber(queuedCountRaw, fallbackQueuedCount),
        priority: toPriority(priorityRaw),
    };
};

/**
 * Hook for triggering face detection scans on media attachments.
 * Follows the same pattern as useRecognitionJob but specifically for face scanning.
 */
export const useFaceScan = (): UseFaceScanReturn => {
    const [isScanning, setIsScanning] = useState(false);
    const [error, setError] = useState<FaceScanError | null>(null);
    const [result, setResult] = useState<FaceScanResult | null>(null);

    const config = useMemo(() => getDashboardConfig(), []);
    const scanEndpoint = config.endpoints?.faceScan ?? null;
    const restNonce = config.restNonce;

    const scanFaces = useCallback(
        async (attachmentIds: number[], options?: FaceScanOptions): Promise<void> => {
            // Reset state
            setError(null);
            setResult(null);

            // Validation
            if (!attachmentIds || attachmentIds.length === 0) {
                setError({
                    message: __("Please select at least one image to scan.", "context-alt-text"),
                    code: "invalid_input",
                });
                return;
            }

            if (attachmentIds.length > MAX_BATCH_SIZE) {
                setError({
                    message: __(`You can scan at most ${MAX_BATCH_SIZE} attachments per request.`, "context-alt-text"),
                    code: "batch_size_exceeded",
                });
                return;
            }

            if (!scanEndpoint) {
                setError({
                    message: __("Face scan endpoint is not configured.", "context-alt-text"),
                    code: "endpoint_unavailable",
                });
                return;
            }

            setIsScanning(true);

            try {
                const requestBody = {
                    attachment_ids: attachmentIds,
                    priority: options?.priority ?? "normal",
                };

                const response = await fetch(scanEndpoint, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/json",
                        "X-WP-Nonce": restNonce ?? "",
                    },
                    body: JSON.stringify(requestBody),
                });

                if (!response.ok) {
                    const errorPayload: unknown = await response.json().catch(() => null);
                    const message =
                        extractMessage(errorPayload) ??
                        __("Failed to start face scan. Please try again.", "context-alt-text");
                    throw new Error(message);
                }

                const payload: unknown = await response.json().catch(() => null);
                const normalized = normalizeScanResult(payload, attachmentIds.length);

                setResult(normalized);
            } catch (err) {
                const errorMessage =
                    err instanceof Error ? err.message : __("Unknown error occurred.", "context-alt-text");

                setError({
                    message: errorMessage,
                    code: "request_failed",
                });
            } finally {
                setIsScanning(false);
            }
        },
        [scanEndpoint, restNonce],
    );

    const reset = useCallback(() => {
        setIsScanning(false);
        setError(null);
        setResult(null);
    }, []);

    return {
        scanFaces,
        isScanning,
        error,
        result,
        reset,
    };
};
