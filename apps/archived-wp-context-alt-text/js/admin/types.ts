export interface DashboardEndpoints {
    coverage?: string;
    workbenchMedia?: string;
    recognitionAnalyze?: string;
    recognitionJob?: string;
    recognitionObservations?: string;
    recognitionObservationUpdate?: string;
    observationsRetry?: string;
    rosterEntries?: string;
    rosterSync?: string;
    settingsRecognition?: string;
    settingsRecognitionTest?: string;
    unknownClusters?: string;
    faceScan?: string;
}

export interface FeatureFlags {
    coverageTrend?: boolean;
    workbenchEnabled?: boolean;
    workbenchRecognition?: boolean;
    workbenchBulkAI?: boolean;
    abilitiesEnabled?: boolean;
    rosterEnabled?: boolean;
    settingsEnabled?: boolean;
}

export interface AdminConfig {
    missingAltMediaUrl?: string;
    endpoints?: DashboardEndpoints;
    restNonce?: string;
    featureFlags?: FeatureFlags;
    settings?: SettingsMeta;
}

export interface AnalyticsClient {
    track: (event: string, detail?: Record<string, unknown>) => void;
}

export interface RecognitionSettingsPayload {
    baseUrl: string;
    apiKey: string;
    timeoutMs: number;
    modelProfile: string;
    enabled: boolean;
}

export interface SettingsData {
    recognition: RecognitionSettingsPayload;
}

export interface SettingsMeta {
    recognition: {
        canManage: boolean;
    };
}

export interface HeroStatus {
    state: "scanning" | "ready";
    message: string;
    cta_label: string;
    cta_url: string;
    last_updated_human?: string | null;
}

export interface CoverageTrendPoint {
    timestamp: number;
    coverage: number;
    total: number;
    with_alt: number;
    missing: number;
}

export interface CoverageCard {
    total: number;
    missing: number;
    with_alt: number;
    coverage_percent: number;
    trend_series?: CoverageTrendPoint[];
}

export interface WorkbenchMediaRecognition {
    status: "matched" | "needs_review" | "unknown";
    matchedCount: number;
    needsReviewCount: number;
    matchedRoster?: {
        remoteId?: string | null;
        displayName?: string | null;
        name?: string | null;
    } | null;
    updatedAt?: number | null;
}

export interface WorkbenchMediaItem {
    id: string;
    title: string;
    status: "missing" | "draft" | "published";
    thumbnailUrl?: string;
    updatedAt?: string;
    altText?: string | null;
    mimeType?: string | null;
    dimensions?: {
        width: number;
        height: number;
    } | null;
    editUrl?: string | null;
    recognition?: WorkbenchMediaRecognition | null;
}

export interface WorkbenchPagination {
    page: number;
    perPage: number;
    total: number;
    totalPages: number;
}

export interface WorkbenchData {
    items: WorkbenchMediaItem[];
    viewMode: "grid" | "list";
    pagination: WorkbenchPagination;
}

export type AdminRouteKey = "dashboard" | "workbench" | "roster";

export interface LatestActivityCard {
    last_recognition: number | string | null;
    last_alt_text_generation: number | string | null;
    last_roster_sync: number | string | null;
}

export interface RecognitionInsightsCard {
    pending_faces: number;
    pending_brands: number;
    unresolved_matches: number;
    roster_pending: number;
    roster_conflicts: number;
    roster_total: number;
    last_roster_sync_human: string | null;
    last_roster_sync_at: string | null;
}

export interface AutomationPipelineCard {
    queued: number;
    running: number;
    completed: number;
    next_run: string | null;
}

export interface FooterAction {
    label: string;
    url: string;
}

export interface DashboardFooter {
    actions: FooterAction[];
    statusText: string;
}

export interface DashboardData {
    hero: HeroStatus;
    coverage: CoverageCard;
    latestActivity: LatestActivityCard;
    recognition: RecognitionInsightsCard;
    automation: AutomationPipelineCard;
    footer: DashboardFooter;
}

export interface RosterEntryMedia {
    attachmentId: number;
    title?: string | null;
    previewUrl?: string | null;
    editUrl?: string | null;
    thumbnailUrl?: string | null;
    matchedAt?: string | null;
    observationId?: string | null;
}

export interface RosterEntry {
    remoteId: string | null;
    label: string;
    type: string;
    status: "LOCAL" | "SYNCED" | "CONFLICT";
    updatedAt: string | null;
    metadata: Record<string, unknown>;
    referenceImages: Record<string, unknown>[];
    avatarUrl: string | null;
    referenceImageCount: number;
    avatarId: number | null;
    media?: RosterEntryMedia[];
    mediaCount?: number;
}

export interface RosterStats {
    total: number;
    synced: number;
    local: number;
    conflicts: number;
    lastSyncAt: string | null;
    lastSyncHuman: string | null;
    metrics: {
        created: number;
        updated: number;
        deleted: number;
        errors: number;
        conflicts: number;
    };
}

export interface RosterData {
    entries: RosterEntry[];
    stats: RosterStats;
}

export interface RecognitionObservationCandidate {
    remoteId: string | null;
    name: string | null;
    confidence: number | null;
    similarity: number;
    meetsThreshold: boolean;
}

export interface RecognitionObservationRecord {
    observationId: string;
    label: string;
    entityType: string;
    confidence: number;
    detectionConfidence?: number | null;
    matchConfidence?: number | null;
    area: number;
    boundingBox: number[];
    status: "matched" | "needs_review";
    source: Record<string, unknown> | null;
    match: {
        isMatch: boolean;
        similarity: number;
        confidence: number;
        threshold: number;
    };
    roster: {
        remoteId: string | null;
        name?: string | null;
        displayName?: string | null;
    } | null;
    candidates: RecognitionObservationCandidate[];
}

export interface RecognitionObservationAttachment {
    attachmentId: number | null;
    jobId: string | null;
    updatedAt: number | null;
    status: "matched" | "needs_review";
    summary: {
        total: number;
        matched: number;
        needs_review: number;
    };
    context: {
        filename?: string;
        imageUrl?: string;
    };
    observations: RecognitionObservationRecord[];
    confidenceScore: number;
    sourceRemoteId: string | null;
}

export interface RecognitionObservationSummary {
    attachments: number;
    observations: {
        total: number;
        matched: number;
        needs_review: number;
    };
}

export interface RecognitionObservationsResult {
    items: RecognitionObservationAttachment[];
    total: number;
    page: number;
    perPage: number;
    totalPages: number;
    summary: RecognitionObservationSummary;
}

export interface GlobalPayload {
    config?: AdminConfig;
    data?: {
        summary?: Record<string, unknown>;
        dashboard?: Partial<DashboardData>;
        workbench?: Partial<
            WorkbenchData & {
                items?: Partial<WorkbenchMediaItem>[];
                pagination?: Partial<WorkbenchPagination>;
            }
        >;
        roster?: Partial<
            RosterData & {
                entries?: Partial<RosterEntry>[];
            }
        >;
        settings?: Partial<SettingsData>;
    };
    page?: AdminRouteKey;
    analytics?: AnalyticsClient;
}
