export type AnalyticsDetail = Record<string, unknown> | undefined;

const getAnalyticsClient = () => {
    if (typeof window === "undefined") {
        return null;
    }

    const payload = (window as any)?.ContextAltTextAdmin;
    const client = payload?.analytics;

    if (client && typeof client.track === "function") {
        return client.track.bind(client) as (event: string, detail?: Record<string, unknown>) => void;
    }

    return null;
};

export const emitDashboardEvent = (eventName: string, detail?: AnalyticsDetail) => {
    if (typeof window === "undefined") {
        return;
    }

    const client = getAnalyticsClient();
    if (client) {
        client(eventName, detail ?? {});
    }

    window.dispatchEvent(new CustomEvent(eventName, { detail }));
};
