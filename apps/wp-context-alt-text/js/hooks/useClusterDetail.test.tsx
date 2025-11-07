import React, { type ReactNode } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { renderHook, waitFor } from "@testing-library/react";

import { useClusterDetail } from "./useClusterDetail";
import { useDashboardHandlers } from "@/admin/testing/mswServer";
import { setAdminBootstrap } from "@/admin/globals";

const endpoint = "http://example.test/wp-json/cat/v1/clusters";

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

describe("useClusterDetail", () => {
    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.restoreAllMocks();
    });

    it("fetches initial page and automatically prefetches page 2", async () => {
        const nonce = "cluster-nonce";

        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: nonce,
            },
        });

        const fetchSpy = vi.spyOn(globalThis, "fetch");

        useDashboardHandlers(
            http.get(`${endpoint}/cluster-001`, ({ request }) => {
                const url = new URL(request.url);
                const page = url.searchParams.get("page") ?? "1";

                if (page === "1") {
                    return HttpResponse.json({
                        faces: [
                            {
                                id: "face-1",
                                attachment_id: 101,
                                cluster_id: "cluster-001",
                                bbox: { x: 10, y: 20, width: 80, height: 90 },
                                thumbnail_url: "http://example.test/crops/face-1.jpg",
                                detected_at: "2025-10-24T12:00:00Z",
                            },
                        ],
                        pagination: {
                            current_page: 1,
                            per_page: 20,
                            total_pages: 3,
                            total_faces: 55,
                            has_more: true,
                        },
                    });
                }

                if (page === "2") {
                    return HttpResponse.json({
                        faces: [
                            {
                                id: "face-2",
                                attachment_id: 102,
                                cluster_id: "cluster-001",
                                bbox: { x: 15, y: 25, width: 85, height: 95 },
                                thumbnail_url: "http://example.test/crops/face-2.jpg",
                                detected_at: "2025-10-24T12:05:00Z",
                            },
                        ],
                        pagination: {
                            current_page: 2,
                            per_page: 20,
                            total_pages: 3,
                            total_faces: 55,
                            has_more: true,
                        },
                    });
                }

                return HttpResponse.json({ faces: [], pagination: { has_more: false } });
            }),
        );

        const { result } = renderHook(() => useClusterDetail("cluster-001"), {
            wrapper: createWrapper(),
        });

        // Wait for initial page to load
        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.faces.length).toBe(1);
        expect(result.current.faces[0].id).toBe("face-1");
        expect(result.current.hasNextPage).toBe(true);

        // Wait a bit for automatic prefetch of page 2
        await waitFor(
            () => {
                const page2Calls = fetchSpy.mock.calls.filter((call) => call[0]?.toString().includes("page=2"));
                expect(page2Calls.length).toBeGreaterThan(0);
            },
            { timeout: 3000 },
        );
    });

    it("loads next page on fetchNextPage call", async () => {
        const nonce = "cluster-nonce";

        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: nonce,
            },
        });

        useDashboardHandlers(
            http.get(`${endpoint}/cluster-002`, ({ request }) => {
                const url = new URL(request.url);
                const page = url.searchParams.get("page") ?? "1";

                if (page === "1") {
                    return HttpResponse.json({
                        faces: [{ id: "face-1", attachment_id: 101, cluster_id: "cluster-002" }],
                        pagination: { current_page: 1, per_page: 20, total_pages: 2, has_more: true },
                    });
                }

                if (page === "2") {
                    return HttpResponse.json({
                        faces: [{ id: "face-2", attachment_id: 102, cluster_id: "cluster-002" }],
                        pagination: { current_page: 2, per_page: 20, total_pages: 2, has_more: false },
                    });
                }

                return HttpResponse.json({ faces: [], pagination: { has_more: false } });
            }),
        );

        const { result } = renderHook(() => useClusterDetail("cluster-002"), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.faces.length).toBe(1);
        expect(result.current.hasNextPage).toBe(true);

        // Manually fetch next page
        await result.current.fetchNextPage();

        await waitFor(() => {
            expect(result.current.faces.length).toBe(2);
        });

        expect(result.current.faces[1].id).toBe("face-2");
        expect(result.current.hasNextPage).toBe(false);
    });

    it("handles empty cluster gracefully", async () => {
        const nonce = "cluster-nonce";

        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: nonce,
            },
        });

        useDashboardHandlers(
            http.get(`${endpoint}/cluster-empty`, () => {
                return HttpResponse.json({
                    faces: [],
                    pagination: { current_page: 1, per_page: 20, total_pages: 0, has_more: false },
                });
            }),
        );

        const { result } = renderHook(() => useClusterDetail("cluster-empty"), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.faces).toEqual([]);
        expect(result.current.hasNextPage).toBe(false);
        expect(result.current.error).toBeNull();
    });
});
