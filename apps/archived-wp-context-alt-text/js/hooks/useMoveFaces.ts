import { useMutation, useQueryClient } from "@tanstack/react-query";
import { sprintf, _n } from "@wordpress/i18n";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import { useToast } from "@/contexts/ToastContext";

interface MoveFacesParams {
    faceIds: number[];
    sourceClusterId: string;
    targetClusterId: string;
}

interface MoveFacesResponse {
    success: boolean;
    moved_count: number;
    source_cluster_id: string;
    target_cluster_id: string;
}

interface OptimisticUpdateContext {
    previousData?: unknown;
}

/**
 * Hook for moving faces from one cluster to another.
 * Uses optimistic updates to immediately reflect changes in the UI.
 * Shows toast notification with working undo functionality.
 */
export const useMoveFaces = () => {
    const queryClient = useQueryClient();
    const { addToast } = useToast();
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters ?? null;
    const restNonce = config.restNonce;

    return useMutation<MoveFacesResponse, Error, MoveFacesParams, OptimisticUpdateContext>({
        mutationFn: async (params: MoveFacesParams): Promise<MoveFacesResponse> => {
            if (!endpoint) {
                throw new Error("Unknown clusters endpoint is not configured");
            }

            const base = endpoint.endsWith("/") ? endpoint.slice(0, -1) : endpoint;
            const url = `${base}/move`;

            const response = await fetchApi<MoveFacesResponse>(url, {
                method: "POST",
                restNonce,
                body: JSON.stringify({
                    face_ids: params.faceIds,
                    source_cluster_id: params.sourceClusterId,
                    target_cluster_id: params.targetClusterId,
                }),
            });

            return response;
        },
        onMutate: async (variables) => {
            // Cancel any outgoing refetches to avoid overwriting our optimistic update
            await queryClient.cancelQueries({ queryKey: ["unknown-clusters"] });
            await queryClient.cancelQueries({ queryKey: ["cluster-detail", endpoint, variables.sourceClusterId] });
            await queryClient.cancelQueries({ queryKey: ["cluster-detail", endpoint, variables.targetClusterId] });

            // Snapshot the previous value
            const previousData = {
                clusters: queryClient.getQueryData(["unknown-clusters"]),
                sourceCluster: queryClient.getQueryData(["cluster-detail", endpoint, variables.sourceClusterId]),
                targetCluster: queryClient.getQueryData(["cluster-detail", endpoint, variables.targetClusterId]),
            };

            // Optimistically update cluster list counts (decrement source, increment target)
            queryClient.setQueryData(["unknown-clusters"], (old: unknown) => {
                if (!old || typeof old !== "object" || !("clusters" in old)) {
                    return old;
                }

                const oldData = old as { clusters: { id: string; face_count: number }[] };
                return {
                    ...oldData,
                    clusters: oldData.clusters.map((cluster) => {
                        if (cluster.id === variables.sourceClusterId) {
                            return {
                                ...cluster,
                                face_count: Math.max(0, cluster.face_count - variables.faceIds.length),
                            };
                        }
                        if (cluster.id === variables.targetClusterId) {
                            return { ...cluster, face_count: cluster.face_count + variables.faceIds.length };
                        }
                        return cluster;
                    }),
                };
            });

            return { previousData };
        },
        onError: (error, variables, context) => {
            // Rollback optimistic updates on error
            if (context?.previousData) {
                const previous = context.previousData as {
                    clusters?: unknown;
                    sourceCluster?: unknown;
                    targetCluster?: unknown;
                };
                queryClient.setQueryData(["unknown-clusters"], previous.clusters);
                queryClient.setQueryData(
                    ["cluster-detail", endpoint, variables.sourceClusterId],
                    previous.sourceCluster,
                );
                queryClient.setQueryData(
                    ["cluster-detail", endpoint, variables.targetClusterId],
                    previous.targetCluster,
                );
            }

            console.error("[useMoveFaces] Error moving faces:", error);
            addToast({
                type: "error",
                message: "Failed to move faces. Please try again.",
                duration: 7000,
            });
        },
        onSuccess: (data, variables) => {
            // Invalidate summary list (all pages)
            void queryClient.invalidateQueries({
                queryKey: ["unknown-clusters"],
            });

            // Invalidate both source and target cluster details
            void queryClient.invalidateQueries({
                queryKey: ["cluster-detail", endpoint, variables.sourceClusterId],
            });

            void queryClient.invalidateQueries({
                queryKey: ["cluster-detail", endpoint, variables.targetClusterId],
            });

            // Show success toast with working undo functionality
            const message = sprintf(
                _n(
                    "Moved %d face to another cluster",
                    "Moved %d faces to another cluster",
                    data.moved_count,
                    "context-alt-text",
                ),
                data.moved_count,
            );

            addToast({
                type: "success",
                message,
                duration: 15000, // 15 seconds for undo window
                action: {
                    label: "Undo",
                    onClick: () => {
                        // Reverse the move by swapping source and target
                        const base = endpoint?.endsWith("/") ? endpoint?.slice(0, -1) : endpoint;
                        const url = `${base}/move`;

                        void fetchApi<MoveFacesResponse>(url, {
                            method: "POST",
                            restNonce,
                            body: JSON.stringify({
                                face_ids: variables.faceIds,
                                source_cluster_id: variables.targetClusterId, // Swap: move back to source
                                target_cluster_id: variables.sourceClusterId, // From the target we just moved to
                            }),
                        })
                            .then(() => {
                                // Invalidate to refresh the UI after undo
                                void queryClient.invalidateQueries({
                                    queryKey: ["unknown-clusters"],
                                });
                                void queryClient.invalidateQueries({
                                    queryKey: ["cluster-detail", endpoint, variables.sourceClusterId],
                                });
                                void queryClient.invalidateQueries({
                                    queryKey: ["cluster-detail", endpoint, variables.targetClusterId],
                                });

                                // Show undo confirmation
                                addToast({
                                    type: "success",
                                    message: "Move undone successfully",
                                    duration: 3000,
                                });
                            })
                            .catch((error) => {
                                console.error("[useMoveFaces] Error undoing move:", error);
                                addToast({
                                    type: "error",
                                    message: "Failed to undo. Please try moving faces back manually.",
                                    duration: 7000,
                                });
                            });
                    },
                },
            });
        },
    });
};
