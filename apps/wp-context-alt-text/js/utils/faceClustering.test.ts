/**
 * Face Clustering Utility Tests
 *
 * Tests for single-linkage hierarchical clustering algorithm.
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import { describe, it, expect, vi } from "vitest";
import { clusterFaces, findMatchingCluster, mergeClusters, DEFAULT_CLUSTER_CONFIG } from "./faceClustering";
import { DEFAULT_CLUSTER_THRESHOLD } from "@/config/matching";
import type { FaceEmbedding } from "./faceEmbeddings";

describe("faceClustering", () => {
    /**
     * Helper: Create normalized embedding from values
     */
    const createEmbedding = (values: number[]): FaceEmbedding => {
        const arr = new Float32Array(values);
        // L2 normalize
        const norm = Math.sqrt(Array.from(arr).reduce((sum, val) => sum + val * val, 0));
        if (norm > 0) {
            for (let i = 0; i < arr.length; i++) {
                arr[i] /= norm;
            }
        }
        return arr;
    };

    /**
     * Helper: Create similar embeddings (high cosine similarity)
     */
    const createSimilarEmbeddings = (count: number): FaceEmbedding[] => {
        const base = Array.from({ length: 512 }, (_, i) => (i % 3 === 0 ? 1 : 0.2));
        return Array.from({ length: count }, (_, i) => {
            const offset = (i + 1) / (count + 1);
            const noisy = base.map((value, idx) => value + offset * ((idx % 5) * 0.01));
            return createEmbedding(noisy);
        });
    };

    /**
     * Helper: Create dissimilar embeddings (low cosine similarity)
     */
    const createDissimilarEmbeddings = (count: number): FaceEmbedding[] => {
        return Array.from({ length: count }, (_, i) => {
            const values = Array.from({ length: 512 }, (_, j) => ((j + i) % count === 0 ? 1 : 0));
            return createEmbedding(values);
        });
    };

    describe("clusterFaces", () => {
        describe("Basic Clustering", () => {
            it("creates single cluster for identical embeddings", () => {
                const embeddings = createSimilarEmbeddings(3);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.8 });

                expect(clusters).toHaveLength(1);
                expect(clusters[0]?.faceIndices).toEqual([0, 1, 2]);
            });

            it("creates separate clusters for dissimilar embeddings", () => {
                const embeddings = createDissimilarEmbeddings(3);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.8 });

                // Should create 3 separate clusters
                expect(clusters.length).toBeGreaterThanOrEqual(3);
                clusters.forEach((cluster) => {
                    expect(cluster.faceIndices).toHaveLength(1);
                });
            });

            it("returns empty array for no embeddings", () => {
                const clusters = clusterFaces([], { similarityThreshold: 0.65 });
                expect(clusters).toEqual([]);
            });

            it("handles single embedding", () => {
                const embeddings = [createEmbedding(Array.from({ length: 512 }, () => Math.random()))];
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.65 });

                expect(clusters).toHaveLength(1);
                expect(clusters[0]?.faceIndices).toEqual([0]);
                expect(clusters[0]?.avgSimilarity).toBe(1.0);
            });
        });

        describe("Similarity Threshold", () => {
            it("creates more clusters with higher threshold", () => {
                const embeddings = [
                    createEmbedding([1, 1, 0, 0]),
                    createEmbedding([1, 0.8, 0, 0]),
                    createEmbedding([1, 0.5, 0, 0]),
                    createEmbedding([0, 0, 1, 1]),
                ];

                const clustersLow = clusterFaces(embeddings, { similarityThreshold: 0.5 });
                const clustersHigh = clusterFaces(embeddings, { similarityThreshold: 0.9 });

                expect(clustersHigh.length).toBeGreaterThanOrEqual(clustersLow.length);
            });

            it("uses default threshold if not specified", () => {
                const embeddings = createSimilarEmbeddings(2);
                const clusters = clusterFaces(embeddings);

                expect(clusters).toBeDefined();
                expect(clusters.length).toBeGreaterThan(0);
            });

            it("respects custom threshold value", () => {
                const embeddings = [
                    createEmbedding([1, 0, 0, 0]),
                    createEmbedding([0.7, 0.7, 0, 0]), // More dissimilar after normalization
                ];

                // With high threshold, should stay separate
                // Normalized: [1, 0, 0, 0] and [0.707, 0.707, 0, 0]
                // Similarity: 0.707 < 0.95, so should NOT merge
                const clustersHigh = clusterFaces(embeddings, { similarityThreshold: 0.95 });
                expect(clustersHigh.length).toBe(2);

                // With low threshold, should merge
                const clustersLow = clusterFaces(embeddings, { similarityThreshold: 0.5 });
                expect(clustersLow.length).toBe(1);
            });
        });

        describe("Cluster Properties", () => {
            it("assigns unique cluster IDs", () => {
                const embeddings = createDissimilarEmbeddings(5);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.8 });

                const clusterIds = clusters.map((c) => c.clusterId);
                const uniqueIds = new Set(clusterIds);

                expect(uniqueIds.size).toBe(clusters.length);
            });

            it("generates cluster IDs in format cluster_<number>", () => {
                const embeddings = createSimilarEmbeddings(3);
                const clusters = clusterFaces(embeddings);

                clusters.forEach((cluster) => {
                    expect(cluster.clusterId).toMatch(/^cluster_\d+$/);
                });
            });

            it("calculates average similarity within cluster", () => {
                const embeddings = createSimilarEmbeddings(3);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.8 });

                expect(clusters[0]?.avgSimilarity).toBeDefined();
                expect(clusters[0]?.avgSimilarity).toBeGreaterThanOrEqual(0);
                expect(clusters[0]?.avgSimilarity).toBeLessThanOrEqual(1);
            });

            it("sets avgSimilarity to 1.0 for single-face clusters", () => {
                const embeddings = createDissimilarEmbeddings(3);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.9 });

                // Each face should be in its own cluster
                clusters.forEach((cluster) => {
                    if (cluster.faceIndices.length === 1) {
                        expect(cluster.avgSimilarity).toBe(1.0);
                    }
                });
            });

            it("maintains face indices in ascending order", () => {
                const embeddings = createSimilarEmbeddings(5);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.8 });

                clusters.forEach((cluster) => {
                    const sorted = [...cluster.faceIndices].sort((a, b) => a - b);
                    expect(cluster.faceIndices).toEqual(sorted);
                });
            });
        });

        describe("Single-Linkage Algorithm", () => {
            it("merges clusters based on maximum similarity between any pair", () => {
                // Create 3 embeddings: A and B similar, C different
                const embeddings = [
                    createEmbedding([1, 0, 0, 0]), // A
                    createEmbedding([0.95, 0.05, 0, 0]), // B (similar to A)
                    createEmbedding([0, 0, 1, 0]), // C (different)
                ];

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.7 });

                // Should have 2 clusters: {A, B} and {C}
                expect(clusters).toHaveLength(2);

                const largeCluster = clusters.find((c) => c.faceIndices.length > 1);
                expect(largeCluster).toBeDefined();
                expect(largeCluster?.faceIndices).toContain(0);
                expect(largeCluster?.faceIndices).toContain(1);
            });

            it("merges transitively (A similar to B, B similar to C → A,B,C cluster)", () => {
                const embeddings = [
                    createEmbedding([1, 0, 0, 0]), // A
                    createEmbedding([0.7, 0.7, 0, 0]), // B (similar to both A and C)
                    createEmbedding([0, 1, 0, 0]), // C
                ];

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.5 });

                // With low threshold, all should merge
                expect(clusters).toHaveLength(1);
                expect(clusters[0]?.faceIndices).toEqual([0, 1, 2]);
            });

            it("stops merging when threshold not met", () => {
                const embeddings = [
                    createEmbedding([1, 0, 0, 0]),
                    createEmbedding([0.9, 0.1, 0, 0]),
                    createEmbedding([0, 1, 0, 0]),
                ];

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.95 });

                // High threshold should prevent some merges
                expect(clusters.length).toBeGreaterThan(1);
            });
        });

        describe("Edge Cases", () => {
            it("handles all zero embeddings", () => {
                const embeddings = [new Float32Array(512).fill(0), new Float32Array(512).fill(0)];

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.5 });

                expect(clusters).toBeDefined();
                expect(clusters.length).toBeGreaterThan(0);
            });

            it("handles very large number of embeddings", () => {
                const embeddings = createSimilarEmbeddings(100);

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.7 });

                expect(clusters).toBeDefined();
                expect(clusters.length).toBeGreaterThan(0);

                // All faces should be assigned to clusters
                const totalFaces = clusters.reduce((sum, c) => sum + c.faceIndices.length, 0);
                expect(totalFaces).toBe(100);
            });

            it("handles embeddings with undefined values", () => {
                const embeddings = [createEmbedding([1, 0, 0, 0]), undefined as any, createEmbedding([0, 1, 0, 0])];

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.5 });

                // Should skip undefined and cluster the valid ones
                expect(clusters).toBeDefined();
                expect(clusters.length).toBeGreaterThan(0);
            });

            it("handles threshold = 0 (merge all)", () => {
                const embeddings = createDissimilarEmbeddings(5);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0 });

                // With threshold 0, might merge more clusters
                expect(clusters).toBeDefined();
                expect(clusters.length).toBeLessThanOrEqual(5);
            });

            it("handles threshold = 1 (no merging)", () => {
                const embeddings = createSimilarEmbeddings(5);
                const clusters = clusterFaces(embeddings, { similarityThreshold: 1.0 });

                // With threshold 1.0, only identical embeddings merge
                expect(clusters).toBeDefined();
            });
        });

        describe("Performance", () => {
            it("completes in reasonable time for 50 faces", () => {
                const embeddings = createSimilarEmbeddings(50);
                const start = performance.now();

                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.65 });

                const duration = performance.now() - start;

                expect(clusters).toBeDefined();
                expect(duration).toBeLessThan(5000); // Should complete in under 5 seconds
            });
        });
    });

    describe("findMatchingCluster", () => {
        const existingEmbeddings = [
            createEmbedding([1, 0, 0, 0]), // Cluster A, face 0
            createEmbedding([0.95, 0.05, 0, 0]), // Cluster A, face 1
            createEmbedding([0, 1, 0, 0]), // Cluster B, face 2
            createEmbedding([0, 0.95, 0.05, 0]), // Cluster B, face 3
        ];

        const clusters = [
            {
                clusterId: "cluster_a",
                faceIndices: [0, 1],
                avgSimilarity: 0.95,
            },
            {
                clusterId: "cluster_b",
                faceIndices: [2, 3],
                avgSimilarity: 0.95,
            },
        ];

        it("finds matching cluster for similar face", () => {
            const newEmbedding = createEmbedding([0.98, 0.02, 0, 0]); // Similar to cluster A

            const matchingClusterId = findMatchingCluster(newEmbedding, existingEmbeddings, clusters, 0.7);

            expect(matchingClusterId).toBe("cluster_a");
        });

        it("returns null for face below threshold", () => {
            const newEmbedding = createEmbedding([0, 0, 0, 1]); // Different from all

            const matchingClusterId = findMatchingCluster(newEmbedding, existingEmbeddings, clusters, 0.9);

            expect(matchingClusterId).toBeNull();
        });

        it("returns cluster with highest similarity", () => {
            const newEmbedding = createEmbedding([0.5, 0.5, 0, 0]); // Somewhat similar to both

            const matchingClusterId = findMatchingCluster(newEmbedding, existingEmbeddings, clusters, 0.3);

            expect(matchingClusterId).toBeDefined();
            expect(["cluster_a", "cluster_b"]).toContain(matchingClusterId);
        });

        it("handles empty clusters array", () => {
            const newEmbedding = createEmbedding([1, 0, 0, 0]);

            const matchingClusterId = findMatchingCluster(newEmbedding, existingEmbeddings, [], 0.5);

            expect(matchingClusterId).toBeNull();
        });

        it("handles undefined embeddings in existing array", () => {
            const embeddingsWithUndefined = [
                createEmbedding([1, 0, 0, 0]),
                undefined as any,
                createEmbedding([0, 1, 0, 0]),
            ];

            const clustersWithGaps = [
                {
                    clusterId: "cluster_a",
                    faceIndices: [0, 1],
                    avgSimilarity: 0.95,
                },
            ];

            const newEmbedding = createEmbedding([0.95, 0.05, 0, 0]);

            const matchingClusterId = findMatchingCluster(newEmbedding, embeddingsWithUndefined, clustersWithGaps, 0.7);

            // Should find cluster_a by comparing with face 0 (skipping undefined face 1)
            expect(matchingClusterId).toBe("cluster_a");
        });

        it("uses all faces in cluster for matching (single-linkage)", () => {
            const largeCluster = [
                {
                    clusterId: "cluster_large",
                    faceIndices: [0, 1, 2, 3],
                    avgSimilarity: 0.8,
                },
            ];

            const newEmbedding = createEmbedding([0, 0.98, 0.02, 0]); // Very similar to face 2

            const matchingClusterId = findMatchingCluster(newEmbedding, existingEmbeddings, largeCluster, 0.7);

            expect(matchingClusterId).toBe("cluster_large");
        });

        it("respects threshold strictly", () => {
            // Normalized: approximately [0.866, 0.5, 0, 0]
            // Similarity with [1, 0, 0, 0] = 0.866 > similarity with [0, 1, 0, 0] = 0.5
            const newEmbedding = createEmbedding([0.866, 0.5, 0, 0]);

            // With high threshold (0.95), shouldn't match anything
            const noMatch = findMatchingCluster(newEmbedding, existingEmbeddings, clusters, 0.95);
            expect(noMatch).toBeNull();

            // With low threshold (0.4), should match cluster_a (closest match)
            const match = findMatchingCluster(newEmbedding, existingEmbeddings, clusters, 0.4);
            expect(match).toBe("cluster_a");
        });
    });

    describe("DEFAULT_CLUSTER_CONFIG", () => {
        it("has reasonable default threshold", () => {
            expect(DEFAULT_CLUSTER_CONFIG.similarityThreshold).toBe(DEFAULT_CLUSTER_THRESHOLD);
            expect(DEFAULT_CLUSTER_CONFIG.similarityThreshold).toBeGreaterThan(0);
            expect(DEFAULT_CLUSTER_CONFIG.similarityThreshold).toBeLessThan(1);
        });
    });

    describe("Integration Tests", () => {
        it("clusters real-world scenario: family photo with 2 people appearing 3 times each", () => {
            // Simulate: Person A appears 3 times, Person B appears 3 times
            const personA = createEmbedding([1, 0, 0, 0]);
            const personB = createEmbedding([0, 1, 0, 0]);

            const embeddings = [
                personA, // Face 0
                createEmbedding([0.95, 0.05, 0, 0]), // Face 1 (similar to A)
                personB, // Face 2
                createEmbedding([0.98, 0.02, 0, 0]), // Face 3 (similar to A)
                createEmbedding([0.05, 0.95, 0, 0]), // Face 4 (similar to B)
                createEmbedding([0.02, 0.98, 0, 0]), // Face 5 (similar to B)
            ];

            const clusters = clusterFaces(embeddings, { similarityThreshold: 0.7 });

            // Should have 2 clusters
            expect(clusters).toHaveLength(2);

            // Each cluster should have 3 faces
            const clusterSizes = clusters.map((c) => c.faceIndices.length).sort();
            expect(clusterSizes).toEqual([3, 3]);
        });

        it("incremental clustering: add new face to existing clusters", () => {
            const embeddings = [
                createEmbedding([1, 0, 0, 0]),
                createEmbedding([0.9, 0.1, 0, 0]),
                createEmbedding([0, 1, 0, 0]),
            ];

            const clusters = clusterFaces(embeddings, { similarityThreshold: 0.7 });

            // New face similar to first cluster
            const newEmbedding = createEmbedding([0.95, 0.05, 0, 0]);
            const matchingCluster = findMatchingCluster(newEmbedding, embeddings, clusters, 0.7);

            expect(matchingCluster).toBeDefined();

            // Verify it matches the cluster containing face 0
            const cluster = clusters.find((c) => c.clusterId === matchingCluster);
            expect(cluster?.faceIndices).toContain(0);
        });

        it("handles mixed scenario: some faces cluster, others don't", () => {
            const embeddings = [
                // Cluster 1: Similar faces
                createEmbedding([1, 0, 0, 0]),
                createEmbedding([0.95, 0.05, 0, 0]),
                // Standalone face
                createEmbedding([0, 0, 1, 0]),
                // Cluster 2: Similar faces
                createEmbedding([0, 1, 0, 0]),
                createEmbedding([0.05, 0.95, 0, 0]),
                // Another standalone
                createEmbedding([0, 0, 0, 1]),
            ];

            const clusters = clusterFaces(embeddings, { similarityThreshold: 0.8 });

            expect(clusters.length).toBeGreaterThanOrEqual(3);

            // Should have at least 2 multi-face clusters
            const multiClusters = clusters.filter((c) => c.faceIndices.length > 1);
            expect(multiClusters.length).toBeGreaterThanOrEqual(2);

            // Should have some single-face clusters
            const singleClusters = clusters.filter((c) => c.faceIndices.length === 1);
            expect(singleClusters.length).toBeGreaterThanOrEqual(1);
        });

        describe("Performance", () => {
            it("clusters 50 faces in under 100ms", () => {
                const embeddings = createSimilarEmbeddings(50);
                const start = performance.now();
                const clusters = clusterFaces(embeddings, { similarityThreshold: 0.7 });
                const duration = performance.now() - start;

                expect(clusters.length).toBeGreaterThan(0);
                expect(duration).toBeLessThan(100);
            });
        });
    });

    describe("mergeClusters", () => {
        it("merges clusters that exceed threshold", () => {
            const clusters = new Map<string, string[]>([
                ["A", ["face-1"]],
                ["B", ["face-2"]],
                ["C", ["face-3"]],
            ]);

            const matrix = new Map<string, Map<string, number>>([
                [
                    "A",
                    new Map<string, number>([
                        ["B", 0.95],
                        ["C", 0.4],
                    ]),
                ],
                [
                    "B",
                    new Map<string, number>([
                        ["A", 0.95],
                        ["C", 0.6],
                    ]),
                ],
                [
                    "C",
                    new Map<string, number>([
                        ["A", 0.4],
                        ["B", 0.6],
                    ]),
                ],
            ]);

            const merged = mergeClusters(clusters, matrix, 0.9);
            expect(merged.size).toBe(2);
            const first = merged.get("cluster_0");
            expect(first).toEqual(["face-1", "face-2"]);
        });

        it("retains clusters below threshold", () => {
            const clusters = new Map<string, string[]>([
                ["A", ["face-1"]],
                ["B", ["face-2"]],
            ]);
            const matrix = new Map<string, Map<string, number>>([
                ["A", new Map<string, number>([["B", 0.5]])],
                ["B", new Map<string, number>([["A", 0.5]])],
            ]);

            const merged = mergeClusters(clusters, matrix, 0.8);
            expect(merged.size).toBe(2);
            expect(merged.get("cluster_0")).toEqual(["face-1"]);
            expect(merged.get("cluster_1")).toEqual(["face-2"]);
        });
    });
});
