import type { AdminConfig, DashboardData, WorkbenchData } from "@/admin/types";

export const dashboardContractPayload: {
    config: AdminConfig;
    data: { dashboard: DashboardData };
} = {
    config: {
        missingAltMediaUrl: "/wp-admin/upload.php?page=context-alt-text-missing",
        restNonce: "nonce-dashboard",
        endpoints: {
            coverage: "https://example.com/wp-json/context-alt-text/v1/dashboard/coverage",
            workbenchMedia: "https://example.com/wp-json/context-alt-text/v1/workbench/media",
            recognitionAnalyze: "https://example.com/wp-json/context-alt-text/v1/recognition/analyze",
            recognitionJob: "https://example.com/wp-json/context-alt-text/v1/recognition/job",
            recognitionObservations: "https://example.com/wp-json/cat/v1/observations",
            recognitionObservationUpdate: "https://example.com/wp-json/cat/v1/observations/",
            rosterEntries: "https://example.com/wp-json/context-alt-text/v1/roster",
            rosterSync: "https://example.com/wp-json/context-alt-text/v1/roster/sync",
            settingsRecognition: "https://example.com/wp-json/context-alt-text/v1/settings/recognition",
            settingsRecognitionTest: "https://example.com/wp-json/context-alt-text/v1/settings/recognition/test",
        },
        featureFlags: {
            coverageTrend: true,
            workbenchEnabled: true,
            workbenchRecognition: true,
            workbenchBulkAI: false,
            abilitiesEnabled: true,
            rosterEnabled: true,
            settingsEnabled: false,
        },
        settings: {
            recognition: {
                canManage: false,
            },
        },
    },
    data: {
        dashboard: {
            hero: {
                state: "ready",
                message: "Alt text coverage is improving.",
                cta_label: "Open Alt-Text Workbench",
                cta_url: "/wp-admin/admin.php?page=context-alt-text-workbench",
                last_updated_human: "just now",
            },
            coverage: {
                total: 250,
                with_alt: 200,
                missing: 50,
                coverage_percent: 80,
                trend_series: [
                    {
                        timestamp: 1_704_000_000_000,
                        coverage: 70,
                        total: 220,
                        with_alt: 154,
                        missing: 66,
                    },
                    {
                        timestamp: 1_704_086_400_000,
                        coverage: 75,
                        total: 240,
                        with_alt: 180,
                        missing: 60,
                    },
                    {
                        timestamp: 1_704_172_800_000,
                        coverage: 80,
                        total: 250,
                        with_alt: 200,
                        missing: 50,
                    },
                ],
            },
            latestActivity: {
                last_recognition: "2024-03-17T00:00:00.000Z",
                last_alt_text_generation: "2024-03-17T01:00:00.000Z",
                last_roster_sync: "2024-03-16T18:30:00.000Z",
            },
            recognition: {
                pending_faces: 2,
                pending_brands: 1,
                unresolved_matches: 3,
                roster_pending: 4,
                roster_conflicts: 1,
                roster_total: 8,
                last_roster_sync_human: "30 minutes",
                last_roster_sync_at: "2024-03-16T18:30:00.000Z",
            },
            automation: {
                queued: 5,
                running: 1,
                completed: 42,
                next_run: "2024-03-18T12:00:00.000Z",
            },
            footer: {
                actions: [
                    {
                        label: "Scan media again",
                        url: "/wp-admin/admin.php?page=context-alt-text-scan",
                    },
                    {
                        label: "Manage recognition",
                        url: "/wp-admin/admin.php?page=context-alt-text-recognition",
                    },
                ],
                statusText: "Last scan finished moments ago.",
            },
        },
    },
};

