import React, { type ReactNode } from "react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClusterConfirmationModal } from "@/components/workbench/ClusterConfirmationModal";
import type { ClusterFaceDetail, ClusterSuggestion } from "@/types/face-clustering";
import { setAdminBootstrap } from "@/admin/globals";

vi.mock("@/api/clusterApi", () => ({
    confirmCluster: vi.fn(),
}));

vi.mock("@/admin/notices", () => ({
    dispatchNotice: vi.fn(),
}));

vi.mock("@/components/workbench/PeoplePicker", () => ({
    PeoplePicker: ({ isOpen, onSelect }: { isOpen: boolean; onSelect: (id: string, name: string) => void }) =>
        isOpen ? (
            <div>
                <button
                    type="button"
                    onClick={() => {
                        onSelect("person-picker", "Picker Person");
                    }}
                >
                    Mock Select Person
                </button>
            </div>
        ) : null,
}));

const { confirmCluster } = await import("@/api/clusterApi");
const { dispatchNotice } = await import("@/admin/notices");

const suggestions: ClusterSuggestion[] = [
    {
        clusterId: "cluster-1",
        rosterId: "person-1",
        displayName: "Jordan Smith",
        confidence: 0.92,
        confidenceLevel: "high",
        matchCount: 3,
        faceIds: ["face-1", "face-2", "face-3"],
    },
];

const faces: ClusterFaceDetail[] = [
    {
        id: "face-1",
        attachmentId: 101,
        bbox: { x: 10, y: 10, width: 20, height: 20 },
        thumbnailUrl: "http://example.test/face-1.jpg",
    },
    {
        id: "face-2",
        attachmentId: 102,
        bbox: { x: 5, y: 15, width: 25, height: 35 },
        thumbnailUrl: "http://example.test/face-2.jpg",
    },
];

const createWrapper = () => {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: {
                retry: false,
            },
        },
    });

    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const Wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    return { Wrapper, queryClient, invalidateSpy };
};

describe("ClusterConfirmationModal", () => {
    beforeEach(() => {
        setAdminBootstrap({
            config: {
                restNonce: "test-nonce",
                endpoints: {
                    unknownClusters: "http://example.test/wp-json/cat/v1/clusters",
                },
            },
        });

        vi.mocked(confirmCluster).mockResolvedValue({
            clusterId: "cluster-1",
            rosterId: "person-1",
            confirmed: [
                {
                    faceId: "face-1",
                    databaseId: 10,
                    observationId: 200,
                },
            ],
            labeledCount: 1,
            warnings: [],
            errors: [],
            cascade: {
                auto: [],
                candidates: [],
            },
        });
    });

    afterEach(() => {
        vi.clearAllMocks();
        setAdminBootstrap(undefined);
    });

    it("submits confirmation using primary suggestion and refreshes queries", async () => {
        const onClose = vi.fn();
        const { Wrapper, invalidateSpy } = createWrapper();

        render(
            <ClusterConfirmationModal
                isOpen
                clusterId="cluster-1"
                faces={faces}
                selectedFaceIds={faces.map((face) => face.id)}
                suggestions={suggestions}
                onClose={onClose}
            />,
            { wrapper: Wrapper },
        );

        const confirmButton = await screen.findByRole("button", { name: /label 2 faces/i });
        expect(confirmButton).not.toBeDisabled();

        await userEvent.click(confirmButton);

        await waitFor(() => {
            expect(confirmCluster).toHaveBeenCalledWith(
                "cluster-1",
                {
                    rosterId: "person-1",
                    faceIds: ["face-1", "face-2"],
                },
                "test-nonce",
            );
        });

        expect(dispatchNotice).toHaveBeenCalledWith("success", expect.stringMatching(/labeled 1 face/i));
        await waitFor(() => {
            expect(invalidateSpy).toHaveBeenCalled();
        });
        expect(onClose).toHaveBeenCalled();
    });

    it("disables confirm button until roster selected when no suggestions provided", async () => {
        const { Wrapper } = createWrapper();

        render(
            <ClusterConfirmationModal
                isOpen
                clusterId="cluster-2"
                faces={faces}
                selectedFaceIds={faces.map((face) => face.id)}
                suggestions={[]}
                onClose={vi.fn()}
            />,
            { wrapper: Wrapper },
        );

        const confirmButton = await screen.findByRole("button", { name: /label 2 faces/i });
        expect(confirmButton).toBeDisabled();

        await userEvent.click(screen.getByRole("button", { name: /select a person/i }));
        const pickerButton = await screen.findByRole("button", { name: /mock select person/i, hidden: true });
        await userEvent.click(pickerButton, { pointerEventsCheck: 0 });

        expect(confirmButton).not.toBeDisabled();
    });

    it("shows error message when confirmation fails", async () => {
        vi.mocked(confirmCluster).mockRejectedValueOnce(new Error("Unable to confirm cluster."));
        const { Wrapper } = createWrapper();

        render(
            <ClusterConfirmationModal
                isOpen
                clusterId="cluster-3"
                faces={faces}
                selectedFaceIds={faces.map((face) => face.id)}
                suggestions={suggestions}
                onClose={vi.fn()}
            />,
            { wrapper: Wrapper },
        );

        const confirmButton = await screen.findByRole("button", { name: /label 2 faces/i });
        await userEvent.click(confirmButton);

        await waitFor(() => {
            expect(screen.getByText(/unable to confirm cluster/i)).toBeInTheDocument();
        });
    });
});
