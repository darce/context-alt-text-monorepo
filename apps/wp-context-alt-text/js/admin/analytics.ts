import { getAdminBootstrap } from "@/admin/globals";
import type { AnalyticsClient, GlobalPayload } from "@/admin/types";

export type AnalyticsDetail = Record<string, unknown> | undefined;

const getAnalyticsClient = (): AnalyticsClient["track"] | null => {
    const payload: GlobalPayload = getAdminBootstrap();
    const client: AnalyticsClient | undefined = payload.analytics;

    if (!client || typeof client.track !== "function") {
        return null;
    }

    return (event, detail) => {
        client.track(event, detail);
    };
};

export const emitDashboardEvent = (eventName: string, detail?: AnalyticsDetail): void => {
    const client = getAnalyticsClient();
    if (client) {
        client(eventName, detail ?? {});
    }

    if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent(eventName, { detail }));
    }
};
