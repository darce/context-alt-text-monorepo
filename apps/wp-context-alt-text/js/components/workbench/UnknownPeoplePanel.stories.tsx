import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { UnknownPeoplePanel } from "./UnknownPeoplePanel";
import { setAdminBootstrap } from "@/admin/globals";
import type { ClusterSummary } from "@/types/face-clustering";

const endpoint = "https://example.test/wp-json/cat/v1/clusters";

const createDecorator = (data: {
    clusters: ClusterSummary[];
    total: number;
    page: number;
    perPage: number;
}) => {
    return (Story: React.ComponentType) => {
        setAdminBootstrap({
            config: {
                endpoints: {
                    unknownClusters: endpoint,
                },
                restNonce: "storybook-nonce",
            },
        });

        const queryClient = new QueryClient({
            defaultOptions: {
                queries: {
                    retry: false,
                    staleTime: Infinity,
                },
            },
        });

        queryClient.setQueryData(["unknown-clusters", endpoint, data.page, data.perPage], data);

        return (
            <QueryClientProvider client={queryClient}>
                <Story />
            </QueryClientProvider>
        );
    };
};

const meta: Meta<typeof UnknownPeoplePanel> = {
    title: "Workbench/Unknown People Panel",
    component: UnknownPeoplePanel,
};

export default meta;

type Story = StoryObj<typeof UnknownPeoplePanel>;

const sampleCluster: ClusterSummary = {
    id: "cluster-alpha",
    faceCount: 4,
    sampleFace: {
        attachmentId: 123,
        thumbnailUrl: "https://placehold.co/160x160",
        bbox: { x: 10, y: 20, width: 80, height: 90 },
    },
    suggestion: {
        rosterId: "person-42",
        displayName: "Ellyn",
        confidence: 0.92,
        reason: "FAISS cosine similarity 0.92",
    },
    createdAt: "2025-10-24T12:00:00Z",
    updatedAt: "2025-10-24T12:30:00Z",
};

export const Default: Story = {
    decorators: [
        createDecorator({
            clusters: [sampleCluster],
            total: 1,
            page: 1,
            perPage: 20,
        }),
    ],
};

export const Empty: Story = {
    decorators: [
        createDecorator({
            clusters: [],
            total: 0,
            page: 1,
            perPage: 20,
        }),
    ],
};

export const Selected: Story = {
    decorators: [
        createDecorator({
            clusters: [sampleCluster],
            total: 1,
            page: 1,
            perPage: 20,
        }),
    ],
    render: () => <UnknownPeoplePanel selectedClusterId="cluster-alpha" />,
};
