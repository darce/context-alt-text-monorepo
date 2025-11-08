import React, { type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";

import { useCoverageMetrics } from "./useCoverageMetrics";
import type { CoverageCard } from "@/admin/types";
import { useDashboardHandlers } from "@/admin/testing/mswServer";
import { setAdminBootstrap } from "@/admin/globals";

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

const INITIAL_DATA: CoverageCard = {
    total: 200,
    with_alt: 120,
    missing: 80,
    coverage_percent: 60,
    trend_series: [],
};

describe("useCoverageMetrics", () => {
    afterEach(() => {
        setAdminBootstrap(undefined);
    });

    it("returns the initial data when no endpoint is configured", () => {
        const { result } = renderHook(() => useCoverageMetrics({ initialData: INITIAL_DATA }), {
            wrapper: createWrapper(),
        });

        expect(result.current.data).toEqual(INITIAL_DATA);
        expect(result.current.isFetching).toBe(false);
    });

    it("fetches coverage metrics and merges them with the bootstrap data", async () => {
        const endpoint = "http://example.test/wp-json/cat/v1/dashboard/coverage";
        setAdminBootstrap({
            config: {
                endpoints: { coverage: endpoint },
                restNonce: "nonce-value",
            },
        });

        let capturedNonce: string | null = null;
        const fetchSpy = vi.spyOn(globalThis, "fetch");
        useDashboardHandlers(
            http.get(endpoint, ({ request }) => {
                capturedNonce = request.headers.get("X-WP-Nonce");
                return HttpResponse.json({
                    total: 210,
                    with_alt: 190,
                    missing: 20,
                    coverage_percent: 90,
                    trend_series: [
                        {
                            timestamp: Date.now(),
                            coverage: 90,
                            total: 210,
                            with_alt: 190,
                            missing: 20,
                        },
                    ],
                });
            }),
        );

        const { result } = renderHook(() => useCoverageMetrics({ initialData: INITIAL_DATA }), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            await result.current.refetch();
        });

        await waitFor(() => {
            expect(result.current.status).toBe("success");
        });

        expect(fetchSpy).toHaveBeenCalled();
        const [requestUrl, requestInit] = fetchSpy.mock.calls[0] ?? [];
        expect(requestUrl).toBe(endpoint);
        const headers = new Headers(requestInit?.headers);
        expect(headers.get("accept")).toBe("application/json");
        expect(headers.get("x-wp-nonce")).toBe("nonce-value");
        expect(capturedNonce).toBe("nonce-value");

        expect(result.current.data.missing).toBe(20);
        expect(result.current.data.total).toBe(210);
        expect(result.current.data.with_alt).toBe(190);
        expect(result.current.data.coverage_percent).toBe(90);
        expect(result.current.data.trend_series).toHaveLength(1);

        fetchSpy.mockRestore();
    });

    it("surfaces errors while keeping the bootstrap metrics available", async () => {
        const endpoint = "http://example.test/wp-json/cat/v1/dashboard/coverage";
        setAdminBootstrap({
            config: {
                endpoints: { coverage: endpoint },
            },
        });

        useDashboardHandlers(
            http.get(endpoint, () =>
                HttpResponse.json(
                    { message: "Server error" },
                    {
                        status: 500,
                    },
                ),
            ),
        );

        const fetchSpy = vi.spyOn(globalThis, "fetch");

        const { result } = renderHook(() => useCoverageMetrics({ initialData: INITIAL_DATA }), {
            wrapper: createWrapper(),
        });

        await act(async () => {
            await result.current.refetch();
        });

        await waitFor(() => {
            expect(fetchSpy).toHaveBeenCalled();
        });

        await waitFor(() => {
            expect(result.current.status).toBe("error");
        });

        expect(result.current.data).toEqual(INITIAL_DATA);

        fetchSpy.mockRestore();
    });
});
