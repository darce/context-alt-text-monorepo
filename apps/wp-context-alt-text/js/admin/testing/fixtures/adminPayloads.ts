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

/**
 * Roster fixtures for testing roster manager and observation resolution flows.
 * Includes taxonomy metadata showing `cat_roster_entity` term associations.
 */
export const rosterContractPayload = {
    entries: [
        {
            remoteId: "remote-alice-123",
            label: "Alice Example",
            type: "Person",
            status: "SYNCED",
            updatedAt: "2024-03-15T14:30:00.000Z",
            metadata: {
                avatarUrl: "https://example.com/avatars/alice.jpg",
                avatarAttachmentId: 501,
                taxonomyTermId: 42, // cat_roster_entity term ID
                taxonomySlug: "alice-example",
            },
            referenceImages: [
                {
                    attachment_id: "501",
                    image_url: "https://example.com/avatars/alice.jpg",
                    metadata: {
                        source: "recognition",
                        observationId: "obs-101",
                        confidence: 0.95,
                        area: 0.15,
                        label: "Alice Example",
                        entityType: "Person",
                    },
                },
            ],
            avatarUrl: "https://example.com/avatars/alice.jpg",
            referenceImageCount: 1,
            avatarId: 501,
            media: [
                {
                    attachmentId: 501,
                    title: "alice-profile.jpg",
                    thumbnailUrl: "https://example.com/thumbs/alice.jpg",
                    editUrl: "https://example.com/wp-admin/post.php?post=501&action=edit",
                    matchedAt: "2024-03-15T14:30:00.000Z",
                    observationId: "obs-101",
                },
            ],
            mediaCount: 1,
        },
        {
            remoteId: "remote-bob-456",
            label: "Bob Designer",
            type: "Person",
            status: "SYNCED",
            updatedAt: "2024-03-14T10:00:00.000Z",
            metadata: {
                avatarUrl: "https://example.com/avatars/bob.jpg",
                avatarAttachmentId: 502,
                taxonomyTermId: 43,
                taxonomySlug: "bob-designer",
                role: "Designer",
                team: "Creative",
            },
            referenceImages: [
                {
                    attachment_id: "502",
                    image_url: "https://example.com/avatars/bob.jpg",
                    metadata: {
                        source: "recognition",
                        observationId: "obs-102",
                        confidence: 0.89,
                        area: 0.12,
                        label: "Bob Designer",
                        entityType: "Person",
                    },
                },
                {
                    attachment_id: "503",
                    image_url: "https://example.com/images/team-photo.jpg",
                    metadata: {
                        source: "recognition",
                        observationId: "obs-103",
                        confidence: 0.92,
                        area: 0.08,
                        label: "Bob Designer",
                        entityType: "Person",
                        boundingBox: [0.1, 0.2, 0.3, 0.4],
                    },
                },
            ],
            avatarUrl: "https://example.com/avatars/bob.jpg",
            referenceImageCount: 2,
            avatarId: 502,
            media: [
                {
                    attachmentId: 502,
                    title: "bob-headshot.jpg",
                    thumbnailUrl: "https://example.com/thumbs/bob.jpg",
                    editUrl: "https://example.com/wp-admin/post.php?post=502&action=edit",
                    matchedAt: "2024-03-14T10:00:00.000Z",
                    observationId: "obs-102",
                },
                {
                    attachmentId: 503,
                    title: "team-photo.jpg",
                    thumbnailUrl: "https://example.com/thumbs/team.jpg",
                    editUrl: "https://example.com/wp-admin/post.php?post=503&action=edit",
                    matchedAt: "2024-03-14T11:30:00.000Z",
                    observationId: "obs-103",
                },
            ],
            mediaCount: 2,
        },
        {
            remoteId: null,
            label: "Charlie Pending",
            type: "Person",
            status: "LOCAL",
            updatedAt: "2024-03-16T09:00:00.000Z",
            metadata: {
                taxonomyTermId: 44,
                taxonomySlug: "charlie-pending",
            },
            referenceImages: [],
            avatarUrl: null,
            referenceImageCount: 0,
            avatarId: null,
            mediaCount: 0,
        },
    ],
    stats: {
        total: 3,
        synced: 2,
        local: 1,
        conflicts: 0,
        lastSyncAt: "2024-03-15T14:30:00.000Z",
        lastSyncHuman: "2 hours",
        metrics: {
            created: 2,
            updated: 1,
            deleted: 0,
            errors: 0,
            conflicts: 0,
        },
    },
};

/**
 * Recognition observation fixtures showing pending face observations
 * that reference roster entries via cat_roster_entity taxonomy.
 */
export const observationContractPayload = {
    items: [
        {
            attachmentId: 504,
            jobId: "job-recognition-789",
            updatedAt: 1_710_504_000,
            status: "needs_review",
            summary: {
                total: 2,
                matched: 1,
                needs_review: 1,
            },
            context: {
                filename: "conference-group.jpg",
                imageUrl: "https://example.com/images/conference-group.jpg",
            },
            observations: [
                {
                    observationId: "obs-201",
                    label: "Alice Example",
                    entityType: "Person",
                    confidence: 0.94,
                    area: 0.14,
                    boundingBox: [0.2, 0.3, 0.4, 0.5],
                    status: "matched",
                    source: "recognition",
                    match: {
                        isMatch: true,
                        similarity: 0.94,
                        confidence: 0.94,
                        threshold: 0.75,
                    },
                    roster: {
                        remoteId: "remote-alice-123",
                        name: "Alice Example",
                        displayName: "Alice Example",
                        taxonomyTermId: 42,
                        taxonomySlug: "alice-example",
                    },
                    candidates: [
                        {
                            remoteId: "remote-alice-123",
                            name: "Alice Example",
                            confidence: 0.94,
                            similarity: 0.94,
                            meetsThreshold: true,
                        },
                    ],
                },
                {
                    observationId: "obs-202",
                    label: "Unidentified Person",
                    entityType: "Person",
                    confidence: 0.87,
                    area: 0.11,
                    boundingBox: [0.5, 0.3, 0.7, 0.5],
                    status: "needs_review",
                    source: "recognition",
                    match: {
                        isMatch: false,
                        similarity: 0.62,
                        confidence: 0.62,
                        threshold: 0.75,
                    },
                    roster: null,
                    candidates: [
                        {
                            remoteId: "remote-bob-456",
                            name: "Bob Designer",
                            confidence: 0.62,
                            similarity: 0.62,
                            meetsThreshold: false,
                        },
                    ],
                },
            ],
            confidenceScore: 0.905,
            sourceRemoteId: null,
        },
    ],
    total: 1,
    page: 1,
    perPage: 10,
    totalPages: 1,
    summary: {
        attachments: 1,
        observations: {
            total: 2,
            matched: 1,
            needs_review: 1,
        },
    },
};
