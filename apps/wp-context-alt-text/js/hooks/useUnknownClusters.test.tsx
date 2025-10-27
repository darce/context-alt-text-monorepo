import React, { type ReactNode } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

import { useUnknownClusters } from "./useUnknownClusters";
import { useDashboardHandlers } from "@/admin/testing/mswServer";
import { setAdminBootstrap } from "@/admin/globals";

const createWrapper = () => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
};

describe("useUnknownClusters", () => {
    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.restoreAllMocks();
    });

    it("returns fallback state when endpoint is not configured", async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch");

        const { result } = renderHook(() => useUnknownClusters(), {
            wrapper: createWrapper(),
        });

        expect(result.current.clusters).toEqual([]);
        expect(result.current.total).toBe(0);
        expect(result.current.page).toBe(1);
        expect(result.current.perPage).toBe(20);
        expect(result.current.isLoading).toBe(false);
        expect(result.current.error).toBeNull();
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("fetches cluster data with REST nonce and maps response", async () => {
        const endpoint = "http://example.test/wp-json/cat/v1/clusters";
        const nonce = "rest-nonce-123";

        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: nonce,
            },
        });

        let capturedNonce: string | null = null;
        useDashboardHandlers(
            http.get(endpoint, ({ request }) => {
                capturedNonce = request.headers.get("X-WP-Nonce");

                return HttpResponse.json({
                    clusters: [
                        {
                            id: "cluster-alpha",
                            face_count: 3,
                            sample_face: {
                                attachment_id: 123,
                                thumbnail_url: "http://example.test/crops/a.jpg",
                                bbox: { x: 10, y: 20, width: 120, height: 130 },
                            },
                            suggestion: {
                                roster_id: "person-42",
                                display_name: "Ellyn",
                                confidence: 0.93,
                                reason: "High cosine similarity",
                            },
                            created_at: "2025-10-24T12:00:00Z",
                            updated_at: "2025-10-24T12:30:00Z",
                        },
                    ],
                    total: 5,
                    page: 2,
                    per_page: 1,
                });
            }),
        );

        const fetchSpy = vi.spyOn(globalThis, "fetch");

        const { result } = renderHook(() => useUnknownClusters({ page: 2, perPage: 1 }), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
            expect(result.current.clusters.length).toBeGreaterThan(0);
        });

        expect(capturedNonce).toBe(nonce);
        expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining("page=2"), expect.any(Object));

        const cluster = result.current.clusters[0];
        expect(cluster.id).toBe("cluster-alpha");
        expect(cluster.faceCount).toBe(3);
        expect(cluster.sampleFace).toEqual({
            attachmentId: 123,
            thumbnailUrl: "http://example.test/crops/a.jpg",
            bbox: { x: 10, y: 20, width: 120, height: 130 },
        });
        expect(cluster.suggestion).toEqual({
            rosterId: "person-42",
            displayName: "Ellyn",
            confidence: 0.93,
            reason: "High cosine similarity",
        });
        expect(result.current.total).toBe(5);
        expect(result.current.page).toBe(2);
        expect(result.current.perPage).toBe(1);
    });
});
