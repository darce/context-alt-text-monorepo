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
    WorkbenchMediaRecognition,
    RosterEntryMedia,
    AdminRouteKey,
    RosterData,
    RosterEntry,
    RosterStats,
    SettingsData,
    RecognitionSettingsPayload,
} from "@/admin/types";
import { getAdminBootstrap } from "@/admin/globals";
import { DEFAULT_CLUSTER_THRESHOLD } from "@/config/matching";

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
    roster_pending: 0,
    roster_conflicts: 0,
    roster_total: 0,
    last_roster_sync_human: null,
    last_roster_sync_at: null,
};

const FALLBACK_AUTOMATION: AutomationPipelineCard = {
    queued: 0,
    running: 0,
    completed: 0,
    next_run: null,
};

export const FALLBACK_RECOGNITION_SETTINGS: RecognitionSettingsPayload = {
    baseUrl: "",
    apiKey: "",
    timeoutMs: 15_000,
    modelProfile: "",
    enabled: false,
};

export const FALLBACK_SETTINGS: SettingsData = {
    recognition: FALLBACK_RECOGNITION_SETTINGS,
};

const normalizeMetric = (value: unknown, fallback: number): number => {
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric >= 0) {
        return numeric;
    }

    return fallback;
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
    abilitiesEnabled: false,
    rosterEnabled: false,
    settingsEnabled: false,
};

