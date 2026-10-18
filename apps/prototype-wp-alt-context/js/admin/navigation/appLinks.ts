/**
 * E21-10 — single-vocabulary cross-surface link contract.
 *
 * Every hash-link builder and cross-surface param name lives here (REF-19 / sr-007).
 * Consumers import; they never re-declare `#/...` strings or param-name literals.
 *
 * Wire shapes are intentional: builders emit the same hrefs as the pre-contract
 * call sites (byte-parity for workbench/retention/history; roster emission cleaned
 * in Slice 2). Param *readers* keep their owning hooks/codecs — this module owns
 * emit + the `run`/`media` codecs that lacked a validated owner.
 */

import type { WorkbenchMediaStatus } from '../api/workbenchMediaApi';
import type { WorkbenchOverlay } from '../api/recognition';
import type { WorkbenchTab } from '../pages/workbench/WorkbenchNavContext';

/** Param names — the one place a cross-surface param key may be spelled. */
export const APP_LINK_PARAMS = {
  status: 'status',
  tab: 'tab',
  panel: 'panel',
  /** WBUX-5 two-pane collapse/host state — independent of overlay `panel`. */
  panes: 'panes',
  advanced: 'advanced',
  personFilter: 'personFilter',
  run: 'run',
  person: 'person',
  /** E21-5-owned codec in workbenchQueueUrl.ts; name only re-exported here. */
  rq: 'rq',
  queue: 'queue',
  face: 'face',
  cluster: 'cluster',
  /** In-page filter/pagination — no builder emits these. */
  s: 's',
  p: 'p',
  perPage: 'perPage',
} as const;

export type AppLinkParam = (typeof APP_LINK_PARAMS)[keyof typeof APP_LINK_PARAMS];

/** Canonical wire values for params the contract serializes. */
export const APP_LINK_VALUES = {
  advancedOpen: 'open',
  personFilterUnassigned: 'unassigned',
  /** UXW2-4: `panel=review` (+ `cluster=<id>`) persists the scan-tab review panel. */
  panelReview: 'review',
  /** WBUX-5 workbench two-pane collapse states (`?panes=`). Default `both` is omitted. */
  panesBoth: 'both',
  panesControlCollapsed: 'control-collapsed',
  panesLibraryCollapsed: 'library-collapsed',
} as const;

export type PersonFilterValue = (typeof APP_LINK_VALUES)['personFilterUnassigned'];

/** Workbench two-pane collapse state carried by `?panes=` (absent ⇔ both). */
export type PanesState =
  | typeof APP_LINK_VALUES.panesBoth
  | typeof APP_LINK_VALUES.panesControlCollapsed
  | typeof APP_LINK_VALUES.panesLibraryCollapsed;

const PANES_VALID: readonly PanesState[] = [
  APP_LINK_VALUES.panesBoth,
  APP_LINK_VALUES.panesControlCollapsed,
  APP_LINK_VALUES.panesLibraryCollapsed,
];

/**
 * Parse `panes` search param. Valid collapse states pass through; absent/other → `'both'`
 * (default two-pane open; param omitted on clean URLs).
 */
export const parsePanes = (raw: string | null | undefined): PanesState =>
  raw != null && (PANES_VALID as readonly string[]).includes(raw) ? (raw as PanesState) : APP_LINK_VALUES.panesBoth;

/** Serialize panes state; `'both'` → null so callers omit the param (absent default). */
export const serializePanes = (v: PanesState): string | null => (v === APP_LINK_VALUES.panesBoth ? null : v);

/** Legal workbench `panel` values: review | conflicts | dead-letter. */
export type WorkbenchPanelValue = Exclude<WorkbenchOverlay, null> | typeof APP_LINK_VALUES.panelReview;

export const reviewPanelUrl = (clusterId: string): string =>
  toWorkbench({ tab: 'scan', panel: APP_LINK_VALUES.panelReview, cluster: clusterId });

export interface ToWorkbenchOptions {
  status?: WorkbenchMediaStatus;
  tab?: WorkbenchTab;
  /** When true or `'open'`, emits `advanced=open`. */
  advanced?: true | typeof APP_LINK_VALUES.advancedOpen;
  panel?: WorkbenchPanelValue;
  /** Review-panel target; emitted only with `panel=review`. */
  cluster?: string;
  /** Two-pane collapse; `'both'` (default) is omitted from the href. */
  panes?: PanesState;
}

