/**
 * Face Clustering Utility
 *
 * Groups similar faces using threshold-based clustering on embedding vectors.
 * Uses a simple single-linkage approach optimized for small face counts (<20).
 *
 * @package ContextAltText
 * @since 2.0.0
 */

import { cosineSimilarity, type FaceEmbedding } from "./faceEmbeddings";
import { DEFAULT_CLUSTER_THRESHOLD, getClusterSimilarityThreshold } from "@/config/matching";

/**
 * Cluster configuration
 */
export interface ClusterConfig {
    /** Similarity threshold for grouping faces (0.0-1.0) */
    similarityThreshold: number;
    /** Minimum cluster size (1 = include single faces) */
    minClusterSize: number;
}

/**
 * Default clustering configuration
 *
 * - Threshold default aligns with backend RecognitionConstants::CLUSTER_SIMILARITY_THRESHOLD.
 * - Min size 1: Include single faces as individual clusters
 */
export const DEFAULT_CLUSTER_CONFIG: ClusterConfig = {
    similarityThreshold: DEFAULT_CLUSTER_THRESHOLD,
    minClusterSize: 1,
};

/**
 * Face cluster
 */
export interface FaceCluster {
    /** Cluster ID */
    clusterId: string;
    /** Indices of faces in this cluster */
    faceIndices: number[];
    /** Average similarity within cluster */
    avgSimilarity: number;
}

/**
 * Cluster faces using single-linkage hierarchical clustering
 *
 * Algorithm:
 * 1. Start with each face as its own cluster
 * 2. Compute similarity matrix
 * 3. Merge most similar clusters until threshold
 * 4. Return final clusters
 *
 * @param embeddings - Array of face embeddings
 * @param config - Clustering configuration (partial config allowed)
 * @returns Array of face clusters
 *
 * @example
 * ```typescript
 * const embeddings = [emb1, emb2, emb3, emb4];
 * const clusters = clusterFaces(embeddings, { similarityThreshold: 0.7 });
 *
 * // Result: [[0, 1], [2], [3]] - faces 0 and 1 are similar
 * clusters.forEach(cluster => {
 *   console.log(`Cluster ${cluster.clusterId}: faces ${cluster.faceIndices.join(',')}`);
 * });
 * ```
 */
export const clusterFaces = (embeddings: FaceEmbedding[], config: Partial<ClusterConfig> = {}): FaceCluster[] => {
    const similarityThreshold =
        typeof config.similarityThreshold === "number"
            ? config.similarityThreshold
            : getClusterSimilarityThreshold();
    const minClusterSize = config.minClusterSize ?? DEFAULT_CLUSTER_CONFIG.minClusterSize;
    const n = embeddings.length;

    if (n === 0) {
        return [];
    }

    // Initialize: each face is its own cluster
    const clusters: number[][] = embeddings.map((_, i) => [i]);

    // Compute similarity matrix
    const similarity: number[][] = new Array(n).fill(null).map(() => new Array(n).fill(0) as number[]);

    for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
            const embI = embeddings[i];
            const embJ = embeddings[j];
            if (embI === undefined || embJ === undefined) {
                continue;
            }
            const sim = cosineSimilarity(embI, embJ);
            const simRow = similarity[i];
            if (simRow !== undefined) {
                simRow[j] = sim;
            }
            const simRowJ = similarity[j];
            if (simRowJ !== undefined) {
                simRowJ[i] = sim;
            }
        }
    }

    // Merge similar clusters iteratively
    let merged = true;
    while (merged) {
        merged = false;
        let maxSim = -1;
        let mergeI = -1;
        let mergeJ = -1;

        // Find most similar pair of clusters
        for (let i = 0; i < clusters.length; i++) {
            for (let j = i + 1; j < clusters.length; j++) {
                const clusterI = clusters[i];
                const clusterJ = clusters[j];
                if (clusterI === undefined || clusterJ === undefined) {
                    continue;
                }

                // Compute cluster similarity (single-linkage: max similarity between any pair)
                let clusterSim = -1;
                for (const faceI of clusterI) {
                    for (const faceJ of clusterJ) {
                        const simRow = similarity[faceI];
                        if (simRow !== undefined) {
                            const simValue = simRow[faceJ];
                            if (simValue !== undefined) {
                                clusterSim = Math.max(clusterSim, simValue);
                            }
                        }
                    }
                }

                if (clusterSim > maxSim && clusterSim >= similarityThreshold) {
                    maxSim = clusterSim;
                    mergeI = i;
                    mergeJ = j;
                }
            }
        }

        // Merge if found
        if (mergeI >= 0 && mergeJ >= 0) {
            const clusterToMergeI = clusters[mergeI];
            const clusterToMergeJ = clusters[mergeJ];
            if (clusterToMergeI !== undefined && clusterToMergeJ !== undefined) {
                clusters[mergeI] = [...clusterToMergeI, ...clusterToMergeJ];
                clusters.splice(mergeJ, 1);
                merged = true;
            }
        }
    }

    // Filter by minimum size and convert to FaceCluster format
    return clusters
        .filter((cluster) => cluster.length >= minClusterSize)
        .map((faceIndices, index) => {
            // Sort face indices in ascending order
            faceIndices.sort((a, b) => a - b);

            // Compute average similarity within cluster
            let avgSim = 1.0;
            if (faceIndices.length > 1) {
                let sumSim = 0;
                let count = 0;
                for (let i = 0; i < faceIndices.length; i++) {
                    for (let j = i + 1; j < faceIndices.length; j++) {
                        const idxI = faceIndices[i];
                        const idxJ = faceIndices[j];
                        if (idxI !== undefined && idxJ !== undefined) {
                            const simRow = similarity[idxI];
                            if (simRow !== undefined) {
                                const simValue = simRow[idxJ];
                                if (simValue !== undefined) {
                                    sumSim += simValue;
                                    count++;
                                }
                            }
                        }
                    }
                }
                avgSim = count > 0 ? sumSim / count : 1.0;
            }

            return {
                clusterId: `cluster_${index}`,
                faceIndices,
                avgSimilarity: avgSim,
            };
        });
};

/**
 * Find which cluster a new face belongs to
 *
 * @param newEmbedding - Embedding of new face
 * @param existingEmbeddings - Embeddings of faces in existing clusters
 * @param clusters - Existing clusters
 * @param threshold - Similarity threshold
 * @returns Cluster ID if match found, null otherwise
 *
 * @example
 * ```typescript
 * const clusterId = findMatchingCluster(newFaceEmb, allEmbeddings, clusters, 0.7);
 * if (clusterId) {
 *   console.log(`New face matches cluster ${clusterId}`);
 * } else {
 *   console.log('New face is unique');
 * }
 * ```
 */
export const findMatchingCluster = (
    newEmbedding: FaceEmbedding,
    existingEmbeddings: FaceEmbedding[],
    clusters: FaceCluster[],
    threshold: number,
): string | null => {
    let maxSim = -1;
    let matchingCluster: string | null = null;

    for (const cluster of clusters) {
        for (const faceIndex of cluster.faceIndices) {
            const existingEmbedding = existingEmbeddings[faceIndex];
            if (existingEmbedding === undefined) {
                continue;
            }
            const sim = cosineSimilarity(newEmbedding, existingEmbedding);
            if (sim > maxSim && sim >= threshold) {
                maxSim = sim;
                matchingCluster = cluster.clusterId;
            }
        }
    }

    return matchingCluster;
};