const FALLBACK_CONFIG: AdminConfig = {
    missingAltMediaUrl: undefined,
    endpoints: {},
    restNonce: undefined,
    featureFlags: FALLBACK_FEATURE_FLAGS,
    settings: {
        recognition: {
            canManage: false,
        },
    },
    matching: {
        clusterSimilarityThreshold: DEFAULT_CLUSTER_THRESHOLD,
    },
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

type WorkbenchPayload = Partial<WorkbenchData> & {
    items?: Partial<WorkbenchMediaItem>[];
    pagination?: Partial<WorkbenchData["pagination"]>;
};

type RosterPayload = Partial<RosterData> & {
    entries?: Partial<RosterEntry>[];
    stats?: Partial<RosterStats>;
};

export const FALLBACK_ROSTER_STATS: RosterStats = {
    total: 0,
    synced: 0,
    local: 0,
    conflicts: 0,
    lastSyncAt: null,
    lastSyncHuman: null,
    metrics: {
        created: 0,
        updated: 0,
        deleted: 0,
        errors: 0,
        conflicts: 0,
    },
};

export const FALLBACK_ROSTER: RosterData = {
    entries: [],
    stats: FALLBACK_ROSTER_STATS,
};

export const getDashboardData = (): DashboardData => {
    const globalPayload: GlobalPayload = getAdminBootstrap();
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
            pending_faces: normalizeMetric(dashboard.recognition?.pending_faces, FALLBACK_RECOGNITION.pending_faces),
            pending_brands: normalizeMetric(dashboard.recognition?.pending_brands, FALLBACK_RECOGNITION.pending_brands),
            unresolved_matches: normalizeMetric(
                dashboard.recognition?.unresolved_matches,
                FALLBACK_RECOGNITION.unresolved_matches,
            ),
            roster_pending: normalizeMetric(dashboard.recognition?.roster_pending, FALLBACK_RECOGNITION.roster_pending),
            roster_conflicts: normalizeMetric(
                dashboard.recognition?.roster_conflicts,
                FALLBACK_RECOGNITION.roster_conflicts,
            ),
            roster_total: normalizeMetric(dashboard.recognition?.roster_total, FALLBACK_RECOGNITION.roster_total),
            last_roster_sync_human:
                typeof dashboard.recognition?.last_roster_sync_human === "string"
                    ? dashboard.recognition?.last_roster_sync_human
                    : FALLBACK_RECOGNITION.last_roster_sync_human,
            last_roster_sync_at:
                typeof dashboard.recognition?.last_roster_sync_at === "string"
                    ? dashboard.recognition?.last_roster_sync_at
                    : FALLBACK_RECOGNITION.last_roster_sync_at,
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
    const globalPayload: GlobalPayload = getAdminBootstrap();
    const config: AdminConfig = globalPayload.config ?? {};
    const endpoints = config.endpoints ?? {};
    const featureFlags = config.featureFlags ?? {};
    const settingsMeta = config.settings ?? FALLBACK_CONFIG.settings;
    const matchingConfig = config.matching ?? FALLBACK_CONFIG.matching;
    const clusterThreshold =
        typeof matchingConfig?.clusterSimilarityThreshold === "number"
            ? matchingConfig.clusterSimilarityThreshold
            : DEFAULT_CLUSTER_THRESHOLD;

    return {
        missingAltMediaUrl:
            typeof config.missingAltMediaUrl === "string"
                ? config.missingAltMediaUrl
                : FALLBACK_CONFIG.missingAltMediaUrl,
        restNonce: typeof config.restNonce === "string" ? config.restNonce : FALLBACK_CONFIG.restNonce,
        endpoints: {
            coverage: typeof endpoints.coverage === "string" ? endpoints.coverage : undefined,
            workbenchMedia: typeof endpoints.workbenchMedia === "string" ? endpoints.workbenchMedia : undefined,
            recognitionAnalyze:
                typeof endpoints.recognitionAnalyze === "string" ? endpoints.recognitionAnalyze : undefined,
            recognitionJob: typeof endpoints.recognitionJob === "string" ? endpoints.recognitionJob : undefined,
            recognitionObservations:
                typeof endpoints.recognitionObservations === "string" ? endpoints.recognitionObservations : undefined,
            recognitionObservationUpdate:
                typeof endpoints.recognitionObservationUpdate === "string"
                    ? endpoints.recognitionObservationUpdate
                    : undefined,
            observationsRetry:
                typeof endpoints.observationsRetry === "string" ? endpoints.observationsRetry : undefined,
            rosterEntries: typeof endpoints.rosterEntries === "string" ? endpoints.rosterEntries : undefined,
            rosterSync: typeof endpoints.rosterSync === "string" ? endpoints.rosterSync : undefined,
            settingsRecognition:
                typeof endpoints.settingsRecognition === "string" ? endpoints.settingsRecognition : undefined,
            settingsRecognitionTest:
                typeof endpoints.settingsRecognitionTest === "string" ? endpoints.settingsRecognitionTest : undefined,
        },
        featureFlags: {
            coverageTrend: Boolean(featureFlags.coverageTrend ?? FALLBACK_FEATURE_FLAGS.coverageTrend),
            workbenchEnabled: Boolean(featureFlags.workbenchEnabled ?? FALLBACK_FEATURE_FLAGS.workbenchEnabled),
            workbenchRecognition: Boolean(
                featureFlags.workbenchRecognition ?? FALLBACK_FEATURE_FLAGS.workbenchRecognition,
            ),
            workbenchBulkAI: Boolean(featureFlags.workbenchBulkAI ?? FALLBACK_FEATURE_FLAGS.workbenchBulkAI),
            abilitiesEnabled: Boolean(featureFlags.abilitiesEnabled ?? FALLBACK_FEATURE_FLAGS.abilitiesEnabled),
            rosterEnabled: Boolean(featureFlags.rosterEnabled ?? FALLBACK_FEATURE_FLAGS.rosterEnabled),
            settingsEnabled: Boolean(featureFlags.settingsEnabled ?? FALLBACK_FEATURE_FLAGS.settingsEnabled),
        },
        settings: {
            recognition: {
                canManage: Boolean(settingsMeta?.recognition?.canManage ?? false),
            },
        },
        matching: {
            clusterSimilarityThreshold: clusterThreshold,
        },
    };
};

export const getSettingsData = (): SettingsData => {
    const globalPayload: GlobalPayload = getAdminBootstrap();
    const settings = globalPayload.data?.settings;
    const recognitionSource = settings?.recognition;
    const recognition =
        recognitionSource && typeof recognitionSource === "object"
            ? (recognitionSource as Partial<RecognitionSettingsPayload>)
            : {};

    const timeout = Number(recognition.timeoutMs);

    return {
        recognition: {
            baseUrl:
                typeof recognition.baseUrl === "string" ? recognition.baseUrl : FALLBACK_RECOGNITION_SETTINGS.baseUrl,
            apiKey: typeof recognition.apiKey === "string" ? recognition.apiKey : FALLBACK_RECOGNITION_SETTINGS.apiKey,
            timeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : FALLBACK_RECOGNITION_SETTINGS.timeoutMs,
            modelProfile:
                typeof recognition.modelProfile === "string"
                    ? recognition.modelProfile
                    : FALLBACK_RECOGNITION_SETTINGS.modelProfile,
            enabled: Boolean(recognition.enabled ?? FALLBACK_RECOGNITION_SETTINGS.enabled),
        },
    };
};

const toNullableString = (value: unknown): string | null => {
    if (typeof value !== "string") {
        return null;
    }

    const trimmed = value.trim();
    return trimmed !== "" ? trimmed : null;
};

const normalizeRecognition = (candidate: unknown): WorkbenchMediaRecognition | null => {
    if (!candidate || typeof candidate !== "object") {
        return null;
    }

    const record = candidate as Record<string, unknown>;
    const rawStatus = typeof record.status === "string" ? record.status : "unknown";

    const matchedCountRaw = Number(
        record.matchedCount ?? record.matched_count ?? record.matched ?? record.matched_faces ?? 0,
    );
    const needsReviewCountRaw = Number(
        record.needsReviewCount ?? record.needs_review_count ?? record.needs_review ?? 0,
    );

    const matchedCount = Number.isFinite(matchedCountRaw) && matchedCountRaw > 0 ? Math.trunc(matchedCountRaw) : 0;
    const needsReviewCount =
        Number.isFinite(needsReviewCountRaw) && needsReviewCountRaw > 0 ? Math.trunc(needsReviewCountRaw) : 0;

    const matchedRosterInput = record.matchedRoster ?? record.matched_roster ?? null;
    let matchedRoster: WorkbenchMediaRecognition["matchedRoster"] = null;

    if (matchedRosterInput && typeof matchedRosterInput === "object") {
        const rosterRecord = matchedRosterInput as Record<string, unknown>;
        matchedRoster = {
            remoteId: toNullableString(rosterRecord.remoteId ?? rosterRecord.remote_id ?? null),
            displayName: toNullableString(rosterRecord.displayName ?? rosterRecord.display_name ?? null),
            name: toNullableString(rosterRecord.name ?? null),
        };
    }

    const status = rawStatus === "matched" || rawStatus === "needs_review" ? rawStatus : "unknown";
    const updatedAtRaw = record.updatedAt ?? record.updated_at ?? null;
    const updatedAt =
        typeof updatedAtRaw === "number" && Number.isFinite(updatedAtRaw) ? Math.trunc(updatedAtRaw) : null;

    if (
        status === "unknown" &&
        matchedCount === 0 &&
        needsReviewCount === 0 &&
        (!matchedRoster || (!matchedRoster.remoteId && !matchedRoster.displayName && !matchedRoster.name))
    ) {
        return null;
    }

    return {
        status,
        matchedCount,
        needsReviewCount,
        matchedRoster,
        updatedAt,
    };
};

const normalizeRosterMedia = (candidate: Partial<RosterEntryMedia> | undefined): RosterEntryMedia | null => {
    if (!candidate || typeof candidate !== "object") {
        return null;
    }

    const attachmentRaw = candidate.attachmentId ?? (candidate as Record<string, unknown>).attachment_id;
    const attachmentId =
        typeof attachmentRaw === "number"
            ? attachmentRaw
            : typeof attachmentRaw === "string"
              ? Number(attachmentRaw)
              : NaN;

    if (!Number.isFinite(attachmentId) || attachmentId <= 0) {
        return null;
    }

    return {
        attachmentId,
        title: typeof candidate.title === "string" ? candidate.title : null,
        previewUrl: typeof candidate.previewUrl === "string" ? candidate.previewUrl : null,
        editUrl: typeof candidate.editUrl === "string" ? candidate.editUrl : null,
        thumbnailUrl: typeof candidate.thumbnailUrl === "string" ? candidate.thumbnailUrl : null,
        matchedAt: typeof candidate.matchedAt === "string" ? candidate.matchedAt : null,
        observationId: typeof candidate.observationId === "string" ? candidate.observationId : null,
    } satisfies RosterEntryMedia;
};

export const normalizeWorkbenchItem = (item: Partial<WorkbenchMediaItem> | undefined): WorkbenchMediaItem | null => {
    if (!item || typeof item !== "object" || !item.id || !item.title) {
        return null;
    }

    const status = item.status;
    const allowedStatus = status === "draft" || status === "published" ? status : "missing";
    const recognition = normalizeRecognition(
        (item as Record<string, unknown>).recognition ?? (item as Record<string, unknown>).recognitionSummary ?? null,
    );

    return {
        id: String(item.id),
        title: String(item.title),
        status: allowedStatus,
        thumbnailUrl: item.thumbnailUrl ?? undefined,
        updatedAt: item.updatedAt ?? undefined,
        altText: typeof item.altText === "string" ? item.altText : null,
        mimeType: typeof item.mimeType === "string" ? item.mimeType : null,
        dimensions:
            item.dimensions && typeof item.dimensions === "object"
                ? normalizeDimensions(item.dimensions as Record<string, unknown>)
                : null,
        editUrl: typeof item.editUrl === "string" ? item.editUrl : null,
        recognition: recognition ?? undefined,
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
    const globalPayload: GlobalPayload = getAdminBootstrap();
    const workbench = (globalPayload.data?.workbench as WorkbenchPayload | undefined) ?? {};
    const rawItems = Array.isArray(workbench.items) ? workbench.items : [];
    const items = rawItems
        .map((candidate) => normalizeWorkbenchItem(candidate))
        .filter((candidate): candidate is WorkbenchMediaItem => candidate !== null);

    const viewMode =
        workbench.viewMode === "grid" || workbench.viewMode === "list"
            ? workbench.viewMode
            : FALLBACK_WORKBENCH.viewMode;
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
            Number.isFinite(totalPages) && totalPages >= 0 ? totalPages : FALLBACK_WORKBENCH_PAGINATION.totalPages,
    };
};

export const getInitialRoute = (): AdminRouteKey => {
    const globalPayload: GlobalPayload = getAdminBootstrap();
    const page = globalPayload.page;
    if (page === "workbench" || page === "dashboard" || page === "roster") {
        return page;
    }

    return "dashboard";
};

export const getRosterData = (): RosterData => {
    const globalPayload: GlobalPayload = getAdminBootstrap();
    const roster = (globalPayload.data?.roster as RosterPayload | undefined) ?? {};
    const rawEntries = Array.isArray(roster.entries) ? roster.entries : [];

    const entries = rawEntries
        .map((candidate) => normalizeRosterEntry(candidate))
        .filter((candidate): candidate is RosterEntry => candidate !== null);

    return {
        entries,
        stats: normalizeRosterStats(roster.stats),
    };
};

export const normalizeRosterEntry = (entry: Partial<RosterEntry> | undefined): RosterEntry | null => {
    if (!entry || typeof entry !== "object") {
        return null;
    }

    const status = typeof entry.status === "string" ? entry.status.toUpperCase() : "";
    const normalizedStatus = status === "SYNCED" || status === "CONFLICT" ? status : "LOCAL";
    const label = typeof entry.label === "string" ? entry.label : "";
    const type = typeof entry.type === "string" ? entry.type : "";

    const metadata = entry.metadata && typeof entry.metadata === "object" ? entry.metadata : {};
    const referenceImages = Array.isArray(entry.referenceImages)
        ? entry.referenceImages.filter((item): item is Record<string, unknown> =>
              Boolean(item && typeof item === "object"),
          )
        : [];

    const media = Array.isArray(entry.media)
        ? entry.media
              .map((item) => normalizeRosterMedia(item as Partial<RosterEntryMedia>))
              .filter((item): item is RosterEntryMedia => item !== null)
        : [];

    const referenceImageCount = Number(entry.referenceImageCount);
    const mediaCount = Number(entry.mediaCount);
    const resolveAvatarId = (candidate?: unknown): number | null => {
        const value =
            typeof candidate === "number" ? candidate : typeof candidate === "string" ? Number(candidate) : NaN;
        return Number.isFinite(value) && value > 0 ? value : null;
    };

    const directAvatarId = resolveAvatarId(entry.avatarId);
    const metadataAvatarId = (() => {
        if (!metadata) {
            return null;
        }

        const keys = ["avatarAttachmentId", "avatar_attachment_id", "avatarId", "avatar_id"];

        for (const key of keys) {
            if (key in metadata) {
                const resolved = resolveAvatarId(metadata[key]);
                if (resolved !== null) {
                    return resolved;
                }
            }
        }

        return null;
    })();

    const avatarId = directAvatarId ?? metadataAvatarId;

    return {
        remoteId: typeof entry.remoteId === "string" ? entry.remoteId : null,
        label,
        type,
        status: normalizedStatus,
        updatedAt: typeof entry.updatedAt === "string" ? entry.updatedAt : null,
        metadata,
        referenceImages,
        avatarUrl: typeof entry.avatarUrl === "string" ? entry.avatarUrl : null,
        referenceImageCount:
            Number.isFinite(referenceImageCount) && referenceImageCount >= 0
                ? referenceImageCount
                : referenceImages.length,
        avatarId,
        media,
        mediaCount: Number.isFinite(mediaCount) && mediaCount >= 0 ? mediaCount : media.length,
    };
};

export const normalizeRosterStats = (stats: Partial<RosterStats> | undefined): RosterStats => {
    if (!stats || typeof stats !== "object") {
        return FALLBACK_ROSTER_STATS;
    }

    const metrics = stats.metrics && typeof stats.metrics === "object" ? stats.metrics : {};

    const total = Number((stats as { total?: unknown }).total);
    const synced = Number((stats as { synced?: unknown }).synced);
    const local = Number((stats as { local?: unknown }).local);
    const conflicts = Number((stats as { conflicts?: unknown }).conflicts);

    const metricValues = {
        created: Number((metrics as { created?: unknown }).created),
        updated: Number((metrics as { updated?: unknown }).updated),
        deleted: Number((metrics as { deleted?: unknown }).deleted),
        errors: Number((metrics as { errors?: unknown }).errors),
        conflicts: Number((metrics as { conflicts?: unknown }).conflicts),
    };

    return {
        total: Number.isFinite(total) && total >= 0 ? total : FALLBACK_ROSTER_STATS.total,
        synced: Number.isFinite(synced) && synced >= 0 ? synced : FALLBACK_ROSTER_STATS.synced,
        local: Number.isFinite(local) && local >= 0 ? local : FALLBACK_ROSTER_STATS.local,
        conflicts: Number.isFinite(conflicts) && conflicts >= 0 ? conflicts : FALLBACK_ROSTER_STATS.conflicts,
        lastSyncAt: typeof stats.lastSyncAt === "string" ? stats.lastSyncAt : null,
        lastSyncHuman: typeof stats.lastSyncHuman === "string" ? stats.lastSyncHuman : null,
        metrics: {
            created: Number.isFinite(metricValues.created) && metricValues.created >= 0 ? metricValues.created : 0,
            updated: Number.isFinite(metricValues.updated) && metricValues.updated >= 0 ? metricValues.updated : 0,
            deleted: Number.isFinite(metricValues.deleted) && metricValues.deleted >= 0 ? metricValues.deleted : 0,
            errors: Number.isFinite(metricValues.errors) && metricValues.errors >= 0 ? metricValues.errors : 0,
            conflicts:
                Number.isFinite(metricValues.conflicts) && metricValues.conflicts >= 0 ? metricValues.conflicts : 0,
        },
    };
};
