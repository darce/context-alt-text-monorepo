import type {
    AdminConfig,
    DashboardData,
    DashboardFooter,
    HeroStatus,
    CoverageCard,
    LatestActivityCard,
    RecognitionInsightsCard,
    AutomationPipelineCard,
    GlobalPayload,
    FeatureFlags,
    WorkbenchData,
    WorkbenchMediaItem,
    AdminRouteKey,
} from "@/admin/types";

const FALLBACK_HERO: HeroStatus = {
    state: "scanning",
    message: "Scanning media library…",
    cta_label: "Open Alt-Text Workbench",
    cta_url: "#",
    last_updated_human: null,
};

export const FALLBACK_COVERAGE: CoverageCard = {
    total: 0,
    missing: 0,
    with_alt: 0,
    coverage_percent: 0,
    trend_series: [],
};

const FALLBACK_ACTIVITY: LatestActivityCard = {
    last_recognition: null,
    last_alt_text_generation: null,
    last_roster_sync: null,
};

const FALLBACK_RECOGNITION: RecognitionInsightsCard = {
    pending_faces: 0,
    pending_brands: 0,
    unresolved_matches: 0,
};

const FALLBACK_AUTOMATION: AutomationPipelineCard = {
    queued: 0,
    running: 0,
    completed: 0,
    next_run: null,
};

const FALLBACK_FOOTER: DashboardFooter = {
    actions: [],
    statusText: "Initial scan is in progress.",
};

const FALLBACK_FEATURE_FLAGS: FeatureFlags = {
    coverageTrend: false,
    workbenchEnabled: false,
    workbenchRecognition: false,
    workbenchBulkAI: false,
};

const FALLBACK_CONFIG: AdminConfig = {
    missingAltMediaUrl: undefined,
    endpoints: {},
    restNonce: undefined,
    featureFlags: FALLBACK_FEATURE_FLAGS,
};

const FALLBACK_WORKBENCH_PAGINATION: WorkbenchData["pagination"] = {
    page: 1,
    perPage: 20,
    total: 0,
    totalPages: 0,
};

const FALLBACK_WORKBENCH: WorkbenchData = {
    items: [],
    viewMode: "list",
    pagination: FALLBACK_WORKBENCH_PAGINATION,
};

export const getDashboardData = (): DashboardData => {
    const globalPayload: GlobalPayload = (globalThis as any)?.ContextAltTextAdmin ?? {};
    const dashboard = globalPayload.data?.dashboard ?? {};

    return {
        hero: { ...FALLBACK_HERO, ...(dashboard.hero ?? {}) },
        coverage: {
            ...FALLBACK_COVERAGE,
            ...(dashboard.coverage ?? {}),
            trend_series: dashboard.coverage?.trend_series ?? [],
        },
        latestActivity: {
            ...FALLBACK_ACTIVITY,
            ...(dashboard.latestActivity ?? {}),
        },
        recognition: {
            ...FALLBACK_RECOGNITION,
            ...(dashboard.recognition ?? {}),
        },
        automation: {
            ...FALLBACK_AUTOMATION,
            ...(dashboard.automation ?? {}),
        },
        footer: {
            ...FALLBACK_FOOTER,
            ...(dashboard.footer ?? {}),
            actions: dashboard.footer?.actions ?? [],
            statusText: dashboard.footer?.statusText ?? FALLBACK_FOOTER.statusText,
        },
    };
};

export const getDashboardConfig = (): AdminConfig => {
    const globalPayload: GlobalPayload = (globalThis as any)?.ContextAltTextAdmin ?? {};
    const config: AdminConfig = globalPayload.config ?? {};
    const endpoints = config.endpoints ?? {};
    const featureFlags = config.featureFlags ?? {};

    return {
        missingAltMediaUrl:
            typeof config.missingAltMediaUrl === "string" ? config.missingAltMediaUrl : FALLBACK_CONFIG.missingAltMediaUrl,
        restNonce: typeof config.restNonce === "string" ? config.restNonce : FALLBACK_CONFIG.restNonce,
        endpoints: {
            coverage: typeof endpoints.coverage === "string" ? endpoints.coverage : undefined,
            workbenchMedia: typeof endpoints.workbenchMedia === "string" ? endpoints.workbenchMedia : undefined,
        },
        featureFlags: {
            coverageTrend: Boolean(featureFlags.coverageTrend ?? FALLBACK_FEATURE_FLAGS.coverageTrend),
            workbenchEnabled: Boolean(featureFlags.workbenchEnabled ?? FALLBACK_FEATURE_FLAGS.workbenchEnabled),
            workbenchRecognition: Boolean(
                featureFlags.workbenchRecognition ?? FALLBACK_FEATURE_FLAGS.workbenchRecognition,
            ),
            workbenchBulkAI: Boolean(featureFlags.workbenchBulkAI ?? FALLBACK_FEATURE_FLAGS.workbenchBulkAI),
        },
    };
};

