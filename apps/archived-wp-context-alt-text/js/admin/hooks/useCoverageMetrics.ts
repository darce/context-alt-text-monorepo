import { useQuery } from "@tanstack/react-query";

import type { CoverageCard } from "@/admin/types";
import { getDashboardConfig } from "@/admin/dashboardData";

export const COVERAGE_QUERY_KEY = ["dashboard", "coverage"] as const;

interface UseCoverageMetricsOptions {
    initialData: CoverageCard;
}

export const useCoverageMetrics = ({ initialData }: UseCoverageMetricsOptions) => {
    const config = getDashboardConfig();
    const endpoint = config.endpoints?.coverage ?? null;
    const restNonce = config.restNonce;
    const hasEndpoint = Boolean(endpoint);

    const query = useQuery<CoverageCard>({
        queryKey: COVERAGE_QUERY_KEY,
        queryFn: async () => {
            if (!endpoint) {
                return initialData;
            }

            const response = await fetch(endpoint, {
                credentials: "same-origin",
                headers: {
                    Accept: "application/json",
                    ...(restNonce ? { "X-WP-Nonce": restNonce } : {}),
                },
            });

            if (!response.ok) {
                throw new Error(`Failed to fetch coverage metrics: ${response.status}`);
            }

            const payload = (await response.json()) as Partial<CoverageCard>;
            return { ...initialData, ...payload };
        },
        initialData,
        staleTime: 60_000,
        gcTime: 5 * 60_000,
        retry: 1,
        enabled: hasEndpoint,
    });

    return {
        ...query,
        data: query.data ?? initialData,
        hasEndpoint,
    };
};