const buildExpectedDashboardConfig = (config: AdminConfig) => ({
    missingAltMediaUrl: config.missingAltMediaUrl,
    restNonce: config.restNonce,
    endpoints: {
        coverage: config.endpoints?.coverage,
        workbenchMedia: config.endpoints?.workbenchMedia,
        recognitionAnalyze: config.endpoints?.recognitionAnalyze,
        recognitionJob: config.endpoints?.recognitionJob,
        recognitionObservations: config.endpoints?.recognitionObservations,
        recognitionObservationUpdate: config.endpoints?.recognitionObservationUpdate,
        rosterEntries: config.endpoints?.rosterEntries,
        rosterSync: config.endpoints?.rosterSync,
        settingsRecognition: config.endpoints?.settingsRecognition,
        settingsRecognitionTest: config.endpoints?.settingsRecognitionTest,
    },
    featureFlags: {
        coverageTrend: Boolean(config.featureFlags?.coverageTrend),
        workbenchEnabled: Boolean(config.featureFlags?.workbenchEnabled),
        workbenchRecognition: Boolean(config.featureFlags?.workbenchRecognition),
        workbenchBulkAI: Boolean(config.featureFlags?.workbenchBulkAI),
        abilitiesEnabled: Boolean(config.featureFlags?.abilitiesEnabled),
        rosterEnabled: Boolean(config.featureFlags?.rosterEnabled),
        settingsEnabled: Boolean(config.featureFlags?.settingsEnabled),
    },
    settings: {
        recognition: {
            canManage: Boolean(config.settings?.recognition?.canManage),
        },
    },
});

export const dashboardContractExpectation: {
    data: DashboardData;
    config: ReturnType<typeof buildExpectedDashboardConfig>;
} = {
    data: dashboardContractPayload.data.dashboard,
    config: buildExpectedDashboardConfig(dashboardContractPayload.config),
};

interface WorkbenchContractItem {
    id: string | number;
    title: string;
    status: WorkbenchData["items"][number]["status"];
    updatedAt: string;
    altText: string | null;
    mimeType: string | null;
    dimensions: { width: number; height: number } | null;
    editUrl: string | null;
    thumbnailUrl?: string;
}

interface WorkbenchContractPayload {
    data: {
        workbench: {
            viewMode: WorkbenchData["viewMode"];
            pagination: WorkbenchData["pagination"];
            items: WorkbenchContractItem[];
        };
    };
}

export const workbenchContractPayload: WorkbenchContractPayload = {
    data: {
        workbench: {
            viewMode: "list",
            pagination: {
                page: 3,
                perPage: 25,
                total: 125,
                totalPages: 5,
            },
            items: [
                {
                    id: 123,
                    title: "Museum entrance",
                    status: "missing",
                    updatedAt: "2024-03-10T00:00:00.000Z",
                    altText: "",
                    mimeType: "image/jpeg",
                    dimensions: { width: 2048, height: 1365 },
                    editUrl: "https://example.com/edit/123",
                    thumbnailUrl: "https://example.com/thumb/123.jpg",
                },
                {
                    id: "alpha",
                    title: "Downtown skyline",
                    status: "draft",
                    updatedAt: "2024-03-11T00:00:00.000Z",
                    altText: "Skyline captured at dusk.",
                    mimeType: "image/png",
                    dimensions: { width: 1600, height: 900 },
                    editUrl: "https://example.com/edit/alpha",
                },
            ],
        },
    },
};

export const workbenchContractExpectation: WorkbenchData = {
    viewMode: "list",
    pagination: workbenchContractPayload.data.workbench.pagination,
    items: [
        {
            id: "123",
            title: "Museum entrance",
            status: "missing",
            updatedAt: "2024-03-10T00:00:00.000Z",
            altText: "",
            mimeType: "image/jpeg",
            dimensions: { width: 2048, height: 1365 },
            editUrl: "https://example.com/edit/123",
            thumbnailUrl: "https://example.com/thumb/123.jpg",
        },
        {
            id: "alpha",
            title: "Downtown skyline",
            status: "draft",
            updatedAt: "2024-03-11T00:00:00.000Z",
            altText: "Skyline captured at dusk.",
            mimeType: "image/png",
            dimensions: { width: 1600, height: 900 },
            editUrl: "https://example.com/edit/alpha",
            thumbnailUrl: undefined,
        },
    ],
};
