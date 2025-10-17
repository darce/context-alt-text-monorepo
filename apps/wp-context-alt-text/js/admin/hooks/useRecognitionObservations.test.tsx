import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

import { useRecognitionObservations } from "@/admin/hooks/useRecognitionObservations";
import type { AdminConfig } from "@/admin/types";
import { useDashboardHandlers } from "@/admin/testing/mswServer";

const OBSERVATIONS_ENDPOINT = "http://example.test/wp-json/cat/v1/observations";

const createWrapper = () => {
    const client = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
};

describe("useRecognitionObservations", () => {
    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("requests observations with pagination filters and surfaces normalized metadata", async () => {
        const config: AdminConfig = {
            restNonce: "nonce-obs",
            endpoints: {
                recognitionObservations: OBSERVATIONS_ENDPOINT,
                recognitionObservationUpdate: `${OBSERVATIONS_ENDPOINT}/update`,
            },
        };

        const filters = {
            status: "needs_review" as const,
            perPage: 5,
            page: 2,
        };

        let capturedUrl: URL | null = null;
        let capturedNonce: string | null = null;

        useDashboardHandlers(
            http.get(OBSERVATIONS_ENDPOINT, ({ request }) => {
                capturedUrl = new URL(request.url);
                capturedNonce = request.headers.get("X-WP-Nonce");

                return HttpResponse.json({
                    items: [
                        {
                            attachmentId: 42,
                            jobId: "job-42",
                            updatedAt: 1_700_000_000,
                            status: "needs_review",
                            summary: {
                                total: 1,
                                matched: 0,
                                needs_review: 1,
                            },
                            context: {
                                filename: "face.jpg",
                                imageUrl: "https://example.com/face.jpg",
                            },
                            observations: [],
                            confidenceScore: 0.91,
                            sourceRemoteId: null,
                        },
                    ],
                    total: 12,
                    page: 2,
                    per_page: 5,
                    total_pages: 3,
                    summary: {
                        attachments: 1,
                        observations: {
                            total: 1,
                            matched: 0,
                            needs_review: 1,
                        },
                    },
                });
            }),
        );

        const { result } = renderHook(
            () => useRecognitionObservations({ config, filters }),
            { wrapper: createWrapper() },
        );

        await waitFor(() => {
            expect(result.current.query.data?.total).toBe(12);
        });

        const data = result.current.query.data!;

        expect(data.page).toBe(2);
        expect(data.perPage).toBe(5);
        expect(data.totalPages).toBe(3);

        expect(capturedUrl).not.toBeNull();
        const params = capturedUrl!.searchParams;
        expect(params.get("status")).toBe("needs_review");
        expect(params.get("per_page")).toBe("5");
        expect(params.get("page")).toBe("2");
        expect(capturedNonce).toBe("nonce-obs");
    });

    it("derives summary and pagination defaults when the API omits them", async () => {
        const config: AdminConfig = {
            endpoints: {
                recognitionObservations: OBSERVATIONS_ENDPOINT,
            },
        };

        useDashboardHandlers(
            http.get(OBSERVATIONS_ENDPOINT, () =>
                HttpResponse.json({
                    items: [
                        {
                            attachmentId: 99,
                            jobId: null,
                            updatedAt: null,
                            status: "matched",
                            summary: {
                                total: 1,
                                matched: 1,
                                needs_review: 0,
                            },
                            context: {},
                            observations: [],
                            confidenceScore: 0.5,
                            sourceRemoteId: "remote-99",
                        },
                    ],
                    total: 1,
                }),
            ),
        );

        const { result } = renderHook(
            () => useRecognitionObservations({ config, filters: {} }),
            { wrapper: createWrapper() },
        );

        await waitFor(() => {
            expect(result.current.query.data?.total).toBe(1);
        });

        const data = result.current.query.data!;

        expect(data.page).toBe(1);
        expect(data.perPage).toBe(20);
        expect(data.totalPages).toBe(1);

        const summary = data.summary;
        expect(summary.attachments).toBe(1);
        expect(summary.observations.total).toBe(0);
        expect(summary.observations.matched).toBe(0);
        expect(summary.observations.needs_review).toBe(0);

        const item = data.items[0]!;
        expect(item.status).toBe("matched");
        expect(item.summary.total).toBe(1);
    });
});
