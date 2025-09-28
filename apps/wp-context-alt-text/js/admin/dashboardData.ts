import type {
  DashboardData,
  DashboardFooter,
  HeroStatus,
  CoverageCard,
  LatestActivityCard,
  RecognitionInsightsCard,
  AutomationPipelineCard,
  GlobalPayload,
} from "@/admin/types";

const FALLBACK_HERO: HeroStatus = {
  state: "scanning",
  message: "Scanning media library…",
  cta_label: "Open Alt-Text Workbench",
  cta_url: "#",
  last_updated_human: null,
};

const FALLBACK_COVERAGE: CoverageCard = {
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
