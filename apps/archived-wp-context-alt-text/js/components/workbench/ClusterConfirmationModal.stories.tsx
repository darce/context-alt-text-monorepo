import type { Meta, StoryObj } from "@storybook/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClusterConfirmationModal } from "@/components/workbench/ClusterConfirmationModal";
import type { ClusterFaceDetail, ClusterSuggestion } from "@/types/face-clustering";
import { setAdminBootstrap } from "@/admin/globals";

const meta: Meta<typeof ClusterConfirmationModal> = {
    title: "Workbench/Cluster Confirmation Modal",
    component: ClusterConfirmationModal,
    decorators: [
        (Story) => {
            const [queryClient] = React.useState(
                () =>
                    new QueryClient({
                        defaultOptions: {
                            queries: {
                                retry: false,
                            },
                        },
                    }),
            );

            React.useEffect(() => {
                setAdminBootstrap({
                    config: {
                        restNonce: "storybook-nonce",
                        endpoints: {
                            unknownClusters: "http://example.test/wp-json/cat/v1/clusters",
                        },
                    },
                });

                return () => {
                    setAdminBootstrap(undefined);
                };
            }, []);

            return (
                <QueryClientProvider client={queryClient}>
                    <Story />
                </QueryClientProvider>
            );
        },
    ],
    args: {
        isOpen: true,
        clusterId: "cluster-story",
        onClose: () => void 0,
    },
    parameters: {
        layout: "fullscreen",
    },
};

export default meta;

type Story = StoryObj<typeof ClusterConfirmationModal>;

const sampleFaces: ClusterFaceDetail[] = [
    {
        id: "face-101",
        attachmentId: 501,
        bbox: { x: 12, y: 18, width: 40, height: 50 },
        thumbnailUrl: "https://placehold.co/80x80?text=Face+1",
    },
    {
        id: "face-102",
        attachmentId: 501,
        bbox: { x: 30, y: 25, width: 32, height: 48 },
        thumbnailUrl: "https://placehold.co/80x80?text=Face+2",
    },
    {
        id: "face-103",
        attachmentId: 502,
        bbox: { x: 15, y: 30, width: 36, height: 44 },
        thumbnailUrl: "https://placehold.co/80x80?text=Face+3",
    },
];

const sampleSuggestions: ClusterSuggestion[] = [
    {
        clusterId: "cluster-story",
        rosterId: "person-101",
        displayName: "Jordan Smith",
        confidence: 0.94,
        confidenceLevel: "high",
        matchCount: 3,
        faceIds: ["face-101", "face-102", "face-103"],
        reason: "High confidence across 3 matches",
    },
    {
        clusterId: "cluster-story",
        rosterId: "person-202",
        displayName: "Taylor Brooks",
        confidence: 0.78,
        confidenceLevel: "medium",
        matchCount: 1,
        faceIds: ["face-103"],
        reason: "Single supporting match",
    },
];

export const WithSuggestions: Story = {
    args: {
        faces: sampleFaces,
        selectedFaceIds: sampleFaces.map((face) => face.id),
        suggestions: sampleSuggestions,
    },
};

export const WithoutSuggestions: Story = {
    args: {
        faces: sampleFaces,
        selectedFaceIds: sampleFaces.map((face) => face.id),
        suggestions: [],
    },
    render: (args) => (
        <ClusterConfirmationModal
            {...args}
            onClose={() => void 0}
        />
    ),
};
