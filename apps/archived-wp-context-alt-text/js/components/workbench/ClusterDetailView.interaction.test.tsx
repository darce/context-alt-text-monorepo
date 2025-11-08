import React, { type ReactNode } from "react";
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClusterDetailView } from "./ClusterDetailView";
import { setAdminBootstrap } from "@/admin/globals";
import { useDashboardHandlers, server } from "@/admin/testing/mswServer";
import { ToastProvider } from "@/contexts/ToastContext";

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
        <QueryClientProvider client={queryClient}>
            <ToastProvider>{children}</ToastProvider>
        </QueryClientProvider>
    );
};

describe("ClusterDetailView interactions", () => {
    beforeEach(() => {
        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: "cluster-detail-nonce",
            },
        });
    });

    afterEach(() => {
        setAdminBootstrap(undefined);
        server.resetHandlers();
    });

    it("allows toggling face selection with mouse and keyboard", async () => {
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
                            bbox: { x: 30, y: 40, width: 100, height: 110 },
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

        const user = userEvent.setup();

        render(<ClusterDetailView clusterId="cluster-alpha" />, { wrapper: createWrapper() });

        const faceButtons = await screen.findAllByRole("button", { name: /face \d+ preview/i });

        expect(faceButtons).toHaveLength(2);
        await waitFor(() => {
            faceButtons.forEach((button) => {
                expect(button).toHaveAttribute("aria-pressed", "true");
            });
        });

        await user.click(faceButtons[0]);
        expect(faceButtons[0]).toHaveAttribute("aria-pressed", "false");
        expect(faceButtons[1]).toHaveAttribute("aria-pressed", "true");

        await user.keyboard("[Space]");

        await waitFor(() => {
            expect(faceButtons[0]).toHaveAttribute("aria-pressed", "true");
        });
    });
});
