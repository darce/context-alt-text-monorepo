import React, { type ReactNode } from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClusterDetailView, type ClusterDetailViewProps } from "./ClusterDetailView";
import { useDashboardHandlers, server } from "@/admin/testing/mswServer";
import { setAdminBootstrap } from "@/admin/globals";
import { ToastProvider } from "@/contexts/ToastContext";

const endpoint = "http://example.test/wp-json/cat/v1/clusters";

const createWrapper = () => {
    const client = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    return ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>
            <ToastProvider>{children}</ToastProvider>
        </QueryClientProvider>
    );
};

const renderDetail = (clusterId = "cluster-alpha", props: Partial<ClusterDetailViewProps> = {}) =>
    render(<ClusterDetailView clusterId={clusterId} {...props} />, {
        wrapper: createWrapper(),
    });

describe("ClusterDetailView", () => {
    beforeEach(() => {
        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: "detail-nonce",
            },
        });

        useDashboardHandlers(
            http.get(`${endpoint}/:clusterId/suggestions`, ({ params }) =>
                HttpResponse.json({
                    cluster_id: params.clusterId,
                    suggestions: [],
                }),
            ),
        );

        useDashboardHandlers(
            http.get("/wp-json/cat/v1/roster", () =>
                HttpResponse.json({
                    entries: [],
                    total: 0,
                    page: 1,
                    per_page: 20,
                    totalPages: 0,
                }),
            ),
        );
    });

    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.restoreAllMocks();
        server.resetHandlers();
    });

    it("shows loading state while fetching", () => {
        useDashboardHandlers(
            http.get(`${endpoint}/cluster-alpha`, () =>
                HttpResponse.json(
                    {
                        faces: [],
                        pagination: {
                            current_page: 1,
                            per_page: 20,
                            total_pages: 0,
                            has_more: false,
                        },
                    },
                    { status: 200, delay: 150 },
                ),
            ),
        );

        renderDetail("cluster-alpha");

        expect(screen.getByRole("status")).toHaveTextContent(/loading cluster faces/i);
    });

    it("renders faces when data loads", async () => {
        useDashboardHandlers(
            http.get(`${endpoint}/cluster-alpha`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-1",
                            attachmentId: 101,
                            bbox: { x: 10, y: 20, width: 80, height: 90 },
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                            detectedAt: "2025-10-24T12:00:00Z",
                        },
                        {
                            id: "face-2",
                            attachmentId: 102,
                            bbox: { x: 12, y: 22, width: 85, height: 95 },
                            thumbnail_url: "http://example.test/crops/face-2.jpg",
                            detectedAt: "2025-10-24T12:05:00Z",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 2,
                        has_more: false,
                    },
                }),
            ),
        );

        renderDetail("cluster-alpha");

        await waitFor(() => {
            expect(screen.getByText(/2 faces ready for review/i)).toBeInTheDocument();
        });

        expect(screen.getAllByRole("img", { name: /face/i })).toHaveLength(2);
    });

    it("shows error message and retries on request failure", async () => {
        useDashboardHandlers(
            http.get(`${endpoint}/cluster-alpha`, () => HttpResponse.json({ message: "error" }, { status: 500 })),
        );

        const fetchSpy = vi.spyOn(globalThis, "fetch");
        renderDetail("cluster-alpha");

        await waitFor(() => {
            expect(screen.getByRole("alert")).toHaveTextContent(/unable to load faces/i);
        });

        const initialClusterCalls = fetchSpy.mock.calls.filter(
            ([request]) =>
                typeof request === "string" && request.includes("/cluster-alpha") && !request.includes("suggestions"),
        );
        expect(initialClusterCalls).toHaveLength(1);

        server.use(
            http.get(`${endpoint}/cluster-alpha`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-1",
                            attachmentId: 101,
                            bbox: { x: 10, y: 20, width: 80, height: 90 },
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                            detectedAt: "2025-10-24T12:00:00Z",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 1,
                        has_more: false,
                    },
                }),
            ),
        );

        fireEvent.click(screen.getByRole("button", { name: /retry/i }));

        await waitFor(() => {
            const clusterCalls = fetchSpy.mock.calls.filter(
                ([request]) =>
                    typeof request === "string" &&
                    request.includes("/cluster-alpha") &&
                    !request.includes("suggestions"),
            );
            expect(clusterCalls).toHaveLength(2);
            expect(screen.getByText(/1 face ready for review/i)).toBeInTheDocument();
        });
    });

    it("renders suggestion chip when backend provides suggestion", async () => {
        server.use(
            http.get(`${endpoint}/cluster-alpha/suggestions`, () =>
                HttpResponse.json({
                    cluster_id: "cluster-alpha",
                    suggestions: [
                        {
                            display_name: "Daniel Rivera",
                            roster_id: "roster-123",
                            confidence: 0.87,
                        },
                    ],
                }),
            ),
        );

        useDashboardHandlers(
            http.get(`${endpoint}/cluster-alpha`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-1",
                            attachmentId: 101,
                            bbox: { x: 10, y: 20, width: 80, height: 90 },
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                            detectedAt: "2025-10-24T12:00:00Z",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 1,
                        has_more: false,
                    },
                }),
            ),
        );

        renderDetail("cluster-alpha");

        await waitFor(() => {
            expect(screen.getByText(/cluster detail/i)).toBeInTheDocument();
        });

        const suggestionChip = screen.getByRole("note", { name: /suggested match/i });
        expect(suggestionChip).toHaveTextContent("Daniel Rivera");
        expect(suggestionChip).toHaveTextContent(/87% confidence/i);
    });

    it("prioritizes suggestions endpoint over cluster summary suggestion", async () => {
        server.use(
            http.get(`${endpoint}/cluster-beta`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-9",
                            attachmentId: 501,
                            bbox: { x: 15, y: 25, width: 50, height: 55 },
                            thumbnail_url: "http://example.test/crops/face-9.jpg",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 1,
                        has_more: false,
                    },
                }),
            ),
        );

        server.use(
            http.get(`${endpoint}/cluster-beta/suggestions`, () =>
                HttpResponse.json({
                    cluster_id: "cluster-beta",
                    suggestions: [
                        {
                            roster_id: "person-prime",
                            display_name: "Primary Suggestion",
                            confidence: 0.94,
                            confidence_level: "high",
                            match_count: 2,
                            face_ids: ["face-9"],
                        },
                    ],
                }),
            ),
        );

        renderDetail("cluster-beta");

        await waitFor(() => {
            expect(screen.getByRole("button", { name: /primary suggestion/i })).toBeInTheDocument();
        });

        expect(
            screen.getByRole("button", { name: /suggested match: primary suggestion, 94% confidence/i }),
        ).toBeInTheDocument();
        expect(screen.queryByText(/fallback name/i)).not.toBeInTheDocument();
    });

    it("opens confirmation modal when suggestion chip is selected", async () => {
        server.use(
            http.get(`${endpoint}/cluster-beta`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-9",
                            attachmentId: 501,
                            bbox: { x: 15, y: 25, width: 50, height: 55 },
                            thumbnail_url: "http://example.test/crops/face-9.jpg",
                        },
                        {
                            id: "face-10",
                            attachmentId: 502,
                            bbox: { x: 20, y: 30, width: 45, height: 50 },
                            thumbnail_url: "http://example.test/crops/face-10.jpg",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 2,
                        has_more: false,
                    },
                }),
            ),
        );

        server.use(
            http.get(`${endpoint}/cluster-beta/suggestions`, () =>
                HttpResponse.json({
                    cluster_id: "cluster-beta",
                    suggestions: [
                        {
                            roster_id: "person-prime",
                            display_name: "Primary Suggestion",
                            confidence: 0.9,
                            confidence_level: "high",
                            match_count: 1,
                            face_ids: ["face-9"],
                        },
                    ],
                }),
            ),
        );

        const onRequestConfirm = vi.fn();
        const user = userEvent.setup();

        renderDetail("cluster-beta", { onRequestConfirm });

        const suggestionButton = await screen.findByRole("button", {
            name: /suggested match: primary suggestion/i,
        });

        await user.click(suggestionButton);

        await waitFor(() => {
            expect(screen.getByRole("heading", { name: /confirm identity/i })).toBeInTheDocument();
        });

        expect(screen.getByRole("button", { name: /label 1 face/i })).not.toBeDisabled();
        expect(onRequestConfirm).toHaveBeenCalledWith("cluster-beta", ["face-9"]);
    });

    it("invokes onRequestConfirm with selected faces", async () => {
        useDashboardHandlers(
            http.get(`${endpoint}/cluster-alpha`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-1",
                            attachmentId: 101,
                            bbox: { x: 10, y: 20, width: 80, height: 90 },
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                            detectedAt: "2025-10-24T12:00:00Z",
                        },
                        {
                            id: "face-2",
                            attachmentId: 102,
                            bbox: { x: 12, y: 22, width: 85, height: 95 },
                            thumbnail_url: "http://example.test/crops/face-2.jpg",
                            detectedAt: "2025-10-24T12:05:00Z",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 2,
                        has_more: false,
                    },
                }),
            ),
        );

        const handleConfirm = vi.fn();
        const user = userEvent.setup();

        renderDetail("cluster-alpha", { onRequestConfirm: handleConfirm });

        await waitFor(() => {
            expect(screen.getByText(/2 faces ready for review/i)).toBeInTheDocument();
        });

        const buttons = screen.getAllByRole("button", { name: /face \d+ preview/i });
        await user.click(buttons[1]);

        const confirmButton = screen.getByRole("button", { name: /label selected/i });
        expect(confirmButton).not.toBeDisabled();

        await user.click(confirmButton);

        expect(handleConfirm).toHaveBeenCalledWith("cluster-alpha", ["face-1"]);
    });

    it("still triggers review later even when no selection exists", async () => {
        useDashboardHandlers(
            http.get(`${endpoint}/cluster-alpha`, () =>
                HttpResponse.json({
                    faces: [
                        {
                            id: "face-1",
                            attachmentId: 101,
                            bbox: { x: 10, y: 20, width: 80, height: 90 },
                            thumbnail_url: "http://example.test/crops/face-1.jpg",
                            detectedAt: "2025-10-24T12:00:00Z",
                        },
                    ],
                    pagination: {
                        current_page: 1,
                        per_page: 20,
                        total_pages: 1,
                        total_faces: 1,
                        has_more: false,
                    },
                }),
            ),
        );

        const handleReviewLater = vi.fn();
        const user = userEvent.setup();

        renderDetail("cluster-alpha", { onReviewLater: handleReviewLater });

        await waitFor(() => {
            expect(screen.getByText(/1 face ready for review/i)).toBeInTheDocument();
        });

        const clearButton = screen.getByRole("button", { name: /clear/i });
        await user.click(clearButton);

        const reviewLater = screen.getByRole("button", { name: /review later/i });
        expect(reviewLater).not.toBeDisabled();

        await user.click(reviewLater);

        expect(handleReviewLater).toHaveBeenCalledWith("cluster-alpha", []);
    });
});
