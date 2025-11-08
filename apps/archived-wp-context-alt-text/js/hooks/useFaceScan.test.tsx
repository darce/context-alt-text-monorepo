import { describe, it, expect, afterEach, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { useFaceScan } from "./useFaceScan";
import { useDashboardHandlers, server } from "@/admin/testing/mswServer";
import { recognitionScanHandler } from "@/admin/testing/recognitionHandlers";
import { setAdminBootstrap } from "@/admin/globals";

describe("useFaceScan", () => {
    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.restoreAllMocks();
    });

    it("should return initial state with scan function", () => {
        const { result } = renderHook(() => useFaceScan());

        expect(result.current.scanFaces).toBeInstanceOf(Function);
        expect(result.current.isScanning).toBe(false);
        expect(result.current.error).toBeNull();
        expect(result.current.result).toBeNull();
    });

    it("should trigger face scan and return job ID", async () => {
        const endpoint = "https://example.com/wp-json/cat/v1/recognition/scan";
        const nonce = "test-nonce-123";

        useDashboardHandlers(recognitionScanHandler);
        <section class="cat-workbench__panel" aria-label="Face scan actions">
            <header>
                <h2>Face Clustering</h2>
                <p>Scan selected images to detect and group similar faces for efficient labeling.</p>
            </header>
            <button type="button" class="cat-button cat-button--default cat-button--md">
                Scan for Faces
            </button>
            <dl class="cat-face-scan__summary" aria-live="polite">
                <div>
                    <dt>Selected items</dt>
                    <dd>8</dd>
                </div>
                <div>
                    <dt>Queued for scanning</dt>
                    <dd>8</dd>
                </div>
            </dl>
            <p class="cat-face-scan__status cat-face-scan__status--success" role="status" aria-live="polite">
                Queued 8 items for face detection. Job ID: sync-68feca25c469d4.61431817. Faces will appear in the
                Unknown People panel once processing completes.
            </p>
        </section>;
        setAdminBootstrap({
            config: {
                restNonce: nonce,
                endpoints: {
                    faceScan: endpoint,
                },
            },
        });

        const { result } = renderHook(() => useFaceScan());

        await result.current.scanFaces([1, 2, 3]);

        // Wait for state to update
        await waitFor(() => {
            expect(result.current.result).not.toBeNull();
        });

        // The global handler returns "scan-mock-job" as job_id
        expect(result.current.result).toEqual({
            jobId: "scan-mock-job",
            queuedCount: 3,
            priority: "normal",
        });
        expect(result.current.error).toBeNull();
    });

    it("should handle network errors", async () => {
        const endpoint = "http://example.test/wp-json/cat/v1/recognition/scan";
        const nonce = "test-nonce-123";

        setAdminBootstrap({
            config: {
                restNonce: nonce,
                endpoints: {
                    faceScan: endpoint,
                },
            },
        });

        // Override the handler to return an error
        useDashboardHandlers(
            http.post(endpoint, () => {
                return HttpResponse.json(
                    {
                        code: "rest_network_error",
                        message: "Failed to connect to recognition service.",
                    },
                    { status: 500 },
                );
            }),
        );

        const { result } = renderHook(() => useFaceScan());

        await result.current.scanFaces([1, 2, 3]);

        await waitFor(() => {
            expect(result.current.error).not.toBeNull();
        });

        expect(result.current.error?.message).toContain("Failed");
        expect(result.current.result).toBeNull();
    });

    it("should validate batch size", async () => {
        setAdminBootstrap({
            config: {
                restNonce: "test-nonce-123",
                endpoints: {
                    faceScan: "https://example.com/wp-json/cat/v1/recognition/scan",
                },
            },
        });

        const { result } = renderHook(() => useFaceScan());

        const largeArray = Array.from({ length: 51 }, (_, i) => i + 1);

        await result.current.scanFaces(largeArray);

        await waitFor(() => {
            expect(result.current.error).not.toBeNull();
        });

        expect(result.current.error?.message).toContain("50");
    });

    it("should reject empty attachment arrays", async () => {
        setAdminBootstrap({
            config: {
                restNonce: "test-nonce-123",
                endpoints: {
                    faceScan: "http://example.test/wp-json/cat/v1/recognition/scan",
                },
            },
        });

        const { result } = renderHook(() => useFaceScan());

        await result.current.scanFaces([]);

        await waitFor(() => {
            expect(result.current.error).not.toBeNull();
        });

        expect(result.current.error?.message).toContain("at least one");
    });

    it("should support high priority scans", async () => {
        useDashboardHandlers(recognitionScanHandler);

        setAdminBootstrap({
            config: {
                restNonce: "test-nonce-123",
                endpoints: {
                    faceScan: "https://example.com/wp-json/cat/v1/recognition/scan",
                },
            },
        });

        const { result } = renderHook(() => useFaceScan());

        await result.current.scanFaces([1], { priority: "high" });

        await waitFor(() => {
            expect(result.current.result).not.toBeNull();
        });

        // The global handler respects the priority from the request
        expect(result.current.result?.priority).toBe("high");
        expect(result.current.result?.jobId).toBe("scan-mock-job");
    });

    it("should reset error on new scan attempt", async () => {
        const endpoint = "https://example.com/wp-json/cat/v1/recognition/scan";
        const nonce = "test-nonce-123";

        setAdminBootstrap({
            config: {
                restNonce: nonce,
                endpoints: {
                    faceScan: endpoint,
                },
            },
        });

        // First request fails
        useDashboardHandlers(
            http.post(endpoint, () => {
                return HttpResponse.json({ message: "Service unavailable" }, { status: 503 });
            }),
        );

        const { result } = renderHook(() => useFaceScan());

        // First scan fails
        await result.current.scanFaces([1]);

        await waitFor(() => {
            expect(result.current.error).not.toBeNull();
        });

        // Reset handlers and add success handler
        server.resetHandlers();
        useDashboardHandlers(recognitionScanHandler);

        // Second scan succeeds
        await result.current.scanFaces([1]);

        await waitFor(() => {
            expect(result.current.result).not.toBeNull();
        });

        expect(result.current.error).toBeNull();
    });
});
