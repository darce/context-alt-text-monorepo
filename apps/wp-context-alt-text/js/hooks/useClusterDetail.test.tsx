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

    it("returns fallback detail when endpoint is missing", async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch");

        const { result } = renderHook(() => useClusterDetail("cluster-alpha"), {
            wrapper: createWrapper(),
        });

        expect(result.current.cluster).toEqual({
            id: "cluster-alpha",
            faceCount: 0,
            createdAt: null,
            updatedAt: null,
            sampleFace: null,
            suggestion: null,
        });
        expect(result.current.faces).toEqual([]);
        expect(result.current.isLoading).toBe(false);
        expect(result.current.error).toBeNull();
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("fetches cluster detail and maps response", async () => {
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
            http.get(`${endpoint}/cluster-alpha`, ({ request }) => {
                expect(request.headers.get("X-WP-Nonce")).toBe(nonce);

                return HttpResponse.json({
                    cluster: {
                        id: "cluster-alpha",
                        face_count: 2,
                        created_at: "2025-10-24T12:00:00Z",
                        updated_at: "2025-10-24T13:00:00Z",
                        sample_face: {
                            attachment_id: 101,
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                            bbox: { x: 10, y: 20, width: 80, height: 90 },
                        },
                    },
                    faces: [
                        {
                            id: "face-1",
                            databaseId: 1,
                            attachmentId: 101,
                            clusterId: "cluster-alpha",
                            bbox: {
                                x: 10,
                                y: 20,
                                width: 80,
                                height: 90,
                                imageWidth: 600,
                                imageHeight: 400,
                            },
                            detectedAt: "2025-10-24T12:00:00Z",
                            resolvedAt: null,
                            rosterId: null,
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                        },
                        {
                            id: "face-2",
                            databaseId: 2,
                            attachmentId: 102,
                            clusterId: "cluster-alpha",
                            bbox: {
                                x: 15,
                                y: 25,
                                width: 85,
                                height: 95,
                                imageWidth: 620,
                                imageHeight: 420,
                            },
                            detectedAt: "2025-10-24T12:05:00Z",
                            resolvedAt: null,
                            rosterId: null,
                            thumbnail_url: "http://example.test/crops/face-2.jpg",
                        },
                    ],
                });
            }),
        );

        const fetchSpy = vi.spyOn(globalThis, "fetch");

        const { result } = renderHook(() => useClusterDetail("cluster-alpha"), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
            expect(result.current.faces.length).toBe(2);
        });

        expect(fetchSpy).toHaveBeenCalledWith(
            `${endpoint}/cluster-alpha`,
            expect.objectContaining({
                headers: expect.objectContaining({
                    "X-WP-Nonce": nonce,
                }),
            }),
        );

        expect(result.current.cluster).toEqual(
            expect.objectContaining({
                id: "cluster-alpha",
                faceCount: 2,
                createdAt: "2025-10-24T12:00:00Z",
                updatedAt: "2025-10-24T13:00:00Z",
            }),
        );
        expect(result.current.cluster.sampleFace).toEqual(
            expect.objectContaining({
                attachmentId: 101,
                thumbnailUrl: "http://example.test/crops/face-1.jpg",
            }),
        );
        expect(result.current.faces[0]).toEqual(
            expect.objectContaining({
                id: "face-1",
                attachmentId: 101,
                thumbnailUrl: "http://example.test/crops/face-1.jpg",
                bbox: expect.objectContaining({
                    imageWidth: 600,
                    imageHeight: 400,
                }),
            }),
        );
    });
});
