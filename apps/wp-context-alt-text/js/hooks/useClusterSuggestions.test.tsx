import React, { type ReactNode } from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { useClusterSuggestions } from "./useClusterSuggestions";
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

describe("useClusterSuggestions", () => {
    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.restoreAllMocks();
    });

    it("returns empty suggestions when endpoint is missing", async () => {
        const fetchSpy = vi.spyOn(globalThis, "fetch");

        const { result } = renderHook(() => useClusterSuggestions("cluster-1"), {
            wrapper: createWrapper(),
        });

        expect(result.current.suggestions).toEqual([]);
        expect(result.current.isLoading).toBe(false);
        expect(result.current.error).toBeNull();
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it("fetches suggestions and normalizes payload", async () => {
        const nonce = "suggestion-nonce";

        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: nonce,
            },
        });

        useDashboardHandlers(
            http.get(`${endpoint}/cluster-1/suggestions`, ({ request }) => {
                expect(request.headers.get("X-WP-Nonce")).toBe(nonce);

                return HttpResponse.json({
                    cluster_id: "cluster-1",
                    suggestions: [
                        {
                            cluster_id: "cluster-1",
                            roster_id: "person-a",
                            display_name: "Jordan",
                            confidence: 0.92,
                            confidence_level: "high",
                            match_count: 3,
                            face_ids: ["face-1", "face-2", "face-3"],
                            reason: "High similarity across 3 faces",
                        },
                        {
                            roster_id: "person-b",
                            display_name: "Taylor",
                            confidence: 0.78,
                            confidence_level: "medium",
                            match_count: 1,
                            face_ids: ["face-4"],
                        },
                    ],
                });
            }),
        );

        const { result } = renderHook(() => useClusterSuggestions("cluster-1"), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
            expect(result.current.suggestions.length).toBe(2);
        });

        expect(result.current.suggestions[0]).toEqual(
            expect.objectContaining({
                clusterId: "cluster-1",
                rosterId: "person-a",
                displayName: "Jordan",
                confidence: 0.92,
                confidenceLevel: "high",
                matchCount: 3,
                faceIds: ["face-1", "face-2", "face-3"],
                reason: "High similarity across 3 faces",
            }),
        );

        expect(result.current.suggestions[1]).toEqual(
            expect.objectContaining({
                rosterId: "person-b",
                displayName: "Taylor",
                confidence: 0.78,
                confidenceLevel: "medium",
                matchCount: 1,
            }),
        );
    });

    it("handles empty suggestion list", async () => {
        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: "nonce",
            },
        });

        useDashboardHandlers(
            http.get(`${endpoint}/cluster-2/suggestions`, () =>
                HttpResponse.json({
                    cluster_id: "cluster-2",
                    suggestions: [],
                }),
            ),
        );

        const { result } = renderHook(() => useClusterSuggestions("cluster-2"), {
            wrapper: createWrapper(),
        });

        await waitFor(() => {
            expect(result.current.isLoading).toBe(false);
        });

        expect(result.current.suggestions).toEqual([]);
        expect(result.current.error).toBeNull();
    });
});
