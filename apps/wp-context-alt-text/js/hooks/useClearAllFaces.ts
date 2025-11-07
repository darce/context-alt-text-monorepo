import { useMutation, useQueryClient } from "@tanstack/react-query";
import { sprintf, _n } from "@wordpress/i18n";

import { fetchApi } from "@/admin/utils/http";
import { getDashboardConfig } from "@/admin/dashboardData";
import { useToast } from "@/contexts/ToastContext";

interface ClearAllFacesResponse {
    success?: boolean;
    message?: string;
    cleared_count: number;
}

/**
 * Hook for bulk clearing all unresolved faces (marking as roster_id='__cleared__').
 * This removes all remaining unknown faces from the UI.
 * Invalidates all cluster-related cache entries on success.
 */
export const useClearAllFaces = () => {
    const queryClient = useQueryClient();
    const { addToast } = useToast();
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.unknownClusters ?? null;
    const restNonce = config.restNonce;

    return useMutation({
        mutationFn: async (): Promise<ClearAllFacesResponse> => {
            if (!endpoint) {
                throw new Error("Unknown clusters endpoint is not configured");
            }

            const base = endpoint.endsWith("/") ? endpoint.slice(0, -1) : endpoint;
            const url = `${base}/clear-all`;

            const response = await fetchApi<ClearAllFacesResponse>(url, {
                method: "POST",
                restNonce,
            });

            return response;
        },
        onSuccess: (data) => {
            // Invalidate all cluster-related queries
            void queryClient.invalidateQueries({
                queryKey: ["unknown-clusters"],
            });

            void queryClient.invalidateQueries({
                queryKey: ["cluster-detail"],
            });

            // Show success toast
            const message = sprintf(
                _n("Cleared %d unknown face", "Cleared %d unknown faces", data.cleared_count, "context-alt-text"),
                data.cleared_count,
            );

            addToast({
                type: "success",
                message,
                duration: 5000,
            });
        },
        onError: (error) => {
            console.error("[useClearAllFaces] Error clearing faces:", error);
            addToast({
                type: "error",
                message: "Failed to clear unknown faces. Please try again.",
                duration: 7000,
            });
        },
    });
};
