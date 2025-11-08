import { useMutation, useQueryClient } from "@tanstack/react-query";
import { __ } from "@wordpress/i18n";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import { useToast } from "@/contexts/ToastContext";

interface DeleteFaceResponse {
    success: boolean;
    face_id: number;
    cluster_id: string;
}

interface DeleteFaceParams {
    faceId: number;
    clusterId: string;
}

interface OptimisticUpdateContext {
    previousData?: unknown;
}

/**
 * Hook for soft deleting a face (marking as resolved with roster_id='__deleted__').
 * Uses optimistic updates to immediately remove the face from the UI.
 * Invalidates relevant cache entries on success.
 */
export const useDeleteFace = () => {
    const queryClient = useQueryClient();
    const { addToast } = useToast();
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters ?? null;
    const restNonce = config.restNonce;

    return useMutation<DeleteFaceResponse, Error, DeleteFaceParams, OptimisticUpdateContext>({
        mutationFn: async (params: DeleteFaceParams): Promise<DeleteFaceResponse> => {
            if (!endpoint) {
                throw new Error("Unknown clusters endpoint is not configured");
            }

            // Remove trailing slash from endpoint
            const base = endpoint.endsWith("/") ? endpoint.slice(0, -1) : endpoint;
            // Navigate up to the /faces endpoint
            const baseUrl = base.replace(/\/clusters\/?$/, "");
            const url = `${baseUrl}/faces/${params.faceId}`;

            const response = await fetchApi<DeleteFaceResponse>(url, {
                method: "DELETE",
                restNonce,
            });

            return response;
        },
        onMutate: async (variables) => {
            // Cancel any outgoing refetches
            await queryClient.cancelQueries({ queryKey: ["unknown-clusters"] });
            await queryClient.cancelQueries({ queryKey: ["cluster-detail", endpoint, variables.clusterId] });

            // Snapshot the previous value
            const previousData = {
                clusters: queryClient.getQueryData(["unknown-clusters"]),
                clusterDetail: queryClient.getQueryData(["cluster-detail", endpoint, variables.clusterId]),
            };

            // Optimistically update cluster list (decrement face_count)
            queryClient.setQueryData(["unknown-clusters"], (old: unknown) => {
                if (!old || typeof old !== "object" || !("clusters" in old)) {
                    return old;
                }

                const oldData = old as { clusters: { id: string; face_count: number }[] };
                return {
                    ...oldData,
                    clusters: oldData.clusters.map((cluster) => {
                        if (cluster.id === variables.clusterId) {
                            return { ...cluster, face_count: Math.max(0, cluster.face_count - 1) };
                        }
                        return cluster;
                    }),
                };
            });

            // Optimistically remove face from cluster detail
            queryClient.setQueryData(["cluster-detail", endpoint, variables.clusterId], (old: unknown) => {
                if (!old || typeof old !== "object" || !("faces" in old)) {
                    return old;
                }

                const oldData = old as { faces: { id: number }[] };
                return {
                    ...oldData,
                    faces: oldData.faces.filter((face) => face.id !== variables.faceId),
                };
            });

            return { previousData };
        },
        onError: (error, variables, context) => {
            // Rollback optimistic updates on error
            if (context?.previousData) {
                const previous = context.previousData as {
                    clusters?: unknown;
                    clusterDetail?: unknown;
                };
                queryClient.setQueryData(["unknown-clusters"], previous.clusters);
                queryClient.setQueryData(["cluster-detail", endpoint, variables.clusterId], previous.clusterDetail);
            }

            console.error("[useDeleteFace] Error deleting face:", error);
            addToast({
                type: "error",
                message: __("Failed to delete face. Please try again.", "context-alt-text"),
                duration: 7000,
            });
        },
        onSuccess: (data) => {
            // Invalidate summary list
            void queryClient.invalidateQueries({
                queryKey: ["unknown-clusters"],
            });

            // Invalidate cluster detail if cluster_id is returned
            if (data.cluster_id) {
                void queryClient.invalidateQueries({
                    queryKey: ["cluster-detail", endpoint, data.cluster_id],
                });
            }

            // Show success toast
            addToast({
                type: "success",
                message: __("Face removed successfully", "context-alt-text"),
                duration: 5000,
            });
        },
    });
};
