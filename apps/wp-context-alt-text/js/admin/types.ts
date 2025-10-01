export type DashboardEndpoints = {
    coverage?: string;
    workbenchMedia?: string;
};

export type FeatureFlags = {
    coverageTrend?: boolean;
    workbenchEnabled?: boolean;
    workbenchRecognition?: boolean;
    workbenchBulkAI?: boolean;
};

export type AdminConfig = {
    missingAltMediaUrl?: string;
    endpoints?: DashboardEndpoints;
    restNonce?: string;
    featureFlags?: FeatureFlags;
};

export type HeroStatus = {
    state: "scanning" | "ready";
    message: string;
    cta_label: string;
    cta_url: string;
    last_updated_human?: string | null;
};

export type CoverageTrendPoint = {
    timestamp: number;
    coverage: number;
    total: number;
    with_alt: number;
    missing: number;
};

export type CoverageCard = {
    total: number;
    missing: number;
    with_alt: number;
    coverage_percent: number;
    trend_series?: CoverageTrendPoint[];
};

export type WorkbenchMediaItem = {
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
};

export type WorkbenchPagination = {
    page: number;
    perPage: number;
    total: number;
    totalPages: number;
};

export type WorkbenchData = {
    items: WorkbenchMediaItem[];
    viewMode: "grid" | "list";
    pagination: WorkbenchPagination;
};

export type AdminRouteKey = "dashboard" | "workbench";

export type LatestActivityCard = {
    last_recognition: number | string | null;
    last_alt_text_generation: number | string | null;
    last_roster_sync: number | string | null;
};

export type RecognitionInsightsCard = {
    pending_faces: number;
    pending_brands: number;
    unresolved_matches: number;
};

export type AutomationPipelineCard = {
    queued: number;
    running: number;
    completed: number;
    next_run: string | null;
};

export type FooterAction = {
    label: string;
    url: string;
};

export type DashboardFooter = {
    actions: FooterAction[];
    statusText: string;
};

export type DashboardData = {
    hero: HeroStatus;
    coverage: CoverageCard;
    latestActivity: LatestActivityCard;
    recognition: RecognitionInsightsCard;
    automation: AutomationPipelineCard;
    footer: DashboardFooter;
};

export type GlobalPayload = {
    config?: AdminConfig;
    data?: {
        summary?: Record<string, unknown>;
        dashboard?: Partial<DashboardData>;
        workbench?: Partial<WorkbenchData & {
            items?: Array<Partial<WorkbenchMediaItem>>;
            pagination?: Partial<WorkbenchPagination>;
        }>;
    };
    page?: AdminRouteKey;
};
