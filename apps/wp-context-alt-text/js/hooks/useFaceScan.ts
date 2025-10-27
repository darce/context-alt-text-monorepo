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
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(
                        errorData.message ?? __("Failed to start face scan. Please try again.", "context-alt-text"),
                    );
                }

                const data = await response.json();

                setResult({
                    jobId: data.job_id ?? "",
                    queuedCount: data.queued_count ?? attachmentIds.length,
                    priority: data.priority ?? "normal",
                });
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
