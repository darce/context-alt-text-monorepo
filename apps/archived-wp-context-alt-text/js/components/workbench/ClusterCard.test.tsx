import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ClusterCard } from "./ClusterCard";
import { setFaceDragData } from "@/components/workbench/dragTypes";

const createCluster = (overrides: Partial<Parameters<typeof ClusterCard>[0]["cluster"]> = {}) => ({
    id: "cluster-alpha",
    faceCount: 3,
    sampleFace: {
        attachmentId: 101,
        thumbnailUrl: "http://example.test/crops/sample.jpg",
        bbox: { x: 0, y: 0, width: 10, height: 10 },
    },
    suggestion: null,
    createdAt: "2025-10-24T12:00:00Z",
    updatedAt: "2025-10-24T12:05:00Z",
    ...overrides,
});

const createDataTransfer = () => {
    const store = new Map<string, string>();
    return {
        data: store,
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
    } as unknown as DataTransfer;
};

describe("ClusterCard", () => {
    it("invokes drop callback when faces are dropped", () => {
        const handleDrop = vi.fn();
        const handleEnter = vi.fn();
        const handleLeave = vi.fn();

        render(
            <ClusterCard
                cluster={createCluster()}
                onDropFaces={handleDrop}
                onDragEnter={handleEnter}
                onDragLeave={handleLeave}
            />,
        );

        const card = screen.getByRole("button", { name: /review cluster/i });
        const dataTransfer = createDataTransfer();
        setFaceDragData(dataTransfer, { clusterId: "cluster-source", faceIds: ["face-1", "face-2"] });

        fireEvent.dragEnter(card, { dataTransfer });
        expect(handleEnter).toHaveBeenCalledWith("cluster-alpha");

        fireEvent.dragOver(card, { dataTransfer });
        fireEvent.drop(card, { dataTransfer });

        expect(handleDrop).toHaveBeenCalledWith("cluster-alpha", {
            clusterId: "cluster-source",
            faceIds: ["face-1", "face-2"],
        });
        expect(handleLeave).toHaveBeenCalledWith("cluster-alpha");
    });

    it("ignores drop when payload belongs to the same cluster", () => {
        const handleDrop = vi.fn();

        render(
            <ClusterCard
                cluster={createCluster({ id: "cluster-1" })}
                onDropFaces={handleDrop}
            />,
        );

        const card = screen.getByRole("button", { name: /review cluster/i });
        const dataTransfer = createDataTransfer();
        setFaceDragData(dataTransfer, { clusterId: "cluster-1", faceIds: ["face-1"] });

        fireEvent.drop(card, { dataTransfer });
        expect(handleDrop).not.toHaveBeenCalled();
    });
});
