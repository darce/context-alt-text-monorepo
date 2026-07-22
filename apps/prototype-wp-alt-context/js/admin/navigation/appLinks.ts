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
  advanced: 'advanced',
  personFilter: 'personFilter',
  run: 'run',
  person: 'person',
  media: 'media',
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
  mediaExpanded: 'expanded',
  personFilterUnassigned: 'unassigned',
} as const;

export type MediaExpandValue = (typeof APP_LINK_VALUES)['mediaExpanded'];
export type PersonFilterValue = (typeof APP_LINK_VALUES)['personFilterUnassigned'];

export interface ToWorkbenchOptions {
  status?: WorkbenchMediaStatus;
  tab?: WorkbenchTab;
  /** When true or `'open'`, emits `advanced=open`. */
  advanced?: true | typeof APP_LINK_VALUES.advancedOpen;
  panel?: Exclude<WorkbenchOverlay, null>;
  media?: MediaExpandValue;
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
} as const;

const href = (path: string, params?: URLSearchParams): string => {
  const query = params?.toString();
  return query ? `#${path}?${query}` : `#${path}`;
};

// ── Builders ──────────────────────────────────────────────────────────────

export const toDashboard = (): string => href(ROUTE.dashboard);

export const toWorkbench = (options: ToWorkbenchOptions = {}): string => {
  const params = new URLSearchParams();
  // Stable emit order matches pre-contract overlays (tab → panel) then filters.
  if (options.tab !== undefined) {
    params.set(APP_LINK_PARAMS.tab, options.tab);
  }
  if (options.panel !== undefined) {
    params.set(APP_LINK_PARAMS.panel, options.panel);
  }
  if (options.advanced === true || options.advanced === APP_LINK_VALUES.advancedOpen) {
    params.set(APP_LINK_PARAMS.advanced, APP_LINK_VALUES.advancedOpen);
  }
  if (options.status !== undefined) {
    params.set(APP_LINK_PARAMS.status, options.status);
  }
  if (options.media !== undefined) {
    params.set(APP_LINK_PARAMS.media, options.media);
  }
  return href(ROUTE.workbench, params);
};

export const toRetention = (): string => href(ROUTE.retention);

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

export const toDescriptionHistoryRun = (runId: string): string => {
  const params = new URLSearchParams();
  params.set(APP_LINK_PARAMS.run, runId);
  return href(ROUTE.descriptionHistory, params);
};

// ── Folded from workbenchOverlayLinks (deleted; single owner) ─────────────

export const buildWorkbenchOverlayHref = (
  section: WorkbenchTab,
  overlay: Exclude<WorkbenchOverlay, null>,
): string => toWorkbench({ tab: section, panel: overlay });

export const SCAN_CONFLICTS_HREF = buildWorkbenchOverlayHref('scan', 'conflicts');
export const SCAN_DEAD_LETTER_HREF = buildWorkbenchOverlayHref('scan', 'dead-letter');

// ── Codecs (malformed → default, never throw) ─────────────────────────────

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

/**
 * Parse `media` search param. Only `expanded` is true; absent/other → false
 * (collapsed-per-heuristic default used by ScanTabContent today).
 */
export const parseMediaExpanded = (raw: string | null | undefined): boolean =>
  raw === APP_LINK_VALUES.mediaExpanded;

/** Serialize expand state; false → null so callers omit the param (absent default). */
export const serializeMediaExpanded = (expanded: boolean): string | null =>
  expanded ? APP_LINK_VALUES.mediaExpanded : null;
