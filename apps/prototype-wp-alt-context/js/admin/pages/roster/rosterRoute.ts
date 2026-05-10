import { __ } from '@wordpress/i18n';
import type { RosterEntry } from '../../api/rosterApi';

export const ROSTER_TABS = {
  entries: { id: 'entries' as const, label: __('Entries', 'alt-context') },
  clusters: { id: 'clusters' as const, label: __('Clusters', 'alt-context') },
} as const;

export type RosterTab = (typeof ROSTER_TABS)[keyof typeof ROSTER_TABS]['id'];

export const ROSTER_ROUTE_PARAM_KEYS = ['person', 'queue', 'face', 'cluster'] as const;

export interface ParsedRosterRoute {
  activeTab: RosterTab;
  selectedClusterId: string | null;
  requiresProjectionGateNotice: boolean;
}

export type ProjectionStatus = RosterEntry['projection_status'];

const PROJECTION_STATUSES = new Set<ProjectionStatus>(['current', 'refreshing', 'stale', 'failed']);

const PROJECTION_PRIORITY: Record<ProjectionStatus, number> = {
  failed: 3,
  stale: 2,
  refreshing: 1,
  current: 0,
};

export const getRouteParam = (searchParams: URLSearchParams, key: string): string | null => {
  const value = searchParams.get(key)?.trim();
  if (!value) {
    return null;
  }
  return value;
};

// Tolerate fixtures and legacy callers that omit the canonical RCL-004 fields by treating
// missing/non-string values as 'no projection'. Strict typecheck handles new code paths.
export const getEntryProjectionStatus = (entry: RosterEntry): ProjectionStatus | null => {
  const raw: unknown = entry.projection_status;
  if (typeof raw !== 'string') {
    return null;
  }
  return PROJECTION_STATUSES.has(raw as ProjectionStatus) ? (raw as ProjectionStatus) : null;
};

export const getEntryPersonUuid = (entry: RosterEntry): string | null => {
  const raw: unknown = entry.person_uuid;
  return typeof raw === 'string' && raw.length > 0 ? raw : null;
};

const getSortableEntryName = (entry: RosterEntry): string => {
  const raw: unknown = entry.name;
  return typeof raw === 'string' ? raw.trim().toLocaleLowerCase() : '';
};

export const selectDeterministicDefaultWorkspaceEntry = (
  entries: readonly RosterEntry[],
): RosterEntry | null => {
  const candidates = entries.filter((entry) => getEntryPersonUuid(entry) !== null);
  if (candidates.length === 0) {
    return null;
  }

  return [...candidates].sort((left, right) => {
    const nameComparison = getSortableEntryName(left).localeCompare(getSortableEntryName(right));
    if (nameComparison !== 0) {
      return nameComparison;
    }

    const leftPersonUuid = getEntryPersonUuid(left) ?? '';
    const rightPersonUuid = getEntryPersonUuid(right) ?? '';
    const personComparison = leftPersonUuid.localeCompare(rightPersonUuid);
    if (personComparison !== 0) {
      return personComparison;
    }

    return String(left.id).localeCompare(String(right.id));
  })[0] ?? null;
};

const getLegacyTab = (searchParams: URLSearchParams): RosterTab => {
  const rawTab = getRouteParam(searchParams, 'tab');
  return rawTab === ROSTER_TABS.clusters.id ? ROSTER_TABS.clusters.id : ROSTER_TABS.entries.id;
};

export const parseRosterRoute = (searchParams: URLSearchParams): ParsedRosterRoute => {
  if (
    getRouteParam(searchParams, 'person') ||
    getRouteParam(searchParams, 'queue') ||
    getRouteParam(searchParams, 'face')
  ) {
    return {
      activeTab: ROSTER_TABS.entries.id,
      selectedClusterId: null,
      requiresProjectionGateNotice: true,
    };
  }

  const clusterId = getRouteParam(searchParams, 'cluster');
  if (clusterId) {
    return {
      activeTab: ROSTER_TABS.clusters.id,
      selectedClusterId: clusterId,
      requiresProjectionGateNotice: false,
    };
  }

  return {
    activeTab: getLegacyTab(searchParams),
    selectedClusterId: null,
    requiresProjectionGateNotice: false,
  };
};

export const hasCanonicalProjectionShape = (entries: readonly RosterEntry[]): boolean =>
  entries.some((entry) => getEntryPersonUuid(entry) !== null && getEntryProjectionStatus(entry) !== null);

export const aggregateProjectionStatus = (entries: readonly RosterEntry[]): ProjectionStatus | null => {
  let aggregate: ProjectionStatus | null = null;
  for (const entry of entries) {
    const status = getEntryProjectionStatus(entry);
    if (status === null) {
      continue;
    }
    if (aggregate === null || PROJECTION_PRIORITY[status] > PROJECTION_PRIORITY[aggregate]) {
      aggregate = status;
    }
  }
  return aggregate;
};

export const PERSON_WORKSPACE_GATE_NOTICE = __(
  'This route is recognized, but the person workspace stays on the legacy Entries view until enriched roster projection data lands.',
  'alt-context',
);

export const PROJECTION_REFRESHING_NOTICE = __(
  'Roster projection is refreshing. Retry once the refresh completes.',
  'alt-context',
);

export const PROJECTION_STALE_NOTICE = __(
  'Roster projection is stale. Person workspace will resume after the next refresh.',
  'alt-context',
);

export const PROJECTION_FAILED_NOTICE = __(
  'Roster projection failed to refresh. Person workspace is unavailable until the projection recovers.',
  'alt-context',
);

export const PERSON_ROUTE_UNMATCHED_NOTICE = __(
  'No roster entry matches this person route yet. The workspace will appear once a matching projection row is available.',
  'alt-context',
);