export const normalizeWorkbenchItem = (
    item: Partial<WorkbenchMediaItem> | undefined,
): WorkbenchMediaItem | null => {
    if (!item || typeof item !== "object" || !item.id || !item.title) {
        return null;
    }

    const status = item.status;
    const allowedStatus = status === "draft" || status === "published" ? status : "missing";

    return {
        id: String(item.id),
        title: String(item.title),
        status: allowedStatus,
        thumbnailUrl: item.thumbnailUrl ?? undefined,
        updatedAt: item.updatedAt ?? undefined,
        altText: typeof item.altText === "string" ? item.altText : null,
        mimeType: typeof item.mimeType === "string" ? item.mimeType : null,
        dimensions: item.dimensions && typeof item.dimensions === "object"
            ? normalizeDimensions(item.dimensions as Record<string, unknown>)
            : null,
        editUrl: typeof item.editUrl === "string" ? item.editUrl : null,
    };
};

const normalizeDimensions = (input: Record<string, unknown>) => {
    const width = Number(input.width ?? 0);
    const height = Number(input.height ?? 0);

    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
        return null;
    }

    return {
        width,
        height,
    };
};

export const getWorkbenchData = (): WorkbenchData => {
    const globalPayload: GlobalPayload = (globalThis as any)?.ContextAltTextAdmin ?? {};
    const workbench = globalPayload.data?.workbench ?? {};
    const rawItems = Array.isArray((workbench as any).items) ? (workbench as any).items : [];
    const items: WorkbenchMediaItem[] = rawItems
        .map((candidate: Partial<WorkbenchMediaItem>) => normalizeWorkbenchItem(candidate))
        .filter((candidate): candidate is WorkbenchMediaItem => candidate !== null);

    const viewMode = workbench.viewMode === "list" ? "list" : FALLBACK_WORKBENCH.viewMode;
    const pagination = normalizeWorkbenchPagination(workbench.pagination);

    return {
        items,
        viewMode,
        pagination,
    };
};

const normalizeWorkbenchPagination = (
    pagination: Partial<WorkbenchData["pagination"]> | undefined,
): WorkbenchData["pagination"] => {
    if (!pagination || typeof pagination !== "object") {
        return FALLBACK_WORKBENCH_PAGINATION;
    }

    const page = Number(pagination.page ?? FALLBACK_WORKBENCH_PAGINATION.page);
    const perPage = Number(pagination.perPage ?? FALLBACK_WORKBENCH_PAGINATION.perPage);
    const total = Number(pagination.total ?? FALLBACK_WORKBENCH_PAGINATION.total);
    const totalPages = Number(pagination.totalPages ?? FALLBACK_WORKBENCH_PAGINATION.totalPages);

    return {
        page: Number.isFinite(page) && page > 0 ? page : FALLBACK_WORKBENCH_PAGINATION.page,
        perPage: Number.isFinite(perPage) && perPage > 0 ? perPage : FALLBACK_WORKBENCH_PAGINATION.perPage,
        total: Number.isFinite(total) && total >= 0 ? total : FALLBACK_WORKBENCH_PAGINATION.total,
        totalPages:
            Number.isFinite(totalPages) && totalPages >= 0
                ? totalPages
                : FALLBACK_WORKBENCH_PAGINATION.totalPages,
    };
};

export const getInitialRoute = (): AdminRouteKey => {
    const globalPayload: GlobalPayload = (globalThis as any)?.ContextAltTextAdmin ?? {};
    const page = globalPayload.page;
    if (page === "workbench" || page === "dashboard") {
        return page;
    }

    return "dashboard";
};
