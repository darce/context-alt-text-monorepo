import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import {
    RecognitionRequestError,
    useRecognitionJob,
} from "@/admin/hooks/useRecognitionJob";
import { useDashboardHandlers } from "@/admin/testing/mswServer";
import { setAdminBootstrap } from "@/admin/globals";

const ANALYZE_ENDPOINT = "/wp-json/context-alt-text/v1/recognition/analyze";
const JOB_ENDPOINT_BASE = "/wp-json/context-alt-text/v1/recognition/job/";
const TEST_POLL_INTERVAL_MS = 50;
const wait = async (ms: number) => {
    await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, ms));
    });
};

const createWrapper = () => ({ children }: { children: ReactNode }) => <>{children}</>;

describe("useRecognitionJob", () => {
    beforeEach(() => {
        setAdminBootstrap(undefined);
    });

    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    it("disables submissions when recognition feature is not available", () => {
        setAdminBootstrap({
            config: {
                featureFlags: {
                    workbenchRecognition: false,
                },
            },
        });

        const { result } = renderHook(() => useRecognitionJob(), { wrapper: createWrapper() });

        expect(result.current.canSubmit).toBe(false);

        act(() => {
            expect(() => result.current.triggerRecognition([42])).toThrow(RecognitionRequestError);
        });

        expect(result.current.error).toBeInstanceOf(RecognitionRequestError);
        expect(result.current.error?.message).toMatch(/currently unavailable/i);
    });

    it("submits recognition, polls job status, and surfaces completed observations", async () => {
        const analyzePayloads: Record<string, unknown>[] = [];
        let jobCallCount = 0;

        setAdminBootstrap({
            config: {
                featureFlags: {
                    workbenchRecognition: true,
                },
                restNonce: "nonce-123",
                endpoints: {
                    recognitionAnalyze: ANALYZE_ENDPOINT,
                    recognitionJob: JOB_ENDPOINT_BASE,
                },
            },
        });

        useDashboardHandlers(
            http.post(ANALYZE_ENDPOINT, async ({ request }) => {
                const payload = (await request.json()) as Record<string, unknown>;
                analyzePayloads.push(payload);

                return HttpResponse.json({
                    jobId: "job-xyz",
                    status: "processing",
                    accepted: 1,
                    rejected: [],
                });
            }),
            http.get(`${JOB_ENDPOINT_BASE}:jobId`, ({ params }) => {
                jobCallCount++;

                if (params.jobId !== "job-xyz") {
                    return HttpResponse.json({ message: "missing" }, { status: 404 });
                }

                if (jobCallCount === 1) {
                    return HttpResponse.json({
                        id: "job-xyz",
                        status: "processing",
                        attachments: [
                            {
                                id: 101,
                                filename: "sample.png",
                                imageUrl: "http://example.test/sample.png",
                            },
                        ],
                        rejected: [],
                        observations: [],
                    });
                }

                return HttpResponse.json({
                    id: "job-xyz",
                    status: "complete",
                    attachments: [
                        {
                            id: 101,
                            filename: "sample.png",
                            imageUrl: "http://example.test/sample.png",
                        },
                    ],
                    rejected: [],
                    observations: [
                        {
                            jobId: "job-xyz",
                            attachmentId: 101,
                            updatedAt: 1_700_000_000,
                            context: {
                                filename: "sample.png",
                                imageUrl: "http://example.test/sample.png",
                            },
                            summary: {
                                total: 2,
                                matched: 1,
                                needs_review: 1,
                            },
                            observations: [],
                        },
                    ],
                });
            }),
        );

        const { result } = renderHook(() => useRecognitionJob(), { wrapper: createWrapper() });

        await act(async () => {
            await result.current.triggerRecognition([101]);
        });

        await waitFor(() => {
            expect(result.current.canSubmit).toBe(true);
            expect(analyzePayloads).toHaveLength(1);
            expect(analyzePayloads).not.toHaveLength(0);
            expect(analyzePayloads[0]?.attachment_ids).toEqual([101]);
            expect(result.current.lastJob?.jobId).toBe("job-xyz");
        });

        await wait(TEST_POLL_INTERVAL_MS * 2);

        await waitFor(() => {
            expect(jobCallCount).toBeGreaterThan(1);
            expect(result.current.jobDetails?.status).toBe("complete");
        }, { timeout: 2000 });

        expect(result.current.isPolling).toBe(false);

        expect(result.current.jobDetails?.observations[0]?.summary.total).toBe(2);
        expect(result.current.error).toBeNull();
        expect(jobCallCount).toBeGreaterThan(1);

        act(() => {
            result.current.reset();
        });

        await waitFor(() => {
            expect(result.current.lastJob).toBeNull();
            expect(result.current.jobDetails).toBeNull();
        });
    });

    it("surfaces polling errors and stops further refetching", async () => {
        setAdminBootstrap({
            config: {
                featureFlags: {
                    workbenchRecognition: true,
                },
                endpoints: {
                    recognitionAnalyze: ANALYZE_ENDPOINT,
                    recognitionJob: JOB_ENDPOINT_BASE,
                },
            },
        });

        useDashboardHandlers(
            http.post(ANALYZE_ENDPOINT, () =>
                HttpResponse.json({
                    jobId: "job-err",
                    status: "processing",
                    accepted: 1,
                    rejected: [],
                }),
            ),
            http.get(`${JOB_ENDPOINT_BASE}:jobId`, () =>
                HttpResponse.json(
                    {
                        message: "not found",
                    },
                    { status: 404 },
                ),
            ),
        );

        const { result } = renderHook(() => useRecognitionJob(), { wrapper: createWrapper() });

        await act(async () => {
            await result.current.triggerRecognition([404]);
        });

        await waitFor(() => {
            expect(result.current.error).toBeInstanceOf(RecognitionRequestError);
        });

        expect(result.current.isPolling).toBe(false);
        expect(result.current.lastJob?.jobId).toBe("job-err");
    });
});
