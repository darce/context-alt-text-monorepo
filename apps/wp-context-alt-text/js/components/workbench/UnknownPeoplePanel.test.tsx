import React, { type ReactNode } from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

import { UnknownPeoplePanel, type UnknownPeoplePanelProps } from "./UnknownPeoplePanel";
import { setFaceDragData } from "@/components/workbench/dragTypes";
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

const renderPanel = (props: Partial<UnknownPeoplePanelProps> = {}) =>
    render(<UnknownPeoplePanel {...props} />, {
        wrapper: createWrapper(),
    });

describe("UnknownPeoplePanel", () => {
    const endpoint = "http://example.test/wp-json/cat/v1/clusters";

    beforeEach(() => {
        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: "test-nonce",
            },
        });
    });

    afterEach(() => {
        setAdminBootstrap(undefined);
        vi.restoreAllMocks();
    });

    it("shows loading state while fetching data", async () => {
        useDashboardHandlers(
            http.get(endpoint, () =>
                HttpResponse.json(
                    {
                        clusters: [],
                        total: 0,
                        page: 1,
                        per_page: 20,
                    },
                    { status: 200, delay: 100 },
                ),
            ),
        );

        renderPanel();

        expect(screen.getByText(/loading unknown people/i)).toBeInTheDocument();
    });

    it("renders empty state when no clusters exist", async () => {
        useDashboardHandlers(
            http.get(endpoint, () =>
                HttpResponse.json({
                    clusters: [],
                    total: 0,
                    page: 1,
                    per_page: 20,
                }),
            ),
        );

        renderPanel();

        await waitFor(() => {
            expect(screen.getByText(/no unknown people/i)).toBeInTheDocument();
        });
    });

    it("renders cluster cards and handles selection", async () => {
        useDashboardHandlers(
            http.get(endpoint, () =>
                HttpResponse.json({
                    clusters: [
                        {
                            id: "cluster-alpha",
                            face_count: 4,
                            sample_face: {
                                attachment_id: 123,
                                thumbnail_url: "http://example.test/image.jpg",
                                bbox: { x: 10, y: 20, width: 30, height: 40 },
                            },
                            suggestion: {
                                roster_id: "person-1",
                                display_name: "Ellyn",
                                confidence: 0.92,
                            },
                            created_at: "2025-10-20T12:00:00Z",
                            updated_at: "2025-10-20T13:00:00Z",
                        },
                    ],
                    total: 1,
                    page: 1,
                    per_page: 20,
                }),
            ),
        );

        const handleSelect = vi.fn();
        renderPanel({ onSelectCluster: handleSelect });

        const cardButton = await screen.findByRole("button", { name: /review cluster/i });
        expect(screen.getByText(/Ellyn/)).toBeInTheDocument();
        expect(screen.getByText(/4 faces/i)).toBeInTheDocument();
        expect(cardButton).toHaveAttribute("aria-pressed", "false");

        fireEvent.click(cardButton);
        expect(handleSelect).toHaveBeenCalledWith("cluster-alpha");
    });

    it("indicates selected cluster card", async () => {
        useDashboardHandlers(
            http.get(endpoint, () =>
                HttpResponse.json({
                    clusters: [
                        {
                            id: "cluster-alpha",
                            face_count: 2,
                            sample_face: {
                                attachment_id: 123,
                                thumbnail_url: "http://example.test/image.jpg",
                                bbox: { x: 10, y: 20, width: 30, height: 40 },
                            },
                            created_at: "2025-10-20T12:00:00Z",
                            updated_at: "2025-10-20T13:00:00Z",
                        },
                    ],
                    total: 1,
                    page: 1,
                    per_page: 20,
                }),
            ),
        );

        renderPanel({ selectedClusterId: "cluster-alpha" });

        const cardButton = await screen.findByRole("button", { name: /review cluster/i });
        expect(cardButton).toHaveAttribute("aria-pressed", "true");
    });

    it("notifies when faces are dropped onto a cluster", async () => {
        useDashboardHandlers(
            http.get(endpoint, () =>
                HttpResponse.json({
                    clusters: [
                        {
                            id: "cluster-alpha",
                            face_count: 2,
                            sample_face: {
                                attachment_id: 123,
                                thumbnail_url: "http://example.test/image-alpha.jpg",
                                bbox: { x: 10, y: 20, width: 30, height: 40 },
                            },
                            created_at: "2025-10-20T12:00:00Z",
                            updated_at: "2025-10-20T13:00:00Z",
                        },
                        {
                            id: "cluster-beta",
                            face_count: 3,
                            sample_face: {
                                attachment_id: 456,
                                thumbnail_url: "http://example.test/image-beta.jpg",
                                bbox: { x: 15, y: 25, width: 35, height: 45 },
                            },
                            created_at: "2025-10-21T12:00:00Z",
                            updated_at: "2025-10-21T13:00:00Z",
                        },
                    ],
                    total: 2,
                    page: 1,
                    per_page: 20,
                }),
            ),
        );

        const handleMove = vi.fn();
        renderPanel({ onMoveFaces: handleMove });

        const cards = await screen.findAllByRole("button", { name: /review cluster/i });
        const targetCard = cards[1];

        const dataTransfer = ((store: Map<string, string>) => ({
            setData(type: string, value: string) {
                store.set(type, value);
                this.types = Array.from(store.keys());
            },
            getData(type: string) {
                return store.get(type) ?? "";
            },
            clearData() {
                store.clear();
                this.types = [];
            },
            effectAllowed: "all",
            dropEffect: "move",
            files: [],
            items: [],
            types: [] as string[],
        }))(
            new Map<string, string>(),
        ) as unknown as DataTransfer;

        setFaceDragData(dataTransfer, { clusterId: "cluster-alpha", faceIds: ["face-1", "face-2"] });

        fireEvent.dragEnter(targetCard, { dataTransfer });
        fireEvent.dragOver(targetCard, { dataTransfer });
        fireEvent.drop(targetCard, { dataTransfer });

        expect(handleMove).toHaveBeenCalledWith({
            targetClusterId: "cluster-beta",
            sourceClusterId: "cluster-alpha",
            faceIds: ["face-1", "face-2"],
        });
    });
});
