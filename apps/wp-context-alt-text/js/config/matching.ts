import { getAdminBootstrap } from "@/admin/globals";
import type { AdminConfig } from "@/admin/types";

export const DEFAULT_CLUSTER_THRESHOLD = 0.65;

export const getClusterSimilarityThreshold = (): number => {
    const bootstrap = getAdminBootstrap();
    const config = (bootstrap.config as AdminConfig | undefined)?.matching;
    const threshold = config?.clusterSimilarityThreshold;

    if (typeof threshold === "number" && threshold > 0 && threshold <= 1) {
        return threshold;
    }

    return DEFAULT_CLUSTER_THRESHOLD;
};