export interface ToRosterOptions {
  personFilter?: PersonFilterValue;
}

const ROUTE = {
  dashboard: '/dashboard',
  workbench: '/workbench',
  roster: '/roster',
  retention: '/retention',
  settings: '/settings',
  descriptionHistory: '/description-history',
  guidedPrototype: '/guided-prototype',
} as const;

const href = (path: string, params?: URLSearchParams): string => {
  const query = params?.toString();
  return query ? `#${path}?${query}` : `#${path}`;
};

// ── Builders ──────────────────────────────────────────────────────────────

export const toDashboard = (): string => href(ROUTE.dashboard);

export const toWorkbench = (options: ToWorkbenchOptions = {}): string => {
  const params = new URLSearchParams();
  // Stable emit order matches pre-contract overlays (tab → panel → panes) then filters.
  if (options.tab !== undefined) {
    params.set(APP_LINK_PARAMS.tab, options.tab);
  }
  if (options.panel !== undefined) {
    params.set(APP_LINK_PARAMS.panel, options.panel);
  }
  if (options.panel === APP_LINK_VALUES.panelReview && options.cluster) {
    params.set(APP_LINK_PARAMS.cluster, options.cluster);
  }
  const panesWire = options.panes !== undefined ? serializePanes(options.panes) : null;
  if (panesWire !== null) {
    params.set(APP_LINK_PARAMS.panes, panesWire);
  }
  if (options.advanced === true || options.advanced === APP_LINK_VALUES.advancedOpen) {
    params.set(APP_LINK_PARAMS.advanced, APP_LINK_VALUES.advancedOpen);
  }
  if (options.status !== undefined) {
    params.set(APP_LINK_PARAMS.status, options.status);
  }
  return href(ROUTE.workbench, params);
};

export const toRetention = (): string => href(ROUTE.retention);

export const toSettings = (): string => href(ROUTE.settings);

export const toRoster = (options: ToRosterOptions = {}): string => {
  const params = new URLSearchParams();
  if (options.personFilter !== undefined) {
    params.set(APP_LINK_PARAMS.personFilter, options.personFilter);
  }
  return href(ROUTE.roster, params);
};

/** Deep-link to a person workspace (`?person=<uuid>`). E21-5 deferred emit ownership here. */
export const toRosterPerson = (personUuid: string): string => {
  const params = new URLSearchParams();
  params.set(APP_LINK_PARAMS.person, personUuid);
  return href(ROUTE.roster, params);
};

export const toDescriptionHistory = (): string => href(ROUTE.descriptionHistory);

export const toGuidedPrototype = (): string => href(ROUTE.guidedPrototype);

/**
 * Parse `run` search param. Empty / whitespace / missing → null (list surface).
 * Non-empty trimmed string is the run id (apply surface).
 */
export const parseRunParam = (raw: string | null | undefined): string | null => {
  if (raw == null) {
    return null;
  }
  const trimmed = raw.trim();
  return trimmed === '' ? null : trimmed;
};

/** Serialize a run id for the `run` param; empty/whitespace → null (omit). */
export const serializeRunParam = (runId: string | null | undefined): string | null => {
  if (runId == null) {
    return null;
  }
  const trimmed = runId.trim();
  return trimmed === '' ? null : trimmed;
};

/** Deep-link to a description-history apply view; empty/whitespace ids omit `run` (list). */
export const toDescriptionHistoryRun = (runId: string): string => {
  const params = new URLSearchParams();
  const serialized = serializeRunParam(runId);
  if (serialized !== null) {
    params.set(APP_LINK_PARAMS.run, serialized);
  }
  return href(ROUTE.descriptionHistory, params);
};

// ── Folded from workbenchOverlayLinks (deleted; single owner) ─────────────

export const buildWorkbenchOverlayHref = (section: WorkbenchTab, overlay: Exclude<WorkbenchOverlay, null>): string =>
  toWorkbench({ tab: section, panel: overlay });

export const SCAN_CONFLICTS_HREF = buildWorkbenchOverlayHref('scan', 'conflicts');
export const SCAN_DEAD_LETTER_HREF = buildWorkbenchOverlayHref('scan', 'dead-letter');
