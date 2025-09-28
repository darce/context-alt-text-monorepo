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
  config?: Record<string, unknown>;
  data?: {
    summary?: Record<string, unknown>;
    dashboard?: Partial<DashboardData>;
  };
};
